"""medic 실행 루프 (스펙 5장). `python -m my_planner_medic` → `main()`.

시작하면 단일 실행 잠금(`state/medic.lock`)을 잡고, `updater.recover_on_start()`를 먼저 한 번 부른 뒤
`watch_interval_s`마다 `watcher.tick()`, `deploy_interval_s`마다 `updater.tick()`을 부른다.
`enabled = false`면 하트비트만 보낸다(죽은 것으로 보이지 않게). 배포에 medic 자신이 바뀌었으면(`updater.self_updated`)
`EXIT_SELF_UPDATE`(3)로 끝나고, `scripts/medic_boot.py`가 새 코드로 바로 다시 띄운다.

한 회차가 어떤 예외를 던져도 루프는 산다. 로그에는 예외 종류만 남긴다(메시지에 경로·토큰이 있을 수 있다).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import IO, Any, Protocol

from .clock import Clock, SystemClock
from .config import MedicConfig, load_config
from .github import GitHub
from .gitops import GitError, GitOps
from .http import UrllibHttp
from .notify import Notifier
from .shell import Shell, SubprocessShell
from .store import MedicStore
from .tasks import TaskControl
from .updater import Updater
from .watcher import Watcher

__all__ = ["EXIT_SELF_UPDATE", "Parts", "acquire_lock", "build", "main", "run"]

log = logging.getLogger(__name__)

EXIT_SELF_UPDATE = 3
MAX_SLEEP_S = 5  # 멈춤 신호를 이 간격 안에 알아챈다
LOG_BYTES = 1_000_000


class WatcherLike(Protocol):
    def tick(self) -> None: ...
    def heartbeat(self) -> None: ...


class UpdaterLike(Protocol):
    self_updated: bool

    def recover_on_start(self) -> None: ...
    def tick(self) -> None: ...


@dataclass
class Parts:
    watcher: WatcherLike
    updater: UpdaterLike
    close: Callable[[], None]


def acquire_lock(path: Path) -> IO[bytes] | None:
    """비차단 잠금. 이미 다른 medic이 쥐고 있으면 None. 프로세스가 죽으면 OS가 푼다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def build(cfg: MedicConfig, clock: Clock, *, shell: Shell | None = None) -> Parts:
    shell = shell or SubprocessShell()
    store = MedicStore(cfg.root / "state" / "medic.db")
    http = UrllibHttp()
    gh = GitHub(http, cfg.github_token, cfg.repo)
    notifier = Notifier(cfg, store, http, clock)
    watcher = Watcher(cfg, store, gh, http, clock, notifier)
    git = GitOps(shell, cfg.root, cfg.github_token, branch=cfg.branch)
    tasks = TaskControl(shell, cfg.root, name=cfg.be_task_name)
    updater = Updater(cfg, store, gh, http, tasks, git, shell, watcher, notifier, clock)
    if not store.kv_get("deployed_sha"):  # 처음 뜨는 medic: 지금 머리 커밋이 배포된 커밋이다
        try:
            store.kv_set("deployed_sha", git.head())
        except GitError:
            log.warning("deployed_sha_unknown")
    return Parts(watcher, updater, store.close)


def _guarded(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - 루프가 죽지 않게. 메시지는 남기지 않는다(경로·토큰)
        log.warning("%s_failed %s", name, type(exc).__name__)


def run(
    cfg: MedicConfig,
    *,
    clock: Clock,
    sleep: Callable[[float], None],
    stop: Callable[[], bool],
    build: Callable[[MedicConfig, Clock], Parts] = build,  # 시험이 가짜 부품을 넣는다
) -> int:
    lock = acquire_lock(cfg.root / "state" / "medic.lock")
    if lock is None:
        log.info("medic_already_running")
        return 0
    parts = build(cfg, clock)
    try:
        # 켜져 있든 아니든 먼저 복구한다: 끊긴 배포 때문에 BE 작업이 꺼진 채 남지 않게
        _guarded("recover", parts.updater.recover_on_start)
        now = clock.now()
        next_watch = next_deploy = now
        while not stop():
            now = clock.now()
            if now >= next_watch:
                _guarded("watcher_tick" if cfg.enabled else "heartbeat",
                         parts.watcher.tick if cfg.enabled else parts.watcher.heartbeat)
                next_watch = now + timedelta(seconds=cfg.watch_interval_s)
            if cfg.enabled and now >= next_deploy:
                _guarded("updater_tick", parts.updater.tick)
                next_deploy = now + timedelta(seconds=cfg.deploy_interval_s)
                if parts.updater.self_updated:
                    log.info("medic_self_update_exit")
                    return EXIT_SELF_UPDATE
            wait = (min(next_watch, next_deploy) if cfg.enabled else next_watch) - clock.now()
            sleep(max(0.0, min(wait.total_seconds(), MAX_SLEEP_S)))
        return 0
    finally:
        parts.close()
        lock.close()


def _setup_logging(root: Path) -> None:
    log_dir = root / "state" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "medic.log", maxBytes=LOG_BYTES, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def _root() -> Path:
    env = os.environ.get("MY_PLANNER_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def main() -> int:
    root = _root()
    _setup_logging(root)
    cfg = load_config(root)
    stopping = False

    def _signal(_num: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _signal)
    log.info("medic_starting")
    code = run(cfg, clock=SystemClock(), sleep=time.sleep, stop=lambda: stopping)
    log.info("medic_stopped code=%d", code)
    return code

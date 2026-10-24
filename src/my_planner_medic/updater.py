"""업데이터 (스펙 5장 1~8단계, 시작 시 복구, 보관). `tick()`을 5분마다, 시작 때 `recover_on_start()`를 한 번.

상태 기계(`kv["deploy_in_progress"]`, 없으면 대기):

    (없음) --재시작 배포--> deploy --성공--> verify --확인 통과--> (없음)
                              |                 |
                              | 머지 뒤 실패     | 확인 실패
                              v                 v
                            rollback ---------> rollback_verify --통과--> (없음)
                              |                       |
                              | 롤백 자체 실패          | 확인 실패
                              v                       v
                            gave_up(포기, 작업은 켠 채) ----> (없음)

`deploy`·`rollback`은 BE 작업이 꺼져 있을 수 있는 단계다. 어느 길로 끝나도 `finally`에서 작업을 켠다. 켜기가
실패하면 `kv["be_task_disabled_by_medic"]`가 남아 다음 tick·다음 시작에서 다시 켠다(medic이 끈 것만 켠다).

kv 키:
- `deploy_in_progress`: `{prev_sha, new_sha, schema_before, started_at, phase, verify_started_at, verify_elapsed_s,
  last_tick_at, grace_until, window_from, repairs, repaired, medic_changed, cause, blamed, actions_done?,
  ran_new?, marked?}`.
  `phase`는 `deploy|verify|rollback|rollback_verify`. `window_from` 이후의 신호만 센다. 배포는 작업을 켜기 전에
  `verify`로, 롤백은 켜기 전에 `actions_done`을 적는다(켠 뒤 끊겨도 시작 시 복구가 같은 일을 되풀이하지 않게).
- `deployed_sha`(성공 → new, 롤백 → prev), `bad_shas`(list), `deploy_deferred` `{since}`, `suppress_until`(ISO),
  `deploy_retry` `{sha, until}`(머지 전에 멈춘 배포는 같은 커밋을 한 시간 뒤에),
  `be_task_disabled_by_medic`(bool), `issue_ops`(못 한 GitHub 라벨·닫기 일), `medic_pinned`(09가 씀).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from . import dbfile
from .clock import Clock
from .config import MedicConfig
from .github import GitHub, GitHubUnavailable
from .gitops import GitError, GitOps, venv_python
from .http import Http
from .notify import NotifierLike
from .redact import issue_body
from .shell import Shell
from .signals import Signal, outside_reasons
from .store import STATES, Incident, MedicStore, iso_utc
from .tasks import TaskControl
from .watcher import Watcher

__all__ = ["RESTART_PATHS", "Updater", "needs_restart", "venv_python"]

log = logging.getLogger(__name__)

RESTART_PATHS = ("src/", "requirements.lock", "pyproject.toml", "config.toml", "scripts/")
MEDIC_PATH = "src/my_planner_medic"
WEB_PARTS = ("app", "dashboard", "vercel")
FAIL_KINDS = ("exception", "late_run", "no_reply", "health")  # 5장 6단계(+ 헬스 연속 실패)
HEALTH_WAIT = timedelta(minutes=3)
HEALTH_POLL_S = 10
SUPPRESS_AFTER = timedelta(minutes=3)
WAKE_GRACE = timedelta(minutes=10)
DEFER_MAX = timedelta(minutes=30)
PIP_TIMEOUT = 1200

DIP = "deploy_in_progress"
TASK_FLAG = "be_task_disabled_by_medic"
RETRY = "deploy_retry"  # 머지 전에 멈춘 배포: 같은 커밋은 한 시간 뒤에 다시(BE를 5분마다 껐다 켜지 않게)
RETRY_AFTER = timedelta(hours=1)
ISSUE_OPS = "issue_ops"
DIRTY_TEXT = "작업 폴더에 손으로 고친 파일이 있어 새 버전을 배포하지 않았어요. PC에서 정리해 주세요."
FF_TEXT = "노트북의 커밋이 원격과 갈라져 새 버전을 배포하지 못했어요. PC에서 git 상태를 확인해 주세요."
BLOCKED_TEXT = "새 버전을 배포하려 했지만 비서를 잠시 멈추지 못해 배포하지 않았어요. 한 시간 뒤 다시 해 볼게요."
BACKUP_TEXT = "새 버전을 배포하기 전 DB 백업에 실패해 배포하지 않았어요. 디스크 공간을 확인해 주세요. 한 시간 뒤 다시 해 볼게요."
DEPLOY_FAILED_TEXT = "새 버전을 배포하다 머지 전에 멈췄어요. 바뀐 것은 없고, 한 시간 뒤 다시 해 볼게요."
TASK_OFF_TEXT = "비서 작업이 꺼져 있거나 상태를 알 수 없어 새 버전을 배포하지 않았어요. 켜 두면 다음 회차에 배포해요."
BRANCH_TEXT = "노트북 저장소가 배포 브랜치가 아닌 곳에 있어 새 버전을 배포하지 않았어요. PC에서 브랜치를 확인해 주세요."
DB_KEPT_TEXT = (
    "자동 배포 롤백을 하지 않았어요: 배포 뒤 오래 지나 DB를 되돌리면 그 사이 기록이 사라지거나, 되돌릴 백업이 없어요. "
    "DB와 코드는 그대로 두었어요(DB kept). 손으로 확인해 주세요."
)
_FAILED_RE = re.compile(r"^failed-(\d+)$")


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def needs_restart(paths: list[str]) -> bool:
    return any(p == r or p.startswith(r) for p in paths for r in RESTART_PATHS)


class DeployError(Exception):
    pass


class RollbackError(Exception):
    pass


class Updater:
    def __init__(
        self,
        cfg: MedicConfig,
        store: MedicStore,
        gh: GitHub,
        http: Http,
        tasks: TaskControl,
        git: GitOps,
        shell: Shell,
        watcher: Watcher,
        notifier: NotifierLike,
        clock: Clock,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._gh = gh
        self._http = http
        self._tasks = tasks
        self._git = git
        self._shell = shell
        self._watcher = watcher
        self._notifier = notifier
        self._clock = clock
        self._sleep = sleep
        self.self_updated = False  # 확인 통과한 배포에 medic 자신이 바뀜 → 09가 끝내고 다시 뜬다
        state = cfg.root / "state"
        self._db = state / "planner.db"
        self._backups = state / "backups"
        self._last_good = state / "medic-last-good.json"

    # --- 바깥 입구 ----------------------------------------------------------

    def tick(self) -> None:
        self._reenable_if_flagged()
        self._flush_issue_ops()
        dip = self._store.kv_json_get(DIP)
        try:
            if isinstance(dip, dict):
                if dip.get("phase") in ("verify", "rollback_verify"):
                    self._advance(dip)
                else:  # deploy·rollback 단계가 남았다 = 이 프로세스 밖에서 끊겼다
                    self.recover_on_start()
                return
            self._refresh_suppression(self._clock.now())
            self._check()
        except GitError as exc:
            log.warning("updater_git_failed %s", exc)
        except Exception as exc:  # noqa: BLE001 - 09 루프가 죽지 않게. 메시지는 남기지 않는다(경로·출력)
            log.warning("updater_tick_failed %s", type(exc).__name__)

    def recover_on_start(self) -> None:
        dip = self._store.kv_json_get(DIP)
        if not isinstance(dip, dict):
            self._reenable_if_flagged()
            return
        phase = dip.get("phase")
        now = self._clock.now()
        if phase in ("verify", "rollback_verify"):
            # 확인 도중 꺼졌다 켜짐: 롤백하지 않고 창을 다시 시작한다(Review Focus 5)
            self._enable_if_medic_disabled()
            dip.update(verify_started_at=None, verify_elapsed_s=0, grace_until=None, window_from=iso_utc(now),
                       last_tick_at=iso_utc(now))
            self._store.kv_json_set(DIP, dip)
            self._store.kv_set("suppress_until", iso_utc(now + SUPPRESS_AFTER))
            self._refresh_suppression(now)
            log.info("updater_resume_verify %s", phase)
            return
        if phase == "deploy":
            try:
                head = self._git.head()
            except GitError:
                head = None
            if head == dip.get("prev_sha"):  # 머지 전에 끊김: 바뀐 것이 없다
                self._enable_if_medic_disabled()
                self._store.kv_delete(DIP)
                self._store.kv_set("suppress_until", iso_utc(now + SUPPRESS_AFTER))
                self._refresh_suppression(now)
                log.info("updater_abandoned_unmerged_deploy")
                return
        self._rollback(dip, {"reason": "interrupted", "fps": []})

    # --- 1~4단계 ------------------------------------------------------------

    def _check(self) -> None:
        now = self._clock.now()
        new = self._git.fetch_main()
        if new is None:
            return
        prev = self._git.head()
        if new == prev:
            return
        if self._git.current_ref() != f"refs/heads/{self._cfg.branch}":
            self._daily(BRANCH_TEXT, "wrong_branch")
            return
        pinned = self._store.kv_get("medic_pinned")
        if not self._git.is_clean([MEDIC_PATH + "/"] if pinned else []):
            self._daily(DIRTY_TEXT, "dirty_tree")
            return
        if self._git.is_ancestor(new, prev):
            return  # 노트북이 앞서 있음: 배포할 것이 없다
        if not self._git.is_ancestor(prev, new):
            self._daily(FF_TEXT, "ff_failed")
            return
        if new in self._bad_shas():
            return
        retry = self._store.kv_json_get(RETRY)
        if isinstance(retry, dict) and retry.get("sha") == new:
            until = _parse(retry.get("until"))
            if until is not None and now < until:
                return
        try:
            ci = self._gh.ci_conclusion(new)  # SHA로만(develop에서 통과한 SHA가 main으로 ff된다)
        except GitHubUnavailable as exc:
            log.warning("updater_ci_unavailable %s (%d)", exc.kind, exc.status)
            return
        if ci != "success":
            log.info("updater_ci_%s", ci)
            return
        changed = self._git.changed_paths(prev, new)
        try:
            repairs = self._gh.repairs_in_range(prev, new)
        except GitHubUnavailable as exc:
            log.warning("updater_compare_unavailable %s (%d)", exc.kind, exc.status)
            return
        if not needs_restart(changed):
            self._fast_forward(prev, new, repairs)
            return
        if self._defer(now):
            return
        self._deploy(prev, new, changed, repairs)

    def _fast_forward(self, prev: str, new: str, repairs: list[int]) -> None:
        if not self._git.merge_ff(new):
            self._daily(FF_TEXT, "ff_failed")
            return
        self._store.kv_set("deployed_sha", new)
        now = self._clock.now()
        for inc in self._by_issue(repairs):
            if inc.part == "be":
                self._resolve(inc, now)
            elif inc.state in ("open", "repairing"):
                self._store.set_state(inc.fingerprint, "merged")
        log.info("updater_fast_forward")

    def _defer(self, now: datetime) -> bool:
        """`/health`에 `running` 회차나 답 기다리는 메시지가 있으면 미룬다. 30분 넘게 미뤘으면 그냥 진행."""
        busy = False
        if self._cfg.api_enabled:
            status, body = self._probe()
            if status == 200 and isinstance(body, dict):
                runs = body.get("runs_today") or []
                busy = any(isinstance(r, dict) and r.get("status") == "running" for r in runs) or bool(
                    body.get("inbound_pending_oldest_at")
                )
        if not busy:
            self._store.kv_delete("deploy_deferred")
            return False
        saved = self._store.kv_json_get("deploy_deferred")
        since = _parse(saved.get("since")) if isinstance(saved, dict) else None
        if since is None:
            self._store.kv_json_set("deploy_deferred", {"since": iso_utc(now)})
            return True
        if now - since > DEFER_MAX:
            log.info("updater_defer_expired")
            return False
        return True

    # --- 5단계: 배포 ----------------------------------------------------------

    def _deploy(self, prev: str, new: str, changed: list[str], repairs: list[int]) -> None:
        if self._tasks.is_enabled() is not True:  # Dahun이 손으로 끈 작업(또는 알 수 없음)은 켜지 않는다
            self._daily(TASK_OFF_TEXT, "task_disabled")
            return
        now = self._clock.now()
        schema_before = self._schema()
        dip: dict[str, Any] = {
            "prev_sha": prev, "new_sha": new, "schema_before": schema_before, "started_at": iso_utc(now),
            "phase": "deploy", "verify_started_at": None, "verify_elapsed_s": 0, "last_tick_at": iso_utc(now),
            "grace_until": None, "window_from": None, "repairs": repairs, "repaired": [],
            "medic_changed": any(p.startswith(MEDIC_PATH + "/") for p in changed), "cause": None, "blamed": [],
        }
        self._store.kv_json_set(DIP, dip)
        self._store.kv_delete("deploy_deferred")
        self._watcher.suppressed = True
        self._store.kv_json_set(TASK_FLAG, True)
        merged = ok = rollback = False
        stage = "stop"
        try:
            self._tasks.disable_stop()
            stage = "backup"
            if schema_before is not None:
                self._backups.mkdir(parents=True, exist_ok=True)
                dbfile.backup_to(self._db, self._backups / f"pre-deploy-{prev}.db")
                dbfile.prune(self._backups, "pre-deploy-*.db", self._cfg.keep_pre_deploy)
            stage = "merge"
            if self._store.kv_get("medic_pinned"):  # 09: 되돌려 둔 medic 파일을 머지 전에 정리
                self._git.checkout_paths("HEAD", [MEDIC_PATH])
            if not self._git.merge_ff(new):
                self._daily(FF_TEXT, "ff_failed")  # 배포 롤백이 아니다: 바뀐 것이 없다
                return
            merged = True
            self._store.kv_delete("medic_pinned")
            self._install("requirements.lock" in changed, strict=True)
            for inc in self._by_issue(repairs):
                if inc.part == "be":
                    self._store.set_state(inc.fingerprint, "deploying")
                    dip["repaired"].append(inc.fingerprint)
                elif inc.state in ("open", "repairing"):
                    self._store.set_state(inc.fingerprint, "merged")  # 웹은 08 WebVerifier
            # 켜기 전에 verify로: 켠 뒤 medic이 죽어도 시작 시 복구가 롤백하지 않고 확인을 이어 간다
            now = self._clock.now()
            dip.update(phase="verify", window_from=iso_utc(now), last_tick_at=iso_utc(now))
            self._store.kv_json_set(DIP, dip)
            ok = True
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 작업은 켠다. 머지 뒤 실패면 배포 롤백
            log.warning("deploy_failed %s", type(exc).__name__)
            rollback = merged
        finally:
            if not rollback:
                self._enable()
                if not ok:
                    self._store.kv_delete(DIP)
                    later = self._clock.now()
                    self._store.kv_json_set(RETRY, {"sha": new, "until": iso_utc(later + RETRY_AFTER)})
                    self._store.kv_set("suppress_until", iso_utc(later + SUPPRESS_AFTER))
                    self._refresh_suppression(later)
        if rollback:
            self._rollback(dip, {"reason": "install", "fps": []})
            return
        if not ok:
            if not merged:
                text, key = {
                    "stop": (BLOCKED_TEXT, "deploy_blocked"), "backup": (BACKUP_TEXT, "backup_failed"),
                }.get(stage, (DEPLOY_FAILED_TEXT, "deploy_failed"))
                self._daily(text, key)
            return
        self._store.kv_set("suppress_until", iso_utc(self._clock.now() + SUPPRESS_AFTER))
        log.info("deploy_done restart=1")
        self._advance(dip)

    def _install(self, lock_changed: bool, *, strict: bool) -> None:
        py = str(venv_python(self._cfg.root))
        steps = ([["-r", "requirements.lock"]] if lock_changed else []) + [["-e", ".", "--no-deps"]]
        for args in steps:
            rc, _ = self._shell.run([py, "-m", "pip", "install", *args], cwd=self._cfg.root, timeout=PIP_TIMEOUT)
            if rc != 0:
                log.warning("pip_install_failed %s rc=%d", args[0], rc)
                if strict:
                    raise DeployError(f"pip install {args[0]} failed")

    # --- 6단계: 확인 ----------------------------------------------------------

    def _advance(self, dip: dict[str, Any]) -> None:
        now = self._clock.now()
        last = _parse(dip.get("last_tick_at")) or now
        gap = (now - last).total_seconds()
        dip["last_tick_at"] = iso_utc(now)
        self._refresh_suppression(now)
        if gap > 2 * self._cfg.deploy_interval_s:  # 잠들었다: 그 구간을 세지 않고 유예 뒤 창을 다시 시작
            log.info("verify_sleep_detected gap=%d", int(gap))
            self._restart_after_sleep(dip, now)
            return
        grace_until = _parse(dip.get("grace_until"))
        if grace_until is not None and now < grace_until:
            self._store.kv_json_set(DIP, dip)
            return
        if dip.get("verify_started_at") is None:
            health = self._await_health()
            if health == "sleep":  # 헬스를 기다리다 잠들었다: 판정하지 않고 유예를 다시 시작
                self._restart_after_sleep(dip, self._clock.now())
                return
            if health == "fail":
                self._verify_failed(dip, {"reason": "health", "fps": []})
                return
            done = self._clock.now()
            dip.update(verify_started_at=iso_utc(done), verify_elapsed_s=0, last_tick_at=iso_utc(done))
            self._store.kv_json_set(DIP, dip)
            return
        dip["verify_elapsed_s"] = int(dip.get("verify_elapsed_s") or 0) + int(gap)
        cause = self._failure(dip)
        if cause is not None:
            self._verify_failed(dip, cause)
            return
        if dip["verify_elapsed_s"] >= self._cfg.verify_minutes * 60:
            self._verify_ok(dip)
            return
        self._store.kv_json_set(DIP, dip)

    def _restart_after_sleep(self, dip: dict[str, Any], now: datetime) -> None:
        grace = now + WAKE_GRACE
        dip.update(verify_started_at=None, verify_elapsed_s=0, grace_until=iso_utc(grace), window_from=iso_utc(grace),
                   last_tick_at=iso_utc(now))
        self._store.kv_json_set(DIP, dip)

    def _failure(self, dip: dict[str, Any]) -> dict[str, Any] | None:
        since = _parse(dip.get("window_from"))
        if since is None:
            return None
        verifying = dip.get("phase") == "verify"
        repaired = set(dip.get("repaired") or [])
        known = repaired | set(dip.get("blamed") or [])
        again: list[str] = []
        fresh: list[str] = []
        for inc in self._store.by_state(*STATES):
            if inc.part != "be":
                continue
            if inc.fingerprint in repaired and verifying:
                last = _parse(inc.last_seen)
                if last is not None and last > since:
                    again.append(inc.fingerprint)
            elif inc.fingerprint not in known and inc.detail.get("kind") in FAIL_KINDS:
                first = _parse(inc.first_seen)
                if first is not None and first > since:
                    fresh.append(inc.fingerprint)
        if again:
            return {"reason": "repaired_again", "fps": again}
        if fresh:
            return {"reason": "new_fingerprint", "fps": fresh}
        return None

    def _verify_failed(self, dip: dict[str, Any], cause: dict[str, Any]) -> None:
        log.warning("verify_failed phase=%s reason=%s", dip.get("phase"), cause.get("reason"))
        if dip.get("phase") == "rollback_verify":
            self._give_up(dip, rolled_back=True)
        else:
            self._rollback(dip, cause)

    def _verify_ok(self, dip: dict[str, Any]) -> None:
        now = self._clock.now()
        if dip.get("phase") == "verify":
            new = str(dip["new_sha"])
            self._store.kv_set("deployed_sha", new)
            self._write_last_good(new)
            for fp in dip.get("repaired") or []:
                inc = self._store.get(fp)
                if inc is not None and inc.state != "resolved":
                    self._resolve(inc, now)
            self.self_updated = bool(dip.get("medic_changed"))
            log.info("verify_ok")
        else:
            log.info("rollback_verify_ok")
        dbfile.prune(self._backups, "pre-deploy-*.db", self._cfg.keep_pre_deploy)
        dbfile.prune(self._backups, "failed-*", self._cfg.keep_failed)
        self._store.kv_delete(DIP)

    def _await_health(self) -> str:
        """`/health`가 3분 안에 `ok`(코드 밖 사유만 있는 `degraded` 포함)면 `"ok"`, 아니면 `"fail"`.

        두 조회 사이 실제 시각이 `2 × HEALTH_POLL_S`보다 벌어지면 잠든 것이라 판정하지 않고 `"sleep"`.
        """
        if not self._cfg.api_enabled:
            return "ok"  # 헬스를 볼 수 없으면 로그 신호로만 확인한다
        start = self._clock.now()
        while True:
            status, body = self._probe()
            if status == 200 and isinstance(body, dict):
                st = body.get("status")
                if st == "ok" or (st == "degraded" and outside_reasons(body, self._clock.now())):
                    return "ok"
            if self._clock.now() - start >= HEALTH_WAIT:
                return "fail"
            before = self._clock.now()
            self._sleep(HEALTH_POLL_S)
            if (self._clock.now() - before).total_seconds() > 2 * HEALTH_POLL_S:
                log.info("health_wait_sleep_detected")
                return "sleep"

    def _probe(self) -> tuple[int, Any]:
        status, body, _ = self._http.request(
            "GET", f"{self._cfg.api_base}/health",
            headers={"Authorization": f"Bearer {self._cfg.api_token}"}, timeout=10,
        )
        return status, body

    # --- 7단계: 배포 롤백 ------------------------------------------------------

    def _rollback(self, dip: dict[str, Any], cause: dict[str, Any]) -> None:
        prev, new = str(dip["prev_sha"]), str(dip["new_sha"])
        if not dip.get("repaired"):  # 설치 실패·머지 뒤 중단: 확인 전에 왔어도 이 범위가 고친 BE 장애
            dip["repaired"] = [i.fingerprint for i in self._by_issue(dip.get("repairs") or []) if i.part == "be"]
        if "ran_new" not in dip:  # BE가 새 코드로 돌았나(확인 단계에서 왔나): DB 되돌리기 나이 제한에 쓴다
            dip["ran_new"] = dip.get("phase") == "verify"
        dip.update(phase="rollback", cause=cause)
        if not dip.get("blamed"):
            dip["blamed"] = list(dip.get("repaired") or []) or self._blame_fps(cause)
        self._store.kv_json_set(DIP, dip)
        bad = self._bad_shas()
        if new not in bad:
            self._store.kv_json_set("bad_shas", [*bad, new])
        rolled = ok = bool(dip.get("actions_done"))
        if not ok:
            refusal = self._rollback_refusal(dip)
            if refusal is not None:
                log.warning("rollback_refused %s", refusal)
                self._give_up(dip, rolled_back=False, note=DB_KEPT_TEXT if refusal.startswith("db_") else None)
                return
            self._store.kv_json_set(TASK_FLAG, True)
        self._watcher.suppressed = True
        try:
            if not ok:  # 켜기 전에 끝났다고 적어 둔다: 켠 뒤 끊겨도 DB를 다시 되돌리지 않는다
                self._tasks.disable_stop()
                pinned = self._store.kv_get("medic_pinned")
                if self._git.is_clean([MEDIC_PATH + "/"] if pinned else []):
                    self._git.reset_hard(prev)
                elif not self._git.reset_keep(prev):  # 손으로 고친 파일은 덮지 않는다
                    raise RollbackError("hand edits block reset")
                rolled = True
                self._store.kv_set("deployed_sha", prev)
                self._install(True, strict=False)  # 5단계와 같은 두 명령. 실패해도 이어서 켠다
                self._rollback_db(dip)
                dip["actions_done"] = True
                self._store.kv_json_set(DIP, dip)
                ok = True
        except Exception as exc:  # noqa: BLE001 - 상태 기계가 끝까지 가야 한다
            log.warning("rollback_failed %s", type(exc).__name__)
        finally:
            self._enable_if_medic_disabled()
        if not ok:
            self._give_up(dip, rolled_back=rolled)
            return
        self._mark_rolled_back(dip)
        now = self._clock.now()
        dip.update(phase="rollback_verify", window_from=iso_utc(now), verify_started_at=None, verify_elapsed_s=0,
                   grace_until=None, last_tick_at=iso_utc(now))
        self._store.kv_json_set(DIP, dip)
        self._store.kv_set("suppress_until", iso_utc(now + SUPPRESS_AFTER))
        log.info("rollback_done")
        self._advance(dip)

    def _rollback_refusal(self, dip: dict[str, Any]) -> str | None:
        """아무것도 건드리기 전에(BE는 아직 돈다) 롤백을 하지 않을 까닭. 없으면 None."""
        if self._store.kv_json_get(TASK_FLAG) is not True and self._tasks.is_enabled() is not True:
            return "task_disabled_by_hand"  # medic이 끈 것이 아니면 켜지도 끄지도 않는다
        try:
            changed = self._schema_changed(dip)
        except sqlite3.Error:
            return "db_unreadable"
        if not changed:
            return None
        if not (self._backups / f"pre-deploy-{dip['prev_sha']}.db").exists():
            return "db_no_backup"
        started = _parse(dip.get("started_at"))
        max_age = timedelta(minutes=self._cfg.db_restore_max_age_minutes)
        if dip.get("ran_new") and started is not None and self._clock.now() - started > max_age:
            return "db_too_old"  # 그 사이 새 코드가 쓴 기록을 지우지 않는다. 옛 코드는 새 스키마를 모른다
        return None

    def _schema_changed(self, dip: dict[str, Any]) -> bool:
        before = dip.get("schema_before")
        if before is None:
            return False
        if (self._backups / f"failed-{dip['new_sha']}" / self._db.name).exists() or not self._db.exists():
            return True  # 옮기기가 이미 시작됐다
        return dbfile.schema_version(self._db) != before

    def _rollback_db(self, dip: dict[str, Any]) -> None:
        """스키마가 바뀐 배포에서만: 지금 DB(+WAL·SHM)를 `failed-<new>/`로 옮기고 배포 직전 백업을 놓는다.

        BE는 꺼져 있다. 중단 뒤 다시 와도 안전하게: 본 파일이 이미 옮겨졌으면 남은 것만 옮기고 복사한다.
        """
        before = dip.get("schema_before")
        if before is None:
            return  # 배포 전에 DB가 없었다: 되돌릴 백업도 없다
        backup = self._backups / f"pre-deploy-{dip['prev_sha']}.db"
        failed = self._backups / f"failed-{dip['new_sha']}"
        if (failed / self._db.name).exists():
            dbfile.move_leftovers(self._db, failed)
        else:
            if not self._db.exists():
                if not backup.exists():
                    return
            elif dbfile.schema_version(self._db) == before:
                return  # 스키마 그대로: DB는 건드리지 않는다(회차·전달 기록 보호)
            if not backup.exists():  # _rollback_refusal이 먼저 막는다. 여기까지 오면 손대지 않고 포기
                raise RollbackError("no backup")
            dbfile.move_with_wal(self._db, failed)
        dbfile.restore(backup, self._db)
        dbfile.prune(self._backups, "failed-*", self._cfg.keep_failed)
        log.info("rollback_db_restored")

    def _blame_fps(self, cause: dict[str, Any]) -> list[str]:
        """사람 커밋 롤백: 롤백을 일으킨 지문. 지문이 없는 실패(헬스·중단·설치)는 `deploy:<사유>`를 만든다."""
        fps = [str(fp) for fp in cause.get("fps") or []]
        if fps:
            return fps
        fp = f"deploy:{cause.get('reason', 'unknown')}"
        now = self._clock.now()
        inc = self._store.upsert_signal(Signal(fp, "be", "health", now), now)
        self._store.set_state(fp, "open", detail={**inc.detail, "kind": "deploy"})
        return [fp]

    def _mark_rolled_back(self, dip: dict[str, Any]) -> None:
        """4.4 `open (다시)` 행: 고친 이슈는 `merged`를 떼고 `rolled-back` + `failed-N`. 사람 커밋이면 범위를 적은 이슈.

        한 번만 한다(`dip["marked"]`): 다시 와도 failed-N을 또 올리지 않는다.
        """
        if dip.get("marked"):
            return
        dip["marked"] = True
        self._store.kv_json_set(DIP, dip)
        if dip.get("repaired"):
            for fp in dip["repaired"]:
                inc = self._store.get(fp)
                if inc is None:
                    continue
                self._store.set_state(fp, "open")
                if inc.issue_number is not None:
                    self._queue_op({"op": "rolled_back", "n": inc.issue_number, "fp": fp, "failed": None})
            self._flush_issue_ops()
            return
        rng = f"{dip['prev_sha']}..{dip['new_sha']}"
        sha = str(dip["prev_sha"])
        for fp in dip.get("blamed") or []:
            inc = self._store.get(fp)
            if inc is None:
                continue
            self._store.set_state(fp, "open", detail={**inc.detail, "rollback_range": rng})
            inc = self._store.get(fp)
            assert inc is not None
            body = issue_body(inc, inc.detail.get("rows") or [], None, sha)
            try:
                if inc.issue_number is None:
                    found = self._gh.find_incident(fp)
                    if found is not None and found.get("state") == "open":
                        n = int(found["number"])
                        self._gh.update_body(n, body)
                    else:
                        n = self._gh.open_incident(fp, "be", body)
                    self._store.set_state(fp, "open", issue_number=n, synced_count=inc.count,
                                          last_synced_at=iso_utc(self._clock.now()))
                else:
                    self._gh.update_body(inc.issue_number, body)
            except GitHubUnavailable as exc:  # 감시자가 같은 본문 틀(범위 포함)로 나중에 올린다
                log.warning("rollback_issue_unavailable %s (%d)", exc.kind, exc.status)

    # --- 8단계: 포기 ----------------------------------------------------------

    def _give_up(self, dip: dict[str, Any], *, rolled_back: bool, note: str | None = None) -> None:
        blamed = list(dip.get("blamed") or []) or list(dip.get("repaired") or [])
        for fp in blamed:
            inc = self._store.get(fp)
            if inc is None:
                continue
            self._store.set_state(fp, "gave_up")
            n = inc.issue_number
            if n is not None:
                self._queue_op({"op": "gave_up", "n": n})
                if note:
                    self._queue_op({"op": "comment", "n": n, "body": note})
            try:
                self._notifier.gave_up(fp, rolled_back, self._gh.issue_url(n) if n is not None else "", direct=True)
            except Exception as exc:  # noqa: BLE001 - 상태 기계가 끝까지 가야 한다
                log.warning("notify_failed %s", type(exc).__name__)
        try:  # 롤백을 못 했으면 새 코드가 그대로다: 하트비트·이슈 본문의 배포된 커밋을 실제 HEAD로
            self._store.kv_set("deployed_sha", self._git.head())
        except GitError:
            pass
        self._keep_enabled()  # BE 작업은 켜 둔 채 둔다(손으로 끈 작업은 켜지 않는다). 마지막 셸 명령
        self._store.kv_delete(DIP)
        now = self._clock.now()
        self._store.kv_set("suppress_until", iso_utc(now + SUPPRESS_AFTER))
        self._refresh_suppression(now)
        self._flush_issue_ops()
        log.warning("updater_gave_up rolled_back=%s", rolled_back)

    # --- 장애·이슈 ------------------------------------------------------------

    def _by_issue(self, numbers: list[int]) -> list[Incident]:
        want = set(numbers)
        return [i for i in self._store.by_state(*STATES) if i.issue_number in want]

    def _resolve(self, inc: Incident, now: datetime) -> None:
        self._store.set_state(inc.fingerprint, "resolved", resolved_at=iso_utc(now))
        if inc.issue_number is None:
            return
        self._queue_op({"op": "close", "n": inc.issue_number})
        try:
            pr = self._gh.pr_for_issue(inc.issue_number)
        except GitHubUnavailable:
            pr = None
        title, url = pr or (inc.fingerprint, self._gh.issue_url(inc.issue_number))
        try:
            self._notifier.fixed(title, url)
        except Exception as exc:  # noqa: BLE001 - 상태 기계가 끝까지 가야 한다
            log.warning("notify_failed %s", type(exc).__name__)
        self._flush_issue_ops()

    def _queue_op(self, op: dict[str, Any]) -> None:
        ops = self._store.kv_json_get(ISSUE_OPS)
        self._store.kv_json_set(ISSUE_OPS, [*(ops if isinstance(ops, list) else []), op])

    def _flush_issue_ops(self) -> None:
        ops = self._store.kv_json_get(ISSUE_OPS)
        if not isinstance(ops, list) or not ops:
            return
        while ops:
            op = ops[0]
            try:
                self._do_op(op, ops)
            except GitHubUnavailable as exc:
                if not exc.rejected:
                    log.warning("issue_op_unavailable %s (%d)", exc.kind, exc.status)
                    break  # 다음 tick에 다시
                log.warning("issue_op_rejected %d", exc.status)
            ops.pop(0)
            self._store.kv_json_set(ISSUE_OPS, ops)

    def _do_op(self, op: dict[str, Any], ops: list[Any]) -> None:
        n = int(op["n"])
        kind = op.get("op")
        if kind == "close":
            self._gh.close(n)
        elif kind == "gave_up":
            self._gh.add_labels(n, ["needs-dahun"])
        elif kind == "comment":
            self._gh.comment(n, str(op.get("body", "")))
        elif kind == "rolled_back":
            if op.get("failed") is None:  # 로컬 failures가 아니라 라벨에서(Actions도 올린다)
                labels = self._gh.issue_labels(n)
                op["failed"] = max((int(m[1]) for x in labels if (m := _FAILED_RE.match(x))), default=0) + 1
                self._store.kv_json_set(ISSUE_OPS, ops)  # 다시 해도 같은 N
            failed = int(op["failed"])
            self._gh.remove_label(n, "merged")
            self._gh.add_labels(n, ["rolled-back", f"failed-{failed}"])  # 한 번에: repair 게이트가 N을 본다
            fp = op.get("fp")
            inc = self._store.get(fp) if isinstance(fp, str) else None
            if inc is not None:
                self._store.set_state(inc.fingerprint, inc.state, failures=failed)

    # --- 바탕 ---------------------------------------------------------------

    def _enable(self) -> None:
        if self._tasks.enable_start():
            self._store.kv_json_set(TASK_FLAG, False)

    def _enable_if_medic_disabled(self) -> None:
        if self._store.kv_json_get(TASK_FLAG) is True:
            self._enable()

    def _keep_enabled(self) -> None:
        """medic이 끈 작업은 켜고, 이미 켜진 작업은 켜고 시작한 상태로 둔다. 꺼졌거나 모르는 작업은 건드리지 않는다."""
        if self._store.kv_json_get(TASK_FLAG) is True or self._tasks.is_enabled() is True:
            self._enable()

    def _reenable_if_flagged(self) -> None:
        dip = self._store.kv_json_get(DIP)
        busy = isinstance(dip, dict) and dip.get("phase") in ("deploy", "rollback")
        if self._store.kv_json_get(TASK_FLAG) is True and not busy:
            self._enable()

    def _refresh_suppression(self, now: datetime) -> None:
        until = _parse(self._store.kv_get("suppress_until"))
        self._watcher.suppressed = until is not None and now < until

    def _schema(self) -> int | None:
        if not self._db.exists():
            return None
        return dbfile.schema_version(self._db)

    def _bad_shas(self) -> list[str]:
        bad = self._store.kv_json_get("bad_shas")
        return [str(x) for x in bad] if isinstance(bad, list) else []

    def _daily(self, text: str, key: str) -> None:
        try:
            self._notifier.daily(text, key)
        except Exception as exc:  # noqa: BLE001 - 상태 기계가 끝까지 가야 한다
            log.warning("notify_failed %s", type(exc).__name__)

    def _write_last_good(self, sha: str) -> None:
        tmp = self._last_good.with_name(self._last_good.name + ".tmp")
        tmp.write_text(json.dumps({"sha": sha}), encoding="utf-8")
        os.replace(tmp, self._last_good)

from __future__ import annotations

import base64
import filecmp
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from my_planner_medic import updater as updater_mod
from my_planner_medic.github import GitHub
from my_planner_medic.gitops import GitOps
from my_planner_medic.signals import Signal
from my_planner_medic.store import MedicStore, iso_utc
from my_planner_medic.tasks import FIND_BE_PIDS, POWERSHELL, TaskControl
from my_planner_medic.updater import Updater
from my_planner_medic.watcher import Watcher

from .fakes import (
    FakeClock,
    FakeGitHub,
    FakeHttp,
    FakeNotifier,
    FakeResponse,
    FakeShell,
    make_config,
)

REPO = "o/r"
HEALTH = "/api/v1/health"
RUNS = f"/repos/{REPO}/actions/runs"
START = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)  # 월 10:00 KST
PREV = "a" * 40
NEW = "b" * 40
TOKEN = "ghp_TOPSECRETtoken123"
API_TOKEN = "t" * 43
HEALTHY: dict[str, Any] = {"status": "ok", "polling": "up", "runs_today": []}
FP = "be:KeyError src/my_planner/tools/todos.py:list_todos"


class GitShell(FakeShell):
    """머지·리셋이 성공하면 `HEAD`를 옮기는 FakeShell."""

    def run(self, args: list[str], **kw: Any) -> tuple[int, str]:  # type: ignore[override]
        rc, out = super().run(args, **kw)
        if rc == 0 and args[:3] in (["git", "merge", "--ff-only"], ["git", "reset", "--hard"]):
            self.on("git", "rev-parse", "HEAD", returns=(0, args[-1] + "\n"))
        return rc, out


@dataclass
class Env:
    root: Path
    clock: FakeClock
    server: FakeGitHub
    http: FakeHttp
    shell: GitShell
    store: MedicStore
    watcher: Watcher
    notifier: FakeNotifier
    updater: Updater
    cfg: Any

    @property
    def db(self) -> Path:
        return self.root / "state" / "planner.db"

    @property
    def cmds(self) -> list[str]:
        return [" ".join(c) for c in self.shell.commands]

    def has(self, needle: str) -> bool:
        return any(needle in c for c in self.cmds)

    def tick(self, minutes: float = 0) -> None:
        self.clock.advance(minutes=minutes)
        self.updater.tick()

    def ci(self, sha: str = NEW, status: str = "completed", conclusion: str | None = "success") -> None:
        self.server.runs = [r for r in self.server.runs if r["head_sha"] != sha]
        self.server.runs.append({
            "id": len(self.server.runs) + 1, "name": "ci", "head_sha": sha, "event": "push",
            "branch": self.cfg.branch, "status": status, "conclusion": conclusion,
            "created_at": "2026-10-26T00:00:00Z",
        })

    def changed(self, *paths: str) -> None:
        self.shell.on("git", "diff", "--name-only", "-z", PREV, NEW, returns=(0, "".join(p + "\0" for p in paths)))

    def health(self, status: int, body: Any = None) -> None:
        self.http.clear("GET", HEALTH)
        self.http.queue("GET", HEALTH, FakeResponse(status, body))

    def incident(self, fp: str, *, issue: int | None, state: str = "merged", part: str = "be",
                 kind: str = "exception", labels: tuple[str, ...] = ("incident", "be", "merged")) -> int | None:
        if issue is not None:
            self.server._next = issue
            issue = self.server.add_issue(f"[incident] {fp}", list(labels))
        self.store.upsert_signal(Signal(fp, part, kind, self.clock.now()), self.clock.now())  # type: ignore[arg-type]
        self.store.set_state(fp, state, issue_number=issue, detail={"kind": kind})
        return issue

    def signal(self, fp: str, kind: str = "exception") -> None:
        """감시자가 1분 뒤 그 지문을 기록한 것처럼."""
        self.clock.advance(minutes=1)
        inc = self.store.upsert_signal(Signal(fp, "be", kind, self.clock.now()), self.clock.now())  # type: ignore[arg-type]
        if "kind" not in inc.detail:
            self.store.set_state(fp, inc.state, detail={**inc.detail, "kind": kind})

    def dip(self) -> Any:
        return self.store.kv_json_get("deploy_in_progress")


def make_db(path: Path, version: int, rows: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS t(a)")
    conn.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(rows)])
    conn.execute(f"PRAGMA user_version={version}")
    conn.commit()
    conn.close()


def make_env(tmp_path: Path, *, repairs: list[int] | None = None, **cfg: Any) -> Env:
    clock = FakeClock(START)
    server = FakeGitHub(REPO, clock)
    http = FakeHttp(route=server.route)
    http.queue("GET", HEALTH, FakeResponse(200, HEALTHY))
    values: dict[str, Any] = {"api_token": API_TOKEN, "github_token": TOKEN, "repo": REPO}
    values.update(cfg)
    config = make_config(tmp_path, **values)
    make_db(tmp_path / "state" / "planner.db", 1)
    shell = GitShell()
    remote = f"refs/remotes/origin/{config.branch}"
    shell.on("git", "rev-parse", "--verify", remote, returns=(0, NEW + "\n"))
    shell.on("git", "rev-parse", "HEAD", returns=(0, PREV + "\n"))
    shell.on("git", "merge-base", "--is-ancestor", NEW, PREV, returns=(1, ""))
    store = MedicStore(tmp_path / "state" / "medic.db")
    gh = GitHub(http, TOKEN, REPO)
    watcher = Watcher(config, store, gh, http, clock)
    notifier = FakeNotifier()
    tasks = TaskControl(
        shell, tmp_path, name=config.be_task_name, sleep=lambda s: clock.advance(seconds=s),
        monotonic=lambda: clock.now().timestamp(), own_pid=4242,
    )
    git = GitOps(shell, tmp_path, TOKEN, branch=config.branch)
    up = Updater(config, store, gh, http, tasks, git, shell, watcher, notifier, clock,
                 sleep=lambda s: clock.advance(seconds=s))
    msgs = [f"fix: thing\n\nRepairs #{n}" for n in repairs or []] or ["feat: human change"]
    server.compares[(PREV, NEW)] = msgs
    env = Env(tmp_path, clock, server, http, shell, store, watcher, notifier, up, config)
    env.ci()
    env.changed("src/my_planner/tools/todos.py")
    return env


def deployed(env: Env) -> None:
    """배포 tick 하나: 끝나면 확인 단계."""
    env.tick()
    assert env.has("merge --ff-only")
    assert env.dip()["phase"] == "verify"


# --- 1~2단계 --------------------------------------------------------------


def test_git_token_never_in_argv(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    env = make_env(tmp_path)
    deployed(env)
    b64 = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    for call in env.shell.calls:
        joined = " ".join(call.args)
        assert TOKEN not in joined and b64 not in joined
    git_calls = [c for c in env.shell.calls if c.args[0] == "git"]
    assert git_calls
    for c in git_calls:
        assert c.env is not None
        assert c.env["GIT_TERMINAL_PROMPT"] == "0"
        assert c.env["GCM_INTERACTIVE"] == "never"
        assert c.env["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: basic {b64}"
    assert TOKEN not in caplog.text and b64 not in caplog.text


def test_no_new_commit_noop(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.shell.on("git", "rev-parse", "--verify", "refs/remotes/origin/main", returns=(0, PREV))
    env.tick()
    assert not env.has("merge --ff-only") and not env.has("Disable-ScheduledTask")
    assert env.http.calls("GET", RUNS) == []
    assert env.dip() is None


def test_ci_pending_waits(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.ci(status="in_progress", conclusion=None)
    env.tick()
    assert not env.has("merge --ff-only")
    env.ci()
    env.tick(5)
    assert env.has("merge --ff-only")


def test_ci_failure_skips_commit(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.ci(conclusion="failure")
    env.tick()
    env.tick(5)
    assert not env.has("merge --ff-only") and not env.has("Disable-ScheduledTask")


def test_ci_unknown_does_not_deploy(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.server.runs = []  # 실행 없음 → unknown
    env.tick()
    assert not env.has("merge --ff-only")
    env.ci()
    env.http.queue("GET", RUNS, FakeResponse(502))  # 조회 실패
    env.tick(5)
    env.http.clear("GET", RUNS)
    env.http.queue("GET", RUNS, FakeResponse(401))
    env.tick(5)
    assert not env.has("merge --ff-only") and not env.has("Disable-ScheduledTask")


def test_bad_sha_skipped(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.store.kv_json_set("bad_shas", [NEW])
    env.tick()
    assert not env.has("merge --ff-only")
    assert env.http.calls("GET", RUNS) == []


# --- 3단계: ff만 ------------------------------------------------------------


def test_docs_only_change_fast_forwards_without_restart(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.changed("docs/notes.md", "web/app/src/x.ts")
    env.tick()
    assert env.has(f"merge --ff-only --quiet {NEW}")
    assert not env.has("Disable-ScheduledTask") and not env.has("pip")
    assert env.store.kv_get("deployed_sha") == NEW
    assert env.dip() is None


def test_ff_only_marks_web_incident_merged(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[21, 22])
    env.changed("web/app/src/x.ts")
    env.incident("app:TypeError /today", issue=21, state="repairing", part="app", kind="client_error")
    env.incident(FP, issue=22, state="repairing")
    env.server.pulls.append({"title": "fix: todos", "html_url": "https://x/pr/9", "state": "closed",
                             "merged_at": "2026-10-26T00:00:00Z", "body": "Repairs #22"})
    env.tick()
    assert env.store.get("app:TypeError /today").state == "merged"  # 웹 확인(08)이 맡는다
    be = env.store.get(FP)
    assert be.state == "resolved"  # BE 장애가 ff만 커밋으로 들어오면 바로 resolved
    assert env.server.issues[22]["state"] == "closed"
    assert env.server.issues[21]["state"] == "open"
    assert env.notifier.fixed_calls == [("fix: todos", "https://x/pr/9")]


# --- 4단계: 기다리기 -------------------------------------------------------


def test_defers_while_run_running_up_to_30_minutes(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    busy = {**HEALTHY, "runs_today": [{"loop": "morning_brief", "status": "running"}]}
    env.health(200, busy)
    env.tick()
    assert not env.has("Disable-ScheduledTask")
    for _ in range(6):  # 30분까지는 미룬다
        env.tick(5)
        assert not env.has("Disable-ScheduledTask")
    env.http.queue("GET", HEALTH, FakeResponse(200, busy), FakeResponse(200, HEALTHY))
    env.tick(1)  # 31분: 그냥 진행
    assert env.has("Disable-ScheduledTask")


def test_defers_while_inbound_pending_then_deploys_when_idle(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.health(200, {**HEALTHY, "inbound_pending_oldest_at": "2026-10-26T00:59:00+00:00"})
    env.tick()
    assert not env.has("Disable-ScheduledTask")
    env.health(200, HEALTHY)
    env.tick(5)
    assert env.has("Disable-ScheduledTask")


# --- 5단계: 배포 ------------------------------------------------------------


def test_deploy_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_env(tmp_path)
    env.changed("src/my_planner/x.py", "requirements.lock")
    events: list[str] = []
    real_schema, real_backup = updater_mod.dbfile.schema_version, updater_mod.dbfile.backup_to

    def schema(db: Path) -> int:
        events.append("schema_version")
        return real_schema(db)

    def backup(db: Path, dest: Path) -> None:
        events.append(f"backup {dest.name}")
        real_backup(db, dest)

    monkeypatch.setattr(updater_mod.dbfile, "schema_version", schema)
    monkeypatch.setattr(updater_mod.dbfile, "backup_to", backup)
    real_set = env.store.kv_json_set

    def kv_set(key: str, value: Any) -> None:
        if key == "deploy_in_progress" and "kv" not in events:
            events.append("kv")
        real_set(key, value)

    monkeypatch.setattr(env.store, "kv_json_set", kv_set)
    real_run = env.shell.run

    def run(args: list[str], **kw: Any) -> tuple[int, str]:
        joined = " ".join(args)
        for needle, name in (("Disable-ScheduledTask", "disable_stop"), ("merge --ff-only", "merge"),
                             ("pip install -r", "pip -r"), ("pip install -e . --no-deps", "pip -e"),
                             ("Enable-ScheduledTask", "enable_start")):
            if needle in joined:
                events.append(name)
        return real_run(args, **kw)

    monkeypatch.setattr(env.shell, "run", run)
    env.tick()
    assert events[:8] == [
        "schema_version", "kv", "disable_stop", f"backup pre-deploy-{PREV}.db", "merge", "pip -r", "pip -e",
        "enable_start",
    ]
    assert "Stop-ScheduledTask" in next(c for c in env.cmds if "Disable-ScheduledTask" in c)
    assert "Start-ScheduledTask" in next(c for c in env.cmds if "Enable-ScheduledTask" in c)
    assert (tmp_path / "state" / "backups" / f"pre-deploy-{PREV}.db").exists()
    dip = env.dip()
    assert dip["prev_sha"] == PREV and dip["new_sha"] == NEW and dip["schema_before"] == 1
    py = str(updater_mod.venv_python(tmp_path))
    assert [py, "-m", "pip", "install", "-e", ".", "--no-deps"] in env.shell.commands


def test_deploy_without_lock_change_skips_pip_r(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    deployed(env)
    assert not env.has("pip install -r") and env.has("pip install -e . --no-deps")


def test_staging_branch_and_task_name_are_configurable(tmp_path: Path) -> None:
    env = make_env(tmp_path, branch="develop", be_task_name="my-planner-dev")
    deployed(env)
    assert env.has("fetch --quiet --no-tags origin +refs/heads/develop:refs/remotes/origin/develop")
    assert env.has("rev-parse --verify refs/remotes/origin/develop")
    disable = next(c for c in env.cmds if "Disable-ScheduledTask" in c)
    enable = next(c for c in env.cmds if "Enable-ScheduledTask" in c)
    assert "-TaskName my-planner-dev |" in disable and "Stop-ScheduledTask -TaskName my-planner-dev" in disable
    assert "Start-ScheduledTask -TaskName my-planner-dev" in enable
    assert not any("-TaskName my-planner " in c or c.endswith("-TaskName my-planner") for c in env.cmds)
    assert env.http.calls("GET", RUNS)[0].query["branch"] == "develop"


def test_be_process_filter_matches_root_and_excludes_medic(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    query = FIND_BE_PIDS.format(root=str(tmp_path), own_pid=4242)
    env.shell.on(*POWERSHELL, query, returns=[(0, "5150\r\n4242\r\n"), (0, "")])  # 죽인 뒤에는 없음
    deployed(env)
    assert str(tmp_path).lower() in query.lower()
    assert "-ne 4242" in query and "my_planner(\\s|$)" in query
    assert env.has("taskkill /T /F /PID 5150")
    assert not env.has("taskkill /T /F /PID 4242")


def test_be_still_running_after_kill_aborts_deploy(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    query = FIND_BE_PIDS.format(root=str(tmp_path), own_pid=4242)
    env.shell.on(*POWERSHELL, query, returns=(0, "5150\r\n"))
    env.tick()
    assert not env.has("merge --ff-only") and not env.has("pre-deploy")
    assert "Enable-ScheduledTask" in env.cmds[-1]
    assert env.dip() is None


def test_disable_failure_aborts_deploy_and_reenables(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.shell.on("powershell", "-NoProfile", "-NonInteractive", "-Command",
                 returns=(1, "Access is denied."))
    env.tick()
    assert not env.has("merge --ff-only")
    assert "Enable-ScheduledTask" in env.cmds[-1]
    assert env.dip() is None
    assert env.store.kv_json_get("bad_shas") in (None, [])
    assert [k for _, k in env.notifier.daily_calls] == ["deploy_blocked"]
    n = len(env.cmds)
    env.tick(5)  # 같은 커밋으로 BE를 5분마다 껐다 켜지 않는다
    assert not any("Disable-ScheduledTask" in c for c in env.cmds[n:])
    env.shell.rules = [r for r in env.shell.rules if r[0][:1] != ("powershell",)]
    env.tick(60)
    assert env.has("merge --ff-only")


def test_always_reenables_when_deploy_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_env(tmp_path)

    def boom(db: Path, dest: Path) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(updater_mod.dbfile, "backup_to", boom)
    env.tick()
    assert env.has("Disable-ScheduledTask")
    assert not env.has("merge --ff-only")
    assert "Enable-ScheduledTask" in env.cmds[-1] and "Start-ScheduledTask" in env.cmds[-1]
    assert env.dip() is None
    assert env.watcher.suppressed is True  # 켠 뒤 3분은 조용히


def test_always_reenables_when_install_raises_after_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_env(tmp_path)
    real_run = env.shell.run

    def run(args: list[str], **kw: Any) -> tuple[int, str]:
        if "pip" in args:
            raise OSError("boom")
        return real_run(args, **kw)

    monkeypatch.setattr(env.shell, "run", run)
    env.tick()  # 머지 뒤 실패 → 배포 롤백
    assert env.has(f"reset --hard --quiet {PREV}")
    assert "Enable-ScheduledTask" in env.cmds[-1]
    assert env.store.kv_json_get("bad_shas") == [NEW]


# --- 6단계: 확인 ------------------------------------------------------------


def test_verify_success_resolves_repaired_incidents_and_notifies_once(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    env.server.pulls.append({"title": "fix: todos", "html_url": "https://x/pr/3", "state": "closed",
                             "merged_at": "2026-10-26T00:00:00Z", "body": "Repairs #17"})
    deployed(env)
    assert env.store.get(FP).state == "deploying"
    for _ in range(3):  # 15분 동안 깨끗
        env.tick(5)
    assert env.server.issues[17]["state"] == "closed"
    assert env.store.get(FP).state == "resolved"
    assert env.notifier.fixed_calls == [("fix: todos", "https://x/pr/3")]
    assert env.store.kv_get("deploy_in_progress") is None
    assert env.store.kv_get("deployed_sha") == NEW
    assert json.loads((tmp_path / "state" / "medic-last-good.json").read_text()) == {"sha": NEW}
    env.tick(5)
    assert len(env.notifier.fixed_calls) == 1
    assert not env.has("reset --hard")


def test_verify_fails_when_health_not_ok_within_3_minutes(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.health(503)
    env.tick()
    assert env.has(f"reset --hard --quiet {PREV}")


def test_verify_fails_on_same_repaired_fingerprint(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    deployed(env)
    env.clock.advance(minutes=4)
    env.signal(FP)
    env.tick(1)
    assert env.has(f"reset --hard --quiet {PREV}")
    assert env.notifier.fixed_calls == []


def test_verify_fails_on_new_fingerprint_but_not_old_one(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.incident("be:Old x.py:f", issue=None, state="open")  # 배포 전부터 있던 장애
    deployed(env)
    env.clock.advance(minutes=4)
    env.signal("be:Old x.py:f")
    env.tick(1)
    assert not env.has("reset --hard")
    env.signal("late_run:morning_brief", kind="late_run")
    env.tick(5)
    assert env.has("reset --hard")


# --- 7단계: 배포 롤백 -------------------------------------------------------


def test_rollback_code_only_when_schema_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17, labels=("incident", "be", "merged", "failed-1"))
    restored: list[Any] = []
    monkeypatch.setattr(updater_mod.dbfile, "restore", lambda *a: restored.append(a))
    deployed(env)
    db_before = env.db.read_bytes()
    env.signal("be:New y.py:g")
    env.tick(5)
    assert env.has(f"reset --hard --quiet {PREV}")
    assert restored == []
    assert env.db.read_bytes() == db_before
    assert env.store.kv_json_get("bad_shas") == [NEW]
    assert env.store.kv_get("deployed_sha") == PREV
    labels = env.server.labels(17)
    assert "merged" not in labels and "rolled-back" in labels and "failed-2" in labels
    inc = env.store.get(FP)
    assert inc.state == "open" and inc.failures == 2
    assert env.dip()["phase"] == "rollback_verify"
    reset_at = next(i for i, c in enumerate(env.cmds) if "reset --hard" in c)
    disable_at = max(i for i, c in enumerate(env.cmds[:reset_at]) if "Disable-ScheduledTask" in c)
    assert disable_at < reset_at
    assert "Enable-ScheduledTask" in env.cmds[-1]


def test_rollback_restores_db_when_schema_changed(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    deployed(env)
    backup = tmp_path / "state" / "backups" / f"pre-deploy-{PREV}.db"
    live = sqlite3.connect(env.db)  # 새 코드의 마이그레이션 + 체크포인트 안 된 WAL
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("INSERT INTO t VALUES(100)")
    live.execute("PRAGMA user_version=2")
    live.commit()
    assert Path(f"{env.db}-wal").exists()
    env.signal(FP)
    env.tick(5)
    failed = tmp_path / "state" / "backups" / f"failed-{NEW}"
    names = {p.name for p in failed.iterdir()}
    assert {"planner.db", "planner.db-wal"} <= names
    assert filecmp.cmp(backup, env.db, shallow=False)
    assert not Path(f"{env.db}-wal").exists()
    live.close()
    check = sqlite3.connect(failed / "planner.db")
    assert check.execute("PRAGMA user_version").fetchone() == (2,)  # 손으로 되살릴 수 있다
    check.close()


def test_rollback_of_human_commit_opens_new_issue_with_range(tmp_path: Path) -> None:
    env = make_env(tmp_path)  # Repairs 없음 = 사람 커밋
    deployed(env)
    env.signal("be:New y.py:g")
    env.tick(5)
    assert env.has(f"reset --hard --quiet {PREV}")
    found = env.server.titled("[incident] be:New y.py:g")
    assert len(found) == 1
    assert f"{PREV}..{NEW}" in found[0]["body"]
    inc = env.store.get("be:New y.py:g")
    assert inc.issue_number == found[0]["number"] and inc.state == "open"
    env.watcher.tick()  # 감시자가 같은 지문으로 이슈를 또 열지 않고 본문도 범위를 지킨다
    assert len(env.server.titled("[incident] be:New y.py:g")) == 1


def test_rollback_of_human_commit_on_health_failure_opens_deploy_issue(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.health(503)
    env.http.queue("GET", HEALTH, *([FakeResponse(503)] * 19), FakeResponse(200, HEALTHY))
    env.tick()
    found = env.server.titled("[incident] deploy:health")
    assert len(found) == 1 and f"{PREV}..{NEW}" in found[0]["body"]


# --- 8단계 -----------------------------------------------------------------


def test_rollback_verify_failure_gives_up_and_keeps_task_enabled(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    deployed(env)
    env.signal(FP)
    env.tick(5)
    assert env.dip()["phase"] == "rollback_verify"
    env.signal("no_reply", kind="no_reply")
    env.tick(5)
    assert env.store.get(FP).state == "gave_up"
    assert "needs-dahun" in env.server.labels(17)
    assert env.notifier.gave_up_calls == [(FP, True, f"https://github.com/{REPO}/issues/17", True)]
    assert "Enable-ScheduledTask" in env.cmds[-1] and "Start-ScheduledTask" in env.cmds[-1]
    assert env.dip() is None
    env.tick(5)
    assert len(env.notifier.gave_up_calls) == 1


def test_rollback_verify_success_keeps_incident_open_for_next_attempt(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    deployed(env)
    env.signal(FP)
    env.tick(5)
    for _ in range(3):
        env.tick(5)
    assert env.dip() is None
    assert env.store.get(FP).state == "open"
    assert env.notifier.fixed_calls == [] and env.notifier.gave_up_calls == []
    assert env.store.kv_get("deployed_sha") == PREV


# --- 시작 시 복구, 절전 -------------------------------------------------------


def test_startup_with_deploy_in_progress_completes_rollback_and_enables_task(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    env.store.kv_json_set("deploy_in_progress", {
        "prev_sha": PREV, "new_sha": NEW, "schema_before": 1, "started_at": iso_utc(START), "phase": "deploy",
        "verify_started_at": None, "verify_elapsed_s": 0,
    })
    env.store.kv_json_set("be_task_disabled_by_medic", True)
    env.shell.on("git", "rev-parse", "HEAD", returns=(0, NEW))  # 머지까지 하고 죽었다
    env.clock.advance(hours=3)
    env.updater.recover_on_start()
    assert env.has(f"reset --hard --quiet {PREV}")
    assert env.has("pip install -e . --no-deps")
    assert "Enable-ScheduledTask" in env.cmds[-1] and "Start-ScheduledTask" in env.cmds[-1]
    assert env.store.kv_json_get("bad_shas") == [NEW]
    assert env.dip()["phase"] == "rollback_verify"
    assert env.store.kv_json_get("be_task_disabled_by_medic") is False


def test_startup_after_finished_rollback_actions_does_not_restore_again(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    env.store.kv_json_set("deploy_in_progress", {
        "prev_sha": PREV, "new_sha": NEW, "schema_before": 1, "started_at": iso_utc(START), "phase": "rollback",
        "actions_done": True, "repaired": [FP], "blamed": [FP],
    })
    env.updater.recover_on_start()  # 켠 직후 끊겼다: BE가 이미 새 기록을 썼을 수 있다
    assert not env.has("reset --hard") and not env.has("Disable-ScheduledTask")
    assert "Enable-ScheduledTask" in env.cmds[-1]
    assert env.dip()["phase"] == "rollback_verify"


def test_startup_with_unmerged_deploy_only_reenables(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.store.kv_json_set("deploy_in_progress", {
        "prev_sha": PREV, "new_sha": NEW, "schema_before": 1, "started_at": iso_utc(START), "phase": "deploy",
    })
    env.updater.recover_on_start()  # HEAD == prev: 머지 전에 죽었다
    assert not env.has("reset --hard")
    assert "Enable-ScheduledTask" in env.cmds[-1]
    assert env.dip() is None and env.store.kv_json_get("bad_shas") in (None, [])


def test_startup_reenables_task_medic_left_disabled(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.store.kv_json_set("be_task_disabled_by_medic", True)
    env.updater.recover_on_start()
    assert env.cmds and "Enable-ScheduledTask" in env.cmds[-1]


def test_startup_does_not_touch_task_medic_did_not_disable(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.updater.recover_on_start()  # Dahun이 손으로 끈 작업은 켜지 않는다
    assert not env.has("Enable-ScheduledTask")


def test_sleep_during_verify_restarts_window(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    deployed(env)
    env.tick(5)
    assert env.dip()["verify_elapsed_s"] == 300
    env.health(0)  # 깨어난 직후 BE가 아직 안 붙음
    env.tick(90)  # 잠듦
    dip = env.dip()
    assert dip["verify_elapsed_s"] == 0 and dip["verify_started_at"] is None
    env.signal("late_run:morning_brief", kind="late_run")  # 절전 탓 신호는 세지 않는다
    env.tick(5)  # 유예 안
    assert not env.has("reset --hard")
    env.health(200, HEALTHY)
    env.tick(5)  # 유예 끝 → 헬스 다시 확인, 창 다시 시작
    assert env.dip()["verify_started_at"] is not None and env.dip()["verify_elapsed_s"] == 0
    env.tick(5)
    assert env.dip() is not None  # 5분만으로는 끝나지 않는다
    env.tick(5)
    assert env.dip() is None
    assert not env.has("reset --hard")
    assert env.store.get(FP).state == "resolved"


def test_startup_during_verify_resumes_without_rollback(tmp_path: Path) -> None:
    env = make_env(tmp_path, repairs=[17])
    env.incident(FP, issue=17)
    deployed(env)
    env.clock.advance(hours=2)  # 꺼졌다 켜짐
    env.updater.recover_on_start()
    assert not env.has("reset --hard")
    assert env.dip()["phase"] == "verify"
    for _ in range(3):
        env.tick(5)
    assert env.store.get(FP).state == "resolved"


# --- Review Focus 4 ----------------------------------------------------------


def test_dirty_tree_never_resets(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.shell.on("git", "status", returns=(0, " M src/my_planner/app.py\0"))
    env.tick()
    env.tick(5)
    assert not env.has("reset") and not env.has("checkout") and not env.has("merge --ff-only")
    assert not env.has("Disable-ScheduledTask")
    assert {k for _, k in env.notifier.daily_calls} == {"dirty_tree"}


def test_ff_only_failure_is_not_rollback(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.shell.on("git", "merge", "--ff-only", returns=(128, "fatal: Not possible to fast-forward"))
    env.tick()
    assert not env.has("reset") and not env.has("checkout")
    assert "Enable-ScheduledTask" in env.cmds[-1]
    assert env.dip() is None
    assert env.store.kv_json_get("bad_shas") in (None, [])
    assert [k for _, k in env.notifier.daily_calls] == ["ff_failed"]


def test_diverged_local_commit_is_not_deployed(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.shell.on("git", "merge-base", "--is-ancestor", PREV, NEW, returns=(1, ""))
    env.tick()
    assert not env.has("Disable-ScheduledTask") and not env.has("reset") and not env.has("merge --ff-only")
    assert [k for _, k in env.notifier.daily_calls] == ["ff_failed"]


# --- 보관, 감시자 -----------------------------------------------------------


def test_prune_keeps_5_pre_deploy_and_3_failed(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    backups = tmp_path / "state" / "backups"
    backups.mkdir(parents=True)
    for i in range(7):
        p = backups / f"pre-deploy-{i:040d}.db"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    for i in range(5):
        d = backups / f"failed-{i:040d}"
        d.mkdir()
        (d / "planner.db").write_bytes(b"x")
        os.utime(d, (1000 + i, 1000 + i))
    deployed(env)
    for _ in range(3):
        env.tick(5)
    assert env.dip() is None
    pre = sorted(p.name for p in backups.glob("pre-deploy-*.db"))
    assert len(pre) == 5 and f"pre-deploy-{PREV}.db" in pre
    assert sorted(p.name for p in backups.glob("failed-*")) == [f"failed-{i:040d}" for i in (2, 3, 4)]


def test_watcher_suppressed_during_deploy_and_3_minutes_after(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    seen: list[bool] = []
    real_run = env.shell.run

    def run(args: list[str], **kw: Any) -> tuple[int, str]:
        if "Disable-ScheduledTask" in " ".join(args):
            seen.append(env.watcher.suppressed)
        return real_run(args, **kw)

    env.shell.run = run  # type: ignore[method-assign]
    deployed(env)
    assert seen == [True]
    assert env.watcher.suppressed is True
    env.tick(2)
    assert env.watcher.suppressed is True
    env.tick(2)
    assert env.watcher.suppressed is False

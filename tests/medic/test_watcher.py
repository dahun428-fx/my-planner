from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from my_planner_medic import watcher as watcher_mod
from my_planner_medic.github import GitHub
from my_planner_medic.store import MedicStore
from my_planner_medic.watcher import Watcher, _trim_rows

from .fakes import (
    FakeClock,
    FakeGitHub,
    FakeHttp,
    FakeNotifier,
    FakeResponse,
    make_config,
)

REPO = "o/r"
ISSUES = f"/repos/{REPO}/issues"
HEALTH = "/api/v1/health"
START = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)  # 월 10:00 KST
HEALTHY: dict[str, Any] = {"status": "ok", "polling": "up", "runs_today": []}
API_TOKEN = "a" * 43
EXC_FP = "be:KeyError src/my_planner/tools/todos.py:list_todos"


@dataclass
class Env:
    root: Path
    clock: FakeClock
    server: FakeGitHub
    http: FakeHttp
    store: MedicStore
    watcher: Watcher
    heartbeat_issue: int

    def log(self, *records: dict[str, Any]) -> None:
        log_dir = self.root / "state" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "my-planner.jsonl").open("a", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def exc(self, **extra: Any) -> dict[str, Any]:
        return {
            "ts": self.clock.now().isoformat(timespec="milliseconds"),
            "level": "ERROR",
            "logger": "my_planner.tools",
            "msg": "tool_failed",
            "exc_type": "KeyError",
            "exc_where": [f"{self.root}/src/my_planner/tools/todos.py:40 list_todos"],
            **extra,
        }

    def tick(self, minutes: float = 0) -> None:
        self.clock.advance(minutes=minutes)
        self.watcher.tick()

    def health(self, status: int, body: Any = None) -> None:
        self.http.queue("GET", HEALTH, FakeResponse(status, body))

    def incident_posts(self) -> list[Any]:
        return [r for r in self.http.calls("POST", ISSUES) if str(r.json["title"]).startswith("[incident]")]

    def body_patches(self, n: int) -> list[Any]:
        return [r for r in self.http.calls("PATCH", f"{ISSUES}/{n}") if "body" in (r.json or {})]


def make_env(tmp_path: Path, start: datetime = START, **cfg: Any) -> Env:
    clock = FakeClock(start)
    server = FakeGitHub(REPO, clock)
    hb = server.add_issue("heartbeat", ["heartbeat"])
    http = FakeHttp(route=server.route)
    http.queue("GET", HEALTH, FakeResponse(200, HEALTHY))
    values: dict[str, Any] = {"api_token": API_TOKEN, "github_token": "gh-secret", "repo": REPO}
    values.update(cfg)
    config = make_config(tmp_path, **values)
    store = MedicStore(tmp_path / "state" / "medic.db")
    w = Watcher(config, store, GitHub(http, "gh-secret", REPO), http, clock, FakeNotifier())
    (tmp_path / "state" / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "logs" / "my-planner.jsonl").write_text("", encoding="utf-8")
    return Env(tmp_path, clock, server, http, store, w, hb)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    e = make_env(tmp_path)
    e.tick()  # 첫 회차: 로그 위치를 잡는다
    return e


# --- 이슈 열기·고치기 -----------------------------------------------------------


def test_new_signal_opens_one_issue_then_updates_count(env: Env) -> None:
    env.log(env.exc())
    env.tick(2)
    assert len(env.incident_posts()) == 1
    n = env.store.get(EXC_FP).issue_number
    assert env.server.titled(f"[incident] {EXC_FP}")[0]["number"] == n
    assert env.server.labels(n) == ["incident", "be"]
    assert "| 발생 수 | 1 |" in env.server.issues[n]["body"]
    env.clock.advance(minutes=4)
    env.log(env.exc())
    env.tick()
    assert env.store.get(EXC_FP).count == 2
    assert env.body_patches(n) == []  # 10분이 안 됐다
    for _ in range(4):
        env.tick(2)
    assert len(env.body_patches(n)) == 1  # 처음 올린 지 10분 뒤 한 번
    assert "| 발생 수 | 2 |" in env.server.issues[n]["body"]
    for _ in range(5):
        env.tick(2)
    assert len(env.body_patches(n)) == 1  # 바뀐 것이 없으면 다시 고치지 않는다
    assert len(env.incident_posts()) == 1


def test_github_down_keeps_incident_pending_then_files_once(env: Env) -> None:
    env.log(env.exc())
    env.http.outage = 503
    env.tick(2)
    assert env.server.titled(f"[incident] {EXC_FP}") == []
    inc = env.store.get(EXC_FP)
    assert (inc.state, inc.issue_number) == ("open", None)
    env.http.outage = None
    env.tick(2)
    env.tick(2)
    assert len(env.server.titled(f"[incident] {EXC_FP}")) == 1
    assert len(env.incident_posts()) == 1
    assert env.store.get(EXC_FP).issue_number == env.server.titled(f"[incident] {EXC_FP}")[0]["number"]


@pytest.mark.parametrize("status", [0, 401, 500])
def test_github_failure_kinds_do_not_stop_the_watcher(env: Env, status: int) -> None:
    env.http.queue("GET", ISSUES, FakeResponse(status, None, {}))
    env.log(env.exc())
    env.tick(2)  # 예외 없이 끝난다
    assert env.store.get(EXC_FP).issue_number is None


def test_one_rejected_issue_does_not_block_other_incidents(env: Env) -> None:
    env.log(env.exc())
    env.tick(2)
    n = env.store.get(EXC_FP).issue_number
    del env.server.issues[n]  # 이슈가 지워졌다: 본문 고치기가 404
    env.clock.advance(minutes=10)
    env.log(env.exc(), env.exc(exc_type="ValueError"))
    env.tick()
    other = env.store.get("be:ValueError src/my_planner/tools/todos.py:list_todos")
    assert other.issue_number is not None
    assert env.store.get(EXC_FP).synced_count == 1  # 실패한 것은 다음 회차에 다시 해 본다


def test_lost_create_response_does_not_duplicate(env: Env) -> None:
    env.log(env.exc())
    env.http.lose_next("POST", ISSUES)
    env.tick(2)
    assert len(env.server.titled(f"[incident] {EXC_FP}")) == 1  # 서버에는 생겼다
    assert env.store.get(EXC_FP).issue_number is None  # 응답은 못 받았다
    env.tick(2)
    assert len(env.incident_posts()) == 1
    assert len(env.server.titled(f"[incident] {EXC_FP}")) == 1
    assert env.store.get(EXC_FP).issue_number == env.server.titled(f"[incident] {EXC_FP}")[0]["number"]


def _file_and_resolve(env: Env) -> int:
    env.log(env.exc())
    env.tick(2)
    inc = env.store.get(EXC_FP)
    env.server.issues[inc.issue_number]["state"] = "closed"
    env.store.set_state(EXC_FP, "resolved", resolved_at=env.clock.now().isoformat(), failures=1)
    return inc.issue_number


def test_recurrence_within_24h_reopens_with_label(env: Env) -> None:
    n = _file_and_resolve(env)
    env.clock.advance(hours=23)
    env.log(env.exc())
    env.tick()
    assert len(env.incident_posts()) == 1
    assert env.server.issues[n]["state"] == "open"
    assert "recurred" in env.server.labels(n)
    inc = env.store.get(EXC_FP)
    assert (inc.state, inc.issue_number, inc.failures, inc.count) == ("open", n, 1, 2)
    assert "| 발생 수 | 2 |" in env.server.issues[n]["body"]
    env.tick(2)
    assert len(env.http.calls("POST", f"{ISSUES}/{n}/labels")) == 1  # 한 번만 다시 연다


def test_recurrence_after_24h_opens_new(env: Env) -> None:
    n = _file_and_resolve(env)
    env.clock.advance(hours=25)
    env.log(env.exc())
    env.tick()
    issues = env.server.titled(f"[incident] {EXC_FP}")
    assert len(issues) == 2
    inc = env.store.get(EXC_FP)
    assert inc.issue_number != n
    assert env.server.issues[n]["state"] == "closed"
    assert (inc.state, inc.count, inc.failures) == ("open", 1, 0)
    assert "recurred" not in env.server.labels(inc.issue_number)


# --- 헬스 ---------------------------------------------------------------------


def test_health_probe_uses_bearer_and_timeout(env: Env) -> None:
    req = env.http.calls("GET", HEALTH)[-1]
    assert req.url == "http://127.0.0.1:8787/api/v1/health"
    assert req.headers == {"Authorization": f"Bearer {API_TOKEN}"}
    assert req.timeout == 10


def test_wake_grace_suppresses_late_run_for_10_minutes(env: Env) -> None:
    env.clock.advance(hours=3)  # 노트북이 잠들었다 깸 (13:00 KST)
    env.health(200, {**HEALTHY, "runs_today": [
        {"loop": "morning_brief", "status": "pending", "scheduled_for": "2026-10-26T09:00:00+09:00"},
    ]})
    env.tick()
    for _ in range(4):
        env.tick(2)
        assert env.store.get("late_run:morning_brief") is None
    env.tick(2)  # 깬 지 10분
    assert env.store.get("late_run:morning_brief") is not None


def test_watcher_suppressed_flag_stops_health_counting(env: Env) -> None:
    env.health(200, {**HEALTHY, "runs_today": [
        {"loop": "morning_brief", "status": "pending", "scheduled_for": "2026-10-26T09:00:00+09:00"},
    ]})
    env.watcher.suppressed = True
    env.tick(2)
    assert env.store.get("late_run:morning_brief") is None
    env.watcher.suppressed = False
    env.tick(2)
    assert env.store.get("late_run:morning_brief") is not None


def test_api_disabled_watches_logs_only(tmp_path: Path) -> None:
    env = make_env(tmp_path, api_enabled=False)
    env.tick()
    env.log(env.exc())
    env.tick(2)
    assert env.http.calls("GET", HEALTH) == []
    assert env.store.get(EXC_FP).issue_number is not None


def test_bind_error_latched_until_health_ok(env: Env) -> None:
    env.log({"ts": env.clock.now().isoformat(), "level": "ERROR", "logger": "my_planner.api.server",
             "msg": "api_bind_error"})
    env.health(0)
    for _ in range(3):  # 레코드는 첫 회차에만 있다
        env.tick(2)
    assert env.store.get("health:bind") is not None
    assert env.store.get("health:unreachable") is None
    assert env.store.kv_json_get("bind_error_seen") is True
    env.health(200, HEALTHY)
    env.tick(2)
    assert env.store.kv_json_get("bind_error_seen") is False


def test_safe_mode_opens_record_issue_without_incident_label(env: Env) -> None:
    env.health(200, {"status": "safe_mode", "polling": "up"})
    for _ in range(3):
        env.tick(2)
    inc = env.store.get("health:safe_mode")
    assert inc is not None
    assert env.server.issues[inc.issue_number]["title"] == "[incident] health:safe_mode"
    assert env.server.labels(inc.issue_number) == ["record"]
    assert '"status": "safe_mode"' in env.server.issues[inc.issue_number]["body"]


# --- 로그 상태 저장 -------------------------------------------------------------


def _warn(env: Env, at: datetime) -> dict[str, Any]:
    return {"ts": at.isoformat(), "level": "WARNING", "logger": "my_planner.x", "msg": "slow_reply"}


def test_warn_window_persists_across_ticks_and_restarts(env: Env) -> None:
    env.log(*[_warn(env, env.clock.now()) for _ in range(12)])
    env.tick(2)
    saved = env.store.kv_json_get("warn_window")
    assert len(saved["slow_reply"]) == 12
    assert all(isinstance(t, str) for t in saved["slow_reply"])
    # medic 재시작: 새 Watcher, 같은 DB
    env.watcher = Watcher(env.watcher._cfg, env.store, env.watcher._gh, env.http, env.clock, FakeNotifier())
    env.clock.advance(minutes=2)
    env.log(*[_warn(env, env.clock.now()) for _ in range(8)])
    env.tick()
    assert env.store.get("be-warn:slow_reply") is not None


def test_warn_window_prunes_entries_older_than_an_hour(env: Env) -> None:
    env.log(*[_warn(env, env.clock.now()) for _ in range(12)])
    env.tick(2)
    env.clock.advance(minutes=61)
    env.log(*[_warn(env, env.clock.now()) for _ in range(8)])
    env.tick()
    assert len(env.store.kv_json_get("warn_window")["slow_reply"]) == 8
    assert env.store.get("be-warn:slow_reply") is None


def test_log_cursor_kept_verbatim_in_kv(env: Env) -> None:
    env.log(env.exc())
    env.tick(2)
    cur = env.store.kv_json_get("log_cursor")
    assert cur["file"].startswith("my-planner.jsonl#")
    assert cur["offset"] > 0


def test_log_read_os_error_is_logged_and_tick_continues(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_: Any) -> Any:
        raise FileNotFoundError("my-planner.jsonl")

    monkeypatch.setattr(watcher_mod, "read_new_lines", boom)
    with caplog.at_level(logging.WARNING):
        env.tick(2)
    assert "log_read_failed" in caplog.text
    assert env.store.kv_get("last_tick_at") == env.clock.now().isoformat()


def test_issue_body_keeps_only_allowlisted_fields_and_no_tokens(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    env.log({"ts": env.clock.now().isoformat(), "level": "INFO", "logger": "my_planner.chat",
             "msg": "reply_sent", "text": "사용자 비밀 글"})
    env.log(env.exc(text="사용자 비밀 글", user="dahun"))
    env.http.outage = 401
    env.tick(2)
    env.http.outage = None
    env.tick(2)
    body = env.server.issues[env.store.get(EXC_FP).issue_number]["body"]
    assert "reply_sent" in body  # 직전 로그 줄(허용 열)
    assert "src/my_planner/tools/todos.py:40 list_todos" in body
    assert "비밀" not in body and "dahun" not in body and str(env.root) not in body
    rows = env.store.get(EXC_FP).detail["rows"]
    assert 0 < len(rows) <= 20
    assert all(set(r) <= {"ts", "level", "logger", "msg", "exc_type", "exc_where"} for r in rows)
    assert API_TOKEN not in caplog.text and "gh-secret" not in caplog.text


# --- 하트비트 -------------------------------------------------------------------


def test_heartbeat_every_30_minutes_keeps_todays_stale_label(tmp_path: Path) -> None:
    env = make_env(tmp_path, start=datetime(2026, 10, 25, 16, 0, tzinfo=UTC))  # 월 01:00 KST
    hb = env.heartbeat_issue
    env.server.issues[hb]["labels"] += [{"name": "stale-2026-10-25"}, {"name": "stale-2026-10-26"}]
    env.store.kv_set("deployed_sha", "abc1234")
    env.tick()
    assert env.server.issues[hb]["body"] == (
        "last_seen: 2026-10-25T16:00:00Z, sha: abc1234, next_run: 2026-10-26T00:00:00Z"
    )
    assert env.server.labels(hb) == ["heartbeat", "stale-2026-10-26"]  # 서울 오늘 것은 남긴다
    for _ in range(14):
        env.tick(2)
    assert len(env.body_patches(hb)) == 1
    env.tick(2)  # 30분
    assert len(env.body_patches(hb)) == 2
    assert env.server.issues[hb]["body"].startswith("last_seen: 2026-10-25T16:30:00Z, ")


def test_heartbeat_uses_unknown_sha_and_creates_issue_when_missing(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    del env.server.issues[env.heartbeat_issue]
    env.tick()
    hb = env.server.titled("heartbeat")
    assert len(hb) == 1
    assert ", sha: unknown, " in hb[0]["body"]


# --- Actions가 연 이슈 ------------------------------------------------------------


def test_imports_actions_opened_incidents(env: Env) -> None:
    v = env.server.add_issue("[incident] vercel:Vercel", ["incident"], body="actions body")
    c = env.server.add_issue("[incident] ci:main", ["incident"], body="actions body")
    other = env.server.add_issue("[incident] be:Foo x.py:f", ["incident", "be"])
    env.tick(30)
    vi, ci = env.store.get("vercel:Vercel"), env.store.get("ci:main")
    assert (vi.state, vi.issue_number, vi.part) == ("open", v, "vercel")
    assert (ci.state, ci.issue_number, ci.part) == ("open", c, "ci")
    assert env.store.get("be:Foo x.py:f") is None
    assert other
    imports = [r for r in env.http.calls("GET", ISSUES) if r.query.get("state") == "open"
               and r.query.get("labels") == "incident"]
    for _ in range(10):
        env.tick(2)
    assert env.server.issues[v]["body"] == "actions body"  # Actions 본문은 덮지 않는다
    assert env.body_patches(v) == [] and env.body_patches(c) == []
    assert len([r for r in env.http.calls("GET", ISSUES) if r.query.get("state") == "open"
                and r.query.get("labels") == "incident"]) == len(imports)  # 30분에 한 번


def test_ci_main_resolves_on_green_main(env: Env) -> None:
    c = env.server.add_issue("[incident] ci:main", ["incident"])
    env.server.branches["main"] = "h1"
    env.server.runs.append({"name": "ci", "head_sha": "h1", "event": "push", "status": "completed",
                            "conclusion": "failure", "id": 1})
    env.tick(30)
    assert env.store.get("ci:main").state == "open"
    env.server.branches["main"] = "h2"
    env.server.runs.append({"name": "ci", "head_sha": "h2", "event": "push", "status": "completed",
                            "conclusion": "success", "id": 2})
    env.tick(2)
    inc = env.store.get("ci:main")
    assert inc.state == "resolved" and inc.resolved_at is not None
    assert env.server.issues[c]["state"] == "closed"
    assert any("고쳤어요" in m for m in env.server.comments[c])
    env.tick(2)
    assert len(env.server.comments[c]) == 1


def test_timezone_fallback_to_utc_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        make_env(tmp_path, timezone="Nowhere/Nope")
    assert "timezone_fallback" in caplog.text


def test_first_tick_has_no_wake_grace_and_sets_last_tick(env: Env) -> None:
    assert env.store.kv_get("last_tick_at") == START.isoformat()
    assert env.store.kv_get("wake_grace_until") is None


# --- 리뷰 수정 1회차 ------------------------------------------------------------


@pytest.mark.parametrize(("offset", "reopened"), [
    (timedelta(hours=24), True),  # 정확히 24시간은 "24시간 안"이다(포함)
    (timedelta(hours=24, seconds=1), False),
])
def test_recurrence_24h_boundary_is_inclusive(env: Env, offset: timedelta, reopened: bool) -> None:
    n = _file_and_resolve(env)
    env.clock.advance(seconds=offset.total_seconds())
    env.log(env.exc())
    env.tick()
    assert (env.store.get(EXC_FP).issue_number == n) is reopened
    assert len(env.server.titled(f"[incident] {EXC_FP}")) == (1 if reopened else 2)


def test_malformed_stale_label_is_left_alone(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    hb = env.heartbeat_issue
    env.server.issues[hb]["labels"] += [{"name": "stale-2026-13-45"}, {"name": "stale-2026-10-20"}]
    env.tick()
    assert env.server.labels(hb) == ["heartbeat", "stale-2026-13-45"]
    assert env.server.issues[hb]["body"].startswith("last_seen: ")


def test_non_list_recent_rows_kv_is_reset(env: Env) -> None:
    env.store.kv_json_set("recent_rows", {"bad": 1})
    env.log(env.exc())
    env.tick(2)
    rows = env.store.kv_json_get("recent_rows")
    assert isinstance(rows, list) and len(rows) == 1
    assert env.store.get(EXC_FP).issue_number is not None


def test_ci_main_failed_comment_leaves_incident_unresolved(env: Env) -> None:
    c = env.server.add_issue("[incident] ci:main", ["incident"])
    env.server.branches["main"] = "h2"
    env.server.runs.append({"name": "ci", "head_sha": "h2", "event": "push", "status": "completed",
                            "conclusion": "success", "id": 2})
    env.http.queue("POST", f"{ISSUES}/{c}/comments", FakeResponse(502))
    env.tick(30)
    assert env.store.get("ci:main").state == "open"
    assert env.server.issues[c]["state"] == "open"  # 댓글이 먼저라 닫지도 않았다
    env.http.clear("POST", f"{ISSUES}/{c}/comments")
    env.tick(2)
    assert env.store.get("ci:main").state == "resolved"
    assert env.server.issues[c]["state"] == "closed"
    assert len(env.server.comments[c]) == 1


@pytest.mark.parametrize(("status", "filed"), [(422, True), (404, True), (503, False), (401, False)])
def test_heartbeat_rejection_does_not_block_incident_sync(tmp_path: Path, status: int, filed: bool) -> None:
    env = make_env(tmp_path)
    env.http.queue("PATCH", f"{ISSUES}/{env.heartbeat_issue}", FakeResponse(status))
    env.tick()
    env.log(env.exc())
    env.tick(2)
    assert (env.store.get(EXC_FP).issue_number is not None) is filed
    assert env.store.kv_get("last_heartbeat_at") is None  # 다음 회차에 다시 해 본다


def _row(i: int, level: str) -> dict[str, Any]:
    return {"ts": f"2026-10-26T01:{i:02d}:00+00:00", "level": level, "msg": f"e{i}"}


def test_trim_rows_keeps_non_info_first_then_newest_info_in_order() -> None:
    rows = [_row(i, "WARNING" if i in (1, 5, 9) else "INFO") for i in range(30)]
    out = _trim_rows(rows)
    assert len(out) == 20
    assert [r["msg"] for r in out if r["level"] != "INFO"] == ["e1", "e5", "e9"]
    assert [r["msg"] for r in out if r["level"] == "INFO"] == [f"e{i}" for i in range(13, 30)]
    assert out == sorted(out, key=lambda r: r["ts"])
    many = [_row(i, "ERROR") for i in range(25)] + [_row(i, "INFO") for i in range(25, 30)]
    assert [r["msg"] for r in _trim_rows(many)] == [f"e{i}" for i in range(5, 25)]
    assert _trim_rows(rows[:3]) == rows[:3]


def test_ci_main_resolve_sends_one_result_notice(tmp_path: Path) -> None:
    e = make_env(tmp_path)
    notifier = FakeNotifier()
    e.watcher = Watcher(e.watcher._cfg, e.store, e.watcher._gh, e.http, e.clock, notifier)
    e.tick()
    c = e.server.add_issue("[incident] ci:main", ["incident"])
    e.server.branches["main"] = "h2"
    e.server.runs.append({"name": "ci", "head_sha": "h2", "event": "push", "status": "completed",
                          "conclusion": "success", "id": 2})
    e.tick(30)
    assert e.store.get("ci:main").state == "resolved"
    assert notifier.fixed_calls == [("main의 CI가 다시 성공했어요", f"https://github.com/{REPO}/issues/{c}")]
    e.tick(2)
    assert len(notifier.fixed_calls) == 1
    assert notifier.flushes >= 2  # 회차마다 쌓인 알림을 살핀다


def test_watcher_ticks_web_verifier(tmp_path: Path) -> None:
    from my_planner_medic.signals import Signal

    e = make_env(tmp_path)
    notifier = FakeNotifier()
    e.watcher = Watcher(e.watcher._cfg, e.store, e.watcher._gh, e.http, e.clock, notifier)
    e.tick()
    fp = "vercel:Vercel – app"
    n = e.server.add_issue(f"[incident] {fp}", ["incident", "merged"])
    e.store.upsert_signal(Signal(fp, "vercel", "health", e.clock.now()), e.clock.now())
    e.store.set_state(fp, "merged", issue_number=n)
    e.server.branches["main"] = "h1"
    e.server.statuses["h1"] = [{"context": "Vercel – app", "state": "success"}]
    e.tick(2)
    assert e.store.get(fp).state == "resolved"
    assert len(notifier.fixed_calls) == 1

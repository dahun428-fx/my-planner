from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from my_planner_medic.signals import (
    HealthProbe,
    Signal,
    has_bind_error,
    health_signals,
    log_signals,
    normal_delay_reasons,
    outside_reasons,
)

from .fakes import make_config

ROOT = Path("/home/dahun/my-planner")
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)  # 월 17:00 KST
CFG = make_config(ROOT)


def kst(h: int, mi: int = 0, d: int = 26) -> datetime:
    return datetime(2026, 10, d, h, mi, tzinfo=KST)


def rec(**kw: Any) -> dict[str, Any]:
    base = {"ts": NOW.isoformat(timespec="milliseconds"), "level": "INFO", "logger": "my_planner.x", "msg": "e"}
    base.update(kw)
    return base


def fps(signals: list[Signal]) -> list[str]:
    return [s.fingerprint for s in signals]


# --- 로그 신호 ---------------------------------------------------------------


def test_exception_fingerprint_uses_deepest_own_frame() -> None:
    r = rec(level="ERROR", msg="tool_failed", exc_type="KeyError", exc_where=[
        f"{ROOT}/src/my_planner/app.py:10 main",
        f"{ROOT}/src/my_planner/tools/todos.py:40 list_todos",
        f"{ROOT}/.venv/lib/python3.12/site-packages/aiosqlite/core.py:5 run",
    ])
    out = log_signals([r], ROOT, now=NOW, warn_window={})
    assert out == [Signal("be:KeyError src/my_planner/tools/todos.py:list_todos", "be", "exception", NOW)]


def test_fingerprint_falls_back_to_last_frame() -> None:
    r = rec(level="CRITICAL", msg="crash", exc_type="OSError", exc_where=[
        "/usr/lib/python3.12/asyncio/events.py:84 _run",
        f"{ROOT}/.venv/lib/python3.12/site-packages/aiohttp/web.py:9 handle",
    ])
    assert fps(log_signals([r], ROOT, now=NOW, warn_window={})) == ["be:OSError site-packages/aiohttp/web.py:handle"]


def test_error_without_exc_type_is_not_exception() -> None:
    assert log_signals([rec(level="ERROR", msg="api_bind_error")], ROOT, now=NOW, warn_window={}) == []


def test_client_error_fingerprint() -> None:
    r = rec(level="WARNING", logger="my_planner.api.recovery", msg="client_error", app="dashboard",
            version="a792f21", route="/runs/[id]", error_name="TypeError", frames=["d.js:1:2"])
    assert log_signals([r], ROOT, now=NOW, warn_window={}) == [
        Signal("dashboard:TypeError /runs/[id]", "dashboard", "client_error", NOW)
    ]


def test_third_party_and_client_error_never_burst() -> None:
    window: dict[str, list[datetime]] = {}
    records = [rec(level="WARNING", logger="aiohttp.access", msg="third_party_log") for _ in range(30)]
    records += [rec(level="WARNING", logger="my_planner.x", msg="third_party_log") for _ in range(30)]
    records += [rec(level="WARNING", logger="my_planner.api.recovery", msg="client_error", app="app",
                    route="/today", error_name="TypeError") for _ in range(30)]
    out = log_signals(records, ROOT, now=NOW, warn_window=window)
    assert all(s.kind != "warn_burst" for s in out)
    assert "third_party_log" not in window and "client_error" not in window


def test_warn_burst_at_20_in_hour() -> None:
    window: dict[str, list[datetime]] = {}
    old = [rec(level="WARNING", msg="send_retry", ts=(NOW - timedelta(minutes=61)).isoformat())]
    assert log_signals(old, ROOT, now=NOW - timedelta(minutes=61), warn_window=window) == []
    batch = [rec(level="WARNING", msg="send_retry", ts=(NOW - timedelta(minutes=50 - i)).isoformat())
             for i in range(19)]
    assert log_signals(batch, ROOT, now=NOW, warn_window=window) == []  # 창 밖 1건 + 19건
    out = log_signals([rec(level="WARNING", msg="send_retry")], ROOT, now=NOW, warn_window=window)
    assert out == [Signal("be-warn:send_retry", "be", "warn_burst", NOW)]


def test_has_bind_error() -> None:
    assert has_bind_error([rec(level="ERROR", msg="api_bind_error")])
    assert not has_bind_error([rec(level="ERROR", msg="other")])


# --- 헬스 ---------------------------------------------------------------------


def body(**kw: Any) -> dict[str, Any]:
    b: dict[str, Any] = {
        "status": "ok", "polling": "running", "last_tick_at": NOW.isoformat(),
        "brain": {"auth": "ok", "limited_until": None}, "paused_until": None, "plan_open": False,
        "proactive": {"sent_today": 0, "cap": 3}, "inbound_pending_oldest_at": None, "runs_today": [],
    }
    b.update(kw)
    return b


def ok(**kw: Any) -> HealthProbe:
    return HealthProbe(200, body(**kw))


def run(loop: str, at: datetime, status: str = "pending") -> dict[str, Any]:
    return {"loop": loop, "status": status, "scheduled_for": at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "skip_reason": None}


def probe_seq(probes: list[HealthProbe], now: datetime = NOW, **kw: Any) -> list[list[Signal]]:
    streak, out = 0, []
    for p in probes:
        sigs, streak = health_signals(p, now, streak=streak, suppress=False, cfg=CFG, **kw)
        out.append(sigs)
    return out


def test_health_streak_three_then_signal() -> None:
    down = HealthProbe(None, None)
    res = probe_seq([down, down, down, down])
    assert [fps(r) for r in res] == [[], [], ["health:unreachable"], ["health:unreachable"]]
    assert res[2][0].kind == "health" and res[2][0].part == "be"
    # 성공 한 번이면 연속이 끊긴다
    assert [fps(r) for r in probe_seq([down, down, ok(), down, down])] == [[], [], [], [], []]
    sigs, streak = health_signals(ok(), NOW, streak=2, suppress=False, cfg=CFG)
    assert (sigs, streak) == ([], 0)


def test_401_is_health_auth() -> None:
    res = probe_seq([HealthProbe(401, None)] * 3)
    assert fps(res[2]) == ["health:auth"]


def test_unreachable_with_bind_error_is_health_bind() -> None:
    res = probe_seq([HealthProbe(None, None)] * 3, bind_error=True)
    assert fps(res[2]) == ["health:bind"]


def test_safe_mode_is_record_kind() -> None:
    sm = HealthProbe(200, {"status": "safe_mode", "version": {"app": "1"}, "now": NOW.isoformat()})
    res = probe_seq([sm] * 3)
    assert res[:2] == [[], []]
    assert res[2] == [Signal("health:safe_mode", "be", "record", NOW)]


def test_suppress_hides_everything() -> None:
    sigs, streak = health_signals(HealthProbe(None, None), NOW, streak=5, suppress=True, cfg=CFG)
    assert (sigs, streak) == ([], 0)
    late = ok(runs_today=[run("morning_brief", kst(9))], inbound_pending_oldest_at=(NOW - timedelta(hours=1)).isoformat())
    assert health_signals(late, NOW, streak=0, suppress=True, cfg=CFG) == ([], 0)


OUTSIDE_CASES = {
    "polling_down": {"polling": "down", "status": "degraded"},
    "auth": {"brain": {"auth": "login", "limited_until": None}, "status": "degraded"},
    "limited": {"brain": {"auth": "ok", "limited_until": (NOW + timedelta(hours=1)).isoformat()}},
    "paused": {"paused_until": (NOW + timedelta(hours=1)).isoformat()},
}


@pytest.mark.parametrize("reason", list(OUTSIDE_CASES))
def test_outside_reasons_suppress_late_run_and_no_reply(reason: str) -> None:
    kw = {
        "runs_today": [run("morning_brief", kst(9))],
        "inbound_pending_oldest_at": (NOW - timedelta(minutes=30)).isoformat(),
        **OUTSIDE_CASES[reason],
    }
    assert outside_reasons(body(**kw), NOW) == [reason]
    sigs, streak = health_signals(ok(**kw), NOW, streak=0, suppress=False, cfg=CFG)
    assert (sigs, streak) == ([], 0)
    # 사유가 없으면 같은 몸이 두 신호를 낸다
    clean = {k: v for k, v in kw.items() if k not in OUTSIDE_CASES[reason]}
    assert fps(health_signals(ok(**clean), NOW, streak=0, suppress=False, cfg=CFG)[0]) == [
        "late_run:morning_brief", "no_reply",
    ]


def test_past_limits_are_not_outside_reasons() -> None:
    past = (NOW - timedelta(minutes=1)).isoformat()
    b = body(brain={"auth": "ok", "limited_until": past}, paused_until=past)
    assert outside_reasons(b, NOW) == []


@pytest.mark.parametrize(
    ("kw", "reason"),
    [({"plan_open": True}, "plan_open"), ({"proactive": {"sent_today": 3, "cap": 3}}, "proactive_cap")],
)
def test_plan_open_and_proactive_cap_suppress_late_run(kw: dict[str, Any], reason: str) -> None:
    now = kst(17, 46)
    rows = {"runs_today": [run("evening_checkin", kst(17, 30))],
            "inbound_pending_oldest_at": (now - timedelta(minutes=11)).isoformat(), **kw}
    assert normal_delay_reasons(body(**rows)) == [reason]
    sigs, _ = health_signals(ok(**rows), now, streak=0, suppress=False, cfg=CFG)
    assert fps(sigs) == ["no_reply"]  # 무응답은 그대로 센다


def test_tick_stalled_without_run_row() -> None:
    now = kst(17, 46)
    b = body(runs_today=[run("morning_brief", kst(9), "done")], last_tick_at=kst(16).isoformat())
    sigs, _ = health_signals(HealthProbe(200, b), now, streak=0, suppress=False, cfg=CFG)
    assert sigs == [Signal("late_run:tick_stalled", "be", "late_run", now)]
    # tick이 제때 돌았으면(16:00 기준 다음 회차 17:30 + 15분이 아직 안 지남) 없다
    sigs, _ = health_signals(HealthProbe(200, b), kst(17, 44), streak=0, suppress=False, cfg=CFG)
    assert sigs == []
    fresh = body(runs_today=[run("morning_brief", kst(9), "done")], last_tick_at=kst(17, 45).isoformat())
    assert health_signals(HealthProbe(200, fresh), now, streak=0, suppress=False, cfg=CFG)[0] == []


def test_late_run_after_15_minutes() -> None:
    b = body(runs_today=[run("morning_brief", kst(9), "done"), run("evening_checkin", kst(17, 30))])
    sigs, _ = health_signals(HealthProbe(200, b), kst(17, 44), streak=0, suppress=False, cfg=CFG)
    assert sigs == []
    now = kst(17, 46)
    sigs, _ = health_signals(HealthProbe(200, b), now, streak=0, suppress=False, cfg=CFG)
    assert sigs == [Signal("late_run:evening_checkin", "be", "late_run", now)]


def test_no_reply_after_10_minutes() -> None:
    oldest = NOW - timedelta(minutes=9)
    b = body(inbound_pending_oldest_at=oldest.isoformat().replace("+00:00", "Z"))
    assert health_signals(HealthProbe(200, b), NOW, streak=0, suppress=False, cfg=CFG)[0] == []
    later = oldest + timedelta(minutes=11)
    sigs, _ = health_signals(HealthProbe(200, b), later, streak=0, suppress=False, cfg=CFG)
    assert sigs == [Signal("no_reply", "be", "no_reply", later)]

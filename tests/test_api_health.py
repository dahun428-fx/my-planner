"""`GET /health` (SP3-4 스펙 6.3.1), 오늘의 회차와 체크인 상태(6.4.5), 회차 전달 기록(7.3)."""

import logging
from datetime import timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.api.health import ErrorCounter
from my_planner.api.models import Health
from my_planner.clock import FakeClock, to_iso
from my_planner.domain import LoopKey, RunStatus
from my_planner.harness.checkins import checkin_state, runs_today
from my_planner.store.db import LATEST_VERSION
from my_planner.store.repos.channels import DeliveriesRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.state import (
    BRAIN_AUTH_CHECKED_AT_KEY,
    BRAIN_AUTH_STATE_KEY,
    LIMITED_UNTIL_KEY,
    NOTIFY_PRIMARY_KEY,
    PAUSE_UNTIL_KEY,
)

SAT_1300 = kst(2026, 10, 24, 13, 0)  # 토요일 오후, 논리적 날짜 10/24


async def _health(env):
    resp = await env.get("/health")
    assert resp.status == 200
    body = await resp.json()
    Health.model_validate(body)  # 모양이 모델과 같다
    return body


def _z(dt):
    return dt.isoformat().replace("+00:00", "Z")


async def test_health_fields_from_sources(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        st = env.parts.state
        st.set(PAUSE_UNTIL_KEY, to_iso(SAT_1300 + timedelta(days=2)))
        st.set(LIMITED_UNTIL_KEY, to_iso(SAT_1300 - timedelta(hours=1)))  # 지난 값은 null
        st.set(NOTIFY_PRIMARY_KEY, "telegram")
        st.incr_usage(SAT_1300.date(), "brain_calls")
        env.conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at, last_success_at) "
            "VALUES ('https://push.example/a', 'k', 'a', ?, ?), ('https://push.example/b', 'k', 'a', ?, NULL)",
            (to_iso(SAT_1300), to_iso(SAT_1300 - timedelta(minutes=5)), to_iso(SAT_1300)),
        )
        env.conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at, disabled_at) "
            "VALUES ('https://push.example/c', 'k', 'a', ?, ?)", (to_iso(SAT_1300), to_iso(SAT_1300)),
        )
        env.conn.commit()
        env.parts.router.start_plan()
        body = await _health(env)

    assert body["version"]["schema"] == LATEST_VERSION
    assert body["version"]["api"] == "v1" and body["version"]["app"]
    assert body["now"] == _z(SAT_1300)
    assert body["started_at"] == _z(SAT_1300)
    assert body["last_tick_at"] == _z(SAT_1300 - timedelta(minutes=1))
    assert body["polling"] == "running"
    assert body["brain"] == {"auth": "unknown", "checked_at": None, "limited_until": None,
                             "calls_today": 1, "calls_cap": 60}
    assert body["proactive"] == {"sent_today": 0, "cap": 3}
    assert body["paused_until"] == _z(SAT_1300 + timedelta(days=2))
    assert body["plan_open"] is True
    assert body["notify"] == {"primary": "telegram", "effective": "telegram"}
    assert body["runs_today"] == []
    assert body["errors"]["window_hours"] == 24 and body["errors"]["since"] == _z(SAT_1300)
    assert body["push"] == {"subscriptions": 2, "last_success_at": _z(SAT_1300 - timedelta(minutes=5))}
    assert "endpoint" not in str(body) and "push.example" not in str(body)
    for v in (body["now"], body["started_at"], body["last_tick_at"], body["paused_until"]):
        assert v.endswith("Z")


@pytest.mark.parametrize("case", ["polling_down", "auth_login", "auth_billing", "limited"])
async def test_degraded_conditions(tmp_path, case):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        st = env.parts.state
        if case == "polling_down":
            env.parts.runner._polling_down = True
        elif case == "auth_login":
            st.set(BRAIN_AUTH_STATE_KEY, "login")
        elif case == "auth_billing":
            st.set(BRAIN_AUTH_STATE_KEY, "billing")
        else:
            st.set(LIMITED_UNTIL_KEY, to_iso(SAT_1300 + timedelta(hours=2)))
        body = await _health(env)
    assert body["status"] == "degraded"
    if case == "polling_down":
        assert body["polling"] == "down"
    if case == "limited":
        assert body["brain"]["limited_until"] == _z(SAT_1300 + timedelta(hours=2))


async def test_brain_auth_unknown_until_first_call_then_written_by_dispatcher(tmp_path):
    errors = [FakeTurn([], "", status="error", error="timeout")] * 4  # 처음 + 백오프 3회
    script = [FakeTurn([], "안녕하세요"), FakeTurn([], "", status="auth_error", error="billing"), *errors]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        assert (await _health(env))["brain"]["auth"] == "unknown"
        await env.telegram("안녕")
        b = (await _health(env))["brain"]
        assert b["auth"] == "ok" and b["checked_at"].endswith("Z")
        first_check = env.parts.state.get(BRAIN_AUTH_CHECKED_AT_KEY)
        env.clock.advance(timedelta(minutes=1))
        await env.telegram("다시")
        assert (await _health(env))["brain"]["auth"] == "billing"
        assert env.parts.state.get(BRAIN_AUTH_CHECKED_AT_KEY) != first_check
        env.clock.advance(timedelta(minutes=10))
        await env.telegram("또")  # 시간 초과 같은 오류는 인증 상태를 알려 주지 않는다: 그대로 둔다
        assert (await _health(env))["brain"]["auth"] == "billing"
    assert len(env.brain.calls) == 6


def test_error_counter_counts_event_names_in_24h_window():
    clock = FakeClock(SAT_1300)
    counter = ErrorCounter(clock)
    own = logging.getLogger("my_planner.test_counter")
    other = logging.getLogger("aiohttp.server")
    for lg in (own, other):
        lg.addHandler(counter)
        lg.propagate = False
    try:
        own.warning("send_error", extra={"error_type": "X"})
        own.info("api_request")  # INFO는 세지 않는다
        other.error("Error handling request 비밀 본문")  # 외부 로거의 메시지는 이름으로 쓰지 않는다
        clock.advance(timedelta(hours=23))
        own.error("tick_error")
        own.warning("send_error")
        snap = counter.snapshot()
        assert snap["total"] == 4
        assert snap["by_event"] == {"send_error": 2, "third_party_log": 1, "tick_error": 1}
        assert snap["since"] == _z(SAT_1300)
        clock.advance(timedelta(hours=2))  # 처음 두 개는 24시간 창 밖
        snap = counter.snapshot()
        assert snap["by_event"] == {"send_error": 1, "tick_error": 1}
        assert snap["since"] == _z(SAT_1300 + timedelta(hours=1))
        assert "비밀" not in str(snap)
    finally:
        for lg in (own, other):
            lg.removeHandler(counter)
            lg.propagate = True


def test_runs_today_delivered_via_and_checkin_state(tmp_path, conn):
    from fakes import make_settings

    settings = make_settings(tmp_path)
    clock = FakeClock(kst(2026, 10, 24, 11, 0))  # 토요일 11:00
    runs = RunsRepo(conn, clock)
    deliveries = DeliveriesRepo(conn, clock)
    morning = runs.ensure(LoopKey.morning_brief, kst(2026, 10, 24, 10, 0))
    evening = runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 24, 18, 0))
    yesterday = runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 23, 17, 30))
    late_night = runs.ensure(LoopKey.return_, kst(2026, 10, 25, 2, 0))  # 04:00 전: 논리적 날짜 10/24
    for r in (morning, yesterday, late_night):
        runs.mark_done(r.id)
    deliveries.record(morning.id, "telegram", "full", "sent")
    deliveries.record(late_night.id, "telegram", "full", "not_sent")

    rows = runs_today(runs=runs, deliveries=deliveries, now=clock.now(), settings=settings)
    assert [r["id"] for r in rows] == [morning.id, evening.id, late_night.id]
    assert rows[0]["delivered_via"] == ["telegram"]
    assert rows[0]["checkin_state"] == "pending"  # 답장 창(12:00) 안, 답 없음
    assert rows[1]["checkin_state"] is None and rows[1]["status"] == "pending"  # 보내지 않은 회차
    assert rows[2]["delivered_via"] == []  # not_sent는 넣지 않는다

    clock.set(kst(2026, 10, 24, 12, 30))  # 아침 답장 창이 지났다
    assert checkin_state(runs.get(morning.id), runs=runs, now=clock.now(), settings=settings) == "missed"
    conn.execute("UPDATE runs SET answered_at = ?, answered_via = 'telegram' WHERE id = ?",
                 (to_iso(kst(2026, 10, 24, 11, 30)), morning.id))
    conn.commit()
    assert checkin_state(runs.get(morning.id), runs=runs, now=clock.now(), settings=settings) == "answered"


def test_merged_run_follows_primary_window(tmp_path, conn):
    from fakes import make_settings

    settings = make_settings(tmp_path)
    clock = FakeClock(kst(2026, 10, 24, 12, 30))
    runs = RunsRepo(conn, clock)
    morning = runs.ensure(LoopKey.morning_brief, kst(2026, 10, 24, 10, 0))
    ret = runs.ensure(LoopKey.return_, kst(2026, 10, 24, 11, 0))  # 복귀 인사: 다음 날 04:00까지
    runs.add_merged(ret.id, [morning.id])
    for r in (ret, morning):
        runs.mark_done(r.id)
    # 아침 창(12:00)은 지났지만 묶음의 가장 늦은 끝은 복귀 인사의 창이다
    assert checkin_state(runs.get(ret.id), runs=runs, now=clock.now(), settings=settings) == "pending"
    assert checkin_state(runs.get(morning.id), runs=runs, now=clock.now(), settings=settings) == "pending"


class _FailingDeliveries(DeliveriesRepo):
    def record(self, *a, **kw):
        super().record(*a, **kw)  # 써 놓고 실패한다: 같은 트랜잭션이면 이 행도 되돌아간다
        raise RuntimeError("기록 실패")


async def test_run_delivered_records_delivery_same_transaction(tmp_path, conn, state):
    env = Env(tmp_path, conn, state, script=[FakeTurn([], "좋은 아침이에요")],
              start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), with_tools=True)
    env.dispatcher.deliveries = _FailingDeliveries(conn, env.clock)
    run = env.runs.ensure(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    env.runs.mark_queued(run.id)
    await env.process_run(env.runs.get(run.id))

    assert len(env.sender.sent) == 1  # 보내기는 했다
    # 한 트랜잭션이었다: 카운터와 전달 기록은 둘 다 그대로
    assert state.usage(kst(2026, 10, 26, 9, 0).date()).proactive_messages == 0
    assert conn.execute("SELECT COUNT(*) FROM run_deliveries").fetchone()[0] == 0
    # 회차는 done만 따로 적어 다음 시작 때 다시 보내지 않는다
    assert env.runs.get(run.id).status is RunStatus.done


async def test_run_delivered_records_telegram_delivery(tmp_path, conn, state):
    env = Env(tmp_path, conn, state, script=[FakeTurn([], "좋은 아침이에요")],
              start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), with_tools=True)
    env.dispatcher.deliveries = DeliveriesRepo(conn, env.clock)
    run = env.runs.ensure(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    env.runs.mark_queued(run.id)
    await env.process_run(env.runs.get(run.id))
    row = conn.execute("SELECT * FROM run_deliveries").fetchone()
    assert (row["run_id"], row["channel"], row["mode"], row["status"]) == (run.id, "telegram", "full", "sent")
    assert env.runs.get(run.id).status is RunStatus.done


def test_to_api_times_converts_time_fields_only():
    from my_planner.api.models import to_api_times

    got = to_api_times({
        "now": "2026-10-24T13:00:00+09:00",
        "scheduled_at": "2026-10-25T14:00:00.000000+09:00",
        "items": [{"completed_at": "2026-10-24T01:00:00.000000+00:00", "title": "2026-10-25T14:00+09:00"}],
        "note": "2026-10-25T14:00:00+09:00",
        "planned_for": "2026-10-25",
        "updated_at": None,
    })
    assert got == {
        "now": "2026-10-24T04:00:00Z",
        "scheduled_at": "2026-10-25T05:00:00Z",
        "items": [{"completed_at": "2026-10-24T01:00:00Z", "title": "2026-10-25T14:00+09:00"}],
        "note": "2026-10-25T14:00:00+09:00",  # 자유 글은 그대로
        "planned_for": "2026-10-25",
        "updated_at": None,
    }


def test_error_counter_prunes_on_emit_without_snapshot():
    clock = FakeClock(SAT_1300)
    counter = ErrorCounter(clock)
    lg = logging.getLogger("my_planner.test_prune")
    lg.addHandler(counter)
    lg.propagate = False
    try:
        for _ in range(3 * 24 * 60):  # 사흘 동안 1분마다, /health는 한 번도 읽지 않는다
            lg.warning("tick_error")
            clock.advance(timedelta(minutes=1))
        assert len(counter._events) <= 24 * 60 + 1
    finally:
        lg.removeHandler(counter)
        lg.propagate = True


async def test_daily_cap_shared_by_channels(tmp_path):
    """하루 두뇌 호출 상한은 두 통로가 함께 쓴다(SP3-4 6.4.1)."""
    from ui_stream import parse_sse

    from my_planner.config import LimitsConfig
    from my_planner.harness.dispatcher import DAILY_CAP_REPLY

    script = [FakeTurn([], "텔레그램 답"), FakeTurn([], "앱 답")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=script,
                           overrides={"limits": LimitsConfig(daily_brain_calls=2)}) as env:
        await env.telegram("안녕")
        _, first = await env.chat("앱에서 안녕")
        _, capped = await env.chat("또 안녕")
        await env.telegram("텔레그램도 또")
        health = await (await env.get("/health")).json()
        sent = [o.text for o in env.sender.sent]

    def text(raw):
        return "".join(c["delta"] for c in parse_sse(raw) if c["type"] == "text-delta")

    assert text(first) == "앱 답"
    assert text(capped) == DAILY_CAP_REPLY
    assert sent == ["텔레그램 답", DAILY_CAP_REPLY]
    assert health["brain"]["calls_today"] == 2


async def test_health_inbound_pending_oldest_at(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        assert (await _health(env))["inbound_pending_oldest_at"] is None
        for uid, at, done in ((1, kst(2026, 10, 24, 10, 5), 0), (2, kst(2026, 10, 24, 10, 0), 0),
                              (3, kst(2026, 10, 24, 9, 0), 1)):
            env.conn.execute(
                "INSERT INTO inbound_pending (update_id, text_redacted, sent_at, received_at, brain_done) "
                "VALUES (?, 'x', ?, ?, ?)", (uid, to_iso(at), to_iso(at), done),
            )
        env.conn.commit()
        body = await _health(env)
    assert body["inbound_pending_oldest_at"] == "2026-10-24T01:00:00Z"


async def test_health_features_include_agent_notes(tmp_path):
    from test_api_read import get_json

    async with BeEnv.start(tmp_path, start=kst(2026, 11, 1, 14, 0)) as env:
        body = await get_json(env, "/health")
    assert body["features"] == ["mate", "agent_notes"]

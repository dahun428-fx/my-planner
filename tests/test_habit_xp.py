"""습관 체크 경험치 X11 (SP7 스펙 5.6). 내용은 꾸며 낸 것이다."""

import sqlite3

import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst
from test_habit_tools import HabitEnv

from my_planner.domain import RunContext
from my_planner.status import xp
from my_planner.tools.actions import ActionRequest

SAT_1300 = kst(2026, 10, 24, 13, 0)


def _ledger(conn):
    return [
        (r["source_kind"], r["source_ref"], r["amount"], r["logical_date"], r["area"], r["label"])
        for r in conn.execute("SELECT * FROM status_xp_ledger ORDER BY id")
    ]


@pytest.fixture
def env(tmp_path, conn):
    return HabitEnv(tmp_path, conn)


def test_habit_xp_once_per_day(env):
    h = env.add("운동", area="health")
    ctx = env.user()
    first = env.tools.check_habit(ctx, id=h)
    env.tools.uncheck_habit(ctx, id=h)
    env.tools.check_habit(ctx, id=h)
    env.tools.check_habit(ctx, id=h)  # already
    assert first["already"] is False
    assert _ledger(env.conn) == [("habit_check", f"habit:{h}:2026-10-24", 3, "2026-10-24", "health", "습관 체크")]
    assert ctx.xp.gained == 3
    assert env.status.total() == 3
    # 다른 날짜, 다른 습관은 따로 쌓인다
    other = env.add("배움", area="learning")
    env.tools.check_habit(ctx, id=h, date="2026-10-23")
    env.tools.check_habit(ctx, id=other)
    assert env.status.total() == 9
    assert xp.XP_HABIT_CHECK == 3 and xp.LABEL_HABIT_CHECK == "습관 체크"


def test_past_day_check_xp_logical_date_is_that_day(env):
    h = env.add()
    env.tools.check_habit(env.user(), id=h, date="2026-10-19")
    (row,) = env.conn.execute("SELECT * FROM status_xp_ledger").fetchall()
    assert (row["logical_date"], row["source_ref"]) == ("2026-10-19", f"habit:{h}:2026-10-19")
    assert row["at"].startswith("2026-10-24T04:00")  # `at`은 지금(UTC)


def test_pause_archive_uncheck_leave_ledger(env):
    h = env.add()
    env.tools.check_habit(env.user(), id=h)
    before = _ledger(env.conn)
    env.tools.uncheck_habit(env.user(), id=h)
    env.tools.set_habit_status(env.user(), id=h, status="paused")
    env.tools.set_habit_status(env.user(), id=h, status="archived")
    assert _ledger(env.conn) == before


async def test_rest_day_unchanged_with_habit_checks(tmp_path):
    """X9: 습관만 체크한 날도 완료한 할 일이 없으면 쉬는 날이다."""
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        ctx = RunContext(conversation_id=None, run_id=None, actor="user", channel="app")
        h = env.parts.tools.add_habit(ctx, title="물 마시기", area="health", kind="daily")["id"]
        env.parts.tools.check_habit(ctx, id=h)
        env.clock.set(kst(2026, 10, 25, 9, 0))
        res = env.parts.dispatcher.apply_action(
            ActionRequest("grant_rest_days", {}, actor="secretary", channel="scheduler"))
        rows = [(r[0], r[1], r[2]) for r in _ledger(env.conn)]
    assert res.body["result"]["granted_dates"] == ["2026-10-24"]
    assert rows == [("habit_check", f"habit:{h}:2026-10-24", 3), ("rest_day", "date:2026-10-24", 5)]


def test_no_habit_week_kind(env, conn):
    """주간 목표 보상은 없다(기간 한정 보상, 5.6): 목표만큼 체크해도 원장은 체크 줄뿐, 원장 CHECK도 받지 않는다."""
    h = env.add("운동", kind="weekly", target=3)
    for d in ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"):
        env.tools.check_habit(env.user(), id=h, date=d)
    assert {r[0] for r in _ledger(conn)} == {"habit_check"}
    assert env.status.total() == 12
    assert not [n for n in dir(xp) if "HABIT" in n and "WEEK" in n]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO status_xp_ledger (at, logical_date, source_kind, source_ref, amount, label) "
            "VALUES ('2026-10-24T04:00:00.000000+00:00', '2026-10-24', 'habit_week', 'x', 5, 'x')"
        )

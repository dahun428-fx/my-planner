"""속성 시험 (SP3-4 1장 완료 조건 8, 16장): 무작위 순서의 도구, 되돌리기, 회차 답, 하루 한 번 작업 뒤에도
경험치 합계와 레벨은 줄지 않고 원장의 모든 행은 양수다. SP8: 활동 보너스의 성질(SP8 스펙 5.3, 13장).
내용은 꾸며 낸 것이다."""

import tempfile
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path

from fakes import FakeBrain, FakeSender, make_settings
from hypothesis import HealthCheck, example, given, settings, target
from hypothesis import strategies as st
from test_dispatcher_messages import kst

from my_planner.app import build_be
from my_planner.clock import FakeClock, period_of, to_iso
from my_planner.domain import Area, Cadence, LoopKey, RunContext
from my_planner.status.activity import (
    BodyDayRow,
    DoneTask,
    HabitCheckRow,
    activity_counts,
    area_bonus,
    area_points,
    effective_score,
)
from my_planner.status.xp import level_for
from my_planner.store.db import migrate, open_db
from my_planner.tools.actions import ActionRequest

START = kst(2026, 10, 24, 13, 0)

OPS = st.one_of(
    st.tuples(st.just("add"), st.integers(0, 5)),
    st.tuples(st.just("complete"), st.integers(0, 7)),
    st.tuples(st.just("reopen"), st.integers(0, 7)),
    st.tuples(st.just("drop"), st.integers(0, 7)),
    st.tuples(st.just("undo"), st.integers(0, 30)),
    st.tuples(st.just("condition"), st.integers(1, 5)),
    st.tuples(st.just("ladder"), st.integers(0, 10)),
    st.tuples(st.just("areas"), st.integers(1, 10)),
    st.tuples(st.just("priority"), st.sampled_from(list(Cadence))),
    st.tuples(st.just("grant"), st.sampled_from([5, 10, 7])),
    st.tuples(st.just("answer"), st.sampled_from(list(LoopKey))),
    st.tuples(st.just("hours"), st.integers(1, 40)),
    st.tuples(st.just("daily"), st.just(0)),
)


def _parts(root: Path):
    s = make_settings(root)
    conn = open_db(s.paths.state_dir / "planner.db")
    migrate(conn)
    clock = FakeClock(START)
    parts = build_be(s, conn, clock, brain_factory=lambda tools: FakeBrain([], tools, clock=clock),
                     sender_factory=lambda _t: FakeSender())
    parts.state.set("installed_at", to_iso(START - timedelta(minutes=1)))
    return parts, conn, clock


def _apply(parts, action, args, channel="app"):
    actor = "secretary" if channel == "scheduler" else "user"
    return parts.dispatcher.apply_action(ActionRequest(action, args, actor=actor, channel=channel))


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(OPS, min_size=1, max_size=25))
def test_xp_and_level_never_decrease(ops):
    with tempfile.TemporaryDirectory() as tmp:
        parts, conn, clock = _parts(Path(tmp))
        try:
            ids: list[int] = []
            total = parts.dispatcher.xp_total()
            for op, v in ops:
                if op == "add":
                    res = _apply(parts, "add_task", {"title": f"꾸민 일 {v}", "areas": ["health"]})
                    if res.status == "applied":
                        ids.append(res.body["result"]["id"])
                elif op in ("complete", "reopen", "drop") and ids:
                    action = {"complete": "complete_task", "reopen": "reopen_task", "drop": "drop_task"}[op]
                    _apply(parts, action, {"id": ids[v % len(ids)]}, channel="telegram")  # 확인 없이 바로
                elif op == "undo":
                    _apply_undo(parts, v)
                elif op == "condition":
                    _apply(parts, "record_condition", {"score": v})
                elif op == "ladder":
                    _apply(parts, "record_ladder_score", {"now": v})
                elif op == "areas":
                    _apply(parts, "record_area_scores", {"scores": {"career": v}})
                elif op == "priority" and ids:
                    today = parts.tools.today()
                    _apply(parts, "set_priorities", {"cadence": v.value, "period": period_of(v, today),
                                                     "task_ids": ids[-1:]}, channel="telegram")
                elif op == "grant":
                    parts.tools.grant_xp(RunContext(conversation_id=None, run_id=None), amount=v, reason="꾸민 사유")
                elif op == "answer":
                    run = parts.runs.ensure(v, clock.now() - timedelta(minutes=10),
                                            Cadence.week if v is LoopKey.review else Cadence.day)
                    parts.runs.mark_done(run.id)
                    parts.dispatcher.mark_answered(run.id, "app")
                elif op == "hours":
                    clock.advance(hours=v)
                elif op == "daily":
                    _apply(parts, "grant_rest_days", {}, channel="scheduler")
                now_total = parts.dispatcher.xp_total()
                assert now_total >= total, op
                assert level_for(now_total) >= level_for(total), op
                total = now_total
            amounts = [r[0] for r in conn.execute("SELECT amount FROM status_xp_ledger")]
            assert all(a > 0 for a in amounts)
            assert sum(amounts) == total
        finally:
            conn.close()


def _apply_undo(parts, v):
    ids = [r[0] for r in parts.tools.tasks.conn.execute("SELECT id FROM activity ORDER BY id").fetchall()]
    if ids:
        parts.dispatcher.apply_action(ActionRequest("undo", {"activity_id": ids[v % len(ids)]}, actor="user",
                                                    channel="app", endpoint="undo"))


# --- SP8 1단계: 활동 보너스의 성질 ---

T_DAY = date(2026, 10, 25)
AREA_NAMES = [a.value for a in Area]
STEPS = (5000, 6000, 12000, None)
SLEEP = (400, 420, None, 480)

# 활동 하나 = (출처, T_DAY에서 며칠 전, 영역들, 값). 창 밖(28일 이상 전)과 경계도 섞는다.
# 할 일의 값은 끝낸 시(KST): 4시 전이면 전날 논리적 날짜다.
ACTIVITY = st.one_of(
    st.tuples(st.just("task"), st.integers(0, 35), st.lists(st.sampled_from(AREA_NAMES), max_size=3, unique=True),
              st.integers(0, 23)),
    st.tuples(st.just("check"), st.integers(0, 35), st.sampled_from(AREA_NAMES).map(lambda a: [a]),
              st.integers(1, 4)),
    st.tuples(st.just("body"), st.integers(0, 35), st.just(["health"]), st.integers(0, 3)),
)

# 촘촘한 묶음: 영역 둘과 건강, 창 안 날짜만, 40~200개. 상한 2와 `min(10, …)` 구역에 닿게 한다.
DENSE_AREAS = [Area.career.value, Area.health.value]
DENSE = st.one_of(
    st.tuples(st.just("task"), st.integers(0, 27), st.sampled_from(DENSE_AREAS).map(lambda a: [a]),
              st.integers(4, 23)),
    st.tuples(st.just("check"), st.integers(0, 27), st.sampled_from(DENSE_AREAS).map(lambda a: [a]),
              st.integers(1, 4)),
    st.tuples(st.just("body"), st.integers(0, 27), st.just(["health"]), st.integers(0, 3)),
)
ACTS = st.one_of(st.lists(ACTIVITY, max_size=60), st.lists(DENSE, min_size=40, max_size=200))
# 포화된 묶음: 28일 매일 커리어 할 일 3개(하루 상한), S = 43.5
SATURATED = [("task", d, ["career"], 9 + k) for d in range(28) for k in range(3)]


def _rows(acts):
    tasks, checks, body, seen_checks, seen_body = [], [], [], set(), set()
    for i, (src, ago, areas, v) in enumerate(acts):
        d = T_DAY - timedelta(days=ago)
        if src == "task":
            tasks.append(DoneTask(id=i, completed_at=kst(d.year, d.month, d.day, v, 30), areas=tuple(areas)))
        elif src == "check" and (v, d) not in seen_checks:  # 습관·날짜마다 한 번(PRIMARY KEY)
            seen_checks.add((v, d))
            checks.append(HabitCheckRow(habit_id=v, area=areas[0], date=d))
        elif src == "body" and d not in seen_body:  # 날짜마다 한 행
            seen_body.add(d)
            body.append(BodyDayRow(date=d, steps=STEPS[v], sleep_minutes=SLEEP[v]))
    return tasks, checks, body


def _bonuses(rows, today):
    tasks, checks, body = rows
    kw = {"tz": "Asia/Seoul", "boundary": time(4, 0)}
    return area_bonus(area_points(tasks, checks, body, today, **kw), today,
                      activity_counts(tasks, checks, body, today, **kw))


@settings(max_examples=300, deadline=None)
@given(ACTS, st.dictionaries(st.sampled_from(AREA_NAMES), st.integers(1, 10)))
@example(SATURATED, {"career": 9, "health": 4})
@example(SATURATED, {"career": 4})
def test_effective_between_base_and_base_plus_2(acts, bases):
    bonuses = _bonuses(_rows(acts), T_DAY)
    target(float(max(b.score_s for b in bonuses.values())))
    for area, b in bonuses.items():
        assert Decimal("0.0") <= b.bonus <= Decimal("2.0")
        base = bases.get(area)
        eff = effective_score(base, b.bonus)
        if base is None:
            assert eff is None
        else:
            assert eff is not None and Decimal(base) <= eff <= min(Decimal(10), Decimal(base) + 2)


@settings(max_examples=300, deadline=None)
@given(ACTS, st.integers(0, 30))
@example(SATURATED, 0)
def test_no_new_activity_bonus_never_rises(acts, shift):
    rows = _rows(acts)  # 모든 활동이 T_DAY 이전이라 `today` 뒤로 새 활동이 없다
    today = T_DAY + timedelta(days=shift)
    now, nxt = _bonuses(rows, today), _bonuses(rows, today + timedelta(days=1))
    for area in AREA_NAMES:
        assert nxt[area].score_s <= now[area].score_s, area
        assert nxt[area].bonus <= now[area].bonus, area


@settings(max_examples=300, deadline=None)
@given(ACTS, st.one_of(st.lists(ACTIVITY, max_size=20), st.lists(DENSE, min_size=10, max_size=40)))
@example(SATURATED, [])
@example([], [("task", 0, ["career"], 9 + k) for k in range(5)])
def test_daily_change_at_most_0_7(acts, extra):
    """하루가 지나며 그날(T + 1) 새 활동이 더해져도, 없어도 보너스가 바뀌는 폭은 0.7 이하."""
    tasks, checks, body = _rows(acts)
    t1 = T_DAY + timedelta(days=1)
    # 새 활동은 모두 T + 1의 논리적 날짜(할 일은 4시 이후에 끝냄)
    new = [(src, -1, areas, max(v, 4) if src == "task" else v) for src, _ago, areas, v in extra]
    n_tasks, n_checks, n_body = _rows(new)
    n_tasks = [DoneTask(id=1000 + t.id, completed_at=t.completed_at, areas=t.areas) for t in n_tasks]
    now = _bonuses((tasks, checks, body), T_DAY)
    nxt = _bonuses((tasks + n_tasks, checks + n_checks, body + n_body), t1)
    for area in AREA_NAMES:
        assert abs(nxt[area].bonus - now[area].bonus) <= Decimal("0.7"), area

"""하루·한 주 보기의 순수 함수 `period_view`, `period_outside` (SP6 스펙 6.4, 10.2). 내용은 꾸며 낸 것이다."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from test_tools_tasks import ToolEnv

from my_planner.domain import RunContext, TaskStatus
from my_planner.store.views import DayView, period_outside, period_view, today_view

TODAY = date(2026, 10, 24)  # 토
MON, SUN = date(2026, 10, 19), date(2026, 10, 25)  # 2026-W43


@pytest.fixture
def env(tmp_path, conn):
    return ToolEnv(tmp_path, conn)


def _ctx():
    return RunContext(conversation_id=1, run_id=None)


def _add(env, title, **kw):
    if "scheduled_at" in kw:  # SP9 전 시각 있는 할 일(도구로는 못 만든다, SP9 5.4): 저장소로 바로 만든다
        pf, at = kw.pop("planned_for", None), kw.pop("scheduled_at")
        assert not kw
        return env.repo.create(title, ["health"], planned_for=date.fromisoformat(pf) if pf else None,
                               scheduled_at=datetime.fromisoformat(at).replace(tzinfo=ZoneInfo("Asia/Seoul"))).id
    return env.tools.add_task(_ctx(), title=title, areas=["health"], **kw)["id"]


def _ids(day: DayView) -> list[int]:
    return [t.id for t in day.tasks]


def _soft_delete(env, tid):
    t = env.repo.get(tid)
    env.repo.restore(tid, status=t.status, completed_at=t.completed_at, deleted_at=env.clock.now())


def test_today_does_not_pull_earlier_open(env):
    earlier = _add(env, "꾸민 어제 일", planned_for="2026-10-23")
    today = _add(env, "꾸민 오늘 일", planned_for="2026-10-24")

    (day,) = period_view(env.repo, TODAY, TODAY, TODAY)
    assert _ids(day) == [today]
    assert day.is_today and day.weekday == "토" and day.date == TODAY
    # 오늘 화면은 전에 잡은 열린 할 일을 끌어온다(다른 규칙)
    tv = today_view(env.repo, None, env.clock.now(), "Asia/Seoul", env.tools.boundary)
    assert earlier in [t.id for g in tv.groups for t in g.tasks]


def test_only_open_and_done(env):
    keep_open = _add(env, "꾸민 열림", planned_for="2026-10-22")
    keep_done = _add(env, "꾸민 끝", planned_for="2026-10-22")
    env.tools.complete_task(_ctx(), id=keep_done)
    dropped = _add(env, "꾸민 뺌", planned_for="2026-10-22")
    env.tools.drop_task(_ctx(), id=dropped)
    gone = _add(env, "꾸민 지움", planned_for="2026-10-22")
    _soft_delete(env, gone)
    env.tools.propose_tasks(_ctx(), tasks=[{"title": "꾸민 초안", "areas": ["health"], "planned_for": "2026-10-22"}])

    days = period_view(env.repo, MON, SUN, TODAY)
    assert [d.date for d in days] == [date(2026, 10, d) for d in range(19, 26)]
    assert [d.weekday for d in days] == list("월화수목금토일")
    assert [d.is_today for d in days] == [False] * 5 + [True, False]
    assert _ids(days[3]) == [keep_open, keep_done]
    assert all(_ids(d) == [] for i, d in enumerate(days) if i != 3)


def test_each_task_once(env):
    a = _add(env, "꾸민 하나", planned_for="2026-10-20", scheduled_at="2026-10-20T09:00")
    b = _add(env, "꾸민 둘", planned_for="2026-10-21")
    days = period_view(env.repo, MON, SUN, TODAY)
    every = [i for d in days for i in _ids(d)]
    assert sorted(every) == sorted([a, b]) and len(every) == len(set(every))


def test_order_scheduled_then_open_then_done(env):
    d = "2026-10-22"
    done_first = _add(env, "꾸민 끝", planned_for=d)
    env.tools.complete_task(_ctx(), id=done_first)
    untimed = _add(env, "꾸민 시각 없음", planned_for=d)
    late = _add(env, "꾸민 늦게", planned_for=d, scheduled_at=f"{d}T18:00")
    early = _add(env, "꾸민 일찍", planned_for=d, scheduled_at=f"{d}T08:00")

    (day,) = period_view(env.repo, date(2026, 10, 22), date(2026, 10, 22), TODAY)
    assert _ids(day) == [early, late, untimed, done_first]
    assert not day.is_today


def test_outside_reasons_order(env):
    inside = _add(env, "꾸민 안", planned_for="2026-10-21")
    dropped_dated = _add(env, "꾸민 뺌", planned_for="2026-10-21")  # 기간 안이어도 뺀 것이 먼저
    env.tools.drop_task(_ctx(), id=dropped_dated)
    no_date = _add(env, "꾸민 날짜 없음")
    moved = _add(env, "꾸민 밖", planned_for="2026-11-03")
    gone = _add(env, "꾸민 지움")
    _soft_delete(env, gone)
    done_inside = _add(env, "꾸민 끝 안", planned_for="2026-10-20")
    env.tools.complete_task(_ctx(), id=done_inside)

    out = period_outside(env.repo, [moved, inside, gone, no_date, dropped_dated, done_inside, 999], MON, SUN)
    assert [(reason, t.id) for reason, t in out] == [("moved", moved), ("no_date", no_date),
                                                     ("dropped", dropped_dated)]
    assert env.repo.get(dropped_dated).status is TaskStatus.dropped

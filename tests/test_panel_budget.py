"""SP15-05: 주간 제안 수 `panel/budget.py` (스펙 7.3, T4). 제안은 지어낸 것이다."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta

import pytest

from my_planner.clock import FakeClock, logical_date
from my_planner.panel.budget import (
    BUDGET_KEY,
    WindowCounts,
    budget_for,
    compute_week_budget,
    next_budget,
    remaining,
    settle_week,
    week_key,
    week_monday,
    weeks_before,
)
from my_planner.store.db import transaction
from my_planner.store.repos.panel import PanelRepo
from my_planner.store.repos.state import StateRepo

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def _w(**kw: int) -> WindowCounts:
    return WindowCounts(**{"accepted": 0, "done": 0, "postponed": 0, "dismissed": 0, "expired": 0, **kw})


@pytest.mark.parametrize(("prev", "w", "expected"), [
    (2, _w(done=7, postponed=3), 3),                                  # 완료율 0.7, 거절률 0
    (2, _w(done=7, postponed=3, accepted=4, dismissed=6), 2),         # 거절률 6/20 = 0.3이라 +1 아님
    (2, _w(done=2, postponed=3), 2),                                  # 완료율 0.4라 −1 아님
    (2, _w(done=1, postponed=2), 1),                                  # 완료율 0.33
    (2, _w(done=3, postponed=5), 1),                                  # 완료율 0.375
    (3, _w(done=2, postponed=0, dismissed=2), 2),                     # 거절률 0.5
    (3, _w(accepted=2, dismissed=2), 2),                              # 닫힌 받은 것 0, 거절률 0.5만으로 −1
    (3, _w(accepted=3, dismissed=1), 3),                              # 완료율 규칙 건너뜀
    (5, _w(done=10), 5),                                              # 최고 조건이어도 5
    (1, _w(dismissed=5, expired=5), 1),                               # 최악 조건이어도 1
    (4, _w(done=1, dismissed=1), 4),                                  # n = 2
    (2, _w(done=2, expired=1, postponed=0, accepted=0), 2),           # 거절률 1/3 ≥ 0.3이라 +1 아님
], ids=range(12))
def test_next_budget_boundaries(prev, w, expected):
    assert next_budget(prev, w) == expected


def test_week_helpers():
    assert week_key(date(2026, 11, 2)) == "2026-W45"
    assert week_key(date(2026, 1, 1)) == "2026-W01"
    assert week_key(date(2027, 1, 3)) == "2026-W53"
    assert week_monday("2026-W45") == date(2026, 11, 2)
    assert weeks_before("2026-W45", 4) == ["2026-W41", "2026-W42", "2026-W43", "2026-W44"]
    assert weeks_before("2027-W01", 2) == ["2026-W52", "2026-W53"]


def _suggest(p: PanelRepo, week: str, state: str = "proposed") -> int:
    with transaction(p.conn):
        sid = p.add_suggestion(
            conversation_id=None, kind="task", title="가짜 제안", area="career", size_min=30, per_week=None,
            due_hint=None, experts=["career"], evidence=[{"type": "record", "ref": "task:1", "note": "가짜"}],
            week=week, now=NOW,
        )
        if state != "proposed":
            p.set_state(sid, state, now=NOW)
    return sid


@pytest.fixture
def repos(conn):
    clock = FakeClock(NOW)
    return PanelRepo(conn, clock), StateRepo(conn, clock)


def test_first_four_weeks_are_two(repos):
    p, s = repos
    assert compute_week_budget(p, s, "2026-W45") == 2  # 제안이 없다
    # W45~W48에 끝낸 것만 10개: 결과가 좋아도 처음 4주는 2
    for week in ("2026-W45", "2026-W46", "2026-W47", "2026-W48"):
        for _ in range(3):
            _suggest(p, week, "done")
    for week in ("2026-W45", "2026-W46", "2026-W47", "2026-W48"):
        assert compute_week_budget(p, s, week) == 2
    assert compute_week_budget(p, s, "2026-W49") == 3  # W45~W48 창(완료율 1, 거절률 0)으로 +1
    assert compute_week_budget(p, s, "2026-W50") == 4  # 저장값 없음: W49를 같은 함수로 계산해 prev 3
    s.set(BUDGET_KEY.format(week="2026-W49"), "1")
    assert compute_week_budget(p, s, "2026-W50") == 2  # 저장값이 있으면 그것이 prev


def test_settle_week_once_per_week(conn, caplog):
    clock = FakeClock(NOW)
    p, s = PanelRepo(conn, clock), StateRepo(conn, clock)
    for week in ("2026-W41", "2026-W42", "2026-W43", "2026-W44"):
        for _ in range(3):
            _suggest(p, week, "done")
    key = BUDGET_KEY.format(week="2026-W45")
    with caplog.at_level(logging.INFO, logger="my_planner.panel.budget"), transaction(conn):
        settle_week(conn, clock, date(2026, 11, 2))  # 월요일
    assert s.get(key) == "3"
    assert [(r.getMessage(), r.week, r.budget) for r in caplog.records] == [("panel_budget_set", "2026-W45", 3)]
    # 같은 주 수요일: 지난 주 창이 나빠져도 이번 주 값은 그대로
    with transaction(conn):
        for sg in p.in_weeks(["2026-W44"]):
            p.set_state(sg.id, "dismissed", now=NOW, dismiss_reason="none")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="my_planner.panel.budget"), transaction(conn):
        settle_week(conn, clock, date(2026, 11, 4))
    assert s.get(key) == "3" and caplog.records == []
    assert budget_for(p, s, date(2026, 11, 4)) == 3
    # 다음 월요일: 새 키(W42~W45 창, 거절률 3/9 ≥ 0.3이라 +1 없음, 완료율 1이라 −1 없음)
    with transaction(conn):
        settle_week(conn, clock, date(2026, 11, 9))
    assert s.get(BUDGET_KEY.format(week="2026-W46")) == "3"


def test_remaining_counts_all_states(repos):
    p, s = repos
    today = date(2026, 11, 4)
    _suggest(p, "2026-W45")
    assert remaining(p, s, today) == 1
    _suggest(p, "2026-W45", "dismissed")
    _suggest(p, "2026-W44")  # 지난 주 것은 세지 않는다
    assert budget_for(p, s, today) == 2
    assert remaining(p, s, today) == 0
    _suggest(p, "2026-W45")  # 넘어도 0 아래로 내려가지 않는다
    assert remaining(p, s, today) == 0


def test_week_key_uses_logical_date(repos):
    p, s = repos
    at = datetime(2026, 11, 9, 2, 0, tzinfo=UTC) - timedelta(hours=9)  # 2026-11-09(월) 02:00 KST
    today = logical_date(at, "Asia/Seoul", time(4, 0))
    assert today == date(2026, 11, 8)
    assert week_key(today) == "2026-W45"
    _suggest(p, "2026-W45")
    _suggest(p, "2026-W45")
    assert remaining(p, s, today) == 0  # 일요일 몫(지난 주)으로 센다
    assert remaining(p, s, date(2026, 11, 9)) == 2

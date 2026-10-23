"""따라잡기 판정 표 (스펙 8). 티켓 05는 R4(한계 안이면 실행)와 R5(한계 밖이면 late)만."""

import pytest
from fakes import make_settings
from test_dispatcher_messages import kst

from my_planner.domain import LoopKey, SkipReason
from my_planner.loop.catchup import decide
from my_planner.loop.schedule import ENABLED_LOOPS, Due, due_between, window_start

ALL_LOOPS = set(LoopKey)


@pytest.fixture
def cfg(tmp_path):
    return make_settings(tmp_path)


def _decide(cfg, last_tick, woke, loops=ALL_LOOPS):
    start = window_start(woke, last_tick, last_tick)
    pending = due_between(start, woke, cfg, cfg.timezone, loops)
    return decide(woke, last_tick, pending, cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)


def test_spec_table_row_1(cfg):
    # 월 08:00 → 월 10:30: morning_brief 실행
    d = _decide(cfg, kst(2026, 10, 26, 8, 0), kst(2026, 10, 26, 10, 30))
    assert d.primary == Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    assert d.merged == [] and d.skipped == []
    assert d.create_return is False and d.carry_review is None


def test_spec_table_row_2(cfg):
    # 월 08:00 → 월 13:00: morning_brief skipped(late)
    d = _decide(cfg, kst(2026, 10, 26, 8, 0), kst(2026, 10, 26, 13, 0))
    assert d.primary is None
    assert d.skipped == [(Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0)), SkipReason.late)]


def test_limit_boundary_12_00_included(cfg):
    # 월 08:00 → 정확히 월 12:00: 한계 시각까지는 보낸다
    d = _decide(cfg, kst(2026, 10, 26, 8, 0), kst(2026, 10, 26, 12, 0))
    assert d.primary == Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    assert d.skipped == []


def test_spec_table_row_3(cfg):
    # 월 17:00 → 화 01:00: evening_checkin(월) 실행. 앱이 켜는 루프(ENABLED_LOOPS)로 판정한다
    d = _decide(cfg, kst(2026, 10, 26, 17, 0), kst(2026, 10, 27, 1, 0), ENABLED_LOOPS)
    assert d.primary == Due(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
    assert d.merged == [] and d.skipped == []


def test_spec_table_row_4(cfg):
    # 월 17:00 → 화 05:00: evening_checkin(월) skipped(late). 화 아침 브리핑은 09:00이라 아직 예정 전
    d = _decide(cfg, kst(2026, 10, 26, 17, 0), kst(2026, 10, 27, 5, 0), ENABLED_LOOPS)
    assert d.primary is None
    assert d.skipped == [(Due(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30)), SkipReason.late)]


def test_spec_table_row_9(cfg):
    # 일 17:00 → 일 18:10: 저녁 체크인이 primary, 회고는 merged(한 메시지로 합쳐 실행)
    from my_planner.domain import Cadence

    d = _decide(cfg, kst(2026, 10, 25, 17, 0), kst(2026, 10, 25, 18, 10), ENABLED_LOOPS)
    assert d.primary == Due(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
    assert d.merged == [Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)]
    assert d.skipped == []


def test_merge_morning_beats_earlier_review(cfg):
    # 일 17:00 → 월 10:00(17시간, R1 아님): 일 저녁은 한계(월 04:00) 밖이라 late,
    # 일 회고(+3일 안)와 월 아침이 남는다. 회고가 더 이르지만 아침이 primary, 회고는 merged
    from my_planner.domain import Cadence

    d = _decide(cfg, kst(2026, 10, 25, 17, 0), kst(2026, 10, 26, 10, 0), ENABLED_LOOPS)
    assert d.primary == Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    assert d.merged == [Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)]
    assert d.skipped == [(Due(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0)), SkipReason.late)]


def test_merge_priority_order(cfg):
    # return_ > evening_checkin > morning_brief > review. 넣는 순서와 상관없이 같은 결과
    from my_planner.domain import Cadence

    now = kst(2026, 10, 26, 10, 0)
    ret = Due(LoopKey.return_, kst(2026, 10, 26, 9, 50))
    eve = Due(LoopKey.evening_checkin, kst(2026, 10, 26, 9, 55))  # 판정만 보려고 시각은 한계 안에 둔다
    mor = Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    rev = Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    for pending in ([rev, mor, eve, ret], [ret, eve, mor, rev], [mor, rev, ret, eve]):
        d = decide(now, now, pending, cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
        assert (d.primary, d.merged) == (ret, [eve, mor, rev])

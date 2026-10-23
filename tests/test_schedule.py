from datetime import timedelta

import pytest
from fakes import make_settings
from test_dispatcher_messages import kst

from my_planner.domain import Cadence, LoopKey
from my_planner.loop.schedule import Due, due_between

ALL_LOOPS = set(LoopKey)


@pytest.fixture
def cfg(tmp_path):
    return make_settings(tmp_path)


def test_weekday_times(cfg):
    # 2026-10-26은 월요일
    got = due_between(kst(2026, 10, 26, 4, 0), kst(2026, 10, 27, 4, 0), cfg, cfg.timezone, ALL_LOOPS)
    assert got == [
        Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0)),
        Due(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30)),
    ]


def test_weekend_times(cfg):
    # 2026-10-24은 토요일
    got = due_between(kst(2026, 10, 24, 4, 0), kst(2026, 10, 25, 4, 0), cfg, cfg.timezone, ALL_LOOPS)
    assert got == [
        Due(LoopKey.morning_brief, kst(2026, 10, 24, 10, 0)),
        Due(LoopKey.evening_checkin, kst(2026, 10, 24, 18, 0)),
    ]


def test_half_open_interval(cfg):
    nine = kst(2026, 10, 26, 9, 0)
    # 시작 시각과 같은 회차는 빼고, 끝 시각과 같은 회차는 넣는다
    assert due_between(nine, kst(2026, 10, 26, 10, 0), cfg, cfg.timezone, ALL_LOOPS) == []
    assert due_between(kst(2026, 10, 26, 8, 0), nine, cfg, cfg.timezone, ALL_LOOPS) == [
        Due(LoopKey.morning_brief, nine)
    ]
    # loops에 없는 루프는 나오지 않는다
    day = (kst(2026, 10, 26, 4, 0), kst(2026, 10, 27, 4, 0))
    assert due_between(*day, cfg, cfg.timezone, {LoopKey.morning_brief}) == [Due(LoopKey.morning_brief, nine)]


def test_sunday_review_has_week_cadence(cfg):
    # 2026-10-25은 일요일: 아침 10:00, 저녁 18:00, 회고(week) 18:00
    got = due_between(kst(2026, 10, 25, 4, 0), kst(2026, 10, 26, 4, 0), cfg, cfg.timezone, ALL_LOOPS)
    assert got == [
        Due(LoopKey.morning_brief, kst(2026, 10, 25, 10, 0)),
        Due(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0)),
        Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week),
    ]


def test_window_start_first_run_uses_installed_at():
    from my_planner.loop.schedule import window_start

    now = kst(2026, 10, 26, 9, 30)
    installed = kst(2026, 10, 26, 8, 0)
    assert window_start(now, None, installed) == installed


def test_window_start_capped_7_days():
    from my_planner.loop.schedule import window_start

    now = kst(2026, 10, 26, 9, 30)
    old = now - timedelta(days=20)
    assert window_start(now, old, old - timedelta(days=1)) == now - timedelta(days=7)


def test_window_start_future_last_seen_clamped_to_now():
    from my_planner.loop.schedule import window_start

    now = kst(2026, 10, 26, 9, 30)
    assert window_start(now, now + timedelta(days=2), now - timedelta(days=1)) == now


def test_limits_and_reply_windows(cfg):
    from my_planner.loop.schedule import limit_for, reply_window_end

    tz, b = cfg.timezone, cfg.day_boundary
    morning = Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    evening = Due(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))  # 월
    review = Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)  # 일

    assert limit_for(morning, cfg, tz, b) == kst(2026, 10, 26, 12, 0)
    assert limit_for(evening, cfg, tz, b) == kst(2026, 10, 27, 4, 0)  # 화 04:00
    assert limit_for(review, cfg, tz, b) == kst(2026, 10, 28, 18, 0)  # +3일

    assert reply_window_end(morning, tz, b) == kst(2026, 10, 26, 12, 0)
    assert reply_window_end(evening, tz, b) == kst(2026, 10, 27, 4, 0)
    assert reply_window_end(review, tz, b) == kst(2026, 10, 26, 18, 0)  # 24시간

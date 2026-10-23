"""따라잡기 판정 표 (스펙 8). 티켓 05는 R4(한계 안이면 실행)와 R5(한계 밖이면 late)만."""

from datetime import timedelta

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


# --- 티켓 09: R1(복귀 인사), 넘겨 받은 회고, 하루 3회 상한, 시계 이상 ---


def _judged(d):
    """판정을 받은 회차: skipped와 carry_review."""
    return sorted([due for due, _ in d.skipped] + ([d.carry_review] if d.carry_review else []),
                  key=lambda x: x.scheduled_for)


def test_clock_jumped_far_ahead_is_capped_at_7_days(cfg):
    # 시계가 30일 앞으로 갔다(월 13:00). 창은 7일로 잘리고 R1: return 하나, 판정 대상은 7일치뿐
    woke = kst(2026, 10, 26, 13, 0)
    last = woke - timedelta(days=30)
    pending = due_between(window_start(woke, last, last), woke, cfg, cfg.timezone, ENABLED_LOOPS)
    d = decide(woke, last, pending, cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)

    assert d.create_return is True
    assert d.primary == Due(LoopKey.return_, woke)
    assert d.merged == []
    assert _judged(d) == pending and len(pending) == 15  # 아침 7 + 저녁 7 + 회고 1
    assert min(x.scheduled_for for x in pending) > woke - timedelta(days=7)
    assert all(r is SkipReason.merged_into_return for _, r in d.skipped)


def test_spec_table_row_5(cfg):
    # 토 17:00 → 일 18:30(25.5시간): R1, return 하나. 일요일 회고는 넘겨 받아 다음 정규 연락에 합친다
    from my_planner.domain import Cadence

    woke = kst(2026, 10, 25, 18, 30)
    d = _decide(cfg, kst(2026, 10, 24, 17, 0), woke, ENABLED_LOOPS)
    assert d.create_return is True
    assert d.primary == Due(LoopKey.return_, woke)
    assert d.merged == []
    assert d.carry_review == Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    assert d.skipped == [
        (Due(LoopKey.evening_checkin, kst(2026, 10, 24, 18, 0)), SkipReason.merged_into_return),
        (Due(LoopKey.morning_brief, kst(2026, 10, 25, 10, 0)), SkipReason.merged_into_return),
        (Due(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0)), SkipReason.merged_into_return),
    ]


def test_spec_table_row_7(cfg):
    # 금 22:00 → 목 08:00(5.4일): R1, return 하나. 일요일 회고는 +3일(수 18:00)이 지나 merged_into_return.
    # 복귀 인사가 목 09:00 아침 브리핑 전에 나가므로 그 아침 브리핑도 merged_into_return
    from my_planner.domain import Cadence

    woke = kst(2026, 10, 29, 8, 0)
    d = _decide(cfg, kst(2026, 10, 23, 22, 0), woke, ENABLED_LOOPS)
    assert (d.create_return, d.primary, d.merged, d.carry_review) == (True, Due(LoopKey.return_, woke), [], None)
    assert all(r is SkipReason.merged_into_return for _, r in d.skipped)
    skipped = [due for due, _ in d.skipped]
    assert Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week) in skipped
    assert skipped[-1] == Due(LoopKey.morning_brief, kst(2026, 10, 29, 9, 0))
    assert len(skipped) == 11 + 1  # 공백 동안 아침 5 + 저녁 5 + 회고 1, 그리고 목 아침


def test_spec_table_row_6(cfg):
    # 금 22:00 → 화 08:00(3.4일): R1, return 하나(08:00). 화 09:00 아침 브리핑은 merged_into_return.
    # 일요일 회고는 +3일(수 18:00) 안이라 carry_review, 화 17:30 저녁 체크인에 합친다
    from my_planner.domain import Cadence

    woke = kst(2026, 10, 27, 8, 0)
    review = Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    d = _decide(cfg, kst(2026, 10, 23, 22, 0), woke, ENABLED_LOOPS)
    assert (d.create_return, d.primary, d.merged) == (True, Due(LoopKey.return_, woke), [])
    assert d.carry_review == review
    assert d.skipped[-1] == (Due(LoopKey.morning_brief, kst(2026, 10, 27, 9, 0)), SkipReason.merged_into_return)
    assert review not in [due for due, _ in d.skipped]

    # 화 17:30 저녁 체크인 tick: 넘겨 받은 회고가 merged로 들어간다.
    # 여기서는 carried_review를 손으로 넘긴다. carry 표시를 저장하고 다시 읽어 넘기는 러너 연결까지의
    # 끝에서 끝은 tests/test_runner.py::test_return_before_morning_skips_that_morning이 확인한다
    eve = Due(LoopKey.evening_checkin, kst(2026, 10, 27, 17, 30))
    now = kst(2026, 10, 27, 17, 31)
    d2 = decide(now, now - timedelta(minutes=1), [eve], carried_review=review,
                cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert (d2.primary, d2.merged, d2.skipped, d2.carry_review) == (eve, [review], [], None)
    assert d2.create_return is False


def _review_sun():
    from my_planner.domain import Cadence

    return Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)


def test_carried_review_not_executed_alone(cfg):
    # 화 14:00, 보낼 정규 연락이 없다: 넘겨 받은 회고는 혼자 나가지 않고 그대로 기다린다
    now = kst(2026, 10, 27, 14, 0)
    d = decide(now, now - timedelta(minutes=1), [], carried_review=_review_sun(),
               cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert (d.primary, d.merged, d.skipped, d.carry_review, d.create_return) == (None, [], [], None, False)


def test_carried_review_late_after_3_days(cfg):
    # 수 18:00(+3일)까지 정규 연락이 없었다. 수 18:01에는 skipped(late)
    review = _review_sun()
    at_limit = kst(2026, 10, 28, 18, 0)
    d = decide(at_limit, at_limit - timedelta(minutes=1), [], carried_review=review,
               cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert d.skipped == []
    now = kst(2026, 10, 28, 18, 1)
    d = decide(now, now - timedelta(minutes=1), [], carried_review=review,
               cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert (d.primary, d.merged) == (None, [])
    assert d.skipped == [(review, SkipReason.late)]


def test_r1_again_rejudges_carried_review(cfg):
    # 넘겨 받은 회고가 있는 채로 다시 24시간 넘게 꺼졌다: 그 회고도 공백의 회차로 다시 판정한다
    review = _review_sun()
    for woke, carry in ((kst(2026, 10, 28, 12, 0), review), (kst(2026, 10, 29, 12, 0), None)):
        d = decide(woke, woke - timedelta(hours=25), [], carried_review=review,
                   cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
        assert d.create_return is True and d.carry_review == carry
        # 한계(수 18:00)를 넘긴 넘겨 받은 회고는 공백 전부터 기다리던 회차라 late(Fix round 1, Minor 4)
        assert d.skipped == ([] if carry else [(review, SkipReason.late)])


def test_spec_table_row_10(cfg):
    # 금 18:00 → 토 09:30(15.5시간, R1 아님): 아직 보낼 회차가 없다. 토 아침 브리핑은 10:00(주말 시각)
    d = _decide(cfg, kst(2026, 10, 23, 18, 0), kst(2026, 10, 24, 9, 30), ENABLED_LOOPS)
    assert (d.primary, d.merged, d.skipped, d.create_return, d.carry_review) == (None, [], [], False, None)
    d = _decide(cfg, kst(2026, 10, 24, 9, 59), kst(2026, 10, 24, 10, 0), ENABLED_LOOPS)
    assert d.primary == Due(LoopKey.morning_brief, kst(2026, 10, 24, 10, 0))


def test_fourth_proactive_message_waits_then_merges_or_late(cfg):
    # 일 18:00: 오늘 이미 먼저 보낸 메시지가 3개다. 저녁 체크인과 회고는 보내지 않고 skip도 기록하지 않는다
    from my_planner.domain import Cadence

    eve = Due(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
    rev = Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    now = kst(2026, 10, 25, 18, 1)
    kw = {"cfg": cfg, "tz": cfg.timezone, "boundary": cfg.day_boundary}
    d = decide(now, now - timedelta(minutes=1), [eve, rev], proactive_today=3, **kw)
    assert (d.primary, d.merged, d.skipped) == (None, [], [])
    # 월 09:00(새 날, 0개): 일 저녁은 한계(월 04:00) 밖이라 late, 회고는 한계 안이라 월 아침 브리핑에 합친다
    mor = Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    now = kst(2026, 10, 26, 9, 0)
    d = decide(now, now - timedelta(minutes=1), [eve, rev, mor], proactive_today=0, **kw)
    assert (d.primary, d.merged, d.skipped) == (mor, [rev], [(eve, SkipReason.late)])


def test_clock_went_backwards(cfg):
    # last_seen_at이 지금보다 30시간 뒤(수동 시각 변경): 공백은 0, R1이 아니다. 남은 회차는 평소대로 판정한다
    now = kst(2026, 10, 26, 10, 0)
    mor = Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    d = decide(now, now + timedelta(hours=30), [mor], cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert d.clock_backwards is True
    assert (d.create_return, d.primary, d.skipped, d.carry_review) == (False, mor, [], None)
    d = decide(now, now - timedelta(minutes=1), [mor], cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert d.clock_backwards is False


def test_future_pending_not_judged_after_clock_backwards(cfg):
    # 상한 때문에 기다리던 일 18:00 저녁이 있는데 시계가 토 20:00으로 돌아갔다: 아직 오지 않은 회차는 판정하지 않는다
    eve = Due(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
    now = kst(2026, 10, 24, 20, 0)
    d = decide(now, kst(2026, 10, 25, 18, 1), [eve], cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert (d.primary, d.merged, d.skipped, d.clock_backwards) == (None, [], [], True)


def test_r1_run_waiting_before_gap_past_limit_is_late(cfg):
    # 일 18:00 저녁과 회고가 상한 때문에 기다리던 중(마지막 tick 일 18:01) 꺼졌다가 화 08:00에 켜졌다.
    # 공백 전부터 기다리던 저녁은 한계(월 04:00)가 지나 late. 회고는 한계 안이라 넘겨 받는다. 공백 안의 회차는 merged_into_return
    from my_planner.domain import Cadence

    eve = Due(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
    rev = Due(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    mon_m = Due(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    mon_e = Due(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
    woke = kst(2026, 10, 27, 8, 0)
    d = decide(woke, kst(2026, 10, 25, 18, 1), [eve, rev, mon_m, mon_e],
               cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert d.create_return is True and d.carry_review == rev
    assert d.skipped == [
        (eve, SkipReason.late),
        (mon_m, SkipReason.merged_into_return),
        (mon_e, SkipReason.merged_into_return),
        (Due(LoopKey.morning_brief, kst(2026, 10, 27, 9, 0)), SkipReason.merged_into_return),
    ]


def test_r1_gap_boundary_exactly_24h(cfg):
    # 공백이 정확히 24시간이면 R1(≥), 1초 모자라면 R1이 아니다
    now = kst(2026, 10, 27, 14, 0)
    kw = {"cfg": cfg, "tz": cfg.timezone, "boundary": cfg.day_boundary}
    assert decide(now, now - timedelta(hours=24), [], **kw).create_return is True
    assert decide(now, now - timedelta(hours=24) + timedelta(seconds=1), [], **kw).create_return is False


def test_carried_review_not_merged_into_return_primary(cfg):
    # 상한 때문에 기다리던 return이 primary가 되어도 넘겨 받은 회고는 합치지 않는다(정규 연락에만 합친다)
    ret = Due(LoopKey.return_, kst(2026, 10, 27, 8, 0))
    now = kst(2026, 10, 27, 8, 30)
    d = decide(now, now - timedelta(minutes=1), [ret], carried_review=_review_sun(),
               cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert (d.primary, d.merged, d.skipped) == (ret, [], [])

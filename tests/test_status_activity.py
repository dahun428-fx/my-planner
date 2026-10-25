"""영역 활동 → 스탯 보너스 공식 (SP8 스펙 5장, 5.4 계산 예). 가짜 행으로 순수 함수만 본다. 내용은 꾸며 낸 것이다."""

from datetime import date, time, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest
from test_dispatcher_messages import kst

from my_planner.domain import Area
from my_planner.status.activity import (
    BodyDayRow,
    DoneTask,
    HabitCheckRow,
    activity_counts,
    area_bonus,
    area_points,
    effective_score,
    round_bonus,
)

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
T = date(2026, 10, 25)  # 일요일


def _task(i, d, *areas, h=12, mi=0):
    return DoneTask(id=i, completed_at=kst(d.year, d.month, d.day, h, mi), areas=tuple(areas))


def _bonus(tasks=(), checks=(), body=(), today=T):
    tasks, checks, body = list(tasks), list(checks), list(body)
    points = area_points(tasks, checks, body, today, tz=TZ, boundary=BOUNDARY)
    counts = activity_counts(tasks, checks, body, today, tz=TZ, boundary=BOUNDARY)
    return area_bonus(points, today, counts)


def _daily_health_checks():
    return [HabitCheckRow(habit_id=1, area="health", date=T - timedelta(days=d)) for d in range(28)]


def _daily_steps():
    return [BodyDayRow(date=T - timedelta(days=d), steps=8123, sleep_minutes=None) for d in range(28)]


def test_example_1_career_mwf_12_tasks():
    # 9/28(월)부터 10/23(금)까지 월·수·금마다 하나씩
    days = [date(2026, 9, 28) + timedelta(weeks=w, days=k) for w in range(4) for k in (0, 2, 4)]
    assert len(days) == 12 and days[-1] == date(2026, 10, 23)
    b = _bonus(tasks=[_task(i, d, "career") for i, d in enumerate(days, start=1)])["career"]
    assert b.score_s == Fraction(162, 28)
    assert b.bonus == Decimal("1.2")
    assert effective_score(6, b.bonus) == Decimal("7.2")
    assert b.counts.tasks == 12 and b.counts.habit_checks == 0


def test_example_2_habit_daily_28_days_rounds_half_up():
    b = _bonus(checks=_daily_health_checks())["health"]
    assert b.score_s == Fraction(29, 4)  # 7.25
    assert b.score_s / 5 == Fraction(29, 20)  # 1.45, 부동소수로는 1.4가 될 수 있다
    assert b.bonus == Decimal("1.5")
    assert effective_score(4, b.bonus) == Decimal("5.5")
    assert b.counts.habit_checks == 28


@pytest.mark.parametrize(
    ("today", "bonus", "visible"),
    [
        (date(2026, 10, 28), "1.2", "5.2"),
        (date(2026, 11, 1), "0.8", "4.8"),
        (date(2026, 11, 8), "0.4", "4.4"),
        (date(2026, 11, 17), "0.1", "4.1"),
        (date(2026, 11, 18), "0.0", "4.0"),
        (date(2026, 11, 22), "0.0", "4.0"),
    ],
)
def test_example_2a_decay_dates(today, bonus, visible):
    b = _bonus(checks=_daily_health_checks(), today=today)["health"]
    assert b.bonus == Decimal(bonus)
    assert effective_score(4, b.bonus) == Decimal(visible)
    if today == date(2026, 11, 22):  # 28일째에는 셈에서도 빠진다
        assert b.score_s == 0 and b.counts.habit_checks == 0


@pytest.mark.parametrize(
    ("today", "bonus", "visible"),
    [
        (date(2026, 10, 25), "2.0", "6.0"),
        (date(2026, 10, 28), "2.0", "6.0"),
        (date(2026, 11, 1), "1.7", "5.7"),
        (date(2026, 11, 8), "0.8", "4.8"),
        (date(2026, 11, 15), "0.2", "4.2"),
        (date(2026, 11, 21), "0.0", "4.0"),
        (date(2026, 11, 22), "0.0", "4.0"),
    ],
)
def test_example_2prime_and_3_cap_and_decay(today, bonus, visible):
    b = _bonus(checks=_daily_health_checks(), body=_daily_steps(), today=today)["health"]
    if today == T:
        assert b.score_s == Fraction(29, 2)  # 14.5
        assert b.counts == type(b.counts)(tasks=0, habit_checks=28, body_days=28)
    assert b.bonus == Decimal(bonus)
    assert effective_score(4, b.bonus) == Decimal(visible)


def test_day_cap_3_ten_health_tasks_today():
    tasks = [_task(i, T, "health", h=10, mi=i) for i in range(10)]
    points = area_points(tasks, [], [], T, tz=TZ, boundary=BOUNDARY)
    assert points["health"] == {T: Fraction(3)}
    b = _bonus(tasks=tasks)["health"]
    assert b.bonus == Decimal("0.6")
    assert b.counts.tasks == 10  # 개수는 상한 없이 센다


def test_task_with_two_areas_splits_half():
    tasks = [_task(1, T, "career", "learning")]
    points = area_points(tasks, [], [], T, tz=TZ, boundary=BOUNDARY)
    assert points["career"] == {T: Fraction(1, 2)} and points["learning"] == {T: Fraction(1, 2)}
    bonuses = _bonus(tasks=tasks)
    assert bonuses["career"].bonus == Decimal("0.1") and bonuses["learning"].bonus == Decimal("0.1")
    assert bonuses["career"].counts.tasks == 1 and bonuses["learning"].counts.tasks == 1


def test_0230_completion_is_previous_logical_day():
    tasks = [_task(1, T, "career", h=2, mi=30)]
    points = area_points(tasks, [], [], T, tz=TZ, boundary=BOUNDARY)
    assert points["career"] == {date(2026, 10, 24): Fraction(1)}
    assert _bonus(tasks=tasks)["career"].score_s == Fraction(27, 28)


def test_window_27_days_in_28_days_out():
    tasks = [_task(1, T - timedelta(days=27), "career"), _task(2, T - timedelta(days=28), "career")]
    checks = [HabitCheckRow(1, "health", T - timedelta(days=27)), HabitCheckRow(1, "health", T - timedelta(days=28))]
    points = area_points(tasks, checks, [], T, tz=TZ, boundary=BOUNDARY)
    assert points["career"] == {T - timedelta(days=27): Fraction(1)}
    assert points["health"] == {T - timedelta(days=27): Fraction(1, 2)}
    b = _bonus(tasks=tasks, checks=checks)
    assert b["career"].score_s == Fraction(1, 28) and b["career"].counts.tasks == 1
    assert b["health"].score_s == Fraction(1, 56) and b["health"].counts.habit_checks == 1


def test_task_without_area_ignored():
    tasks = [_task(1, T)]
    points = area_points(tasks, [], [], T, tz=TZ, boundary=BOUNDARY)
    assert all(not v for v in points.values())
    bonuses = _bonus(tasks=tasks)
    assert set(bonuses) == {a.value for a in Area}
    assert all(b.bonus == Decimal("0.0") and b.counts.tasks == 0 for b in bonuses.values())


def test_bonus_never_negative_and_effective_at_most_10():
    bonuses = _bonus()
    assert all(b.bonus == Decimal("0.0") and b.score_s == 0 for b in bonuses.values())
    assert round_bonus(Fraction(0)) == Decimal("0.0")
    assert round_bonus(Fraction(1000)) == Decimal("2.0")  # S = 10에서 상한
    assert round_bonus(Fraction(10)) == Decimal("2.0") and round_bonus(Fraction(29, 4)) == Decimal("1.5")
    assert effective_score(9, Decimal("1.5")) == Decimal("10.0")
    assert str(effective_score(9, Decimal("1.5"))) == "10.0"
    assert effective_score(10, Decimal("2.0")) == Decimal("10.0")


def test_no_base_effective_null_bonus_kept():
    b = _bonus(checks=_daily_health_checks())["health"]
    assert effective_score(None, b.bonus) is None
    assert b.bonus == Decimal("1.5")  # 바탕이 없어도 보너스는 계산한다(5.5)
    assert effective_score(None, Decimal("1.2")) is None


def test_body_counts_health_only_with_thresholds():
    body = [
        BodyDayRow(T, steps=6000, sleep_minutes=420),  # 0.5 + 0.5
        BodyDayRow(T - timedelta(days=1), steps=5999, sleep_minutes=419),  # 셈에 들지 않는다
        BodyDayRow(T - timedelta(days=2), steps=None, sleep_minutes=480),  # 0.5
    ]
    points = area_points([], [], body, T, tz=TZ, boundary=BOUNDARY)
    assert points["health"] == {T: Fraction(1), T - timedelta(days=2): Fraction(1, 2)}
    assert all(not points[a.value] for a in Area if a is not Area.health)
    counts = activity_counts([], [], body, T, tz=TZ, boundary=BOUNDARY)
    assert counts["health"].body_days == 2 and counts["career"].body_days == 0

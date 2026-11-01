"""영역 활동 → 스탯 보너스 (SP8 스펙 5장). 저장하지 않고 읽을 때마다 지난 28일 행으로 계산하는 순수 함수다.

`w(d) = (28 − d) / 28`(`d = 0..27`), `S = Σ p × w`, `bonus = round_half_up(min(2, S / 5), 1)`,
`effective_score = min(10, base + bonus)`(base 없으면 None). 보너스는 0 이상이라 보이는 스탯은 바탕 아래로 가지 않는다
(ADR 0006). 디버프는 여기서 다루지 않는다(바탕 점수끼리, `snapshot._stats`). 입출력과 로그는 없다.
상수는 경험치 상수처럼 `config.toml`로 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from my_planner.clock import logical_date
from my_planner.domain import Area

WINDOW_DAYS = 28
TASK_POINT = 1
HABIT_POINT = Fraction(1, 2)  # 0.5
BODY_STEPS_MIN = 6000
BODY_SLEEP_MIN = 420
BODY_POINT = Fraction(1, 2)  # 0.5
WORKOUT_POINT = Fraction(1, 2)  # 0.5, 운동 기록이 있는 날(SP12 10장). 같은 날 여러 기록도 한 번
DAY_CAP = 3
BONUS_FULL = 10
BONUS_MAX = 2

_ONE_PLACE = Decimal("0.1")
_AREAS = tuple(a.value for a in Area)


@dataclass(frozen=True)
class DoneTask:
    id: int
    completed_at: datetime
    areas: tuple[str, ...]


@dataclass(frozen=True)
class HabitCheckRow:
    habit_id: int
    area: str
    date: date


@dataclass(frozen=True)
class BodyDayRow:
    date: date
    steps: int | None
    sleep_minutes: int | None


@dataclass(frozen=True)
class ActivityCounts:
    tasks: int
    habit_checks: int
    body_days: int
    workout_days: int = 0


@dataclass(frozen=True)
class Bonus:
    score_s: Fraction
    bonus: Decimal
    counts: ActivityCounts


def _in_window(day: date, today: date) -> bool:
    return 0 <= (today - day).days < WINDOW_DAYS


def _body_point(row: BodyDayRow) -> Fraction:
    p = Fraction(0)
    if row.steps is not None and row.steps >= BODY_STEPS_MIN:
        p += BODY_POINT
    if row.sleep_minutes is not None and row.sleep_minutes >= BODY_SLEEP_MIN:
        p += BODY_POINT
    return p


def _task_days(
    tasks: Iterable[DoneTask], today: date, tz: str | tzinfo, boundary: time
) -> list[tuple[DoneTask, date]]:
    """영역이 있고 창 안에 끝낸 할 일과 그 논리적 날짜."""
    out = []
    for t in tasks:
        if not t.areas:
            continue
        day = logical_date(t.completed_at, tz, boundary)
        if _in_window(day, today):
            out.append((t, day))
    return out


def area_points(
    tasks: Iterable[DoneTask], checks: Iterable[HabitCheckRow], body: Iterable[BodyDayRow], today: date, *,
    tz: str | tzinfo, boundary: time, workout_days: frozenset[date] = frozenset(),
) -> dict[str, dict[date, Fraction]]:
    """영역마다 창(`today − 27 .. today`) 안 날짜별 점수 `p(a, day)`, 하루 상한 3을 적용한 값(5.2). 영역 6개 모두."""
    raw: dict[str, dict[date, Fraction]] = {a: {} for a in _AREAS}

    def add(area: str, day: date, p: Fraction) -> None:
        if area in raw and p > 0:
            raw[area][day] = raw[area].get(day, Fraction(0)) + p

    for t, day in _task_days(tasks, today, tz, boundary):
        share = Fraction(TASK_POINT, len(t.areas))
        for area in t.areas:
            add(area, day, share)
    for c in checks:
        if _in_window(c.date, today):
            add(c.area, c.date, HABIT_POINT)
    for b in body:
        if _in_window(b.date, today):
            add(Area.health.value, b.date, _body_point(b))
    for d in workout_days:
        if _in_window(d, today):
            add(Area.health.value, d, WORKOUT_POINT)
    return {a: {d: min(Fraction(DAY_CAP), p) for d, p in days.items()} for a, days in raw.items()}


def activity_counts(
    tasks: Iterable[DoneTask], checks: Iterable[HabitCheckRow], body: Iterable[BodyDayRow], today: date, *,
    tz: str | tzinfo, boundary: time, workout_days: frozenset[date] = frozenset(),
) -> dict[str, ActivityCounts]:
    """창 안의 가중하지 않은 개수(5.6): 끝낸 할 일, 습관 체크, 셈에 든 몸 기록 날·운동 기록 날(건강만). 영역 6개 모두."""
    n_tasks = dict.fromkeys(_AREAS, 0)
    n_checks = dict.fromkeys(_AREAS, 0)
    for t, _day in _task_days(tasks, today, tz, boundary):
        for area in set(t.areas):
            if area in n_tasks:
                n_tasks[area] += 1
    for c in checks:
        if _in_window(c.date, today) and c.area in n_checks:
            n_checks[c.area] += 1
    body_days = len({b.date for b in body if _in_window(b.date, today) and _body_point(b) > 0})
    n_workout = len({d for d in workout_days if _in_window(d, today)})
    return {
        a: ActivityCounts(tasks=n_tasks[a], habit_checks=n_checks[a],
                          body_days=body_days if a == Area.health.value else 0,
                          workout_days=n_workout if a == Area.health.value else 0)
        for a in _AREAS
    }


def round_bonus(s: Fraction) -> Decimal:
    """`min(2, S / 5)`를 소수 한 자리로 반올림(ROUND_HALF_UP). `Decimal(Fraction)`은 쓸 수 없어 분자·분모로 나눈다."""
    x = min(Fraction(BONUS_MAX), s * BONUS_MAX / BONUS_FULL)
    return (Decimal(x.numerator) / Decimal(x.denominator)).quantize(_ONE_PLACE, ROUND_HALF_UP)


def effective_score(base: int | None, bonus: Decimal) -> Decimal | None:
    """보이는 스탯 `min(10, base + bonus)`, 소수 한 자리. 바탕이 없으면 None."""
    if base is None:
        return None
    return min(Decimal(10), Decimal(base) + bonus).quantize(_ONE_PLACE, ROUND_HALF_UP)


def area_bonus(
    points: dict[str, dict[date, Fraction]], today: date, counts: dict[str, ActivityCounts]
) -> dict[str, Bonus]:
    """영역 6개 모두의 `S`와 보너스. 창 밖 날짜는 무게 0이다."""
    out = {}
    for a in _AREAS:
        s = Fraction(0)
        for day, p in points.get(a, {}).items():
            d = (today - day).days
            if 0 <= d < WINDOW_DAYS:
                s += p * Fraction(WINDOW_DAYS - d, WINDOW_DAYS)
        out[a] = Bonus(score_s=s, bonus=round_bonus(s),
                       counts=counts.get(a, ActivityCounts(tasks=0, habit_checks=0, body_days=0, workout_days=0)))
    return out


def window_start(today: date) -> date:
    """창의 첫날 `T − 27`."""
    return today - timedelta(days=WINDOW_DAYS - 1)

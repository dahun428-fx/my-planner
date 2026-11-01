"""내 속도 표 (SP15 스펙 8장). 라이프 매니저 앞머리에 들어가는 표로, 모두 내 기록에서 계산한다.

`compute_pace`는 순수 함수, `load_pace`는 저장소에서 입력을 모으기만 한다(쓰기 없음). 날짜는 모두 논리적 날짜.
글에는 비율(`%`)을 쓰지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, local, logical_date
from my_planner.status.xp import AREA_LABELS
from my_planner.store.repos.agents import AgentsRepo
from my_planner.store.repos.body import BodyRepo
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.events import EventsRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.panel import PanelRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.repos.workout import WorkoutRepo

PACE_DONE_WEEKS = 8
PACE_RECENT_DAYS = 28
PACE_AHEAD_DAYS = 14

NO_RECORD = "기록 없음"
_WEEKDAYS = "월화수목금토일"
_DEFAULT_MINUTES = 60  # 길이 없는 일정
_EVENING = (time(19, 0), time(23, 0))
_MORNING = (time(9, 0), time(13, 0))
_AFTERNOON = (time(13, 0), time(19, 0))
_LOW_CONDITION = 3
_PANEL_KEYS = ("accepted", "done", "postponed", "dismissed")
_HABIT_STATUSES = ("active", "paused", "archived")


@dataclass(frozen=True)
class Occ:
    """그날 일정 하나(현지 시작 시각, 분). 하루 종일이면 `start`·`minutes`는 None."""

    day: date
    start: time | None
    minutes: int | None
    all_day: bool


@dataclass(frozen=True)
class PaceInputs:
    done: list[tuple[date, str | None]]       # (완료 논리적 날짜, 첫 영역)
    postponed: list[tuple[date, str | None]]  # `task_postponed` 사건 (날짜, 영역)
    workout_days: set[date]                    # 운동 기록 날 ∪ 건강 영역 습관 체크 날
    occurrences: list[Occ]
    conditions: list[tuple[date, int]]
    body: list[tuple[date, int | None, int | None]]  # (날짜, 걸음, 잠 분)
    panel: dict[str, int]                      # 지난 4주 accepted(받은 것 전부)·done·postponed·dismissed


@dataclass(frozen=True)
class Pace:
    done_per_week: dict[str, float]
    postponed: dict[str, int]
    postponed_weekday: int | None
    workout_days_per_week: float
    free_evenings: int
    free_weekend_halves: int
    condition_avg: float | None
    low_condition_days: int
    sleep_avg_h: float | None
    steps_avg: int | None
    panel: dict[str, int]


def _in(d: date, lo: date, hi: date) -> bool:
    return lo <= d <= hi


def _area_counts(rows: list[tuple[date, str | None]], lo: date, hi: date) -> Counter[str]:
    return Counter(a for d, a in rows if a is not None and _in(d, lo, hi))


def _ordered(counts: Counter[str]) -> list[str]:
    """영역 순서는 `AREA_LABELS` 순서(모르는 영역은 뒤)."""
    order = list(AREA_LABELS)
    return sorted(counts, key=lambda a: order.index(a) if a in order else len(order))


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _busy(occs: list[Occ], window: tuple[time, time]) -> bool:
    """하루 종일 일정이 있거나, 시각 있는 일정이 그 시간대와 겹친다(끝이 시작과 같으면 겹치지 않는다)."""
    lo, hi = _minutes(window[0]), _minutes(window[1])
    for o in occs:
        if o.all_day or o.start is None:
            return True
        start = _minutes(o.start)
        end = start + (o.minutes if o.minutes is not None else _DEFAULT_MINUTES)
        if start < hi and end > lo:
            return True
    return False


def _avg(xs: list[int]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def compute_pace(inp: PaceInputs, today: date) -> Pace:
    done_lo = today - timedelta(days=PACE_DONE_WEEKS * 7 - 1)
    recent_lo = today - timedelta(days=PACE_RECENT_DAYS - 1)
    ahead_hi = today + timedelta(days=PACE_AHEAD_DAYS - 1)

    done = _area_counts(inp.done, done_lo, today)
    postponed = _area_counts(inp.postponed, recent_lo, today)
    by_weekday = Counter(d.weekday() for d, _ in inp.postponed if _in(d, recent_lo, today))
    weekday = min(by_weekday, key=lambda w: (-by_weekday[w], w)) if by_weekday else None
    workout = sum(1 for d in inp.workout_days if _in(d, done_lo, today))

    by_day: dict[date, list[Occ]] = {}
    for o in inp.occurrences:
        if _in(o.day, today, ahead_hi):
            by_day.setdefault(o.day, []).append(o)
    evenings = halves = 0
    for k in range(PACE_AHEAD_DAYS):
        d = today + timedelta(days=k)
        occs = by_day.get(d, [])
        if d.weekday() < 5:
            evenings += not _busy(occs, _EVENING)
        else:
            halves += (not _busy(occs, _MORNING)) + (not _busy(occs, _AFTERNOON))

    scores = [s for d, s in inp.conditions if _in(d, recent_lo, today)]
    body = [(steps, sleep) for d, steps, sleep in inp.body if _in(d, recent_lo, today)]
    cond = _avg(scores)
    sleep = _avg([m for _, m in body if m is not None])
    steps = _avg([s for s, _ in body if s is not None])
    return Pace(
        done_per_week={a: round(done[a] / PACE_DONE_WEEKS, 1) for a in _ordered(done)},
        postponed={a: postponed[a] for a in _ordered(postponed)},
        postponed_weekday=weekday,
        workout_days_per_week=round(workout / PACE_DONE_WEEKS, 1),
        free_evenings=evenings,
        free_weekend_halves=halves,
        condition_avg=round(cond, 1) if cond is not None else None,
        low_condition_days=sum(1 for s in scores if s <= _LOW_CONDITION),
        sleep_avg_h=round(sleep / 60, 1) if sleep is not None else None,
        steps_avg=round(steps) if steps is not None else None,
        panel={k: inp.panel.get(k, 0) for k in _PANEL_KEYS} if inp.panel else {},
    )


def _label(area: str) -> str:
    return AREA_LABELS.get(area, area)


def pace_text(p: Pace) -> str:
    """앞머리 표. 값이 없는 줄은 `기록 없음`(빈 저녁·주말 줄은 늘 숫자)."""
    done = " · ".join(f"{_label(a)} {v:.1f}" for a, v in p.done_per_week.items()) or NO_RECORD
    if p.postponed:
        postponed = " · ".join(f"{_label(a)} {n}" for a, n in p.postponed.items())
        if p.postponed_weekday is not None:
            postponed += f" · 가장 많이 미룬 요일 {_WEEKDAYS[p.postponed_weekday]}"
    else:
        postponed = NO_RECORD
    workout = f"{p.workout_days_per_week:.1f}" if p.workout_days_per_week > 0 else NO_RECORD
    # 빈 시간은 앞으로의 달력에서 센 값이라 늘 있다: 0 · 0은 "꽉 찼다"는 뜻이지 기록 없음이 아니다(스펙 7.4 `no_time`)
    free = f"평일 저녁 {p.free_evenings} · 주말 반나절 {p.free_weekend_halves}"
    cond = (
        f"평균 {p.condition_avg:.1f} · 3 이하 날 {p.low_condition_days}" if p.condition_avg is not None else NO_RECORD
    )
    if p.sleep_avg_h is None and p.steps_avg is None:
        body = NO_RECORD
    else:
        sleep = f"{p.sleep_avg_h:.1f}시간" if p.sleep_avg_h is not None else NO_RECORD
        steps = str(p.steps_avg) if p.steps_avg is not None else NO_RECORD
        body = f"잠 {sleep} · 걸음 {steps}"
    pn = p.panel
    panel = (
        f"받음 {pn.get('accepted', 0)} · 끝냄 {pn.get('done', 0)} · 미룸 {pn.get('postponed', 0)} · "
        f"버림 {pn.get('dismissed', 0)}" if any(pn.values()) else NO_RECORD
    )
    return "\n".join([
        "## 내 속도 표",
        f"- 한 주에 끝낸 할 일(지난 {PACE_DONE_WEEKS}주 평균): {done}",
        f"- 미룬 할 일(지난 {PACE_RECENT_DAYS // 7}주): {postponed}",
        f"- 운동한 날(지난 {PACE_DONE_WEEKS}주 주 평균): {workout}",
        f"- 빈 저녁·주말(다음 {PACE_AHEAD_DAYS // 7}주): {free}",
        f"- 컨디션(지난 {PACE_RECENT_DAYS // 7}주): {cond}",
        f"- 잠·걸음(지난 {PACE_RECENT_DAYS // 7}주 평균): {body}",
        f"- 패널 제안(지난 {PACE_RECENT_DAYS // 7}주): {panel}",
    ])


def _occ(o_start: datetime | None, o_end: datetime | None, day: date, all_day: bool, tz: ZoneInfo) -> Occ:
    if all_day or o_start is None:
        return Occ(day=day, start=None, minutes=None, all_day=True)
    minutes = round((o_end - o_start).total_seconds() / 60) if o_end is not None else None
    return Occ(day=day, start=local(o_start, tz).time(), minutes=minutes, all_day=False)


def load_pace(
    conn: sqlite3.Connection, clock: Clock, today: date, *, tz: str, boundary: time
) -> Pace:
    """저장소에서 `PaceInputs`를 모아 `compute_pace`. 읽기만 한다. `tz`·`boundary`는 설정의 시간대·하루 경계."""
    zone = ZoneInfo(tz)
    done_lo = today - timedelta(days=PACE_DONE_WEEKS * 7 - 1)
    recent_lo = today - timedelta(days=PACE_RECENT_DAYS - 1)

    tasks = TasksRepo(conn, clock, tz=tz, boundary=boundary)
    done = [
        (logical_date(t.completed_at, zone, boundary), t.areas[0].value if t.areas else None)
        for t in tasks.list(status="done", from_=done_lo, to=today) if t.completed_at is not None
    ]
    postponed = [(e.day, e.area) for e in AgentsRepo(conn, clock).events_since(["task_postponed"], recent_lo)]

    habits = HabitsRepo(conn, clock)
    workout_days = WorkoutRepo(conn, clock).log_days(done_lo, today)
    for h in habits.list(_HABIT_STATUSES):
        if h.area == "health":
            workout_days.update(habits.checks_between(h.id, done_lo, today))

    events = EventsRepo(conn, clock, zone)
    occurrences = [
        _occ(o.start, o.end, o.date, o.all_day, zone)
        for o in events.occurrences(today, today + timedelta(days=PACE_AHEAD_DAYS - 1))
    ]
    conditions = [(c.date, c.score) for c in ConditionsRepo(conn, clock).between(recent_lo, today)]
    body = [(b.date, b.steps, b.sleep_minutes) for b in BodyRepo(conn, clock).between(recent_lo, today)]

    # 제안 창은 논리적 날짜로: 창 첫날의 하루 경계(현지)부터
    since = datetime.combine(recent_lo, boundary, zone)
    counts = Counter(s.state for s in PanelRepo(conn, clock).suggestions(since=since))
    panel = {
        "accepted": counts["accepted"] + counts["done"] + counts["postponed"],
        "done": counts["done"], "postponed": counts["postponed"], "dismissed": counts["dismissed"],
    }
    return compute_pace(PaceInputs(
        done=done, postponed=postponed, workout_days=workout_days, occurrences=occurrences, conditions=conditions,
        body=body, panel=panel,
    ), today)

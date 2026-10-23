"""회차 정의 → 예정 시각 목록 (스펙 5.4). 순수 함수만 둔다."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from my_planner.clock import is_weekend, logical_date
from my_planner.config import ReplyWindowConfig
from my_planner.domain import Cadence, LoopKey

if TYPE_CHECKING:
    from my_planner.config import Settings


MAX_WINDOW = timedelta(days=7)

# 앱이 켜는 루프. 프롬프트가 있는 루프만 넣는다: 05 morning_brief, 07 evening_checkin, 08 review.
ENABLED_LOOPS: frozenset[LoopKey] = frozenset({LoopKey.morning_brief, LoopKey.evening_checkin})


@dataclass(frozen=True)
class Due:
    loop: LoopKey
    scheduled_for: datetime  # UTC
    cadence: Cadence = Cadence.day


def _zone(tz: str | tzinfo) -> tzinfo:
    return ZoneInfo(tz) if isinstance(tz, str) else tz


def due_between(
    start: datetime, end: datetime, cfg: Settings, tz: str | tzinfo, loops: Iterable[LoopKey]
) -> list[Due]:
    """`(start, end]` 구간의 예정 회차를 시간순으로. `loops`에 든 루프만."""
    zone = _zone(tz)
    wanted = set(loops)
    first = start.astimezone(zone).date() - timedelta(days=1)
    last = end.astimezone(zone).date() + timedelta(days=1)
    out: list[Due] = []
    d = first
    while d <= last:
        for loop in (LoopKey.morning_brief, LoopKey.evening_checkin):
            if loop not in wanted:
                continue
            times = getattr(cfg.schedule, loop.value)
            at = datetime.combine(d, times.weekend if is_weekend(d) else times.weekday, zone).astimezone(UTC)
            if start < at <= end:
                out.append(Due(loop, at))
        week = cfg.schedule.review.week
        if LoopKey.review in wanted and d.weekday() == week.weekday_index:
            at = datetime.combine(d, week.time, zone).astimezone(UTC)
            if start < at <= end:
                out.append(Due(LoopKey.review, at, Cadence.week))
        d += timedelta(days=1)
    out.sort(key=lambda x: x.scheduled_for)
    return out


def window_start(now: datetime, last_seen_at: datetime | None, installed_at: datetime | None) -> datetime:
    """창 시작 = min(now, max(last_seen_at, installed_at, now - 7일)). 없는 값은 빼고 본다."""
    return min(now, max(t for t in (last_seen_at, installed_at, now - MAX_WINDOW) if t is not None))


def limit_for(due: Due, cfg: Settings, tz: str | tzinfo, boundary: time) -> datetime:
    """루프별 한계: 이 시각이 지나면 보내지 않는다(그 시각까지는 보낸다)."""
    lim = cfg.limits.catchup_limit
    if due.loop is LoopKey.review:
        return due.scheduled_for + timedelta(days=lim.review_days)
    return _day_bound(due, tz, boundary, lim.morning_brief_until, lim.evening_checkin_until)


def reply_window_end(
    due: Due, tz: str | tzinfo, boundary: time, *, cfg: Settings | None = None
) -> datetime:
    """답장 창의 끝: 이 시각까지 답하면 같은 회차 대화로 잇는다. `cfg`가 없으면 기본값을 쓴다."""
    win = cfg.limits.reply_window if cfg is not None else ReplyWindowConfig()
    if due.loop is LoopKey.review:
        return due.scheduled_for + timedelta(hours=win.review_hours)
    return _day_bound(due, tz, boundary, win.morning_brief_until, win.evening_checkin_until)


def _day_bound(
    due: Due, tz: str | tzinfo, boundary: time, morning_until: time, evening_until: time
) -> datetime:
    """아침은 예정일 당일의 `morning_until`, 저녁(과 복귀 인사)은 논리적 날짜 다음 날의 `evening_until`."""
    zone = _zone(tz)
    if due.loop is LoopKey.morning_brief:
        d = due.scheduled_for.astimezone(zone).date()
        return datetime.combine(d, morning_until, zone).astimezone(UTC)
    next_day = logical_date(due.scheduled_for, zone, boundary) + timedelta(days=1)
    return datetime.combine(next_day, evening_until, zone).astimezone(UTC)

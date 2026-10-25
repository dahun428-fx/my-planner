"""회차 정의 → 예정 시각 목록 (스펙 5.4). 순수 함수만 둔다."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from my_planner.clock import is_weekend, logical_date
from my_planner.config import ReplyWindowConfig
from my_planner.domain import Cadence, LoopKey

if TYPE_CHECKING:
    from my_planner.config import Settings


MAX_WINDOW = timedelta(days=7)

# 앱이 켜는 루프. 프롬프트가 있는 루프만 넣는다: 05 morning_brief, 07 evening_checkin, 08 review.
ENABLED_LOOPS: frozenset[LoopKey] = frozenset(
    {LoopKey.morning_brief, LoopKey.evening_checkin, LoopKey.review}
)


DayType = Literal["weekday", "weekend"]
DAY_TYPES: tuple[DayType, ...] = ("weekday", "weekend")
# 앱에서 시각을 바꿀 수 있는 루프(SP9 8장). 주간 회고는 주말 저녁을 따라간다
CHECKIN_LOOPS: tuple[LoopKey, ...] = (LoopKey.morning_brief, LoopKey.evening_checkin)


@dataclass(frozen=True)
class CheckinSlot:
    """바꾼 체크인 시각 한 칸(`app_state.schedule_override`, SP9 8장). 날짜 d(현지)의 시각은 `d >= from_`이면 `time`,
    아니면 `prev`(바꾸기 전 시각)."""

    time: time
    from_: date | None = None
    prev: time | None = None


Overrides = dict[LoopKey, dict[DayType, CheckinSlot]]


def day_type_of(d: date) -> DayType:
    return "weekend" if is_weekend(d) else "weekday"


def config_time(cfg: Settings, loop: LoopKey, day_type: DayType) -> time:
    """`config.toml`의 `[schedule.*]` 값(바꾸지 않은 칸)."""
    return getattr(getattr(cfg.schedule, loop.value), day_type)


def slot_time(cfg: Settings, overrides: Overrides | None, loop: LoopKey, day_type: DayType, d: date) -> time:
    """그 칸(루프, 평일·주말)의 날짜 d 시각. 칸이 없으면 config 값."""
    slot = (overrides or {}).get(loop, {}).get(day_type)
    if slot is None:
        return config_time(cfg, loop, day_type)
    if slot.from_ is None or d >= slot.from_:
        return slot.time
    return slot.prev if slot.prev is not None else config_time(cfg, loop, day_type)


def checkin_time(cfg: Settings, overrides: Overrides | None, loop: LoopKey, d: date) -> time:
    """날짜 d(현지)의 아침 브리핑·저녁 체크인 시각(SP9 8장)."""
    return slot_time(cfg, overrides, loop, day_type_of(d), d)


def review_time(cfg: Settings, overrides: Overrides | None, sunday: date) -> time:
    """주간 회고 시각은 주말 저녁 체크인을 따라간다(SP9 8장). 주말 저녁 칸이 없으면 지금처럼 config의
    `review.week.time`. 칸이 있으면 `from`부터 그 시각이고, 그 전은 바꾸기 전 값(`prev`가 config 주말 저녁 그대로였으면,
    즉 그 전에 바꾼 적이 없으면 config의 회고 시각)."""
    slot = (overrides or {}).get(LoopKey.evening_checkin, {}).get("weekend")
    week = cfg.schedule.review.week.time
    if slot is None:
        return week
    if slot.from_ is None or sunday >= slot.from_:
        return slot.time
    if slot.prev is None or slot.prev == config_time(cfg, LoopKey.evening_checkin, "weekend"):
        return week
    return slot.prev


def _hm(v: Any) -> time | None:
    if not isinstance(v, str):
        return None
    try:
        t = time.fromisoformat(v)
    except ValueError:
        return None
    return t.replace(second=0, microsecond=0)


def parse_overrides(raw: str | Mapping[str, Any] | None) -> Overrides:
    """`app_state.schedule_override` JSON → `Overrides`. 모르는 루프·칸, 잘못된 값은 버린다(그 칸은 config 값)."""
    if raw is None:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return {}
    out: Overrides = {}
    if not isinstance(data, Mapping):
        return out
    for loop in CHECKIN_LOOPS:
        slots = data.get(loop.value)
        if not isinstance(slots, Mapping):
            continue
        for day_type in DAY_TYPES:
            v = slots.get(day_type)
            if not isinstance(v, Mapping) or (t := _hm(v.get("time"))) is None:
                continue
            try:
                from_ = date.fromisoformat(v["from"]) if isinstance(v.get("from"), str) else None
            except ValueError:
                from_ = None
            out.setdefault(loop, {})[day_type] = CheckinSlot(t, from_, _hm(v.get("prev")))
    return out


def dump_overrides(overrides: Overrides) -> str:
    """`Overrides` → JSON(칸마다 `{"time", "from", "prev"}`)."""
    data = {
        loop.value: {
            day_type: {
                "time": f"{slot.time:%H:%M}",
                "from": slot.from_.isoformat() if slot.from_ else None,
                "prev": f"{slot.prev:%H:%M}" if slot.prev else None,
            }
            for day_type, slot in slots.items()
        }
        for loop, slots in overrides.items() if slots
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class Due:
    loop: LoopKey
    scheduled_for: datetime  # UTC
    cadence: Cadence = Cadence.day


def _zone(tz: str | tzinfo) -> tzinfo:
    return ZoneInfo(tz) if isinstance(tz, str) else tz


def due_between(
    start: datetime, end: datetime, cfg: Settings, tz: str | tzinfo, loops: Iterable[LoopKey],
    overrides: Overrides | None = None,
) -> list[Due]:
    """`(start, end]` 구간의 예정 회차를 시간순으로. `loops`에 든 루프만. 시각은 날마다 `checkin_time`(SP9 8장)."""
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
            at = datetime.combine(d, checkin_time(cfg, overrides, loop, d), zone).astimezone(UTC)
            if start < at <= end:
                out.append(Due(loop, at))
        week = cfg.schedule.review.week
        if LoopKey.review in wanted and d.weekday() == week.weekday_index:
            at = datetime.combine(d, review_time(cfg, overrides, d), zone).astimezone(UTC)
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

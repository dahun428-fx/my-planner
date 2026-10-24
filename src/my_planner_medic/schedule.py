"""다음 회차 예정 시각 (스펙 3.5 `next_run`). config.toml `[schedule]`과 `timezone`만 본다.

BE `loop/schedule.py`와 같은 규칙: 아침·저녁은 Asia/Seoul 달력 요일로 주말(토, 일)을 판정하고,
주간 회고는 `review.week.day`의 요일 `time`에 돈다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from .config import MedicConfig
from .tz import zone as _zone

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DEFAULTS: dict[str, Any] = {
    "morning_brief": {"weekday": "09:00", "weekend": "10:00"},
    "evening_checkin": {"weekday": "17:30", "weekend": "18:00"},
    "review": {"week": {"day": "sun", "time": "18:00"}},
}


def _hm(value: str) -> time:
    parts = [int(p) for p in str(value).split(":")]
    return time(*parts)


def _slots_on(d: date, schedule: dict[str, Any], zone: tzinfo) -> list[tuple[datetime, str]]:
    out: list[tuple[datetime, str]] = []
    weekend = d.weekday() >= 5
    for loop in ("morning_brief", "evening_checkin"):
        times = schedule.get(loop) or _DEFAULTS[loop]
        at = _hm(times["weekend"] if weekend else times["weekday"])
        out.append((datetime.combine(d, at, zone), loop))
    week = (schedule.get("review") or _DEFAULTS["review"]).get("week") or _DEFAULTS["review"]["week"]
    if d.weekday() == _WEEKDAYS.index(str(week["day"]).lower()):
        out.append((datetime.combine(d, _hm(week["time"]), zone), "review"))
    return out


def next_slot(cfg: MedicConfig, now: datetime) -> tuple[datetime, str]:
    """`now`보다 뒤의 첫 회차(시각, 루프). 시각은 설정 시간대의 aware datetime."""
    zone = _zone(cfg.timezone)
    local = now.astimezone(zone)
    for offset in range(8):
        d = local.date() + timedelta(days=offset)
        upcoming = sorted(s for s in _slots_on(d, cfg.schedule, zone) if s[0] > local)
        if upcoming:
            return upcoming[0]
    raise ValueError("schedule has no runs")  # 아침·저녁은 매일 있으므로 오지 않는다


def next_run(cfg: MedicConfig, now: datetime) -> datetime:
    return next_slot(cfg, now)[0]

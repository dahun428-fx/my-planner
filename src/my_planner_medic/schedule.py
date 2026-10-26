"""다음 회차 예정 시각 (스펙 3.5 `next_run`). config.toml `[schedule]`과 `timezone`, 그리고 앱에서 바꾼 체크인 시각
(`state/planner.db`의 `app_state.schedule_override`, 읽기 전용 `mode=ro`, SP9 8장)을 본다.

BE `loop/schedule.py`와 같은 규칙: 아침·저녁은 Asia/Seoul 달력 요일로 주말(토, 일)을 판정하고,
주간 회고는 `review.week.day`의 요일 `time`에 돈다. 바꾼 칸은 날짜 d가 `from` 이후면 `time`, 아니면 `prev`이고,
주간 회고는 주말 저녁 칸을 따라간다(`from` 전에는 `prev`, `prev`가 config 주말 저녁과 같으면 config 회고 시각).
DB가 없거나 못 읽으면 config만 쓴다. medic은 `my_planner`를 가져오지 않으므로 같은 규칙을 여기 따로 둔다.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
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


# (time, from, prev). from이 없으면 언제나 time
Slot = tuple[time, date | None, time | None]
Overrides = dict[str, dict[str, Slot]]
DB_FILE = Path("state") / "planner.db"


def _hm_or_none(v: Any) -> time | None:
    if not isinstance(v, str):
        return None
    try:
        return time.fromisoformat(v).replace(second=0, microsecond=0)
    except ValueError:
        return None


def parse_overrides(raw: str | None) -> Overrides:
    """`schedule_override` JSON → 칸들. 모르는 칸, 잘못된 값은 버린다(BE `parse_overrides`와 같은 규칙)."""
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return {}
    out: Overrides = {}
    if not isinstance(data, dict):
        return out
    for loop in ("morning_brief", "evening_checkin"):
        slots = data.get(loop)
        if not isinstance(slots, dict):
            continue
        for kind in ("weekday", "weekend"):
            v = slots.get(kind)
            if not isinstance(v, dict) or (t := _hm_or_none(v.get("time"))) is None:
                continue
            try:
                from_ = date.fromisoformat(v["from"]) if isinstance(v.get("from"), str) else None
            except ValueError:
                from_ = None
            out.setdefault(loop, {})[kind] = (t, from_, _hm_or_none(v.get("prev")))
    return out


def load_overrides(root: Path) -> Overrides:
    """`state/planner.db`의 바꾼 체크인 시각. 읽기 전용(`mode=ro`). 없거나 못 읽으면 빈 값(config만)."""
    db = Path(root) / DB_FILE
    if not db.exists():
        return {}
    try:
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = 'schedule_override'").fetchone()
    except sqlite3.Error:
        return {}
    return parse_overrides(row[0]) if row is not None else {}


def _slot(schedule: dict[str, Any], overrides: Overrides, loop: str, kind: str, d: date) -> time:
    base = _hm((schedule.get(loop) or _DEFAULTS[loop])[kind])
    slot = overrides.get(loop, {}).get(kind)
    if slot is None:
        return base
    t, from_, prev = slot
    if from_ is None or d >= from_:
        return t
    return prev if prev is not None else base


def _review(schedule: dict[str, Any], overrides: Overrides, week_time: time, d: date) -> time:
    slot = overrides.get("evening_checkin", {}).get("weekend")
    if slot is None:
        return week_time
    t, from_, prev = slot
    if from_ is None or d >= from_:
        return t
    base = _hm((schedule.get("evening_checkin") or _DEFAULTS["evening_checkin"])["weekend"])
    return week_time if prev is None or prev == base else prev


def _slots_on(
    d: date, schedule: dict[str, Any], zone: tzinfo, overrides: Overrides | None = None
) -> list[tuple[datetime, str]]:
    ov = overrides or {}
    out: list[tuple[datetime, str]] = []
    kind = "weekend" if d.weekday() >= 5 else "weekday"
    for loop in ("morning_brief", "evening_checkin"):
        out.append((datetime.combine(d, _slot(schedule, ov, loop, kind, d), zone), loop))
    week = (schedule.get("review") or _DEFAULTS["review"]).get("week") or _DEFAULTS["review"]["week"]
    if d.weekday() == _WEEKDAYS.index(str(week["day"]).lower()):
        out.append((datetime.combine(d, _review(schedule, ov, _hm(week["time"]), d), zone), "review"))
    return out


def next_slot(cfg: MedicConfig, now: datetime, overrides: Overrides | None = None) -> tuple[datetime, str]:
    """`now`보다 뒤의 첫 회차(시각, 루프). 시각은 설정 시간대의 aware datetime. `overrides`를 주지 않으면 DB에서 읽는다."""
    ov = load_overrides(cfg.root) if overrides is None else overrides
    zone = _zone(cfg.timezone)
    local = now.astimezone(zone)
    for offset in range(8):
        d = local.date() + timedelta(days=offset)
        upcoming = sorted(s for s in _slots_on(d, cfg.schedule, zone, ov) if s[0] > local)
        if upcoming:
            return upcoming[0]
    raise ValueError("schedule has no runs")  # 아침·저녁은 매일 있으므로 오지 않는다


def next_run(cfg: MedicConfig, now: datetime) -> datetime:
    return next_slot(cfg, now)[0]

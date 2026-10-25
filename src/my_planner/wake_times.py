"""깨우기 작업 `my-planner-wake`의 트리거 시각 (스펙 5.1, S4).

`python -m my_planner.wake_times`는 회차 시각보다 5분 이른 시각을 한 줄에 하나씩 출력한다:
`weekday HH:MM`(월~금) 또는 `weekend HH:MM`(토·일). `scripts/register_task.ps1`이 이 출력으로 트리거를 만든다.

`config.toml`의 `[schedule]`(과 오늘을 정할 `timezone`, `day_boundary`)만 읽는다. `.env`(비밀값)는 읽지 않는다.
SP9 8장: 앱에서 바꾼 체크인 시각(DB `app_state.schedule_override`)을 읽기 전용(`mode=ro`)으로 읽어 합친다.
`from` 이후 값과, `from`이 아직 오지 않았으면 그 전 값(`prev`)도 넣는다. DB가 없거나 못 읽으면 config만 쓴다.
"""

from __future__ import annotations

import sqlite3
import sys
import tomllib
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from my_planner.clock import logical_date
from my_planner.config import ScheduleConfig, Settings, resolve_root
from my_planner.domain import LoopKey
from my_planner.loop.schedule import Overrides, parse_overrides, review_time

WAKE_LEAD = timedelta(minutes=5)

DayKind = Literal["weekday", "weekend"]


DB_FILE = Path("state") / "planner.db"  # `app.DB_FILE`(app을 가져오지 않는다)


def _config(root: Path) -> dict[str, Any]:
    path = Path(root) / "config.toml"
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def load_schedule(root: Path) -> ScheduleConfig:
    return ScheduleConfig.model_validate(_config(root).get("schedule", {}))


def load_overrides(root: Path) -> Overrides:
    """DB의 `schedule_override`. 읽기 전용 연결(`mode=ro`)만 연다. DB가 없거나 못 읽으면 빈 값(config만)."""
    path = Path(root) / DB_FILE
    if not path.exists():
        return {}
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = 'schedule_override'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    return parse_overrides(row[0]) if row is not None else {}


def _early(t: time) -> time:
    """`t`보다 `WAKE_LEAD` 이른 시각. 00:05 전이면 전날 밤 시각이 되지만 같은 요일 묶음으로 둔다."""
    return (datetime.combine(datetime(2000, 1, 3), t) - WAKE_LEAD).time()


def _slot_times(schedule: ScheduleConfig, overrides: Overrides, loop: LoopKey, kind: DayKind, today: date) -> set[time]:
    """그 칸에서 깨워야 할 시각: 바꾼 칸이면 `time`과, `from`이 오늘보다 뒤면 `prev`도. 아니면 config 값."""
    slot = overrides.get(loop, {}).get(kind)
    if slot is None:
        return {getattr(getattr(schedule, loop.value), kind)}
    out = {slot.time}
    if slot.from_ is not None and slot.from_ > today:
        out.add(slot.prev if slot.prev is not None else getattr(getattr(schedule, loop.value), kind))
    return out


def wake_times(
    schedule: ScheduleConfig, overrides: Overrides | None = None, today: date | None = None
) -> list[tuple[DayKind, time]]:
    """평일·주말별로 정렬하고 같은 시각은 한 번만 둔다.

    일요일 회고는 주말 묶음에 넣는다(토요일에도 깨우지만 하는 일이 없어 해가 없다). 기본값처럼 주말 저녁과 같은
    시각이면 한 번만 나온다. 회고는 주말 저녁 칸을 따라간다(SP9 8장): 다음 일요일과 그 뒤의 회고 시각을 넣는다.
    """
    ov = overrides or {}
    d = today or date.today()
    weekday: set[time] = set()
    weekend: set[time] = set()
    for loop in (LoopKey.morning_brief, LoopKey.evening_checkin):
        weekday |= _slot_times(schedule, ov, loop, "weekday", d)
        weekend |= _slot_times(schedule, ov, loop, "weekend", d)
    cfg = Settings.model_construct(schedule=schedule)  # `review_time`은 `schedule`만 본다
    sunday = d + timedelta(days=(6 - d.weekday()) % 7)
    weekend |= {review_time(cfg, ov, sunday), review_time(cfg, ov, sunday + timedelta(days=7))}
    out: list[tuple[DayKind, time]] = []
    for kind, times in (("weekday", weekday), ("weekend", weekend)):
        out.extend((kind, t) for t in sorted({_early(t) for t in times}))
    return out


def _today(root: Path) -> date:
    data = _config(root)
    tz = data.get("timezone", "Asia/Seoul")
    raw = data.get("day_boundary", "04:00")
    boundary = raw if isinstance(raw, time) else time.fromisoformat(str(raw))
    return logical_date(datetime.now(ZoneInfo(tz)), tz, boundary)


def wake_lines(root: Path) -> list[str]:
    """`"weekday HH:MM"`/`"weekend HH:MM"` 줄. config에 DB의 바꾼 시각을 합친다(DB가 없거나 못 읽으면 config만)."""
    return [f"{kind} {t:%H:%M}" for kind, t in wake_times(load_schedule(root), load_overrides(root), _today(root))]


def main() -> int:
    for line in wake_lines(resolve_root()):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

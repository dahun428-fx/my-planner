"""깨우기 작업 `my-planner-wake`의 트리거 시각 (스펙 5.1, S4).

`python -m my_planner.wake_times`는 회차 시각보다 5분 이른 시각을 한 줄에 하나씩 출력한다:
`weekday HH:MM`(월~금) 또는 `weekend HH:MM`(토·일). `scripts/register_task.ps1`이 이 출력으로 트리거를 만든다.

`config.toml`의 `[schedule]`만 읽는다. `.env`(비밀값)는 읽지 않는다.
"""

from __future__ import annotations

import sys
import tomllib
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Literal

from my_planner.config import ScheduleConfig, resolve_root

WAKE_LEAD = timedelta(minutes=5)

DayKind = Literal["weekday", "weekend"]


def load_schedule(root: Path) -> ScheduleConfig:
    path = Path(root) / "config.toml"
    if not path.exists():
        return ScheduleConfig()
    with path.open("rb") as f:
        data = tomllib.load(f)
    return ScheduleConfig.model_validate(data.get("schedule", {}))


def _early(t: time) -> time:
    """`t`보다 `WAKE_LEAD` 이른 시각. 00:05 전이면 전날 밤 시각이 되지만 같은 요일 묶음으로 둔다."""
    return (datetime.combine(datetime(2000, 1, 3), t) - WAKE_LEAD).time()


def wake_times(schedule: ScheduleConfig) -> list[tuple[DayKind, time]]:
    """평일·주말별로 정렬하고 같은 시각은 한 번만 둔다.

    일요일 회고는 주말 묶음에 넣는다(토요일에도 깨우지만 하는 일이 없어 해가 없다). 기본값처럼 주말 저녁과 같은
    시각이면 한 번만 나온다.
    """
    weekday = {schedule.morning_brief.weekday, schedule.evening_checkin.weekday}
    weekend = {schedule.morning_brief.weekend, schedule.evening_checkin.weekend, schedule.review.week.time}
    out: list[tuple[DayKind, time]] = []
    for kind, times in (("weekday", weekday), ("weekend", weekend)):
        out.extend((kind, t) for t in sorted({_early(t) for t in times}))
    return out


def main() -> int:
    for kind, t in wake_times(load_schedule(resolve_root())):
        print(f"{kind} {t:%H:%M}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from my_planner_medic.schedule import next_run, next_slot

from .fakes import make_config

KST = ZoneInfo("Asia/Seoul")


def kst(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=KST)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (kst(2026, 10, 26, 8), kst(2026, 10, 26, 9)),  # 월 08:00 → 월 아침
        (kst(2026, 10, 26, 18), kst(2026, 10, 27, 9)),  # 월 18:00 → 화 아침
        (kst(2026, 10, 30, 18), kst(2026, 10, 31, 10)),  # 금 18:00 → 토 주말 아침
        (kst(2026, 11, 1, 17), kst(2026, 11, 1, 18)),  # 일 17:00 → 일 18:00 (저녁·주간 회고)
    ],
)
def test_next_run(now: datetime, expected: datetime) -> None:
    got = next_run(make_config(), now)
    assert got == expected
    assert got.tzinfo is not None


def test_next_slot_names_loop_and_prefers_review_on_sunday_tie() -> None:
    at, loop = next_slot(make_config(), kst(2026, 11, 1, 17))
    assert at == kst(2026, 11, 1, 18)
    assert loop in ("evening_checkin", "review")
    at, loop = next_slot(make_config(), kst(2026, 10, 26, 10))
    assert (at, loop) == (kst(2026, 10, 26, 17, 30), "evening_checkin")


def test_next_run_is_strictly_after_now() -> None:
    assert next_run(make_config(), kst(2026, 10, 26, 9)) == kst(2026, 10, 26, 17, 30)

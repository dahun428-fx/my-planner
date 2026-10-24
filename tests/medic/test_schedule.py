from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import my_planner_medic.tz as tz_mod
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


def test_next_slot_names_loop() -> None:
    # 일요일 18:00은 저녁 회차와 주간 회고가 겹친다: (시각, 루프) 정렬로 evening_checkin이 먼저다
    assert next_slot(make_config(), kst(2026, 11, 1, 17)) == (kst(2026, 11, 1, 18), "evening_checkin")
    at, loop = next_slot(make_config(), kst(2026, 10, 26, 10))
    assert (at, loop) == (kst(2026, 10, 26, 17, 30), "evening_checkin")


def test_next_run_is_strictly_after_now() -> None:
    assert next_run(make_config(), kst(2026, 10, 26, 9)) == kst(2026, 10, 26, 17, 30)


def test_timezone_falls_back_to_fixed_kst_without_tzdata(monkeypatch: pytest.MonkeyPatch) -> None:
    from zoneinfo import ZoneInfoNotFoundError

    def broken(name: str) -> ZoneInfo:
        raise ZoneInfoNotFoundError(name)

    monkeypatch.setattr(tz_mod, "ZoneInfo", broken)
    got = next_run(make_config(), kst(2026, 10, 26, 8))
    assert got == kst(2026, 10, 26, 9)
    assert got.utcoffset().total_seconds() == 9 * 3600
    assert tz_mod.zone("Asia/Seoul").tzname(None) == "Asia/Seoul"
    assert tz_mod.zone("Europe/Nowhere").utcoffset(None).total_seconds() == 0


def test_zone_bad_name_value_error_falls_back() -> None:
    assert tz_mod.zone("../etc").utcoffset(None).total_seconds() == 0

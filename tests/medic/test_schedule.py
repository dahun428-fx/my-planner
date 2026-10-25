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


# --- 앱에서 바꾼 체크인 시각 (SP9 8장): state/planner.db app_state.schedule_override ---


def _write_override(root, value: str) -> None:  # type: ignore[no-untyped-def]
    import sqlite3

    (root / "state").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "state" / "planner.db")
    conn.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO app_state VALUES ('schedule_override', ?)", (value,))
    conn.commit()
    conn.close()


def test_next_slot_reads_override(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_override(tmp_path, '{"morning_brief": {"weekday": {"time": "07:30", "from": null, "prev": null}}}')
    assert next_slot(make_config(root=tmp_path), kst(2026, 10, 26, 6)) == (kst(2026, 10, 26, 7, 30), "morning_brief")


def test_next_slot_override_from_prev(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # 월(10/26)은 prev 08:00, 화(10/27)부터 10:00
    _write_override(
        tmp_path, '{"morning_brief": {"weekday": {"time": "10:00", "from": "2026-10-27", "prev": "08:00"}}}'
    )
    cfg = make_config(root=tmp_path)
    assert next_slot(cfg, kst(2026, 10, 26, 6))[0] == kst(2026, 10, 26, 8)
    assert next_slot(cfg, kst(2026, 10, 26, 20))[0] == kst(2026, 10, 27, 10)


def test_next_slot_review_follows_weekend_evening(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_override(tmp_path, '{"evening_checkin": {"weekend": {"time": "20:00", "from": null, "prev": null}}}')
    cfg = make_config(root=tmp_path)
    # 일 19:00 이후 첫 회차는 20:00 저녁, 20:00 직후엔 다음 날 아침(회고도 20:00으로 옮겨졌다)
    assert next_slot(cfg, kst(2026, 11, 1, 19)) == (kst(2026, 11, 1, 20), "evening_checkin")
    assert next_slot(cfg, kst(2026, 11, 1, 20))[0] == kst(2026, 11, 2, 9)


def test_next_slot_missing_db_uses_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert next_slot(make_config(root=tmp_path), kst(2026, 10, 26, 8))[0] == kst(2026, 10, 26, 9)


def test_next_slot_corrupt_db_uses_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "planner.db").write_bytes(b"not a sqlite file at all" * 10)
    assert next_slot(make_config(root=tmp_path), kst(2026, 10, 26, 8))[0] == kst(2026, 10, 26, 9)


def test_next_slot_bad_json_uses_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _write_override(tmp_path, "{nope")
    assert next_slot(make_config(root=tmp_path), kst(2026, 10, 26, 8))[0] == kst(2026, 10, 26, 9)


def test_tick_stalled_uses_override(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from my_planner_medic.signals import _tick_stalled

    _write_override(tmp_path, '{"evening_checkin": {"weekday": {"time": "21:00", "from": null, "prev": null}}}')
    health = {"last_tick_at": kst(2026, 10, 26, 17).isoformat(), "runs_today": []}
    # config 기준(17:30)이면 15분 유예가 지나 멈춤이지만, 바꾼 21:00 기준으로는 아직 아니다
    assert _tick_stalled(health, kst(2026, 10, 26, 20), make_config()) is True  # /repo: DB 없음
    assert _tick_stalled(health, kst(2026, 10, 26, 20), make_config(root=tmp_path)) is False
    assert _tick_stalled(health, kst(2026, 10, 26, 21, 20), make_config(root=tmp_path)) is True

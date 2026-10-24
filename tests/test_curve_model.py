"""곡선 확대 단위, 컨디션 묶음, 안심 보기 (SP3-4 스펙 6.3.5, 8장). 내용은 모두 꾸며 낸 것이다."""

from datetime import UTC, date, datetime, timedelta

import pytest

from my_planner.clock import FakeClock
from my_planner.curve.model import (
    MAX_BUCKETS,
    TooManyBuckets,
    bucket_conditions,
    buckets,
    default_range,
    reassurance,
)
from my_planner.store.repos.conditions import Condition
from my_planner.store.repos.curve import CurveRepo, Ladder

D = date.fromisoformat
NOW = datetime(2026, 10, 24, tzinfo=UTC)


def test_buckets_iso_week_and_quarter_boundaries():
    (w,) = buckets("week", D("2026-12-28"), D("2027-01-03"))
    assert (w.name, w.start, w.end) == ("2026-W53", D("2026-12-28"), D("2027-01-03"))
    assert [b.name for b in buckets("week", D("2026-12-27"), D("2027-01-04"))] == ["2026-W52", "2026-W53", "2027-W01"]
    qs = buckets("quarter", D("2026-03-31"), D("2026-07-01"))
    assert [(b.name, b.start, b.end) for b in qs] == [
        ("2026-Q1", D("2026-01-01"), D("2026-03-31")),
        ("2026-Q2", D("2026-04-01"), D("2026-06-30")),
        ("2026-Q3", D("2026-07-01"), D("2026-09-30")),
    ]
    assert [b.name for b in buckets("month", D("2024-02-10"), D("2024-03-01"))] == ["2024-02", "2024-03"]
    assert buckets("month", D("2024-02-10"), D("2024-02-11"))[0].end == D("2024-02-29")
    assert [b.name for b in buckets("day", D("2026-10-23"), D("2026-10-24"))] == ["2026-10-23", "2026-10-24"]
    assert [b.name for b in buckets("year", D("2025-06-01"), D("2026-01-01"))] == ["2025", "2026"]


def test_default_ranges_per_zoom():
    today = D("2026-10-24")  # 토요일
    assert default_range("day", today, None) == (D("2026-09-25"), today)
    assert default_range("week", today, None) == (D("2026-04-27"), D("2026-10-25"))
    assert default_range("month", today, None) == (D("2024-11-01"), D("2026-10-31"))
    assert default_range("quarter", today, None) == (D("2022-01-01"), D("2026-12-31"))
    assert default_range("year", today, None) == (D("2026-01-01"), D("2026-12-31"))
    for zoom, expected in (("day", 30), ("week", 26), ("month", 24), ("quarter", 20)):
        assert len(buckets(zoom, *default_range(zoom, today, None))) == expected


def test_year_zoom_from_earliest_chapter(conn):
    curve = CurveRepo(conn, FakeClock(NOW))
    assert curve.earliest_chapter_start() is None
    ts = "2026-10-01T00:00:00.000000+00:00"
    for start, status in (("2015-04", "draft"), ("2019-03", "confirmed"), ("2012-01", "confirmed")):
        conn.execute(
            "INSERT INTO curve_chapters (title, start_month, status, origin, draft_since, created_at, updated_at) "
            "VALUES ('꾸민 챕터', ?, ?, 'seed', ?, ?, ?)",
            (start, status, ts if status == "draft" else None, ts, ts),
        )
    start = curve.earliest_chapter_start()
    assert start == D("2012-01-01")  # 초안(2015)은 세지 않는다
    assert default_range("year", D("2026-10-24"), start) == (D("2012-01-01"), D("2026-12-31"))
    assert len(buckets("year", *default_range("year", D("2026-10-24"), start))) == 15


def test_over_400_buckets_raises():
    assert len(buckets("day", D("2026-01-01"), D("2026-01-01") + timedelta(days=MAX_BUCKETS - 1))) == MAX_BUCKETS
    with pytest.raises(TooManyBuckets):
        buckets("day", D("2026-01-01"), D("2026-01-01") + timedelta(days=MAX_BUCKETS))
    with pytest.raises(TooManyBuckets):
        buckets("day", D("0002-01-01"), D("9998-01-01"))  # 끝까지 세지 않고 멈춘다


def cond(d, score):
    return Condition(date=D(d), score=score, note=None, recorded_at=NOW)


def test_bucket_conditions_average_logged_days_only():
    days = [cond("2026-10-01", 2), cond("2026-10-02", 3), cond("2026-10-05", 5), cond("2026-09-30", 1)]
    got = bucket_conditions(days, buckets("month", D("2026-09-01"), D("2026-11-30")))
    assert got == [
        {"bucket": "2026-09", "start": "2026-09-01", "end": "2026-09-30", "average": 1.0, "days_logged": 1},
        {"bucket": "2026-10", "start": "2026-10-01", "end": "2026-10-31", "average": 3.3, "days_logged": 3},
        {"bucket": "2026-11", "start": "2026-11-01", "end": "2026-11-30", "average": None, "days_logged": 0},
    ]
    (w,) = bucket_conditions(days, buckets("week", D("2026-10-01"), D("2026-10-02")))
    assert (w["bucket"], w["average"], w["days_logged"]) == ("2026-W40", 2.0, 3)


def test_reassurance_scaling_and_7_day_threshold():
    ladder = [
        Ladder("2026-08", 6, None, None, NOW),
        Ladder("2026-09", None, 8, None, NOW),  # 5년 뒤만 있는 달은 뺀다
        Ladder("2026-10", 6, 8, None, NOW),
        Ladder("2026-07", 4, None, None, NOW),
    ]
    scores = [3, 3, 4, 4, 3, 4, 3, 4, 3, 3]  # 평균 3.4, 10일
    days = [cond(f"2026-08-{i + 1:02d}", s) for i, s in enumerate(scores)]
    days += [cond(f"2026-10-{i + 1:02d}", 5) for i in range(6)]  # 6일: 근거가 적다
    days += [cond(f"2026-07-{i + 1:02d}", 1) for i in range(7)]  # 7일: 충분하다, 평균 1.0
    got = {r["period"]: r for r in reassurance(ladder, days)}
    assert set(got) == {"2026-07", "2026-08", "2026-10"}
    assert got["2026-08"] == {
        "period": "2026-08", "ladder_now": 6, "condition_average": 3.4, "condition_scaled": 6.0,
        "days_logged": 10, "gap": 0.0,
    }
    assert got["2026-10"] == {
        "period": "2026-10", "ladder_now": 6, "condition_average": None, "condition_scaled": None,
        "days_logged": 6, "gap": None,
    }
    assert got["2026-07"]["condition_scaled"] == 0.0 and got["2026-07"]["gap"] == -4.0

"""StandingRepo와 지표 검사 (SP13 스펙 6.1, 6.2)."""

from datetime import UTC, date, datetime

import pytest

from my_planner.clock import FakeClock
from my_planner.standing.metrics import METRICS, validate
from my_planner.store.db import transaction
from my_planner.store.repos.standing import StandingRepo

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
TODAY = date(2026, 10, 31)


@pytest.fixture
def s(conn):
    return StandingRepo(conn, FakeClock(NOW))


def _add(s, metric, value, on, kind="manual", ref=None):
    with transaction(s._conn):
        return s.add(metric, value, on, kind, ref, "mid", NOW)


def test_validate_rejects_unknown_range_future():
    assert validate("iq", 120, TODAY, TODAY) == "모르는 측정값이에요."
    assert validate("body_fat_pct", 80, TODAY, TODAY) == "체지방률 값이 맞지 않아요."
    assert validate("body_fat_pct", 17.5, date(2026, 11, 1), TODAY) == "측정일이 오늘보다 늦어요."
    assert validate("body_fat_pct", 17.5, TODAY, TODAY) is None
    assert validate("body_fat_pct", 3, TODAY, TODAY) is None and validate("body_fat_pct", 60, TODAY, TODAY) is None


def test_validate_enum_cert_birth_year():
    assert validate("profile_sex", "m", TODAY, TODAY) is None
    assert validate("profile_sex", "x", TODAY, TODAY) is not None
    assert validate("profile_sex", 1, TODAY, TODAY) is not None
    assert validate("profile_birth_year", 1930, TODAY, TODAY) is None
    assert validate("profile_birth_year", 2011, TODAY, TODAY) is None
    assert validate("profile_birth_year", 2012, TODAY, TODAY) is not None
    assert validate("profile_birth_year", 1929, TODAY, TODAY) is not None
    for ok in ("jlpt_n1", "toeic:825", "toeic:10", "toeic:990", "other:abc_1"):
        assert validate("cert", ok, TODAY, TODAY) is None, ok
    for bad in ("toeic:5", "toeic:995", "toeic:8x", "other:", "other:" + "a" * 31, "other:a-b", "foo", 5):
        assert validate("cert", bad, TODAY, TODAY) is not None, bad
    assert validate("weight_kg", "70", TODAY, TODAY) is not None
    assert validate("weight_kg", True, TODAY, TODAY) is not None


def test_every_metric_has_label():
    assert len(METRICS) == 50 and all(m.label for m in METRICS.values())
    assert METRICS["salary_krw"].label == "연봉(세전)" and METRICS["cert"].kind == "multi"


def test_salary_in_manwon_is_rejected():
    assert validate("salary_krw", 5500, TODAY, TODAY) is not None
    assert validate("salary_krw", 55_000_000, TODAY, TODAY) is None


def test_add_validates_and_roundtrips(s):
    with pytest.raises(ValueError):
        _add(s, "iq", 120, TODAY)
    with pytest.raises(ValueError):
        _add(s, "body_fat_pct", 80, TODAY)
    with pytest.raises(ValueError):
        _add(s, "body_fat_pct", 17, date(2026, 11, 5))
    i = _add(s, "weight_kg", 70.5, TODAY, "photo", "photo:3")
    m = s.get(i)
    assert m and m.value_num == 70.5 and m.value_text is None and m.source_ref == "photo:3"
    assert m.created_at == NOW and m.measured_on == TODAY and m.reliability == "mid"
    j = _add(s, "profile_sex", "m", TODAY)
    assert s.get(j).value_text == "m" and s.get(j).value_num is None
    assert s.get(999) is None


def test_latest_by_date_then_id(s):
    id1 = _add(s, "weight_kg", 70, date(2026, 9, 1))
    id2 = _add(s, "weight_kg", 71, date(2026, 10, 1))
    id3 = _add(s, "weight_kg", 72, date(2026, 10, 1))
    assert s.latest()["weight_kg"].id == id3
    with transaction(s._conn):
        assert s.delete(id3, NOW) is True
        assert s.delete(id3, NOW) is False
    assert s.latest()["weight_kg"].id == id2
    assert [m.id for m in s.active()] == [id2, id1]
    assert s.latest(as_of=date(2026, 9, 15))["weight_kg"].id == id1
    assert "weight_kg" not in s.latest(as_of=date(2026, 8, 1))
    with transaction(s._conn):
        assert s.restore(id3) is True
        assert s.restore(id3) is False
    assert s.latest()["weight_kg"].id == id3


def test_cert_latest_per_key(s):
    _add(s, "cert", "toeic:825", date(2026, 9, 1))
    _add(s, "cert", "toeic:900", date(2026, 10, 1))
    _add(s, "cert", "jlpt_n1", date(2026, 8, 1))
    certs = s.latest()["cert"]
    assert {m.value_text for m in certs} == {"toeic:900", "jlpt_n1"}
    assert {m.value_text for m in s.latest(as_of=date(2026, 9, 15))["cert"]} == {"toeic:825", "jlpt_n1"}


def test_has_import(s):
    _add(s, "weight_kg", 70, date(2026, 10, 1), "import")
    _add(s, "cert", "toeic:900", date(2026, 10, 1), "import")
    _add(s, "height_cm", 175, date(2026, 10, 1), "manual")
    assert s.has_import("weight_kg", date(2026, 10, 1))
    assert not s.has_import("weight_kg", date(2026, 10, 2))
    assert not s.has_import("height_cm", date(2026, 10, 1))
    assert s.has_import("cert", date(2026, 10, 1), "toeic:900")
    assert not s.has_import("cert", date(2026, 10, 1), "toeic:800")


def test_snapshot_put_replaces_and_period_before(s):
    t = datetime(2026, 10, 1, tzinfo=UTC)
    with transaction(s._conn):
        s.put_snapshot("2026-Q3", "height", "national", 50, "2026.1", '{"a": 1}', t)
        s.put_snapshot("2026-Q4", "height", "national", 55, "2026.1", "{}", t)
        s.put_snapshot("2026-Q4", "height", "peer", 60, "2026.1", "{}", t)
        s.put_snapshot("2026-Q4", "height", "national", 58, "2026.1", '{"b": 2}', t)
    rows = s.snapshots_for("2026-Q4")
    assert len(rows) == 2
    row = s.snapshot("2026-Q4", "height", "national")
    assert row and row.score == 58 and row.inputs == {"b": 2} and row.taken_at == t
    assert s.snapshot("2026-Q3", "height", "peer") is None
    assert s.latest_period_before("2026-Q4") == "2026-Q3"
    assert s.latest_period_before("2026-Q3") is None

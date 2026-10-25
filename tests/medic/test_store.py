from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from my_planner_medic.signals import Signal
from my_planner_medic.store import MedicStore

T0 = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)


def _sig(at: datetime, fp: str = "fp1") -> Signal:
    return Signal(fingerprint=fp, part="be", kind="exception", at=at)


def test_store_upsert_counts_and_keeps_first_seen(tmp_path: Path) -> None:
    store = MedicStore(tmp_path / "state" / "medic.db")
    first = store.upsert_signal(_sig(T0), T0)
    assert (first.state, first.count) == ("open", 1)
    assert first.first_seen == first.last_seen == "2026-10-26T00:00:00+00:00"
    later = T0 + timedelta(minutes=5)
    second = store.upsert_signal(_sig(later), later)
    assert second.count == 2
    assert second.first_seen == first.first_seen
    assert second.last_seen == "2026-10-26T00:05:00+00:00"
    store.set_state("fp1", "resolved", resolved_at="x")
    third = store.upsert_signal(_sig(later), later)
    assert third.state == "resolved" and third.count == 3
    assert [i.fingerprint for i in store.by_state("resolved")] == ["fp1"]
    assert store.by_state("open") == []
    assert store.get("nope") is None


def test_kv_json_roundtrip(tmp_path: Path) -> None:
    store = MedicStore(tmp_path / "medic.db")
    assert store.kv_get("k") is None
    store.kv_set("k", "v")
    store.kv_set("k", "v2")
    assert store.kv_get("k") == "v2"
    store.kv_json_set("log_cursor", {"file": "a.log", "offset": 7})
    assert store.kv_json_get("log_cursor") == {"file": "a.log", "offset": 7}
    assert store.kv_json_get("missing") is None


def test_schema_created_once(tmp_path: Path) -> None:
    path = tmp_path / "medic.db"
    a = MedicStore(path)
    a.upsert_signal(_sig(T0), T0)
    b = MedicStore(path)
    assert b.get("fp1") is not None
    tables = {r[0] for r in b._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"incidents", "kv", "notices"} <= tables


def test_set_state_validation_and_context_manager(tmp_path: Path) -> None:
    import pytest

    with MedicStore(tmp_path / "medic.db") as store:
        store.upsert_signal(_sig(T0), T0)
        with pytest.raises(ValueError):
            store.set_state("fp1", "bogus")
        with pytest.raises(ValueError):
            store.set_state("fp1", "open", nope=1)
        with pytest.raises(KeyError):
            store.set_state("missing", "open")
    with pytest.raises(sqlite3.ProgrammingError):
        store.get("fp1")


def test_notice_counts_and_spill_roundtrip(tmp_path: Path) -> None:
    store = MedicStore(tmp_path / "medic.db")
    store.add_notice("2026-10-26", "a", "2026-10-26T01:00:00+00:00")
    store.add_notice("2026-10-26", "b", None)
    store.add_notice("2026-10-27", "c", "2026-10-27T01:00:00+00:00")
    assert store.sent_notices("2026-10-26") == 1
    assert store.spilled_notices() == [(2, "b")]
    store.mark_notices_sent([2], "2026-10-27T00:00:00+00:00")
    assert store.spilled_notices() == []
    assert store.sent_notices("2026-10-26") == 2

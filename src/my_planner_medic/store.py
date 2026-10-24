"""medic 자기 DB(state/medic.db). planner.db는 건드리지 않는다."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .signals import Signal

STATES = ("open", "repairing", "merged", "deploying", "resolved", "gave_up")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents(
  fingerprint TEXT PRIMARY KEY, part TEXT, state TEXT, issue_number INT,
  first_seen TEXT, last_seen TEXT, count INT, synced_count INT,
  last_synced_at TEXT, failures INT DEFAULT 0, resolved_at TEXT, detail_json TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS notices(
  id INTEGER PRIMARY KEY, logical_date TEXT, text TEXT, sent_at TEXT);
"""
_COLUMNS = (
    "fingerprint", "part", "state", "issue_number", "first_seen", "last_seen", "count",
    "synced_count", "last_synced_at", "failures", "resolved_at", "detail_json",
)


@dataclass(frozen=True)
class Incident:
    fingerprint: str
    part: str
    state: str
    issue_number: int | None
    first_seen: str
    last_seen: str
    count: int
    synced_count: int | None
    last_synced_at: str | None
    failures: int
    resolved_at: str | None
    detail: dict[str, Any] = field(default_factory=dict)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _row_to_incident(row: tuple[Any, ...]) -> Incident:
    d = dict(zip(_COLUMNS, row, strict=True))
    raw = d.pop("detail_json")
    d["detail"] = json.loads(raw) if raw else {}
    d["failures"] = d["failures"] or 0
    return Incident(**d)


class MedicStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def get(self, fp: str) -> Incident | None:
        row = self._db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM incidents WHERE fingerprint=?", (fp,)
        ).fetchone()
        return _row_to_incident(row) if row else None

    def by_state(self, *states: str) -> list[Incident]:
        if not states:
            return []
        marks = ", ".join("?" for _ in states)
        rows = self._db.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM incidents WHERE state IN ({marks}) "
            "ORDER BY first_seen, fingerprint",
            states,
        ).fetchall()
        return [_row_to_incident(r) for r in rows]

    def upsert_signal(self, sig: Signal, now: datetime) -> Incident:
        at = iso_utc(sig.at)
        if self.get(sig.fingerprint) is None:
            self._db.execute(
                "INSERT INTO incidents(fingerprint, part, state, first_seen, last_seen, count, "
                "failures) VALUES(?, ?, 'open', ?, ?, 1, 0)",
                (sig.fingerprint, sig.part, at, at),
            )
        else:
            self._db.execute(
                "UPDATE incidents SET count = count + 1, last_seen = ? WHERE fingerprint = ?",
                (at, sig.fingerprint),
            )
        self._db.commit()
        inc = self.get(sig.fingerprint)
        assert inc is not None
        return inc

    def set_state(self, fp: str, state: str, **fields: Any) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state: {state}")
        allowed = set(_COLUMNS) - {"fingerprint", "state", "detail_json"} | {"detail"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown fields: {sorted(unknown)}")
        values: dict[str, Any] = {"state": state}
        for k, v in fields.items():
            if k == "detail":
                values["detail_json"] = json.dumps(v, ensure_ascii=False)
            else:
                values[k] = v
        sets = ", ".join(f"{k}=?" for k in values)
        self._db.execute(
            f"UPDATE incidents SET {sets} WHERE fingerprint=?", (*values.values(), fp)
        )
        self._db.commit()

    def kv_get(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def kv_set(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._db.commit()

    def kv_json_get(self, key: str) -> Any | None:
        raw = self.kv_get(key)
        return None if raw is None else json.loads(raw)

    def kv_json_set(self, key: str, value: Any) -> None:
        self.kv_set(key, json.dumps(value, ensure_ascii=False))

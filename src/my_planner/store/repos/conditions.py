"""conditions 표 (스펙 5.5): 논리적 날짜마다 컨디션 하나. 같은 날 다시 기록하면 덮어쓴다."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.store.db import transaction


@dataclass
class Condition:
    date: date
    score: int
    note: str | None
    recorded_at: datetime


class ConditionsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def upsert(self, d: date, score: int, note: str | None) -> Condition:
        """그 날의 점수를 덮어쓴다. 메모는 새로 준 것이 있으면 바꾸고, 없으면(버튼) 가장 최근 메모를 둔다."""
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO conditions (date, score, note, recorded_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (date) DO UPDATE SET score = excluded.score, "
                "note = COALESCE(excluded.note, conditions.note), "
                "recorded_at = excluded.recorded_at",
                (d.isoformat(), score, note, to_iso(self.clock.now())),
            )
        got = self.get(d)
        assert got is not None
        return got

    def get(self, d: date) -> Condition | None:
        r = self.conn.execute("SELECT * FROM conditions WHERE date = ?", (d.isoformat(),)).fetchone()
        if r is None:
            return None
        return Condition(
            date=date.fromisoformat(r["date"]),
            score=r["score"],
            note=r["note"],
            recorded_at=from_iso(r["recorded_at"]),
        )

    def between(self, from_: date, to: date) -> list[Condition]:
        """`from_`~`to`(포함)에 기록한 컨디션, 날짜순. 기록 없는 날은 넣지 않는다."""
        rows = self.conn.execute(
            "SELECT * FROM conditions WHERE date >= ? AND date <= ? ORDER BY date",
            (from_.isoformat(), to.isoformat()),
        ).fetchall()
        return [
            Condition(
                date=date.fromisoformat(r["date"]), score=r["score"], note=r["note"],
                recorded_at=from_iso(r["recorded_at"]),
            )
            for r in rows
        ]

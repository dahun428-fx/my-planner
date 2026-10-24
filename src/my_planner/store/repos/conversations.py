"""conversations 표."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.domain import ConversationKind
from my_planner.store.db import transaction


@dataclass
class Conversation:
    id: int
    kind: ConversationKind
    run_id: int | None
    session_id: str | None
    logical_date: date
    opened_at: datetime
    last_message_at: datetime
    closed_at: datetime | None


def _row(r: sqlite3.Row) -> Conversation:
    return Conversation(
        id=r["id"],
        kind=ConversationKind(r["kind"]),
        run_id=r["run_id"],
        session_id=r["session_id"],
        logical_date=date.fromisoformat(r["logical_date"]),
        opened_at=from_iso(r["opened_at"]),
        last_message_at=from_iso(r["last_message_at"]),
        closed_at=from_iso(r["closed_at"]) if r["closed_at"] else None,
    )


class ConversationsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def open(
        self, kind: ConversationKind | str, logical_date: date, run_id: int | None = None
    ) -> Conversation:
        now = to_iso(self.clock.now())
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO conversations (kind, run_id, logical_date, opened_at, last_message_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (ConversationKind(kind).value, run_id, logical_date.isoformat(), now, now),
            )
        conv = self.get(cur.lastrowid)
        assert conv is not None
        return conv

    def get(self, id: int) -> Conversation | None:
        r = self.conn.execute("SELECT * FROM conversations WHERE id = ?", (id,)).fetchone()
        return _row(r) if r is not None else None

    def touch(self, id: int) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET last_message_at = ? WHERE id = ?",
                (to_iso(self.clock.now()), id),
            )

    def set_session(self, id: int, session_id: str | None) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET session_id = ? WHERE id = ?", (session_id, id)
            )

    def close(self, id: int) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET closed_at = ? WHERE id = ? AND closed_at IS NULL",
                (to_iso(self.clock.now()), id),
            )

    def latest_open_run_opened_by(self, at: datetime) -> Conversation | None:
        """`at`(보낸 시각) 이전에 열린 열린 `run` 대화 가운데 가장 최근 것."""
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = 'run' AND closed_at IS NULL AND opened_at <= ? "
            "ORDER BY opened_at DESC, id DESC LIMIT 1",
            (to_iso(at),),
        ).fetchone()
        return _row(r) if r is not None else None

    def latest_open(self, kind: ConversationKind | str) -> Conversation | None:
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = ? AND closed_at IS NULL "
            "ORDER BY last_message_at DESC, id DESC LIMIT 1",
            (ConversationKind(kind).value,),
        ).fetchone()
        return _row(r) if r is not None else None

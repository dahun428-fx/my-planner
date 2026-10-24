"""conversations 표."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.domain import Channel, ConversationKind
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
    channel: str = "telegram"  # 'telegram' | 'app' (SP3-4 5.1)
    forked_from: int | None = None


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
        channel=r["channel"],
        forked_from=r["forked_from"],
    )


class ConversationsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def open(
        self, kind: ConversationKind | str, logical_date: date, run_id: int | None = None, *,
        channel: Channel = "telegram", forked_from: int | None = None,
    ) -> Conversation:
        """`forked_from`: 다른 통로의 회차 대화를 갈라 연 대화면 그 원래 대화(SP3-4 7.2 가르기)."""
        now = to_iso(self.clock.now())
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO conversations (kind, run_id, logical_date, opened_at, last_message_at, channel, "
                "forked_from) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ConversationKind(kind).value, run_id, logical_date.isoformat(), now, now, channel, forked_from),
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

    def set_channel(self, id: int, channel: Channel) -> None:
        """대화의 통로를 바꾼다(회차 대화는 전체 본문을 받은 통로에 둔다, 7.3 D5)."""
        with transaction(self.conn):
            self.conn.execute("UPDATE conversations SET channel = ? WHERE id = ?", (channel, id))

    def close(self, id: int) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET closed_at = ? WHERE id = ? AND closed_at IS NULL",
                (to_iso(self.clock.now()), id),
            )

    def latest_open_run_opened_by(self, at: datetime) -> Conversation | None:
        """`at`(보낸 시각) 이전에 열린 열린 `run` 대화 가운데 가장 최근 것. 통로와 상관없다(SP3-4 7.2 규칙 3).

        갈라 연 대화(`forked_from`)는 보지 않는다: 회차를 보낸 때 연 원래 대화만 "가장 최근에 보낸 회차"를 가리킨다.
        """
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = 'run' AND closed_at IS NULL AND forked_from IS NULL "
            "AND opened_at <= ? "
            "ORDER BY opened_at DESC, id DESC LIMIT 1",
            (to_iso(at),),
        ).fetchone()
        return _row(r) if r is not None else None

    def latest_open(self, kind: ConversationKind | str, channel: Channel = "telegram") -> Conversation | None:
        """그 통로의 열린 대화 가운데 마지막 메시지가 가장 최근인 것(SP3-4 7.1: 통로마다 따로)."""
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = ? AND channel = ? AND closed_at IS NULL "
            "ORDER BY last_message_at DESC, id DESC LIMIT 1",
            (ConversationKind(kind).value, channel),
        ).fetchone()
        return _row(r) if r is not None else None

    def run_conversation(self, run_id: int, channel: Channel) -> Conversation | None:
        """그 회차의 그 통로 쪽 열린 회차 대화(7.2). 여럿이면 가장 나중에 연 것."""
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = 'run' AND run_id = ? AND channel = ? AND closed_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (run_id, channel),
        ).fetchone()
        return _row(r) if r is not None else None

    def recent(self, *, channel: str | None = None, limit: int = 20) -> list[Conversation]:
        """마지막 메시지가 최근인 것부터. `channel`을 주면 그 통로 대화만."""
        where, args = ("WHERE channel = ? ", [channel]) if channel is not None else ("", [])
        rows = self.conn.execute(
            f"SELECT * FROM conversations {where}ORDER BY last_message_at DESC, id DESC LIMIT ?", (*args, limit)
        ).fetchall()
        return [_row(r) for r in rows]

    def for_run(self, run_id: int) -> list[Conversation]:
        """그 회차에 붙은 대화(통로마다 있을 수 있다), id 순."""
        rows = self.conn.execute("SELECT * FROM conversations WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [_row(r) for r in rows]

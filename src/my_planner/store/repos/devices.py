"""devices 표 (기기 연결 스펙 4.1). 토큰은 sha256만 둔다. 쓰기는 즉시 갈래(`device_*` 동작)로만 한다."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from my_planner.clock import from_iso, to_iso
from my_planner.store.db import transaction


@dataclass(frozen=True)
class Device:
    id: int
    token_hash: str
    label: str
    client: str
    created_at: datetime
    last_used_at: datetime | None


def _row(r: sqlite3.Row) -> Device:
    return Device(
        id=r["id"], token_hash=r["token_hash"], label=r["label"], client=r["client"],
        created_at=from_iso(r["created_at"]),
        last_used_at=from_iso(r["last_used_at"]) if r["last_used_at"] else None,
    )


class DevicesRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def active(self) -> list[Device]:
        """끊지 않은 기기, 만든 순서."""
        rows = self.conn.execute("SELECT * FROM devices WHERE revoked_at IS NULL ORDER BY id").fetchall()
        return [_row(r) for r in rows]

    def add(self, token_hash: str, label: str, client: str, at: datetime) -> int:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO devices (token_hash, label, client, created_at) VALUES (?, ?, ?, ?)",
                (token_hash, label, client, to_iso(at)),
            )
        return int(cur.lastrowid or 0)

    def revoke(self, id: int, at: datetime) -> bool:
        """끊는다. 없거나 이미 끊었으면 False. 그 기기의 푸시 구독도 끈다(4.6)."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (to_iso(at), id)
            )
            if cur.rowcount == 0:
                return False
            self.conn.execute(
                "UPDATE push_subscriptions SET disabled_at = ? WHERE device_id = ? AND disabled_at IS NULL",
                (to_iso(at), id),
            )
        return True

    def touch(self, id: int, at: datetime) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE devices SET last_used_at = ? WHERE id = ? AND revoked_at IS NULL", (to_iso(at), id)
            )

"""run_deliveries 표 (SP3-4 스펙 5.1, 7.3): 회차를 어느 통로로 어떻게 보냈나."""

from __future__ import annotations

import sqlite3
from typing import Literal

from my_planner.clock import Clock, to_iso
from my_planner.store.db import transaction

Channel = Literal["telegram", "app"]
DeliveryMode = Literal["full", "fallback"]
DeliveryStatus = Literal["sent", "not_sent"]


class DeliveriesRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def record(
        self,
        run_id: int,
        channel: Channel,
        mode: DeliveryMode,
        status: DeliveryStatus,
        *,
        push_ok: int = 0,
        push_failed: int = 0,
    ) -> None:
        """그 회차의 그 통로 전달을 적는다. 같은 `(run_id, channel)`은 덮어쓴다(재전송, 대체)."""
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO run_deliveries (run_id, channel, mode, status, push_ok, push_failed, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (run_id, channel) DO UPDATE SET mode = excluded.mode, status = excluded.status, "
                "push_ok = excluded.push_ok, push_failed = excluded.push_failed, at = excluded.at",
                (run_id, channel, mode, status, push_ok, push_failed, to_iso(self.clock.now())),
            )

    def sent_channels(self, run_id: int) -> list[str]:
        """`status = 'sent'`인 통로(`delivered_via`). 보낸 순서, 같으면 이름순."""
        rows = self.conn.execute(
            "SELECT channel FROM run_deliveries WHERE run_id = ? AND status = 'sent' ORDER BY at, channel",
            (run_id,),
        ).fetchall()
        return [r["channel"] for r in rows]

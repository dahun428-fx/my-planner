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
        telegram_message_id: int | None = None,
    ) -> None:
        """그 회차의 그 통로 전달을 적는다. 같은 `(run_id, channel)`은 덮어쓴다(재전송, 대체).

        `telegram_message_id`: 버튼이 붙은 마지막 조각(답한 뒤 버튼을 거둘 때 쓴다, 6.4.5).
        """
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO run_deliveries (run_id, channel, mode, status, telegram_message_id, push_ok, "
                "push_failed, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (run_id, channel) DO UPDATE SET mode = excluded.mode, status = excluded.status, "
                "telegram_message_id = excluded.telegram_message_id, "
                "push_ok = excluded.push_ok, push_failed = excluded.push_failed, at = excluded.at",
                (run_id, channel, mode, status, telegram_message_id, push_ok, push_failed,
                 to_iso(self.clock.now())),
            )

    def telegram_message_id(self, run_id: int) -> int | None:
        """그 회차를 텔레그램에 보낸 메시지 가운데 버튼이 붙은 마지막 조각의 id. 없으면 None."""
        r = self.conn.execute(
            "SELECT telegram_message_id FROM run_deliveries WHERE run_id = ? AND channel = 'telegram'", (run_id,)
        ).fetchone()
        return r["telegram_message_id"] if r is not None else None

    def run_for_message(self, message_id: int) -> int | None:
        """그 텔레그램 메시지(버튼이 붙은 조각)로 보낸 회차. 없으면 None."""
        r = self.conn.execute(
            "SELECT run_id FROM run_deliveries WHERE channel = 'telegram' AND telegram_message_id = ? "
            "ORDER BY at DESC LIMIT 1",
            (message_id,),
        ).fetchone()
        return r["run_id"] if r is not None else None

    def sent_channels(self, run_id: int) -> list[str]:
        """`status = 'sent'`인 통로(`delivered_via`). 보낸 순서, 같으면 이름순."""
        rows = self.conn.execute(
            "SELECT channel FROM run_deliveries WHERE run_id = ? AND status = 'sent' ORDER BY at, channel",
            (run_id,),
        ).fetchall()
        return [r["channel"] for r in rows]

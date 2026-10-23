"""app_state, usage_state, telegram_updates."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from my_planner.clock import Clock, SystemClock, to_iso

# app_state 키 (티켓 10). 시각은 UTC ISO, 날짜는 논리적 날짜 ISO.
PAUSE_UNTIL_KEY = "pause_until"  # /pause가 정한 멈춤 끝 시각
LIMITED_UNTIL_KEY = "limited_until"  # 사용 한도가 풀리는 시각
LAST_AUTH_NOTICE_KEY = "last_auth_notice_date"  # 로그인·결제 안내를 보낸 논리적 날짜(하루 한 번)
LAST_RATE_LIMIT_NOTICE_KEY = "last_rate_limit_notice_until"  # 안내를 보낸 한도 구간(limited_until 값)

UsageField = Literal["brain_calls", "proactive_messages"]
_USAGE_FIELDS = ("brain_calls", "proactive_messages")


@dataclass
class Usage:
    brain_calls: int
    proactive_messages: int


class StateRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None) -> None:
        self.conn = conn
        self.clock = clock or SystemClock()

    # app_state
    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else default

    def set(self, key: str, value: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # usage_state (논리적 날짜 기준)
    def incr_usage(self, d: date, field: UsageField) -> int:
        if field not in _USAGE_FIELDS:
            raise ValueError(f"unknown usage field: {field}")
        with self.conn:
            self.conn.execute(
                f"INSERT INTO usage_state (date, {field}) VALUES (?, 1) "
                f"ON CONFLICT (date) DO UPDATE SET {field} = {field} + 1",
                (d.isoformat(),),
            )
        return getattr(self.usage(d), field)

    def usage(self, d: date) -> Usage:
        row = self.conn.execute(
            "SELECT brain_calls, proactive_messages FROM usage_state WHERE date = ?",
            (d.isoformat(),),
        ).fetchone()
        if row is None:
            return Usage(brain_calls=0, proactive_messages=0)
        return Usage(brain_calls=row["brain_calls"], proactive_messages=row["proactive_messages"])

    # telegram_updates (처리를 마친 update_id)
    def is_seen_update(self, update_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM telegram_updates WHERE update_id = ?", (update_id,)
        ).fetchone()
        return row is not None

    def mark_updates_done(self, ids: list[int]) -> None:
        if not ids:
            return
        now = to_iso(self.clock.now())
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO telegram_updates (update_id, received_at) VALUES (?, ?)",
                [(i, now) for i in ids],
            )

    def prune_updates(self, older_than: datetime) -> int:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM telegram_updates WHERE received_at < ?", (to_iso(older_than),)
            )
        return cur.rowcount

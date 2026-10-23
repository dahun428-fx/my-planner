"""app_state, usage_state, telegram_updates, inbound_pending."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from my_planner.clock import Clock, SystemClock, from_iso, to_iso

# app_state 키 (티켓 10). 시각은 UTC ISO, 날짜는 논리적 날짜 ISO.
PAUSE_UNTIL_KEY = "pause_until"  # /pause가 정한 멈춤 끝 시각
LIMITED_UNTIL_KEY = "limited_until"  # 사용 한도가 풀리는 시각
LAST_AUTH_NOTICE_KEY = "last_auth_notice_date"  # 로그인·결제 안내를 보낸 논리적 날짜(하루 한 번)
LAST_RATE_LIMIT_NOTICE_KEY = "last_rate_limit_notice_until"  # 안내를 보낸 한도 구간(limited_until 값)
CARRY_REVIEW_KEY = "carry_review_run_id"  # R1로 넘겨 받은 회고 회차(혼자 실행하지 않는다)

UsageField = Literal["brain_calls", "proactive_messages"]
_USAGE_FIELDS = ("brain_calls", "proactive_messages")


@dataclass
class Usage:
    brain_calls: int
    proactive_messages: int


@dataclass
class PendingInbound:
    """받았지만 아직 답하지 못한 사용자 메시지. `text`는 가린 뒤의 글이다."""

    update_id: int
    text: str
    sent_at: datetime
    received_at: datetime
    user_logged: bool = False
    brain_done: bool = False
    reply_text: str | None = None
    conversation_id: int | None = None
    attempts: int = 0


def _pending(r: sqlite3.Row) -> PendingInbound:
    return PendingInbound(
        update_id=r["update_id"],
        text=r["text_redacted"],
        sent_at=from_iso(r["sent_at"]),
        received_at=from_iso(r["received_at"]),
        user_logged=bool(r["user_logged"]),
        brain_done=bool(r["brain_done"]),
        reply_text=r["reply_text"],
        conversation_id=r["conversation_id"],
        attempts=r["attempts"],
    )


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
        """처리 완료로 기록하고, 같은 트랜잭션에서 그 메시지의 `inbound_pending` 행을 지운다."""
        if not ids:
            return
        now = to_iso(self.clock.now())
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO telegram_updates (update_id, received_at) VALUES (?, ?)",
                [(i, now) for i in ids],
            )
            self.conn.executemany("DELETE FROM inbound_pending WHERE update_id = ?", [(i,) for i in ids])

    # inbound_pending (받았지만 아직 답하지 못한 메시지, 가린 글만)
    def add_pending_inbound(
        self, update_id: int, text_redacted: str, sent_at: datetime, received_at: datetime
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO inbound_pending (update_id, text_redacted, sent_at, received_at) "
                "VALUES (?, ?, ?, ?)",
                (update_id, text_redacted, to_iso(sent_at), to_iso(received_at)),
            )

    def is_pending_inbound(self, update_id: int) -> bool:
        row = self.conn.execute("SELECT 1 FROM inbound_pending WHERE update_id = ?", (update_id,)).fetchone()
        return row is not None

    def pending_inbound(self) -> list[PendingInbound]:
        """남은 메시지를 받은 순서(update_id)로."""
        rows = self.conn.execute("SELECT * FROM inbound_pending ORDER BY update_id").fetchall()
        return [_pending(r) for r in rows]

    def get_pending_inbound(self, update_id: int) -> PendingInbound | None:
        r = self.conn.execute("SELECT * FROM inbound_pending WHERE update_id = ?", (update_id,)).fetchone()
        return _pending(r) if r is not None else None

    def merge_pending_inbound(self, ids: list[int]) -> None:
        """여러 메시지를 한 번에 처리할 때 첫 행 하나로 합친다(본문은 빈 줄로 잇고, 보낸 시각은 가장 이른 것).

        나머지 행은 지우고 처리 완료로 기록한다(중복 수신 방지). 다시 넣을 때 묶음째 한 번에 처리된다.
        """
        if len(ids) < 2:
            return
        rows = [p for i in ids if (p := self.get_pending_inbound(i)) is not None]
        if len(rows) < 2:
            return
        lead, rest = rows[0], rows[1:]
        now = to_iso(self.clock.now())
        with self.conn:
            self.conn.execute(
                "UPDATE inbound_pending SET text_redacted = ?, sent_at = ? WHERE update_id = ?",
                ("\n\n".join(p.text for p in rows), to_iso(min(p.sent_at for p in rows)), lead.update_id),
            )
            for p in rest:
                self.conn.execute("DELETE FROM inbound_pending WHERE update_id = ?", (p.update_id,))
                self.conn.execute(
                    "INSERT OR IGNORE INTO telegram_updates (update_id, received_at) VALUES (?, ?)",
                    (p.update_id, now),
                )

    def mark_inbound_user_logged(self, update_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE inbound_pending SET user_logged = 1 WHERE update_id = ?", (update_id,))

    def save_inbound_reply(self, update_id: int, reply_redacted: str, conversation_id: int | None) -> None:
        """보내기 전에 답(확인 문구 포함, 가린 뒤)을 저장하고 `brain_done`을 한 트랜잭션에서 세운다."""
        with self.conn:
            self.conn.execute(
                "UPDATE inbound_pending SET brain_done = 1, reply_text = ?, conversation_id = ? WHERE update_id = ?",
                (reply_redacted, conversation_id, update_id),
            )

    def bump_inbound_attempts(self, update_id: int) -> int:
        with self.conn:
            self.conn.execute("UPDATE inbound_pending SET attempts = attempts + 1 WHERE update_id = ?", (update_id,))
        p = self.get_pending_inbound(update_id)
        return p.attempts if p is not None else 0

    def drop_pending_inbound(self, update_id: int) -> None:
        """다시 넣기를 그만둔다. 처리 완료로 기록해 다시 받아도 건너뛴다."""
        self.mark_updates_done([update_id])

    def prune_updates(self, older_than: datetime) -> int:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM telegram_updates WHERE received_at < ?", (to_iso(older_than),)
            )
        return cur.rowcount

"""activity, api_idempotency, pending_confirms 표 (SP3-4 스펙 5.2).

- `activity`: 사람(운영 앱)에게 보여 주고 되돌리는 변경 기록. 변경과 같은 트랜잭션에서 쓴다(`tools/activity.py`).
  `summary`는 확인 문구 한 줄이고 메시지 본문은 넣지 않는다.
- `api_idempotency`: 쓰기 요청의 `client_msg_id`마다 처음 응답(2일 보관).
- `pending_confirms`: 확인을 기다리는 변경(`ct_` 토큰). 쓰고 나면 다시 쓰지 않는다(7일 보관).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.store.db import transaction

Endpoint = Literal["chat", "actions", "undo"]
ConfirmOrigin = Literal["actions", "run_turn"]
Resolution = Literal["applied", "declined", "expired", "stale"]
TOKEN_PREFIX = "ct_"


@dataclass
class Activity:
    id: int
    at: datetime
    actor: str
    channel: str
    kind: str
    target: str | None
    summary: str
    risk: str
    undo: dict[str, Any] | None
    undone_at: datetime | None
    undone_by: int | None
    conversation_id: int | None
    run_id: int | None
    inbound_id: int | None


class ActivityRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def add(
        self,
        *,
        actor: str,
        channel: str,
        kind: str,
        target: str | None,
        summary: str,
        risk: str,
        undo: dict[str, Any] | None,
        conversation_id: int | None = None,
        run_id: int | None = None,
        inbound_id: int | None = None,
    ) -> int:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO activity (at, actor, channel, kind, target, summary, risk, undo_json, "
                "conversation_id, run_id, inbound_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    to_iso(self.clock.now()), actor, channel, kind, target, summary, risk,
                    json.dumps(undo, ensure_ascii=False) if undo is not None else None,
                    conversation_id, run_id, inbound_id,
                ),
            )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def get(self, id: int) -> Activity | None:
        r = self.conn.execute("SELECT * FROM activity WHERE id = ?", (id,)).fetchone()
        return _activity(r) if r is not None else None

    def changed_after(self, target: str, after: datetime) -> bool:
        """`after`보다 나중에 그 대상을 바꾼 활동이 있다(확인 토큰의 `stale` 판정, 5.2)."""
        r = self.conn.execute(
            "SELECT 1 FROM activity WHERE target = ? AND at > ? LIMIT 1", (target, to_iso(after))
        ).fetchone()
        return r is not None


def _activity(r: sqlite3.Row) -> Activity:
    return Activity(
        id=r["id"],
        at=from_iso(r["at"]),
        actor=r["actor"],
        channel=r["channel"],
        kind=r["kind"],
        target=r["target"],
        summary=r["summary"],
        risk=r["risk"],
        undo=json.loads(r["undo_json"]) if r["undo_json"] is not None else None,
        undone_at=from_iso(r["undone_at"]) if r["undone_at"] else None,
        undone_by=r["undone_by"],
        conversation_id=r["conversation_id"],
        run_id=r["run_id"],
        inbound_id=r["inbound_id"],
    )


@dataclass
class StoredResponse:
    endpoint: str
    status_code: int
    body: Any
    conversation_id: int | None


class IdempotencyRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def get(self, client_msg_id: str) -> StoredResponse | None:
        r = self.conn.execute(
            "SELECT * FROM api_idempotency WHERE client_msg_id = ?", (client_msg_id,)
        ).fetchone()
        if r is None:
            return None
        return StoredResponse(
            endpoint=r["endpoint"],
            status_code=r["status_code"],
            body=json.loads(r["response_json"]) if r["response_json"] is not None else None,
            conversation_id=r["conversation_id"],
        )

    def put(
        self, client_msg_id: str, endpoint: Endpoint, status_code: int, body: Any, *, conversation_id: int | None = None
    ) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO api_idempotency (client_msg_id, endpoint, status_code, response_json, conversation_id, at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    client_msg_id, endpoint, status_code,
                    json.dumps(body, ensure_ascii=False) if body is not None else None,
                    conversation_id, to_iso(self.clock.now()),
                ),
            )

    def prune(self, older_than: datetime) -> int:
        with transaction(self.conn):
            cur = self.conn.execute("DELETE FROM api_idempotency WHERE at < ?", (to_iso(older_than),))
        return cur.rowcount


@dataclass
class PendingConfirm:
    token: str
    action: str
    args: dict[str, Any]
    summary: str
    origin: str
    run_id: int | None
    conversation_id: int | None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None
    resolution: str | None

    def open_at(self, now: datetime) -> bool:
        """아직 쓰지 않았고 만료 전이다."""
        return self.resolved_at is None and now < self.expires_at


class ConfirmsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def create(
        self,
        *,
        action: str,
        args: dict[str, Any],
        summary: str,
        origin: ConfirmOrigin,
        expires_at: datetime,
        run_id: int | None = None,
        conversation_id: int | None = None,
    ) -> PendingConfirm:
        token = TOKEN_PREFIX + secrets.token_urlsafe(16)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO pending_confirms (token, action, args_json, summary, origin, run_id, conversation_id, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    token, action, json.dumps(args, ensure_ascii=False), summary, origin, run_id, conversation_id,
                    to_iso(self.clock.now()), to_iso(expires_at),
                ),
            )
        got = self.get(token)
        assert got is not None
        return got

    def get(self, token: str) -> PendingConfirm | None:
        r = self.conn.execute("SELECT * FROM pending_confirms WHERE token = ?", (token,)).fetchone()
        if r is None:
            return None
        return PendingConfirm(
            token=r["token"],
            action=r["action"],
            args=json.loads(r["args_json"]),
            summary=r["summary"],
            origin=r["origin"],
            run_id=r["run_id"],
            conversation_id=r["conversation_id"],
            created_at=from_iso(r["created_at"]),
            expires_at=from_iso(r["expires_at"]),
            resolved_at=from_iso(r["resolved_at"]) if r["resolved_at"] else None,
            resolution=r["resolution"],
        )

    def resolve(self, token: str, resolution: Resolution) -> bool:
        """아직 열린 토큰만 닫는다. 닫았으면 True."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE pending_confirms SET resolved_at = ?, resolution = ? WHERE token = ? AND resolved_at IS NULL",
                (to_iso(self.clock.now()), resolution, token),
            )
        return cur.rowcount == 1

    def expire(self, now: datetime) -> int:
        """만료 시각이 지난 열린 토큰을 `expired`로 닫는다."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE pending_confirms SET resolved_at = ?, resolution = 'expired' "
                "WHERE resolved_at IS NULL AND expires_at <= ?",
                (to_iso(self.clock.now()), to_iso(now)),
            )
        return cur.rowcount

    def prune(self, older_than: datetime) -> int:
        """만든 지 오래된 토큰 행을 지운다(7일, 5.2)."""
        with transaction(self.conn):
            cur = self.conn.execute("DELETE FROM pending_confirms WHERE created_at < ?", (to_iso(older_than),))
        return cur.rowcount

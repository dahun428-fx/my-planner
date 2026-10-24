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
        targets: list[str] | None = None,
    ) -> int:
        """`targets`는 이 활동이 바꾼 대상 전부(`activity_targets`, 같은 트랜잭션). 없으면 `[target]`."""
        every = list(dict.fromkeys(targets if targets is not None else ([target] if target else [])))
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
            aid = cur.lastrowid
            assert aid is not None
            self.conn.executemany(
                "INSERT INTO activity_targets (activity_id, target) VALUES (?, ?)", [(aid, t) for t in every]
            )
        return aid

    def targets(self, id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT target FROM activity_targets WHERE activity_id = ? ORDER BY rowid", (id,)
        ).fetchall()
        return [r["target"] for r in rows]

    def get(self, id: int) -> Activity | None:
        r = self.conn.execute("SELECT * FROM activity WHERE id = ?", (id,)).fetchone()
        return _activity(r) if r is not None else None

    def changed_after(
        self, target: str, after: datetime, *, after_id: int | None = None, skip_undone: bool = False
    ) -> bool:
        """`after`보다 나중에 그 대상을 바꾼 활동이 있다. 여러 대상 활동도 본다(`activity_targets`).

        확인 토큰의 `stale` 판정(5.2)은 시각만 본다. 되돌리기 U3(6.4.3)은 그 활동 `(at, id)`보다 나중 행을 보고
        (`after_id`: 같은 시각이면 id가 큰 행이 나중이다), 되돌린 활동은 빼고(`skip_undone`) 되돌리기 활동은 센다.
        """
        sql = "SELECT 1 FROM activity_targets t JOIN activity a ON a.id = t.activity_id WHERE t.target = ? AND "
        args: list[object] = [target, to_iso(after)]
        if after_id is None:
            sql += "a.at > ?"
        else:
            sql += "(a.at > ? OR (a.at = ? AND a.id > ?))"
            args += [to_iso(after), after_id]
        if skip_undone:
            sql += " AND a.undone_at IS NULL"
        return self.conn.execute(sql + " LIMIT 1", args).fetchone() is not None

    def mark_undone(self, id: int, undo_id: int) -> None:
        """원래 행에 `undone_at`(되돌리기 활동의 시각)과 `undone_by`를 적는다(U5). 이미 되돌린 행이면 예외."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE activity SET undone_at = (SELECT at FROM activity WHERE id = ?), undone_by = ? "
                "WHERE id = ? AND undone_at IS NULL",
                (undo_id, undo_id, id),
            )
            if cur.rowcount != 1:
                raise LookupError(f"activity {id} is missing or already undone")

    def since(
        self,
        after: datetime | None,
        limit: int,
        *,
        order: Literal["asc", "desc"] = "asc",
        before: Activity | None = None,
    ) -> tuple[list[Activity], bool]:
        """`GET /activity`(6.4.4)의 한 쪽과, 더 앞선 행이 남았는지(`desc`의 `next_before`).

        `asc`: `after`보다 나중 행을 `(at, id)` 순으로 `limit`개. 마지막 행과 같은 시각의 행은 쪽을 넘쳐도 함께 준다
        (다음 쪽은 `since=<마지막 at>`이라 같은 시각의 나머지가 빠지면 다시 받을 길이 없다).
        `desc`: 최근 것부터 `limit`개. `before`(앞 쪽의 마지막 행)가 있으면 그보다 앞선 `(at, id)`만.
        """
        where: list[str] = []
        args: list[object] = []
        if after is not None:
            where.append("at > ?")
            args.append(to_iso(after))
        if order == "asc":
            sql = "SELECT * FROM activity" + (" WHERE " + " AND ".join(where) if where else "")
            rows = [_activity(r) for r in self.conn.execute(sql + " ORDER BY at, id LIMIT ?", (*args, limit))]
            if len(rows) == limit:
                tail = self.conn.execute(
                    "SELECT * FROM activity WHERE at = ? AND id > ? ORDER BY id", (to_iso(rows[-1].at), rows[-1].id)
                ).fetchall()
                rows += [_activity(r) for r in tail]
            return rows, False
        if before is not None:
            where.append("(at < ? OR (at = ? AND id < ?))")
            args += [to_iso(before.at), to_iso(before.at), before.id]
        sql = "SELECT * FROM activity" + (" WHERE " + " AND ".join(where) if where else "")
        got = [_activity(r) for r in self.conn.execute(sql + " ORDER BY at DESC, id DESC LIMIT ?", (*args, limit + 1))]
        return got[:limit], len(got) > limit


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

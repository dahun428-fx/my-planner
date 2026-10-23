"""runs 표 (스펙 5.4: 회차와 두 단계 실행)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.domain import Cadence, LoopKey, RunStatus, SkipReason


@dataclass
class Run:
    id: int
    loop: LoopKey
    cadence: Cadence
    scheduled_for: datetime
    status: RunStatus
    skip_reason: SkipReason | None
    attempt: int
    outbound_text: str | None
    resent: int
    conversation_id: int | None
    merged_run_ids: list[int] = field(default_factory=list)


def _row(r: sqlite3.Row) -> Run:
    return Run(
        id=r["id"],
        loop=LoopKey(r["loop"]),
        cadence=Cadence(r["cadence"]),
        scheduled_for=from_iso(r["scheduled_for"]),
        status=RunStatus(r["status"]),
        skip_reason=SkipReason(r["skip_reason"]) if r["skip_reason"] else None,
        attempt=r["attempt"],
        outbound_text=r["outbound_text"],
        resent=r["resent"],
        conversation_id=r["conversation_id"],
        merged_run_ids=[int(i) for i in json.loads(r["merged_run_ids"])],
    )


class RunsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def _now(self) -> str:
        return to_iso(self.clock.now())

    def _update(self, id: int, sql: str, *args: object) -> None:
        with self.conn:
            self.conn.execute(f"UPDATE runs SET {sql} WHERE id = ?", (*args, id))

    # --- 만들기와 읽기 ---

    def ensure(
        self, loop: LoopKey | str, scheduled_for: datetime, cadence: Cadence | str = Cadence.day
    ) -> Run:
        """없으면 `pending`으로 만든다. 있으면 그대로 돌려준다."""
        key = (LoopKey(loop).value, Cadence(cadence).value, to_iso(scheduled_for))
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO runs (loop, cadence, scheduled_for, status, created_at) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (*key, self._now()),
            )
        r = self.conn.execute(
            "SELECT * FROM runs WHERE loop = ? AND cadence = ? AND scheduled_for = ?", key
        ).fetchone()
        return _row(r)

    def get(self, id: int) -> Run | None:
        r = self.conn.execute("SELECT * FROM runs WHERE id = ?", (id,)).fetchone()
        return _row(r) if r is not None else None

    def pending(self) -> list[Run]:
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE status = 'pending' ORDER BY scheduled_for, id"
        ).fetchall()
        return [_row(r) for r in rows]

    def between(self, start: datetime, end: datetime) -> list[Run]:
        """예정 시각이 `(start, end]`인 회차, 시간순."""
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE scheduled_for > ? AND scheduled_for <= ? ORDER BY scheduled_for, id",
            (to_iso(start), to_iso(end)),
        ).fetchall()
        return [_row(r) for r in rows]

    def has_tool_events(self, id: int) -> bool:
        r = self.conn.execute("SELECT 1 FROM tool_events_log WHERE run_id = ? LIMIT 1", (id,)).fetchone()
        return r is not None

    # --- 상태 바꾸기 ---

    def mark_pending(self, id: int) -> None:
        """큐에서 실행하지 않고 돌려 놓는다(계획 대화가 열려 있음). 다음 tick이 다시 판정한다.

        queued인 회차만 바꾼다. 이미 실행 중이거나 끝난 회차는 되살리지 않는다.
        """
        with self.conn:
            self.conn.execute("UPDATE runs SET status = 'pending' WHERE id = ? AND status = 'queued'", (id,))

    def mark_queued(self, id: int) -> None:
        self._update(id, "status = 'queued'")

    def mark_running(self, id: int) -> None:
        """두뇌 실행을 시작한다. `attempt`가 하나 는다."""
        self._update(id, "status = 'running', attempt = attempt + 1, started_at = ?, error = NULL", self._now())

    def set_conversation(self, id: int, conversation_id: int) -> None:
        self._update(id, "conversation_id = ?", conversation_id)

    def save_outbound(self, id: int, text: str) -> None:
        self._update(id, "outbound_text = ?", text)

    def mark_done(self, id: int) -> None:
        self._update(id, "status = 'done', finished_at = ?, error = NULL", self._now())

    def mark_failed(self, id: int, error: str) -> None:
        self._update(id, "status = 'failed', finished_at = ?, error = ?", self._now(), error)

    def mark_skipped(self, id: int, reason: SkipReason | str) -> None:
        self._update(
            id, "status = 'skipped', skip_reason = ?, finished_at = ?", SkipReason(reason).value, self._now()
        )

    def add_merged(self, id: int, ids: list[int]) -> None:
        run = self.get(id)
        if run is None:
            return
        merged = run.merged_run_ids + [i for i in ids if i not in run.merged_run_ids]
        self._update(id, "merged_run_ids = ?", json.dumps(merged))

    def mark_resent(self, id: int) -> None:
        self._update(id, "resent = 1")

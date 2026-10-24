"""status_xp_ledger, status_titles 표 읽기 (SP3-4 스펙 5.5). 원장은 쌓기만 하고 이 저장소에는 쓰는 함수가 없다."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from my_planner.clock import Clock, from_iso


@dataclass
class XpEntry:
    at: datetime
    label: str
    amount: int


@dataclass
class TitleRow:
    milestone_id: int
    kind: str
    title: str
    title_label: str | None
    date_text: str
    granted_at: datetime


class StatusRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def total(self) -> int:
        r = self.conn.execute("SELECT COALESCE(SUM(amount), 0) AS n FROM status_xp_ledger").fetchone()
        return int(r["n"])

    def recent(self, n: int = 5) -> list[XpEntry]:
        rows = self.conn.execute(
            "SELECT at, label, amount FROM status_xp_ledger ORDER BY at DESC, id DESC LIMIT ?", (n,)
        ).fetchall()
        return [XpEntry(at=from_iso(r["at"]), label=r["label"], amount=r["amount"]) for r in rows]

    def titles(self, *, include_sensitive: bool) -> list[TitleRow]:
        """확정한 고점·전환점 사건의 칭호, 받은 순서. 민감 사건은 `include_sensitive`일 때만."""
        sql = (
            "SELECT t.milestone_id, t.granted_at, m.kind, m.title, m.title_label, m.date_text "
            "FROM status_titles t JOIN curve_milestones m ON m.id = t.milestone_id "
            "WHERE m.status = 'confirmed' AND m.kind IN ('high', 'turning_point')"
        )
        if not include_sensitive:
            sql += " AND m.sensitive = 0"
        sql += " ORDER BY t.granted_at, t.id"
        return [
            TitleRow(
                milestone_id=r["milestone_id"], kind=r["kind"], title=r["title"], title_label=r["title_label"],
                date_text=r["date_text"], granted_at=from_iso(r["granted_at"]),
            )
            for r in self.conn.execute(sql).fetchall()
        ]

    def first_steps(self, task_id: int) -> tuple[int, int]:
        """그 할 일의 첫 걸음(`parent_id`가 그 할 일인 것) 수: (열림, 완료). 소프트 삭제한 것은 뺀다."""
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE parent_id = ? AND deleted_at IS NULL "
            "AND status IN ('open', 'done') GROUP BY status",
            (task_id,),
        ).fetchall()
        counts = {r["status"]: r["n"] for r in rows}
        return counts.get("open", 0), counts.get("done", 0)

    def next_undated_step(self, task_id: int) -> int | None:
        """날짜 없는 다음 첫 걸음(`open`, `planned_for` 없음)의 id. 없으면 None."""
        r = self.conn.execute(
            "SELECT id FROM tasks WHERE parent_id = ? AND deleted_at IS NULL AND status = 'open' "
            "AND planned_for IS NULL ORDER BY id LIMIT 1",
            (task_id,),
        ).fetchone()
        return r["id"] if r else None

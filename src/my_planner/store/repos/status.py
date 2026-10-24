"""status_xp_ledger, status_titles 표 (SP3-4 스펙 5.5).

원장은 쌓기만 한다(ADR 0006, 9.1): 쓰는 함수는 `grant`(`INSERT … ON CONFLICT DO NOTHING`) 하나이고 UPDATE·DELETE
함수는 없다. 쌓는 자리는 4.3 표 그대로다(변경 도구, 디스패처의 `mark_answered`, 하루 한 번 작업). 칭호는 원장이
아니라서 사건 확정을 되돌리면 지운다(9.4, 6.4.3 `milestones_confirmed`).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.status.xp import XpGain
from my_planner.store.db import transaction


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

    def grant(
        self, *, at: datetime, logical_date: date, source_kind: str, source_ref: str, amount: int, label: str,
        area: str | None = None, gain: XpGain | None = None,
    ) -> bool:
        """원장에 한 줄 쌓는다. 같은 `(source_kind, source_ref)`가 이미 있으면 그대로 두고 False(9.1 "한 번만").

        바깥 트랜잭션 안에서 부르면 그 변경과 함께 커밋된다(`transaction`이 합류한다). `gain`이 있으면 쌓은 경우에만
        쌓기 직전·직후 합계를 적는다(레벨 오름은 그 쌓기를 한 차례에만 붙인다, 9.2).
        """
        with transaction(self.conn):
            before = self.total() if gain is not None else 0
            cur = self.conn.execute(
                "INSERT INTO status_xp_ledger (at, logical_date, source_kind, source_ref, amount, area, label) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (source_kind, source_ref) DO NOTHING",
                (to_iso(at), logical_date.isoformat(), source_kind, source_ref, amount, area, label),
            )
            if gain is not None and cur.rowcount > 0:
                gain.add(before, before + amount)
        return cur.rowcount > 0

    def count_secretary_on(self, d: date) -> int:
        """그 논리적 날짜에 비서가 준 경험치(X10) 수. 하루 3회 상한에 쓴다."""
        r = self.conn.execute(
            "SELECT COUNT(*) AS n FROM status_xp_ledger WHERE source_kind = 'secretary' AND logical_date = ?",
            (d.isoformat(),),
        ).fetchone()
        return int(r["n"])

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

    def add_title(self, milestone_id: int, at: datetime) -> bool:
        """그 사건의 칭호. 이미 있으면 그대로 둔다(False)."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO status_titles (milestone_id, granted_at) VALUES (?, ?)",
                (milestone_id, to_iso(at)),
            )
        return cur.rowcount > 0

    def remove_title(self, milestone_id: int) -> bool:
        with transaction(self.conn):
            cur = self.conn.execute("DELETE FROM status_titles WHERE milestone_id = ?", (milestone_id,))
        return cur.rowcount > 0

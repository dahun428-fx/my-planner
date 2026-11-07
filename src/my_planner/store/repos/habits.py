"""habits, habit_checks 표 (SP7 스펙 5.1~5.2). 날짜는 논리적 날짜로 부르는 쪽이 이미 정해서 넘긴다.

안 한 날은 행이 없다. "놓친 날"을 저장하거나 계산하는 함수는 두지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.domain import Area
from my_planner.store.db import transaction


@dataclass(frozen=True)
class Habit:
    id: int
    title: str
    area: Area
    kind: Literal["daily", "weekly"]
    target_per_week: int | None
    status: Literal["active", "paused", "archived"]
    sort_order: int
    created_at: datetime
    updated_at: datetime


_UPDATABLE = {"title", "area", "kind", "target_per_week"}


def _habit(r: sqlite3.Row) -> Habit:
    return Habit(
        id=r["id"],
        title=r["title"],
        area=Area(r["area"]),
        kind=r["kind"],
        target_per_week=r["target_per_week"],
        status=r["status"],
        sort_order=r["sort_order"],
        created_at=from_iso(r["created_at"]),
        updated_at=from_iso(r["updated_at"]),
    )


class HabitsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # --- 읽기 ---

    def get(self, id: int) -> Habit | None:
        r = self.conn.execute("SELECT * FROM habits WHERE id = ? AND deleted_at IS NULL", (id,)).fetchone()
        return _habit(r) if r else None

    def find_by_title(self, title: str, statuses: Sequence[str]) -> Habit | None:
        marks = ", ".join("?" for _ in statuses)
        r = self.conn.execute(
            f"SELECT * FROM habits WHERE title = ? AND deleted_at IS NULL AND status IN ({marks}) "
            "ORDER BY sort_order LIMIT 1",
            (title, *statuses),
        ).fetchone()
        return _habit(r) if r else None

    def list(self, statuses: Sequence[str] = ("active",)) -> list[Habit]:
        marks = ", ".join("?" for _ in statuses)
        rows = self.conn.execute(
            f"SELECT * FROM habits WHERE deleted_at IS NULL AND status IN ({marks}) ORDER BY sort_order, id",
            tuple(statuses),
        ).fetchall()
        return [_habit(r) for r in rows]

    def count_active(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM habits WHERE deleted_at IS NULL AND status = 'active'"
        ).fetchone()[0]

    def has_checks(self, id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM habit_checks WHERE habit_id = ? LIMIT 1", (id,)).fetchone() is not None

    def checked_on(self, day: date) -> set[int]:
        rows = self.conn.execute("SELECT habit_id FROM habit_checks WHERE date = ?", (day.isoformat(),)).fetchall()
        return {r["habit_id"] for r in rows}

    def week_counts(self, week_start: date) -> dict[int, int]:
        """`week_start`(월요일)부터 일요일까지 습관별 체크 수. 체크가 없는 습관은 넣지 않는다."""
        end = week_start + timedelta(days=6)
        rows = self.conn.execute(
            "SELECT habit_id, COUNT(*) AS n FROM habit_checks WHERE date >= ? AND date <= ? GROUP BY habit_id",
            (week_start.isoformat(), end.isoformat()),
        ).fetchall()
        return {r["habit_id"]: r["n"] for r in rows}

    def checks_between(self, id: int, from_: date, to: date) -> list[date]:
        rows = self.conn.execute(
            "SELECT date FROM habit_checks WHERE habit_id = ? AND date >= ? AND date <= ? ORDER BY date",
            (id, from_.isoformat(), to.isoformat()),
        ).fetchall()
        return [date.fromisoformat(r["date"]) for r in rows]

    def checks_in(self, from_: date, to: date) -> list[tuple[Habit, date]]:
        """`from_..to`(양끝 포함)의 모든 체크와 그 습관(지운 습관은 뺀다), 최근 날짜부터."""
        rows = self.conn.execute(
            "SELECT h.*, c.date AS check_date FROM habit_checks c JOIN habits h ON h.id = c.habit_id "
            "WHERE h.deleted_at IS NULL AND c.date >= ? AND c.date <= ? ORDER BY c.date DESC, h.sort_order, h.id",
            (from_.isoformat(), to.isoformat()),
        ).fetchall()
        return [(_habit(r), date.fromisoformat(r["check_date"])) for r in rows]

    # --- 쓰기 ---

    def add(self, title: str, area: Area | str, kind: str, target: int | None, now: datetime) -> Habit:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO habits (title, area, kind, target_per_week, status, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'active', (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM habits), ?, ?)",
                (title, Area(area).value, kind, target, to_iso(now), to_iso(now)),
            )
            id = cur.lastrowid
        h = self.get(id)  # type: ignore[arg-type]
        assert h is not None
        return h

    def update(self, id: int, *, now: datetime, **fields: Any) -> Habit:
        bad = set(fields) - _UPDATABLE
        if bad:
            raise ValueError(f"고칠 수 없는 필드: {sorted(bad)}")
        sets = ["updated_at = ?"]
        args: list[Any] = [to_iso(now)]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            args.append(Area(v).value if k == "area" else v)
        with transaction(self.conn):
            cur = self.conn.execute(
                f"UPDATE habits SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL", (*args, id)
            )
            if cur.rowcount == 0:
                raise KeyError(id)
        h = self.get(id)
        assert h is not None
        return h

    def set_status(self, id: int, status: str, now: datetime) -> Habit:
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE habits SET status = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (status, to_iso(now), id),
            )
            if cur.rowcount == 0:
                raise KeyError(id)
        h = self.get(id)
        assert h is not None
        return h

    def soft_delete(self, id: int, now: datetime) -> None:
        """되돌린 추가(스펙 5.1). 없거나 이미 지운 습관이면 `update`·`set_status`처럼 `KeyError`."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE habits SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (to_iso(now), to_iso(now), id),
            )
            if cur.rowcount == 0:
                raise KeyError(id)

    def check(self, id: int, day: date, now: datetime) -> bool:
        """체크한다. 새로 넣었으면 True, 이미 있었으면 바꾸지 않고 False."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO habit_checks (habit_id, date, checked_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (id, day.isoformat(), to_iso(now)),
            )
            return cur.rowcount == 1

    def uncheck(self, id: int, day: date) -> str | None:
        """체크를 지우고 그 행의 `checked_at`(되돌리기용)을 돌려준다. 없었으면 None."""
        with transaction(self.conn):
            r = self.conn.execute(
                "DELETE FROM habit_checks WHERE habit_id = ? AND date = ? RETURNING checked_at",
                (id, day.isoformat()),
            ).fetchone()
        return r["checked_at"] if r else None

    def restore_check(self, id: int, day: date, checked_at: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO habit_checks (habit_id, date, checked_at) VALUES (?, ?, ?) "
                "ON CONFLICT (habit_id, date) DO UPDATE SET checked_at = excluded.checked_at",
                (id, day.isoformat(), checked_at),
            )

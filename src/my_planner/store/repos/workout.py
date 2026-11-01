"""body_notes, workout_plans, workout_plan_sessions, workout_logs, workout_log_items 표 (SP12 스펙 6.1, 7.1~7.3, 8.1).

날짜는 논리적 날짜로 부르는 쪽이 이미 정해서 넘긴다. 칸마다의 값 검증(7.3 표)은 도구가 하고, 여기서는 DB CHECK만 믿는다.
쓰기는 모두 부르는 쪽 `transaction` 안에서 한다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from my_planner.clock import Clock, from_iso, to_iso

BodyKind = Literal["equipment", "injury", "preference", "availability", "other"]


@dataclass(frozen=True)
class BodyNote:
    id: int
    kind: BodyKind
    text: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PlanItem:
    name: str
    sets: int | None
    reps: str | None
    weight_kg: float | None
    minutes: int | None
    note: str | None


@dataclass(frozen=True)
class PlanSession:
    id: int
    position: int
    label: str
    weekdays: tuple[int, ...] | None
    items: tuple[PlanItem, ...]


@dataclass(frozen=True)
class Plan:
    id: int
    title: str
    note: str | None
    created_at: datetime
    sessions: tuple[PlanSession, ...]


@dataclass(frozen=True)
class LogItem:
    name: str
    sets: int | None
    reps: int | None
    weight_kg: float | None
    minutes: int | None
    distance_km: float | None


@dataclass(frozen=True)
class WorkoutLog:
    id: int
    date: date
    title: str
    session_id: int | None
    effort: int | None
    note: str | None
    items: tuple[LogItem, ...]
    created_at: datetime
    updated_at: datetime


_LOG_UPDATABLE = {"date", "title", "session_id", "effort", "note", "items"}
_PLAN_ITEM_KEYS = ("name", "sets", "reps", "weight_kg", "minutes", "note")
_LOG_ITEM_KEYS = ("name", "sets", "reps", "weight_kg", "minutes", "distance_km")


def _note(r: sqlite3.Row) -> BodyNote:
    return BodyNote(
        id=r["id"],
        kind=r["kind"],
        text=r["text"],
        created_at=from_iso(r["created_at"]),
        updated_at=from_iso(r["updated_at"]),
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class WorkoutRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # --- 몸 메모 ---

    def notes(self) -> list[BodyNote]:
        rows = self.conn.execute(
            "SELECT * FROM body_notes WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [_note(r) for r in rows]

    def note(self, id: int) -> BodyNote | None:
        r = self.conn.execute(
            "SELECT * FROM body_notes WHERE id = ? AND deleted_at IS NULL", (id,)
        ).fetchone()
        return _note(r) if r else None

    def count_notes(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM body_notes WHERE deleted_at IS NULL"
        ).fetchone()[0]

    def find_note(self, kind: str, text: str) -> BodyNote | None:
        r = self.conn.execute(
            "SELECT * FROM body_notes WHERE kind = ? AND text = ? AND deleted_at IS NULL ORDER BY id LIMIT 1",
            (kind, text),
        ).fetchone()
        return _note(r) if r else None

    def add_note(self, kind: str, text: str, now: datetime) -> BodyNote:
        cur = self.conn.execute(
            "INSERT INTO body_notes (kind, text, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (kind, text, to_iso(now), to_iso(now)),
        )
        n = self.note(cur.lastrowid)  # type: ignore[arg-type]
        assert n is not None
        return n

    def update_note(self, id: int, kind: str, text: str, now: datetime) -> None:
        cur = self.conn.execute(
            "UPDATE body_notes SET kind = ?, text = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (kind, text, to_iso(now), id),
        )
        if cur.rowcount == 0:
            raise KeyError(id)

    def drop_note(self, id: int, now: datetime) -> None:
        cur = self.conn.execute(
            "UPDATE body_notes SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (to_iso(now), to_iso(now), id),
        )
        if cur.rowcount == 0:
            raise KeyError(id)

    def restore_note(self, id: int) -> None:
        cur = self.conn.execute(
            "UPDATE body_notes SET deleted_at = NULL WHERE id = ?", (id,)
        )
        if cur.rowcount == 0:
            raise KeyError(id)

    # --- 플랜 ---

    def _plan(self, r: sqlite3.Row) -> Plan:
        rows = self.conn.execute(
            "SELECT * FROM workout_plan_sessions WHERE plan_id = ? ORDER BY position",
            (r["id"],),
        ).fetchall()
        sessions = tuple(
            PlanSession(
                id=s["id"],
                position=s["position"],
                label=s["label"],
                weekdays=tuple(json.loads(s["weekdays"]))
                if s["weekdays"] is not None
                else None,
                items=tuple(
                    PlanItem(*(i.get(k) for k in _PLAN_ITEM_KEYS))
                    for i in json.loads(s["items"])
                ),
            )
            for s in rows
        )
        return Plan(
            id=r["id"],
            title=r["title"],
            note=r["note"],
            created_at=from_iso(r["created_at"]),
            sessions=sessions,
        )

    def current_plan(self) -> Plan | None:
        r = self.conn.execute(
            "SELECT * FROM workout_plans WHERE replaced_at IS NULL AND cleared_at IS NULL"
        ).fetchone()
        return self._plan(r) if r else None

    def plan(self, id: int) -> Plan | None:
        r = self.conn.execute(
            "SELECT * FROM workout_plans WHERE id = ?", (id,)
        ).fetchone()
        return self._plan(r) if r else None

    def replace_plan(
        self,
        title: str,
        note: str | None,
        sessions: Sequence[tuple[str, tuple[int, ...] | None, Sequence[PlanItem]]],
        now: datetime,
    ) -> tuple[int | None, int]:
        """지금 플랜에 `replaced_at`을 쓰고 새 플랜과 세션을 넣는다. (앞 플랜 id 또는 None, 새 플랜 id)."""
        prev = self.conn.execute(
            "UPDATE workout_plans SET replaced_at = ? WHERE replaced_at IS NULL AND cleared_at IS NULL RETURNING id",
            (to_iso(now),),
        ).fetchone()
        new_id = self.conn.execute(
            "INSERT INTO workout_plans (title, note, created_at) VALUES (?, ?, ?)",
            (title, note, to_iso(now)),
        ).lastrowid
        for pos, (label, weekdays, items) in enumerate(sessions, start=1):
            self.conn.execute(
                "INSERT INTO workout_plan_sessions (plan_id, position, label, weekdays, items) VALUES (?, ?, ?, ?, ?)",
                (
                    new_id,
                    pos,
                    label,
                    _dump(list(weekdays)) if weekdays is not None else None,
                    _dump([{k: getattr(i, k) for k in _PLAN_ITEM_KEYS} for i in items]),
                ),
            )
        return (prev["id"] if prev else None, new_id)  # type: ignore[return-value]

    def clear_plan(self, now: datetime) -> int | None:
        """지금 플랜에 `cleared_at`을 쓰고 그 id를 돌려준다. 지금 플랜이 없으면 None."""
        r = self.conn.execute(
            "UPDATE workout_plans SET cleared_at = ? WHERE replaced_at IS NULL AND cleared_at IS NULL RETURNING id",
            (to_iso(now),),
        ).fetchone()
        return r["id"] if r else None

    def undo_replace(self, new_id: int, prev_id: int | None, now: datetime) -> None:
        """새 플랜에 `replaced_at`을 쓰고, 앞 플랜이 있으면 그 `replaced_at`을 NULL로 돌린다(지금 플랜은 늘 하나)."""
        cur = self.conn.execute(
            "UPDATE workout_plans SET replaced_at = ? WHERE id = ?",
            (to_iso(now), new_id),
        )
        if cur.rowcount == 0:
            raise KeyError(new_id)
        if prev_id is not None:
            self.conn.execute(
                "UPDATE workout_plans SET replaced_at = NULL WHERE id = ?", (prev_id,)
            )

    def has_session(self, id: int) -> bool:
        """그 세션 행이 있다(지난 플랜의 세션도. 기록의 `session_id`가 가리킬 수 있다, 7.2)."""
        return (
            self.conn.execute(
                "SELECT 1 FROM workout_plan_sessions WHERE id = ?", (id,)
            ).fetchone()
            is not None
        )

    def undo_clear(self, plan_id: int) -> None:
        cur = self.conn.execute(
            "UPDATE workout_plans SET cleared_at = NULL WHERE id = ?", (plan_id,)
        )
        if cur.rowcount == 0:
            raise KeyError(plan_id)

    # --- 기록 ---

    def _log(self, r: sqlite3.Row) -> WorkoutLog:
        rows = self.conn.execute(
            "SELECT * FROM workout_log_items WHERE log_id = ? ORDER BY position",
            (r["id"],),
        ).fetchall()
        return WorkoutLog(
            id=r["id"],
            date=date.fromisoformat(r["date"]),
            title=r["title"],
            session_id=r["session_id"],
            effort=r["effort"],
            note=r["note"],
            items=tuple(LogItem(*(i[k] for k in _LOG_ITEM_KEYS)) for i in rows),
            created_at=from_iso(r["created_at"]),
            updated_at=from_iso(r["updated_at"]),
        )

    def _put_items(self, log_id: int, items: Sequence[LogItem]) -> None:
        self.conn.execute("DELETE FROM workout_log_items WHERE log_id = ?", (log_id,))
        for pos, i in enumerate(items, start=1):
            self.conn.execute(
                "INSERT INTO workout_log_items (log_id, position, name, sets, reps, weight_kg, minutes, distance_km) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (log_id, pos, *(getattr(i, k) for k in _LOG_ITEM_KEYS)),
            )

    def log(self, id: int) -> WorkoutLog | None:
        r = self.conn.execute(
            "SELECT * FROM workout_logs WHERE id = ? AND deleted_at IS NULL", (id,)
        ).fetchone()
        return self._log(r) if r else None

    def add_log(
        self,
        date: date,
        title: str,
        session_id: int | None,
        effort: int | None,
        note: str | None,
        items: Sequence[LogItem],
        now: datetime,
    ) -> WorkoutLog:
        cur = self.conn.execute(
            "INSERT INTO workout_logs (date, title, session_id, effort, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                date.isoformat(),
                title,
                session_id,
                effort,
                note,
                to_iso(now),
                to_iso(now),
            ),
        )
        self._put_items(cur.lastrowid, items)  # type: ignore[arg-type]
        got = self.log(cur.lastrowid)  # type: ignore[arg-type]
        assert got is not None
        return got

    def update_log(self, id: int, now: datetime, **fields: Any) -> None:
        """넘긴 칸만 고친다. `items`를 넘기면 줄 전체를 바꾼다."""
        bad = set(fields) - _LOG_UPDATABLE
        if bad:
            raise ValueError(f"고칠 수 없는 필드: {sorted(bad)}")
        items = fields.pop("items", None)
        sets = ["updated_at = ?"]
        args: list[Any] = [to_iso(now)]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            args.append(v.isoformat() if k == "date" else v)
        cur = self.conn.execute(
            f"UPDATE workout_logs SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL",
            (*args, id),
        )
        if cur.rowcount == 0:
            raise KeyError(id)
        if items is not None:
            self._put_items(id, items)

    def delete_log(self, id: int, now: datetime) -> None:
        cur = self.conn.execute(
            "UPDATE workout_logs SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (to_iso(now), to_iso(now), id),
        )
        if cur.rowcount == 0:
            raise KeyError(id)

    def restore_log(self, id: int) -> None:
        cur = self.conn.execute(
            "UPDATE workout_logs SET deleted_at = NULL WHERE id = ?", (id,)
        )
        if cur.rowcount == 0:
            raise KeyError(id)

    def logs(
        self, since: date, until: date, name: str | None = None
    ) -> list[WorkoutLog]:
        """지우지 않은 기록, 날짜 내림차순. `name`은 운동 줄 이름 부분 일치."""
        sql = "SELECT * FROM workout_logs WHERE deleted_at IS NULL AND date >= ? AND date <= ?"
        args: list[Any] = [since.isoformat(), until.isoformat()]
        if name is not None:
            sql += " AND EXISTS (SELECT 1 FROM workout_log_items i WHERE i.log_id = workout_logs.id AND instr(i.name, ?) > 0)"
            args.append(name)
        rows = self.conn.execute(sql + " ORDER BY date DESC, id DESC", args).fetchall()
        return [self._log(r) for r in rows]

    def has_log_on(self, d: date) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM workout_logs WHERE date = ? AND deleted_at IS NULL LIMIT 1",
                (d.isoformat(),),
            ).fetchone()
            is not None
        )

    def log_days(self, since: date, until: date) -> set[date]:
        rows = self.conn.execute(
            "SELECT DISTINCT date FROM workout_logs WHERE deleted_at IS NULL AND date >= ? AND date <= ?",
            (since.isoformat(), until.isoformat()),
        ).fetchall()
        return {date.fromisoformat(r["date"]) for r in rows}

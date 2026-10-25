"""status_moments, status_moment_days 표 (SP8 스펙 6.1, ADR 0013). 날짜는 논리적 날짜, 시각은 UTC ISO 8601.

순간의 글은 이 표에만 둔다. 이 모듈은 로그를 남기지 않는다.
읽기(`between`, `hidden_count`, `get`)는 읽기 전용 연결로도 된다. 숨기기·지우기는 쓰기 연결로만(SP8-04).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.store.db import transaction

DayState = Literal["pending", "done", "empty", "failed"]


@dataclass(frozen=True)
class Moment:
    id: int
    date: date
    slot: int
    text: str
    area: str | None
    sources: list[str]
    hidden_at: datetime | None


@dataclass(frozen=True)
class MomentDay:
    date: date
    state: DayState
    saved: int
    attempts: int


def _moment(r: sqlite3.Row) -> Moment:
    return Moment(
        id=r["id"],
        date=date.fromisoformat(r["date"]),
        slot=r["slot"],
        text=r["text"],
        area=r["area"],
        sources=list(json.loads(r["sources_json"])),
        hidden_at=from_iso(r["hidden_at"]) if r["hidden_at"] else None,
    )


def _day(r: sqlite3.Row) -> MomentDay:
    return MomentDay(date=date.fromisoformat(r["date"]), state=r["state"], saved=r["saved"], attempts=r["attempts"])


class MomentsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # --- 날 행 ---

    def day(self, d: date) -> MomentDay | None:
        r = self.conn.execute("SELECT * FROM status_moment_days WHERE date = ?", (d.isoformat(),)).fetchone()
        return _day(r) if r else None

    def days_since(self, from_: date) -> dict[date, MomentDay]:
        """`from_`(포함) 이후 날 행 전부."""
        rows = self.conn.execute(
            "SELECT * FROM status_moment_days WHERE date >= ? ORDER BY date", (from_.isoformat(),)
        ).fetchall()
        return {d.date: d for d in map(_day, rows)}

    def mark(self, d: date, state: DayState, now: datetime, *, saved: int = 0) -> None:
        """그날의 상태를 적는다(행이 없으면 만든다). `attempts`는 그대로 둔다."""
        self.conn.execute(
            "INSERT INTO status_moment_days (date, state, saved, attempts, updated_at) VALUES (?, ?, ?, 0, ?) "
            "ON CONFLICT (date) DO UPDATE SET state = excluded.state, saved = excluded.saved, "
            "updated_at = excluded.updated_at",
            (d.isoformat(), state, saved, to_iso(now)),
        )

    def bump_attempt(self, d: date, now: datetime, max_attempts: int) -> DayState:
        """`pending` 행의 `attempts + 1`. `max_attempts`에 닿으면 `failed`로(그래도 `pending` 행만 바꾼다:
        이미 `done`인 날은 덮지 않는다, 6.2-6). 바꾼 뒤의 상태를 돌려준다."""
        key, at = d.isoformat(), to_iso(now)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO status_moment_days (date, state, saved, attempts, updated_at) "
                "VALUES (?, 'pending', 0, 0, ?)",
                (key, at),
            )
            self.conn.execute(
                "UPDATE status_moment_days SET attempts = attempts + 1, updated_at = ? "
                "WHERE date = ? AND state = 'pending'",
                (at, key),
            )
            self.conn.execute(
                "UPDATE status_moment_days SET state = 'failed', updated_at = ? "
                "WHERE date = ? AND state = 'pending' AND attempts >= ?",
                (at, key, max_attempts),
            )
        got = self.day(d)
        assert got is not None
        return got.state

    def prune_days(self, older_than: date) -> int:
        """`older_than`보다 오래된 날 행을 지운다(순간 행은 그대로, 6.4 보관)."""
        cur = self.conn.execute("DELETE FROM status_moment_days WHERE date < ?", (older_than.isoformat(),))
        return cur.rowcount

    # --- 순간 ---

    def save_day(self, d: date, items: list[tuple[str, str | None, list[str]]], now: datetime) -> list[Moment]:
        """그날의 순간(글, 영역, 근거)을 slot 1..n으로 저장하고 날 행을 `done`, `saved = n`으로. 바깥 트랜잭션에 합류한다."""
        key, at = d.isoformat(), to_iso(now)
        with transaction(self.conn):
            ids = [
                self.conn.execute(
                    "INSERT INTO status_moments (date, slot, text, area, sources_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key, slot, text, area, json.dumps(sources, ensure_ascii=False), at),
                ).lastrowid
                for slot, (text, area, sources) in enumerate(items, start=1)
            ]
            self.mark(d, "done", now, saved=len(items))
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        rows = self.conn.execute(f"SELECT * FROM status_moments WHERE id IN ({marks}) ORDER BY slot", ids).fetchall()
        return [_moment(r) for r in rows]

    def between(self, from_: date, to: date, *, include_hidden: bool) -> list[Moment]:
        """`from_`~`to`(둘 다 포함)의 순간. 최근 날짜부터, 같은 날은 `slot` 순."""
        hidden = "" if include_hidden else " AND hidden_at IS NULL"
        rows = self.conn.execute(
            f"SELECT * FROM status_moments WHERE date BETWEEN ? AND ?{hidden} ORDER BY date DESC, slot",
            (from_.isoformat(), to.isoformat()),
        ).fetchall()
        return [_moment(r) for r in rows]

    def hidden_count(self, from_: date, to: date) -> int:
        r = self.conn.execute(
            "SELECT COUNT(*) FROM status_moments WHERE date BETWEEN ? AND ? AND hidden_at IS NOT NULL",
            (from_.isoformat(), to.isoformat()),
        ).fetchone()
        return int(r[0])

    def get(self, moment_id: int) -> Moment | None:
        r = self.conn.execute("SELECT * FROM status_moments WHERE id = ?", (moment_id,)).fetchone()
        return _moment(r) if r else None

    def _hidden_at(self, moment_id: int) -> str | None:
        r = self.conn.execute("SELECT hidden_at FROM status_moments WHERE id = ?", (moment_id,)).fetchone()
        return r["hidden_at"] if r else None

    def hide(self, moment_id: int, at: datetime) -> str | None:
        """숨긴다. 이전 `hidden_at`(저장 형식 그대로)을 돌려준다. 이미 숨겼으면 바꾸지 않는다."""
        prev = self._hidden_at(moment_id)
        if prev is None:
            self.conn.execute("UPDATE status_moments SET hidden_at = ? WHERE id = ?", (to_iso(at), moment_id))
        return prev

    def unhide(self, moment_id: int) -> str | None:
        """다시 보이게 한다. 이전 `hidden_at`을 돌려준다(숨기지 않았으면 None)."""
        prev = self._hidden_at(moment_id)
        if prev is not None:
            self.conn.execute("UPDATE status_moments SET hidden_at = NULL WHERE id = ?", (moment_id,))
        return prev

    def restore_hidden(self, moment_id: int, hidden_at: str | None) -> bool:
        """되돌리기: `hidden_at`을 그 값으로. 행이 없으면(지웠으면) False."""
        cur = self.conn.execute("UPDATE status_moments SET hidden_at = ? WHERE id = ?", (hidden_at, moment_id))
        return cur.rowcount > 0

    def delete(self, moment_id: int) -> Moment | None:
        """행을 지운다(되돌릴 수 없다). 지운 순간, 없으면 None. 날 행(`status_moment_days`)은 그대로다(6.4)."""
        m = self.get(moment_id)
        if m is not None:
            self.conn.execute("DELETE FROM status_moments WHERE id = ?", (moment_id,))
        return m

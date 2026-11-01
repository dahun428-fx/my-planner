"""agent_events, agent_inbox, agent_notes 표 (SP14 스펙 5.1~5.4).

사건에는 종류·`ref`(id)·영역·날짜·출처만 둔다(제목·본문·값 없음). 쓰기는 모두 부르는 쪽 `transaction` 안에서 한다.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.domain import EVENT_KINDS, EVENT_ORIGINS, INBOX_AGENTS, InboxAgent

EVENT_DEDUPE_S = 60
EVENTS_KEEP_DAYS = 90
INBOX_SEEN_KEEP_DAYS = 30
NOTES_KEEP_DAYS = 365

_REF = re.compile(r"^[a-z_]+:[0-9A-Za-z_:-]+$")


@dataclass(frozen=True)
class AgentEvent:
    id: int
    occurred_at: datetime
    day: date
    kind: str
    ref: str
    area: str | None
    origin: str


@dataclass(frozen=True)
class AgentNote:
    id: int
    agent: str
    day: date
    text: str
    priority: int
    refs: tuple[str, ...]
    shown_at: datetime | None
    created_at: datetime


_EV_COLS = "e.id, e.occurred_at, e.day, e.kind, e.ref, e.area, e.origin"
_NOTE_COLS = "id, agent, day, text, priority, refs_json, shown_at, created_at"


def _event(r: sqlite3.Row) -> AgentEvent:
    return AgentEvent(
        id=r["id"], occurred_at=from_iso(r["occurred_at"]), day=date.fromisoformat(r["day"]), kind=r["kind"],
        ref=r["ref"], area=r["area"], origin=r["origin"],
    )


def _note(r: sqlite3.Row) -> AgentNote:
    return AgentNote(
        id=r["id"], agent=r["agent"], day=date.fromisoformat(r["day"]), text=r["text"], priority=r["priority"],
        refs=tuple(json.loads(r["refs_json"])), shown_at=from_iso(r["shown_at"]) if r["shown_at"] else None,
        created_at=from_iso(r["created_at"]),
    )


def _qs(n: int) -> str:
    return ",".join("?" * n)


class AgentsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # --- 사건 ---

    def add_event(
        self, kind: str, ref: str, area: str | None, origin: str, day: date, *,
        to: tuple[str, ...], now: datetime, seen_by: str | None = None,
    ) -> int | None:
        if kind not in EVENT_KINDS:
            raise ValueError(f"모르는 사건 종류: {kind}")
        if origin not in EVENT_ORIGINS:
            raise ValueError(f"모르는 출처: {origin}")
        if not _REF.match(ref):
            raise ValueError("ref 모양이 맞지 않아요.")
        for a in to:
            if a not in INBOX_AGENTS:
                raise ValueError(f"모르는 상대: {a}")
        cutoff = to_iso(now - timedelta(seconds=EVENT_DEDUPE_S))
        if self.conn.execute(
            "SELECT 1 FROM agent_events WHERE kind = ? AND ref = ? AND occurred_at >= ? LIMIT 1", (kind, ref, cutoff)
        ).fetchone():
            return None
        at = to_iso(now)
        eid = self.conn.execute(
            "INSERT INTO agent_events (occurred_at, day, kind, ref, area, origin) VALUES (?, ?, ?, ?, ?, ?)",
            (at, day.isoformat(), kind, ref, area, origin),
        ).lastrowid
        assert eid is not None
        for a in to:
            self.conn.execute(
                "INSERT INTO agent_inbox (agent, event_id, seen_at) VALUES (?, ?, ?)",
                (a, eid, at if a == seen_by else None),
            )
        return eid

    def events_since(self, kinds: Iterable[str], since: date) -> list[AgentEvent]:
        ks = list(kinds)
        if not ks:
            return []
        rows = self.conn.execute(
            f"SELECT {_EV_COLS} FROM agent_events e WHERE e.kind IN ({_qs(len(ks))}) AND e.day >= ? "
            "ORDER BY e.occurred_at, e.id",
            (*ks, since.isoformat()),
        ).fetchall()
        return [_event(r) for r in rows]

    def unseen(self, agent: str, since: date, limit: int | None = None) -> list[AgentEvent]:
        sql = (
            f"SELECT {_EV_COLS} FROM agent_inbox i JOIN agent_events e ON e.id = i.event_id "
            "WHERE i.agent = ? AND i.seen_at IS NULL AND e.day >= ? ORDER BY e.occurred_at DESC, e.id DESC"
        )
        args: list[object] = [agent, since.isoformat()]
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [_event(r) for r in self.conn.execute(sql, args).fetchall()]

    def unseen_count(self, agent: str, since: date) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM agent_inbox i JOIN agent_events e ON e.id = i.event_id "
            "WHERE i.agent = ? AND i.seen_at IS NULL AND e.day >= ?",
            (agent, since.isoformat()),
        ).fetchone()[0]

    def ref_in_inbox(self, agent: InboxAgent, ref: str) -> bool:
        """그 상대 받은편지함(본 것 포함)에 `ref`를 가리키는 사건이 있는가. 행이 사라진 사건(`event_removed`)의 참조용."""
        return self.conn.execute(
            "SELECT 1 FROM agent_inbox i JOIN agent_events e ON e.id = i.event_id WHERE i.agent = ? AND e.ref = ? "
            "LIMIT 1",
            (agent, ref),
        ).fetchone() is not None

    def mark_seen(self, agent: str, event_ids: Iterable[int], now: datetime) -> int:
        ids = list(event_ids)
        if not ids:
            return 0
        cur = self.conn.execute(
            f"UPDATE agent_inbox SET seen_at = ? WHERE agent = ? AND seen_at IS NULL AND event_id IN ({_qs(len(ids))})",
            (to_iso(now), agent, *ids),
        )
        return cur.rowcount

    def mark_seen_before(self, agent: str, day: date, now: datetime) -> int:
        cur = self.conn.execute(
            "UPDATE agent_inbox SET seen_at = ? WHERE agent = ? AND seen_at IS NULL "
            "AND event_id IN (SELECT id FROM agent_events WHERE day < ?)",
            (to_iso(now), agent, day.isoformat()),
        )
        return cur.rowcount

    # --- 관찰 ---

    def add_note(self, agent: str, day: date, text: str, priority: int, refs: list[str], now: datetime) -> int:
        cur = self.conn.execute(
            "INSERT INTO agent_notes (agent, day, text, priority, refs_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (agent, day.isoformat(), text, priority, json.dumps(refs, ensure_ascii=False), to_iso(now)),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def notes(self, agent: str | None, since_day: date, limit: int | None = None) -> list[AgentNote]:
        sql = f"SELECT {_NOTE_COLS} FROM agent_notes WHERE day >= ?"
        args: list[object] = [since_day.isoformat()]
        if agent is not None:
            sql += " AND agent = ?"
            args.append(agent)
        sql += " ORDER BY day DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [_note(r) for r in self.conn.execute(sql, args).fetchall()]

    def handoffs_on(self, agent: str, day: date) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM agent_notes WHERE agent = ? AND day = ? AND priority = 3", (agent, day.isoformat())
        ).fetchone()[0]

    def brief_candidates(self, today: date) -> list[AgentNote]:
        rows = self.conn.execute(
            f"SELECT {_NOTE_COLS} FROM agent_notes WHERE shown_at IS NULL AND priority IN (1, 2) AND day >= ? "
            "ORDER BY priority, created_at, id",
            ((today - timedelta(days=2)).isoformat(),),
        ).fetchall()
        return [_note(r) for r in rows]

    def mark_shown(self, ids: Iterable[int], now: datetime) -> int:
        xs = list(ids)
        if not xs:
            return 0
        cur = self.conn.execute(
            f"UPDATE agent_notes SET shown_at = ? WHERE shown_at IS NULL AND id IN ({_qs(len(xs))})",
            (to_iso(now), *xs),
        )
        return cur.rowcount

    # --- 보관 ---

    def prune(self, today: date, now: datetime) -> dict[str, int]:
        seen = self.conn.execute(
            "DELETE FROM agent_inbox WHERE seen_at IS NOT NULL AND seen_at < ?",
            (to_iso(now - timedelta(days=INBOX_SEEN_KEEP_DAYS)),),
        ).rowcount
        events = self.conn.execute(
            "DELETE FROM agent_events WHERE day < ?", ((today - timedelta(days=EVENTS_KEEP_DAYS)).isoformat(),)
        ).rowcount
        notes = self.conn.execute(
            "DELETE FROM agent_notes WHERE day < ?", ((today - timedelta(days=NOTES_KEEP_DAYS)).isoformat(),)
        ).rowcount
        return {"events": events, "inbox": seen, "notes": notes}

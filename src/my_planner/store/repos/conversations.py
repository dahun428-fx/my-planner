"""conversations 표와 conversation_sessions 표 (SP9 스펙 7.1).

제목·요약은 앱 통로 대화에만 붙는다(7.2). 지운 대화(`deleted_at`)는 목록·검색·`find_conversations`에서 빠진다(7.7).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.domain import Channel, ConversationKind
from my_planner.store.db import transaction


@dataclass
class Conversation:
    id: int
    kind: ConversationKind
    run_id: int | None
    session_id: str | None
    logical_date: date
    opened_at: datetime
    last_message_at: datetime
    closed_at: datetime | None
    channel: str = "telegram"  # 'telegram' | 'app' (SP3-4 5.1)
    forked_from: int | None = None
    # SP9 7.1: 제목(20자)·요약(600자, 짧은 대화는 '')·요약이 덮는 마지막 시각, 사용자 메시지 수(말아 넣기), 지운 시각
    title: str | None = None
    summary: str | None = None
    summary_through: datetime | None = None
    user_messages: int = 0
    deleted_at: datetime | None = None
    continued_from: int | None = None  # 지난 대화를 골라 새로 연 `chat`이면 그 대화(7.3)


def _row(r: sqlite3.Row) -> Conversation:
    return Conversation(
        id=r["id"],
        kind=ConversationKind(r["kind"]),
        run_id=r["run_id"],
        session_id=r["session_id"],
        logical_date=date.fromisoformat(r["logical_date"]),
        opened_at=from_iso(r["opened_at"]),
        last_message_at=from_iso(r["last_message_at"]),
        closed_at=from_iso(r["closed_at"]) if r["closed_at"] else None,
        channel=r["channel"],
        forked_from=r["forked_from"],
        title=r["title"],
        summary=r["summary"],
        summary_through=from_iso(r["summary_through"]) if r["summary_through"] else None,
        user_messages=r["user_messages"],
        deleted_at=from_iso(r["deleted_at"]) if r["deleted_at"] else None,
        continued_from=r["continued_from"],
    )


TRIGRAM_MIN = 3  # trigram 토크나이저는 3글자부터. 그보다 짧은 검색어는 LIKE(메모와 같다, 6.1)


def _fts_phrase(q: str) -> str:
    """검색어를 FTS5 구문 하나로(따옴표는 두 번). 연산자로 읽히지 않는다."""
    return '"' + q.replace('"', '""') + '"'


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class ConversationsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def open(
        self, kind: ConversationKind | str, logical_date: date, run_id: int | None = None, *,
        channel: Channel = "telegram", forked_from: int | None = None, continued_from: int | None = None,
    ) -> Conversation:
        """`forked_from`: 다른 통로의 회차 대화를 갈라 연 대화면 그 원래 대화(SP3-4 7.2 가르기).

        `continued_from`: 지난 대화(계획, 창이 지난 회차)를 골라 새로 연 `chat`이면 그 대화(SP9 7.3)."""
        now = to_iso(self.clock.now())
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO conversations (kind, run_id, logical_date, opened_at, last_message_at, channel, "
                "forked_from, continued_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ConversationKind(kind).value, run_id, logical_date.isoformat(), now, now, channel, forked_from,
                 continued_from),
            )
        conv = self.get(cur.lastrowid)
        assert conv is not None
        return conv

    def get(self, id: int) -> Conversation | None:
        r = self.conn.execute("SELECT * FROM conversations WHERE id = ?", (id,)).fetchone()
        return _row(r) if r is not None else None

    def touch(self, id: int) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET last_message_at = ? WHERE id = ?",
                (to_iso(self.clock.now()), id),
            )

    def set_session(self, id: int, session_id: str | None) -> None:
        """새 세션 id면 `conversation_sessions`에도 한 행(7.1: 지우기가 그 대화의 세션 파일을 모두 지운다)."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET session_id = ? WHERE id = ?", (session_id, id)
            )
            if session_id:
                self.add_session(id, session_id, self.clock.now())

    def add_session(self, id: int, session_id: str, at: datetime) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO conversation_sessions (conversation_id, session_id, started_at) VALUES (?, ?, ?)",
                (id, session_id, to_iso(at)),
            )

    def sessions(self, id: int) -> list[str]:
        """그 대화에 생긴 두뇌 세션 id 모두(시작 순)."""
        rows = self.conn.execute(
            "SELECT session_id FROM conversation_sessions WHERE conversation_id = ? ORDER BY started_at, rowid",
            (id,),
        ).fetchall()
        return [r["session_id"] for r in rows]

    def bump_user_messages(self, id: int) -> int:
        """사용자 메시지 수를 1 올리고 새 값을 돌려준다(말아 넣기, 7.4)."""
        with transaction(self.conn):
            self.conn.execute("UPDATE conversations SET user_messages = user_messages + 1 WHERE id = ?", (id,))
        r = self.conn.execute("SELECT user_messages FROM conversations WHERE id = ?", (id,)).fetchone()
        return int(r["user_messages"]) if r is not None else 0

    def reset_session(self, id: int) -> None:
        """말아 넣기(7.4): 세션을 비우고 사용자 메시지 수를 1(이번 메시지)로. 옛 세션 id는 `conversation_sessions`에 남는다."""
        with transaction(self.conn):
            self.conn.execute("UPDATE conversations SET session_id = NULL, user_messages = 1 WHERE id = ?", (id,))

    def set_summary(self, id: int, title: str | None, summary: str | None, through: datetime | None) -> None:
        """제목·요약·요약이 덮는 마지막 시각(7.2). 지운 대화는 바꾸지 않는다."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET title = ?, summary = ?, summary_through = ? WHERE id = ? AND deleted_at IS NULL",
                (title, summary, to_iso(through) if through is not None else None, id),
            )

    def reopen(self, id: int, at: datetime) -> None:
        """닫힌 대화를 다시 연다(목록에서 고른 `chat`, 7.3)."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET closed_at = NULL, last_message_at = ? WHERE id = ? AND deleted_at IS NULL",
                (to_iso(at), id),
            )

    def delete(self, id: int, at: datetime) -> bool:
        """지운다(7.7): 열려 있으면 닫고, `deleted_at`을 채우고 제목·요약을 비운다. 처음 지웠으면 True."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE conversations SET closed_at = COALESCE(closed_at, ?), deleted_at = ?, title = NULL, "
                "summary = NULL, summary_through = NULL WHERE id = ? AND deleted_at IS NULL",
                (to_iso(at), to_iso(at), id),
            )
        return cur.rowcount > 0

    def deleted_since(self, since: datetime) -> list[Conversation]:
        """`since` 뒤에 지운 대화, 지운 순(7.7 하루 한 번 원문 다시 지우기)."""
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE deleted_at IS NOT NULL AND deleted_at >= ? ORDER BY deleted_at, id",
            (to_iso(since),),
        ).fetchall()
        return [_row(r) for r in rows]

    def summary_pending(self) -> list[int]:
        """요약할 닫힌 앱 대화(7.2), 닫힌 순: 아직 제목도 요약도 없는 것, 그리고 요약 뒤에 말이 더 있는 것(다시 연
        대화, 말아 넣기 뒤 이어진 대화. 스펙 7.2 "닫힐 때", 티켓 SP9-09 결정)."""
        rows = self.conn.execute(
            "SELECT id FROM conversations WHERE closed_at IS NOT NULL AND deleted_at IS NULL AND channel = 'app' "
            "AND ((summary IS NULL AND title IS NULL) "
            "OR (summary IS NOT NULL AND summary_through IS NOT NULL AND summary_through < last_message_at)) "
            "ORDER BY closed_at, id"
        ).fetchall()
        return [r["id"] for r in rows]

    def open_app_runs_unsummarized(self) -> list[Conversation]:
        """제목이 아직 없는 열린 앱 회차 대화. 회차 대화는 닫히지 않으므로(SP1) 답장 창이 끝났는지는 라우터가 본다."""
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = 'run' AND channel = 'app' AND closed_at IS NULL "
            "AND deleted_at IS NULL AND title IS NULL ORDER BY id"
        ).fetchall()
        return [_row(r) for r in rows]

    def summary_retry(self, since: datetime) -> list[int]:
        """하루 한 번 다시 해 볼 것(7.2): `since` 뒤에 말이 있었던 닫힌 앱 대화(와 앱 회차 대화, 창이 끝났는지는
        디스패처가 본다) 가운데 요약이 없는 것(대체 제목뿐)."""
        rows = self.conn.execute(
            "SELECT id FROM conversations WHERE (closed_at IS NOT NULL OR kind = 'run') AND deleted_at IS NULL "
            "AND channel = 'app' AND summary IS NULL AND last_message_at >= ? ORDER BY id",
            (to_iso(since),),
        ).fetchall()
        return [r["id"] for r in rows]

    def set_channel(self, id: int, channel: Channel) -> None:
        """대화의 통로를 바꾼다(회차 대화는 전체 본문을 받은 통로에 둔다, 7.3 D5)."""
        with transaction(self.conn):
            self.conn.execute("UPDATE conversations SET channel = ? WHERE id = ?", (channel, id))

    def close(self, id: int) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE conversations SET closed_at = ? WHERE id = ? AND closed_at IS NULL",
                (to_iso(self.clock.now()), id),
            )

    def latest_open_run_opened_by(self, at: datetime) -> Conversation | None:
        """`at`(보낸 시각) 이전에 열린 열린 `run` 대화 가운데 가장 최근 것. 통로와 상관없다(SP3-4 7.2 규칙 3).

        갈라 연 대화(`forked_from`)는 보지 않는다: 회차를 보낸 때 연 원래 대화만 "가장 최근에 보낸 회차"를 가리킨다.
        """
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = 'run' AND closed_at IS NULL AND forked_from IS NULL "
            "AND opened_at <= ? "
            "ORDER BY opened_at DESC, id DESC LIMIT 1",
            (to_iso(at),),
        ).fetchone()
        return _row(r) if r is not None else None

    def latest_open(self, kind: ConversationKind | str, channel: Channel = "telegram") -> Conversation | None:
        """그 통로의 열린 대화 가운데 마지막 메시지가 가장 최근인 것(SP3-4 7.1: 통로마다 따로)."""
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = ? AND channel = ? AND closed_at IS NULL "
            "ORDER BY last_message_at DESC, id DESC LIMIT 1",
            (ConversationKind(kind).value, channel),
        ).fetchone()
        return _row(r) if r is not None else None

    def latest_follow(self, conversation_id: int) -> Conversation | None:
        """그 대화를 이어 가는(`continued_from`) 앱 `chat` 가운데 가장 나중에 연 것. 열림·닫힘 상관없이, 지운 것은 빼고(SP9 7.3)."""
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = 'chat' AND channel = 'app' AND continued_from = ? "
            "AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return _row(r) if r is not None else None

    def run_conversation(self, run_id: int, channel: Channel) -> Conversation | None:
        """그 회차의 그 통로 쪽 열린 회차 대화(7.2). 여럿이면 가장 나중에 연 것."""
        r = self.conn.execute(
            "SELECT * FROM conversations WHERE kind = 'run' AND run_id = ? AND channel = ? AND closed_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (run_id, channel),
        ).fetchone()
        return _row(r) if r is not None else None

    def recent(
        self, *, channel: str | None = None, limit: int = 20, q: str | None = None,
        before: tuple[datetime, int] | None = None, closed_only: bool = False, since: datetime | None = None,
    ) -> list[Conversation]:
        """마지막 메시지가 최근인 것부터, 지운 대화는 뺀다(7.6). `channel`을 주면 그 통로 대화만.

        `q`: 제목·요약 검색(3글자 이상 trigram, 미만 LIKE). `before`: (`last_message_at`, `id`) 커서(쪽 넘기기).
        `closed_only`, `since`: `find_conversations`(7.5)의 닫힌 대화, 그 시각 뒤에 말이 있었던 것.
        """
        where: list[str] = ["deleted_at IS NULL"]
        args: list[object] = []
        if channel is not None:
            where.append("channel = ?")
            args.append(channel)
        if q is not None and q.strip():
            q = q.strip()
            if len(q) >= TRIGRAM_MIN:
                where.append("id IN (SELECT rowid FROM conversations_fts WHERE conversations_fts MATCH ?)")
                args.append(_fts_phrase(q))
            else:
                where.append("(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')")
                args += [_like(q), _like(q)]
        if before is not None:
            at = to_iso(before[0])
            where.append("(last_message_at < ? OR (last_message_at = ? AND id < ?))")
            args += [at, at, before[1]]
        if closed_only:  # 닫힌 대화, 그리고 답장 창이 끝나 요약한 회차 대화(회차 대화는 닫히지 않는다)
            where.append("(closed_at IS NOT NULL OR (kind = 'run' AND title IS NOT NULL))")
        if since is not None:
            where.append("last_message_at >= ?")
            args.append(to_iso(since))
        rows = self.conn.execute(
            f"SELECT * FROM conversations WHERE {' AND '.join(where)} ORDER BY last_message_at DESC, id DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
        return [_row(r) for r in rows]

    def for_run(self, run_id: int) -> list[Conversation]:
        """그 회차에 붙은 대화(통로마다 있을 수 있다), id 순."""
        rows = self.conn.execute("SELECT * FROM conversations WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [_row(r) for r in rows]

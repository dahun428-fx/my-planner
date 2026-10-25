"""memos 표와 memos_fts 색인 (SP9 스펙 6.1). 시각은 UTC ISO 8601.

메모 본문은 이 표(와 그 색인), 하루 한 번 내보내기 `data/exports/memos.md`에만 둔다. 이 모듈은 로그를 남기지 않는다.
지운 메모(`deleted_at`)는 읽기·검색에서 빠지고, 30일 뒤 하루 한 번 작업이 `purge_deleted`로 완전히 지운다.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.domain import Area
from my_planner.store.db import transaction

MemoOrigin = Literal["user", "chat"]

TITLE_MAX = 40  # 제목 = 첫 줄 서식 뺀 앞 40자(6.1). 따로 저장하지 않는다
UNTITLED = "제목 없는 메모"  # Review Focus 4
TRIGRAM_MIN = 3  # trigram 토크나이저는 3글자부터. 그보다 짧은 검색어는 LIKE(6.1)

# 제목에서 빼는 서식(6.1): 줄 앞의 `#`, 체크박스 `- [ ]`/`- [x]`, 목록 `- `, 그리고 줄 어디의 `**`.
# `-` 뒤가 공백이나 줄 끝일 때만 목록 기호다("-5도"는 그대로)
_HEADING = re.compile(r"^#+\s*")
_CHECKBOX = re.compile(r"^-\s*\[[ xX]\](\s+|$)")
_BULLET = re.compile(r"^-(\s+|$)")


def _plain_line(line: str) -> str:
    s = _HEADING.sub("", line.strip())
    s = _CHECKBOX.sub("", s)
    s = _BULLET.sub("", s)
    return s.replace("**", "").strip()


def memo_title(body: str) -> str:
    """본문에서 서식을 뺀 첫 비지 않은 줄의 앞 40자. 그런 줄이 없으면 "제목 없는 메모"(Review Focus 4)."""
    for line in body.splitlines():
        s = _plain_line(line)
        if s:
            return s[:TITLE_MAX]
    return UNTITLED


def memo_preview(body: str, n: int) -> str:
    """제목 줄 다음부터 서식을 뺀 줄들을 공백 하나로 이은 앞 `n`자(목록 둘째 줄, 6.4). 제목뿐이면 빈 문자열."""
    lines = [s for s in (_plain_line(x) for x in body.splitlines()) if s]
    return " ".join(lines[1:])[:n]


@dataclass(frozen=True)
class Memo:
    id: int
    body: str
    area: Area | None
    pinned: bool
    origin: MemoOrigin
    created_at: datetime
    updated_at: datetime


class MemoConflict(Exception):
    """`update`의 `expected_updated_at`이 지금 값과 다르다(다른 기기에서 먼저 고쳤다, 6.4 `409 memo_conflict`)."""


def _memo(r: sqlite3.Row) -> Memo:
    return Memo(
        id=r["id"],
        body=r["body"],
        area=Area(r["area"]) if r["area"] is not None else None,
        pinned=r["pinned_at"] is not None,
        origin=r["origin"],
        created_at=from_iso(r["created_at"]),
        updated_at=from_iso(r["updated_at"]),
    )


def _area(area: Area | str | None) -> str | None:
    return Area(area).value if area is not None else None


def _fts_phrase(q: str) -> str:
    """검색어 전체를 FTS 구 하나로(따옴표, AND·OR 같은 문법 글자를 글자 그대로)."""
    return '"' + q.replace('"', '""') + '"'


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class MemosRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # --- 읽기 ---

    def get(self, id: int) -> Memo | None:
        """살아 있는 메모. 지운 메모는 없는 메모다."""
        r = self.conn.execute("SELECT * FROM memos WHERE id = ? AND deleted_at IS NULL", (id,)).fetchone()
        return _memo(r) if r else None

    def count_live(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM memos WHERE deleted_at IS NULL").fetchone()[0]

    def count_pinned(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM memos WHERE deleted_at IS NULL AND pinned_at IS NOT NULL"
        ).fetchone()[0]

    def all_live(self) -> list[Memo]:
        """내보내기용: 살아 있는 메모 전부, 고정 먼저 그다음 고친 시각 최근순."""
        rows = self.conn.execute(
            "SELECT * FROM memos WHERE deleted_at IS NULL "
            "ORDER BY pinned_at IS NULL, updated_at DESC, id DESC"
        ).fetchall()
        return [_memo(r) for r in rows]

    def _match(self, q: str | None) -> tuple[str, list[object]]:
        """검색 조건(살아 있는 메모만). 3글자 이상은 trigram 색인, 미만은 LIKE(6.1)."""
        if q is None or not q.strip():
            return "m.deleted_at IS NULL", []
        q = q.strip()
        if len(q) >= TRIGRAM_MIN:
            return (
                "m.deleted_at IS NULL AND m.id IN (SELECT rowid FROM memos_fts WHERE memos_fts MATCH ?)",
                [_fts_phrase(q)],
            )
        return "m.deleted_at IS NULL AND m.body LIKE ? ESCAPE '\\'", [_like(q)]

    def list(
        self, q: str | None = None, limit: int = 50, before: tuple[datetime, int] | None = None
    ) -> list[Memo]:
        """첫 쪽(`before` 없음)은 고정 메모 전부(고친 시각 최근순) + 고정 아닌 메모 `limit`개(고친 시각 최근순).

        `before`는 고정 아닌 메모의 (`updated_at`, `id`) 커서다. 다음 쪽에는 고정 메모가 다시 나오지 않는다.
        `limit`은 고정 아닌 메모에만 센다(고정은 10개까지라 첫 쪽이 그만큼 길어질 수 있다).
        """
        where, args = self._match(q)
        pinned: list[Memo] = []
        if before is None:
            rows = self.conn.execute(
                f"SELECT m.* FROM memos m WHERE {where} AND m.pinned_at IS NOT NULL "
                "ORDER BY m.updated_at DESC, m.id DESC",
                args,
            ).fetchall()
            pinned = [_memo(r) for r in rows]
            cursor_sql, cursor_args = "", []
        else:
            at = to_iso(before[0])
            cursor_sql, cursor_args = " AND (m.updated_at < ? OR (m.updated_at = ? AND m.id < ?))", [at, at, before[1]]
        rows = self.conn.execute(
            f"SELECT m.* FROM memos m WHERE {where} AND m.pinned_at IS NULL{cursor_sql} "
            "ORDER BY m.updated_at DESC, m.id DESC LIMIT ?",
            [*args, *cursor_args, limit],
        ).fetchall()
        return pinned + [_memo(r) for r in rows]

    def search(self, q: str, limit: int) -> list[Memo]:
        """검색어가 든 살아 있는 메모, 고친 시각 최근순(고정 여부는 보지 않는다). 빈 검색어는 빈 목록."""
        if not q or not q.strip():
            return []
        where, args = self._match(q)
        rows = self.conn.execute(
            f"SELECT m.* FROM memos m WHERE {where} ORDER BY m.updated_at DESC, m.id DESC LIMIT ?", [*args, limit]
        ).fetchall()
        return [_memo(r) for r in rows]

    # --- 쓰기 (`transaction`: 바깥 트랜잭션에 합류하고, 혼자 부르면 커밋한다. 상한은 부르는 쪽이 본다) ---

    def create(self, body: str, area: Area | str | None, origin: MemoOrigin, now: datetime) -> Memo:
        at = to_iso(now)
        with transaction(self.conn):
            mid = self.conn.execute(
                "INSERT INTO memos (body, area, origin, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (body, _area(area), origin, at, at),
            ).lastrowid
        got = self.get(int(mid))  # type: ignore[arg-type]
        assert got is not None
        return got

    def update(
        self, id: int, body: str, area: Area | str | None, expected_updated_at: datetime, now: datetime
    ) -> Memo:
        """본문과 영역을 통째로 바꾼다. 살아 있는 메모의 `updated_at`이 `expected_updated_at`과 다르면 `MemoConflict`."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE memos SET body = ?, area = ?, updated_at = ? "
                "WHERE id = ? AND deleted_at IS NULL AND updated_at = ?",
                (body, _area(area), to_iso(now), id, to_iso(expected_updated_at)),
            )
        if cur.rowcount != 1:
            raise MemoConflict(id)
        got = self.get(id)
        assert got is not None
        return got

    def pinned_at(self, id: int) -> datetime | None:
        r = self.conn.execute("SELECT pinned_at FROM memos WHERE id = ?", (id,)).fetchone()
        return from_iso(r[0]) if r and r[0] else None

    def pin(self, id: int, now: datetime) -> None:
        """고정(고친 시각은 그대로: 고정은 고치기가 아니다)."""
        with transaction(self.conn):
            self.conn.execute("UPDATE memos SET pinned_at = ? WHERE id = ? AND deleted_at IS NULL", (to_iso(now), id))

    def unpin(self, id: int) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE memos SET pinned_at = NULL WHERE id = ? AND deleted_at IS NULL", (id,))

    def delete(self, id: int, now: datetime) -> None:
        """소프트 삭제(색인에서 빠진다). 30일 동안은 `restore`로 되살릴 수 있다."""
        with transaction(self.conn):
            self.conn.execute("UPDATE memos SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (to_iso(now), id))

    def restore(self, id: int, *, unpin: bool = False) -> bool:
        """지운 메모를 되살린다(색인에 다시 들어간다). `unpin`이면 고정을 풀고 되살린다. 완전히 지워졌으면 False."""
        pinned = "NULL" if unpin else "pinned_at"
        with transaction(self.conn):
            cur = self.conn.execute(
                f"UPDATE memos SET deleted_at = NULL, pinned_at = {pinned} WHERE id = ? AND deleted_at IS NOT NULL", (id,)
            )
        return cur.rowcount == 1

    def purge_deleted(self, older_than: datetime) -> int:
        """`older_than`보다 먼저 지운 메모를 완전히 지운다(6.1 30일 보관). 지운 개수."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "DELETE FROM memos WHERE deleted_at IS NOT NULL AND deleted_at < ?", (to_iso(older_than),)
            )
        return cur.rowcount

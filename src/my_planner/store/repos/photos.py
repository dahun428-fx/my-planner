"""photos·memo_photos·message_photos 표 (SP10 스펙 5.1). 시각은 UTC ISO 8601.

연결(`conn`)을 메서드마다 받는다: 쓰기는 즉시 갈래의 연결, 읽기는 읽기 전용 연결(`mode=ro`)에서도 같은 함수를 쓴다.
쓰기는 `transaction`으로 바깥 트랜잭션에 합류한다. 이 모듈은 로그를 남기지 않는다(경로·읽기 결과가 로그에 가지 않게).

- 위치: 붙일 때 비어 있는 가장 작은 위치(0~9). 10장이면 `TooManyPhotos`.
- 한 사진은 한 메모에만(`memo_photos.photo_id UNIQUE`): 다른 메모에 붙어 있으면 `PhotoInUse`.
- 살아 있는 사진(`is_live`): 살아 있는 메모에 붙었거나 지우지 않은 대화의 메시지에 붙은 사진. 따로 `deleted_at`은 없다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

from my_planner.clock import from_iso, to_iso
from my_planner.store.db import transaction

PhotoOrigin = Literal["memo", "chat"]

MEMO_PHOTOS_MAX = 10  # 메모당(5.1)
READ_TEXT_MAX = 8000  # `photos.read_text` CHECK(5.1), 사진 읽기 출력 자르기(5.4)
KEEP_DAYS = 30  # 연결 없는 사진 보관(5.6 1번)


@dataclass(frozen=True)
class Photo:
    id: int
    sha256: str
    path: str
    thumb_path: str
    bytes: int
    width: int
    height: int
    origin: PhotoOrigin
    read_text: str | None
    created_at: datetime
    unlinked_at: datetime | None


class TooManyPhotos(Exception):
    """메모에 이미 10장이 붙어 있다(422 `too_many_photos`)."""


class PhotoInUse(Exception):
    """다른 메모에 이미 붙은 사진이다(409 `photo_in_use`)."""


def _photo(r: sqlite3.Row) -> Photo:
    return Photo(
        id=r["id"], sha256=r["sha256"], path=r["path"], thumb_path=r["thumb_path"], bytes=r["bytes"],
        width=r["width"], height=r["height"], origin=r["origin"], read_text=r["read_text"],
        created_at=from_iso(r["created_at"]),
        unlinked_at=from_iso(r["unlinked_at"]) if r["unlinked_at"] is not None else None,
    )


# 살아 있는 사진(5.1). `p`는 photos 별칭
_LIVE = (
    "(EXISTS (SELECT 1 FROM memo_photos mp JOIN memos m ON m.id = mp.memo_id "
    "WHERE mp.photo_id = p.id AND m.deleted_at IS NULL) "
    "OR EXISTS (SELECT 1 FROM message_photos xp JOIN conversations c ON c.id = xp.conversation_id "
    "WHERE xp.photo_id = p.id AND c.deleted_at IS NULL))"
)


class PhotosRepo:
    def __init__(self, tz: str | tzinfo, boundary: time) -> None:
        self.tz = ZoneInfo(tz) if isinstance(tz, str) else tz
        self.boundary = boundary  # 논리적 날짜 경계(`uploaded_on`)

    # --- 읽기 ---

    def get(self, conn: sqlite3.Connection, photo_id: int) -> Photo | None:
        """행이 있으면 살아 있든 아니든 돌려준다. 보일지는 `is_live`로 본다."""
        r = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return _photo(r) if r else None

    def is_live(self, conn: sqlite3.Connection, photo_id: int) -> bool:
        return conn.execute(f"SELECT 1 FROM photos p WHERE p.id = ? AND {_LIVE}", (photo_id,)).fetchone() is not None

    def is_readable(self, conn: sqlite3.Connection, photo_id: int) -> bool:
        """사진 읽기(SP10 5.4)를 할 수 있나: 살아 있거나, 아직 어디에도 붙지 않은 새 사진(새 메모의 사진은 저장 때
        `create_memo`로 붙는다, 7.1). 빼고 되돌리기를 기다리는 사진·지운 메모·지운 대화의 사진은 아니다."""
        return conn.execute(
            f"SELECT 1 FROM photos p WHERE p.id = ? AND ({_LIVE} OR (p.unlinked_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM memo_photos a WHERE a.photo_id = p.id) "
            "AND NOT EXISTS (SELECT 1 FROM message_photos b WHERE b.photo_id = p.id)))",
            (photo_id,),
        ).fetchone() is not None

    def memo_of(self, conn: sqlite3.Connection, photo_id: int) -> tuple[int, int] | None:
        """붙은 메모(지운 메모 포함)의 (메모 id, 위치). 없으면 None."""
        r = conn.execute("SELECT memo_id, position FROM memo_photos WHERE photo_id = ?", (photo_id,)).fetchone()
        return (r[0], r[1]) if r else None

    def on_message(self, conn: sqlite3.Connection, photo_id: int) -> bool:
        return conn.execute("SELECT 1 FROM message_photos WHERE photo_id = ?", (photo_id,)).fetchone() is not None

    def for_memo(self, conn: sqlite3.Connection, memo_id: int) -> list[Photo]:
        """위치 순."""
        rows = conn.execute(
            "SELECT p.* FROM memo_photos mp JOIN photos p ON p.id = mp.photo_id WHERE mp.memo_id = ? "
            "ORDER BY mp.position", (memo_id,),
        ).fetchall()
        return [_photo(r) for r in rows]

    def first_for_memos(self, conn: sqlite3.Connection, memo_ids: list[int]) -> dict[int, Photo]:
        """메모마다 가장 앞 위치의 사진 하나(`GET /memos` 목록, SP10 5.3). 사진이 없는 메모는 빠진다."""
        if not memo_ids:
            return {}
        marks = ",".join("?" * len(memo_ids))
        rows = conn.execute(
            f"SELECT mp.memo_id AS memo_id, p.* FROM memo_photos mp JOIN photos p ON p.id = mp.photo_id "
            f"WHERE mp.memo_id IN ({marks}) AND mp.position = "
            "(SELECT MIN(position) FROM memo_photos f WHERE f.memo_id = mp.memo_id)",
            memo_ids,
        ).fetchall()
        return {r["memo_id"]: _photo(r) for r in rows}

    def for_message(self, conn: sqlite3.Connection, inbound_id: int) -> list[Photo]:
        """보낸 순서(연결을 넣은 순서, `rowid`). 다시 보내기·시작 때 다시 넣기가 처음과 같은 입력을 만든다(5.5)."""
        rows = conn.execute(
            "SELECT p.* FROM message_photos xp JOIN photos p ON p.id = xp.photo_id WHERE xp.inbound_id = ? "
            "ORDER BY xp.rowid", (inbound_id,),
        ).fetchall()
        return [_photo(r) for r in rows]

    def in_conversation(self, conn: sqlite3.Connection, conversation_id: int, photo_ids: list[int]) -> bool:
        """모든 사진이 그 대화의 메시지에 붙어 있는가."""
        ids = set(photo_ids)
        if not ids:
            return True
        marks = ",".join("?" * len(ids))
        n = conn.execute(
            f"SELECT COUNT(*) FROM message_photos WHERE conversation_id = ? AND photo_id IN ({marks})",
            (conversation_id, *ids),
        ).fetchone()[0]
        return n == len(ids)

    def for_conversation(self, conn: sqlite3.Connection, conversation_id: int) -> dict[int, list[Photo]]:
        """그 대화의 받은 메시지마다 붙은 사진(`{inbound_id: [Photo…]}`, 보낸 순서). 메시지 목록의 `photos`(5.3)."""
        rows = conn.execute(
            "SELECT xp.inbound_id AS inbound_id, p.* FROM message_photos xp JOIN photos p ON p.id = xp.photo_id "
            "WHERE xp.conversation_id = ? ORDER BY xp.rowid",
            (conversation_id,),
        ).fetchall()
        out: dict[int, list[Photo]] = {}
        for r in rows:
            out.setdefault(r["inbound_id"], []).append(_photo(r))
        return out

    def free_chat_photo(self, conn: sqlite3.Connection, photo_id: int) -> bool:
        """채팅 `data-photo`(5.5)로 받을 수 있나: `origin = 'chat'`이고 아직 어느 메시지에도 메모에도 붙지 않았다."""
        return conn.execute(
            "SELECT 1 FROM photos p WHERE p.id = ? AND p.origin = 'chat' "
            "AND NOT EXISTS (SELECT 1 FROM memo_photos a WHERE a.photo_id = p.id) "
            "AND NOT EXISTS (SELECT 1 FROM message_photos b WHERE b.photo_id = p.id)",
            (photo_id,),
        ).fetchone() is not None

    def purgeable(self, conn: sqlite3.Connection, now: datetime) -> list[Photo]:
        """완전히 지울 사진(5.6 1번): 메모 연결이 없고, 메시지 연결이 없거나 그 대화가 지워졌고, `created_at`과
        `unlinked_at`(있으면) 모두 30일보다 오래됐다."""
        cutoff = to_iso(now - timedelta(days=KEEP_DAYS))
        rows = conn.execute(
            "SELECT p.* FROM photos p WHERE NOT EXISTS (SELECT 1 FROM memo_photos mp WHERE mp.photo_id = p.id) "
            "AND NOT EXISTS (SELECT 1 FROM message_photos xp JOIN conversations c ON c.id = xp.conversation_id "
            "WHERE xp.photo_id = p.id AND c.deleted_at IS NULL) "
            "AND p.created_at < ? AND (p.unlinked_at IS NULL OR p.unlinked_at < ?) ORDER BY p.id",
            (cutoff, cutoff),
        ).fetchall()
        return [_photo(r) for r in rows]

    def file_rows(self, conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
        """모든 행의 (id, 큰 사진 경로, 작은 사진 경로). 하루 한 번 작업의 없는 파일·고아 파일 찾기(5.6 2·3번)."""
        return [(r[0], r[1], r[2]) for r in conn.execute("SELECT id, path, thumb_path FROM photos ORDER BY id")]

    def uploaded_on(self, conn: sqlite3.Connection, logical_day: date) -> int:
        """그 논리적 날짜(경계 04:00)에 올린 사진 수(하루 100장, 5.1)."""
        start = datetime.combine(logical_day, self.boundary, self.tz)
        end = datetime.combine(logical_day + timedelta(days=1), self.boundary, self.tz)
        return conn.execute(
            "SELECT COUNT(*) FROM photos WHERE created_at >= ? AND created_at < ?", (to_iso(start), to_iso(end))
        ).fetchone()[0]

    # --- 쓰기 ---

    def insert(
        self, conn: sqlite3.Connection, *, sha256: str, path: str, thumb_path: str, bytes: int, width: int,
        height: int, origin: str, now: datetime,
    ) -> Photo:
        with transaction(conn):
            pid = conn.execute(
                "INSERT INTO photos (sha256, path, thumb_path, bytes, width, height, origin, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sha256, path, thumb_path, bytes, width, height, origin, to_iso(now)),
            ).lastrowid
        got = self.get(conn, int(pid))  # type: ignore[arg-type]
        assert got is not None
        return got

    def set_paths(self, conn: sqlite3.Connection, photo_id: int, path: str, thumb_path: str) -> None:
        """`store_photo`: id를 받은 뒤 최종 경로로(5.2 2번)."""
        with transaction(conn):
            conn.execute("UPDATE photos SET path = ?, thumb_path = ? WHERE id = ?", (path, thumb_path, photo_id))

    def free_position(self, conn: sqlite3.Connection, memo_id: int) -> int | None:
        """비어 있는 가장 작은 위치(0~9). 다 찼으면 None."""
        taken = {r[0] for r in conn.execute("SELECT position FROM memo_photos WHERE memo_id = ?", (memo_id,))}
        return next((i for i in range(MEMO_PHOTOS_MAX) if i not in taken), None)

    def attach(self, conn: sqlite3.Connection, memo_id: int, photo_id: int, *, position: int | None = None) -> int:
        """메모에 붙이고 위치를 돌려준다. 이미 그 메모에 있으면 그 위치. `position`이 비어 있으면 그 자리(되돌리기),
        아니면 가장 작은 빈 자리. 다른 메모에 붙어 있으면 `PhotoInUse`, 10장이면 `TooManyPhotos`.
        `unlinked_at`을 지운다. `memos.updated_at`은 바꾸지 않는다(5.3)."""
        at = self.memo_of(conn, photo_id)
        if at is not None:
            if at[0] != memo_id:
                raise PhotoInUse(photo_id)
            return at[1]
        taken = {r[0] for r in conn.execute("SELECT position FROM memo_photos WHERE memo_id = ?", (memo_id,))}
        if position is None or position in taken:
            position = self.free_position(conn, memo_id)
        if position is None:
            raise TooManyPhotos(memo_id)
        with transaction(conn):
            conn.execute(
                "INSERT INTO memo_photos (memo_id, photo_id, position) VALUES (?, ?, ?)", (memo_id, photo_id, position)
            )
            conn.execute("UPDATE photos SET unlinked_at = NULL WHERE id = ?", (photo_id,))
        return position

    def detach(self, conn: sqlite3.Connection, memo_id: int, photo_id: int, now: datetime) -> None:
        """연결을 끊고 `unlinked_at = now`(5.6 1번의 30일은 여기서 센다)."""
        with transaction(conn):
            cur = conn.execute("DELETE FROM memo_photos WHERE memo_id = ? AND photo_id = ?", (memo_id, photo_id))
            if cur.rowcount:
                conn.execute("UPDATE photos SET unlinked_at = ? WHERE id = ?", (to_iso(now), photo_id))

    def link_message(self, conn: sqlite3.Connection, inbound_id: int, conversation_id: int, photo_ids: list[int]) -> None:
        """받은 메시지에 사진을 잇는다(5.5). 같은 연결은 다시 넣지 않는다(INSERT OR IGNORE)."""
        link_message_rows(conn, inbound_id, conversation_id, photo_ids)

    def move_message(self, conn: sqlite3.Connection, inbound_id: int, conversation_id: int) -> None:
        """받을 때 고른 대화가 처리 전에 닫혀 다시 골랐다(SP3-4 M3): 그 메시지의 사진도 새 대화로(5.5 "이번 대화")."""
        with transaction(conn):
            conn.execute(
                "UPDATE message_photos SET conversation_id = ? WHERE inbound_id = ?", (conversation_id, inbound_id)
            )

    def unlink_conversation(self, conn: sqlite3.Connection, conversation_id: int) -> int:
        """대화 지우기(SP9 7.7, SP10 5.5): 그 대화의 `message_photos`를 지운다. 메모 연결은 그대로. 지운 행 수."""
        with transaction(conn):
            return conn.execute("DELETE FROM message_photos WHERE conversation_id = ?", (conversation_id,)).rowcount

    def delete_rows(self, conn: sqlite3.Connection, photo_ids: list[int]) -> int:
        """완전히 지울 사진(`purgeable`)의 행을 지운다(5.6 1번). 남은 연결 행은 CASCADE. 파일은 부르는 쪽이 커밋 뒤에
        지운다. 지운 행 수."""
        if not photo_ids:
            return 0
        with transaction(conn):
            return conn.executemany("DELETE FROM photos WHERE id = ?", [(i,) for i in photo_ids]).rowcount

    def set_read_text(self, conn: sqlite3.Connection, photo_id: int, text: str) -> None:
        with transaction(conn):
            conn.execute("UPDATE photos SET read_text = ? WHERE id = ?", (text, photo_id))


def link_message_rows(conn: sqlite3.Connection, inbound_id: int, conversation_id: int, photo_ids: list[int]) -> None:
    """`message_photos` 행 쓰기(INSERT OR IGNORE). `StateRepo.add_pending_inbound`가 받은 메시지 행과 한 트랜잭션에서
    부른다(5.5, 같은 `client_msg_id` 재전송에 안전)."""
    with transaction(conn):
        conn.executemany(
            "INSERT OR IGNORE INTO message_photos (inbound_id, conversation_id, photo_id) VALUES (?, ?, ?)",
            [(inbound_id, conversation_id, pid) for pid in photo_ids],
        )

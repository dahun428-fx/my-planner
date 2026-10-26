"""사진 동작 (SP10 스펙 5.2·5.3). `Tools`가 이 mixin을 상속한다. 두뇌 도구가 아니다(`mcp_adapter` 목록에 없다).

- `store_photo`: `POST /photos`(PH-02)만 부르는 내부 동작. 처리기가 갈래 밖에서 쓴 `.incoming/` tmp 둘을 받아 한
  트랜잭션에서 행을 넣고 최종 이름으로 바꾼다(5.2 2번). 트랜잭션이 롤백되면 tmp와 바꾼 파일을 지운다(5.2 3번,
  `after_rollback`). 활동·되돌리기는 없다(올리기만으로는 아무것도 보이지 않는다).
- `attach_photo`, `detach_photo`: 앱의 `/actions`. 빼기만 되돌릴 수 있다. 둘 다 `memos.updated_at`을 바꾸지 않는다(5.3).
- 활동은 `photo_attached`/`photo_detached`, 대상 `photo:<id>`. `summary`에는 고정 문구만, `undo_json`에는 id와
  위치만 둔다. 파일 경로, sha256, 사진 읽기 결과는 활동·로그·결과에 넣지 않는다(6장).
- 오류 코드(`code`): `too_many_photos`(422), `photo_not_found`(422), `photo_in_use`(409). `tools/actions.py`가 HTTP로 바꾼다.
  그 메모에 없는 사진을 빼면 코드 없는 일반 거절(422 `rejected`, 8장)이다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from my_planner.clock import local
from my_planner.store.db import after_rollback, transaction
from my_planner.store.photos import IMAGE_MAX_BYTES, SIDE_MAX, PhotoFiles
from my_planner.store.repos.photos import (
    MEMO_PHOTOS_MAX,
    Photo,
    PhotosRepo,
    TooManyPhotos,
)
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import SUPERSEDED, UndoRefused, register_undo

if TYPE_CHECKING:
    from datetime import tzinfo

    from my_planner.clock import Clock
    from my_planner.domain import RunContext
    from my_planner.store.repos.memos import Memo, MemosRepo
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

TOO_MANY_PHOTOS = "too_many_photos"
PHOTO_NOT_FOUND = "photo_not_found"
PHOTO_IN_USE = "photo_in_use"

# 스펙 8장 문구
MSG_TOO_MANY_PHOTOS = "사진은 메모 하나에 10장까지예요."
MSG_PHOTO_IN_USE = "이 사진은 다른 곳에 이미 붙어 있어요."
MSG_PHOTO_NOT_FOUND = "사진을 올리지 못했어요. 다시 보내 주세요."
MSG_NO_PHOTOS = "사진을 다룰 수 없어요."
MSG_MEMO_NOT_FOUND = "없는 메모예요."
MSG_STORE_ARGS = "사진 정보가 맞지 않아요."
MSG_PHOTO_IDS = "photo_ids는 서로 다른 사진 번호(정수) 목록이에요."
MSG_NOT_ON_MEMO = "그 메모에 없는 사진이에요."  # 빼기의 낡은 대상: 일반 거절(8장 응답→문구, `photo_not_found`가 아니다)
# 8장 "사진 보기"(v2.5). 활동 `summary`이자 `/actions` 확인 문구. 이 문구는 여기에만 둔다
ATTACHED = "✓ 사진을 붙였어요"
DETACHED = "✓ 사진을 뺐어요"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def photo_target(photo_id: int) -> str:
    return f"photo:{photo_id}"


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _code(msg: str, code: str) -> dict[str, Any]:
    return {"error": msg, "code": code}


class PhotoTools:
    """사진 동작 셋(즉시 갈래만). `Tools`의 공통 부품(`_record`)을 쓴다."""

    photos: PhotosRepo | None
    photo_files: PhotoFiles | None

    if TYPE_CHECKING:
        clock: Clock
        tasks: TasksRepo
        tz: tzinfo
        memos: MemosRepo | None

        def _record(self, ctx: RunContext, kind: str, target: str | None, summary: str | None,
                    undo: dict[str, Any] | None, *, targets: list[str] | None = None) -> None: ...

    # --- 공통 ---

    def _free_memo_photo(self, photo_id: Any) -> Photo | dict[str, Any]:
        """새로 붙일 수 있는 메모 사진(5.3: 붙지 않은 `origin=memo` 사진). 아니면 오류 결과."""
        assert self.photos is not None
        conn = self.tasks.conn
        p = self.photos.get(conn, photo_id) if _is_int(photo_id) else None
        if p is None:
            return _code(MSG_PHOTO_NOT_FOUND, PHOTO_NOT_FOUND)
        if self.photos.memo_of(conn, p.id) is not None or self.photos.on_message(conn, p.id):
            return _code(MSG_PHOTO_IN_USE, PHOTO_IN_USE)
        if p.origin != "memo":
            return _code(MSG_PHOTO_NOT_FOUND, PHOTO_NOT_FOUND)
        return p

    def _photo_memo(self, memo_id: Any) -> Memo | dict[str, Any]:
        if self.memos is None or self.photos is None:
            return _err(MSG_NO_PHOTOS)
        m = self.memos.get(memo_id) if _is_int(memo_id) else None
        return m if m is not None else _err(MSG_MEMO_NOT_FOUND)

    def check_photo_ids(self, photo_ids: Any) -> list[int] | dict[str, Any]:
        """`create_memo(photo_ids)`(5.3): 서로 다른 정수 10개 이하, 모두 붙지 않은 `origin=memo` 사진. 아니면 오류 결과."""
        if self.photos is None:
            return _err(MSG_NO_PHOTOS)
        if not isinstance(photo_ids, list) or not all(_is_int(i) for i in photo_ids):
            return _err(MSG_PHOTO_IDS)
        if len(set(photo_ids)) != len(photo_ids):
            return _err(MSG_PHOTO_IDS)
        if len(photo_ids) > MEMO_PHOTOS_MAX:
            return _code(MSG_TOO_MANY_PHOTOS, TOO_MANY_PHOTOS)
        for pid in photo_ids:
            got = self._free_memo_photo(pid)
            if isinstance(got, dict):
                return got
        return list(photo_ids)

    # --- 내부 동작 ---

    @_tool
    def store_photo(
        self, ctx: RunContext, image_tmp: Any = None, thumb_tmp: Any = None, sha256: Any = None, bytes: Any = None,
        width: Any = None, height: Any = None, origin: Any = None,
    ) -> dict[str, Any]:
        """올린 사진의 행과 최종 파일(5.2 2번). 크기·바이트는 처리기가 `check_photo`로 본 값이다."""
        files, repo = self.photo_files, self.photos
        if files is None or repo is None:
            return _err(MSG_NO_PHOTOS)
        ok = (
            isinstance(image_tmp, str) and isinstance(thumb_tmp, str) and image_tmp != thumb_tmp
            and files.is_incoming(Path(image_tmp)) and files.is_incoming(Path(thumb_tmp))
            and isinstance(sha256, str) and _SHA256.match(sha256) is not None
            and _is_int(bytes) and 1 <= bytes <= IMAGE_MAX_BYTES
            and _is_int(width) and 1 <= width <= SIDE_MAX and _is_int(height) and 1 <= height <= SIDE_MAX
            and origin in ("memo", "chat")
        )
        if not ok:
            return _err(MSG_STORE_ARGS)  # `.incoming/` 밖의 파일은 건드리지 않는다
        tmp = (Path(image_tmp), Path(thumb_tmp))
        conn = self.tasks.conn
        created: list[Path] = []

        def cleanup() -> None:  # 5.2 3번: 롤백되면 tmp와 이번에 바꾼 파일을 지운다
            for p in (*created, *tmp):
                try:
                    p.unlink(missing_ok=True)
                except OSError:  # 남으면 하루 한 번 작업의 고아 정리(5.6 2번)
                    pass

        now = self.clock.now()
        with transaction(conn):
            after_rollback(conn, cleanup)
            # 최종 이름은 id를 받은 뒤에 정해진다: 그때까지는 겹치지 않는 tmp 이름을 둔다
            p = repo.insert(
                conn, sha256=sha256, path=f"{tmp[0].parent.name}/{tmp[0].name}",
                thumb_path=f"{tmp[1].parent.name}/{tmp[1].name}", bytes=bytes, width=width, height=height,
                origin=origin, now=now,
            )
            rel = files.place(tmp, p.id, sha256, local(now, self.tz).date(), created=created)
            repo.set_paths(conn, p.id, *rel)
        log.info("photo_stored", extra={"photo_id": p.id, "origin": origin})
        return {"id": p.id, "width": p.width, "height": p.height, "bytes": p.bytes}

    # --- 즉시 갈래 동작(`/actions`) ---

    @_tool
    def attach_photo(self, ctx: RunContext, memo_id: Any = None, photo_id: Any = None) -> dict[str, Any]:
        """메모에 사진을 붙인다(가장 작은 빈 자리). 이미 그 메모에 있으면 `already`. 되돌릴 수 없다(빼기로 한다)."""
        m = self._photo_memo(memo_id)
        if isinstance(m, dict):
            return m
        assert self.photos is not None
        conn = self.tasks.conn
        at = self.photos.memo_of(conn, photo_id) if _is_int(photo_id) else None
        if at is not None and at[0] == m.id:
            return {"memo_id": m.id, "photo_id": photo_id, "position": at[1], "already": True}
        p = self._free_memo_photo(photo_id)
        if isinstance(p, dict):
            return p
        try:
            with transaction(conn):
                position = self.photos.attach(conn, m.id, p.id)
                self._record(ctx, "photo_attached", photo_target(p.id), ATTACHED, None)
        except TooManyPhotos:
            return _code(MSG_TOO_MANY_PHOTOS, TOO_MANY_PHOTOS)
        log.info("photo_attached", extra={"memo_id": m.id, "photo_id": p.id})
        return {"memo_id": m.id, "photo_id": p.id, "position": position}

    @_tool
    def detach_photo(self, ctx: RunContext, memo_id: Any = None, photo_id: Any = None) -> dict[str, Any]:
        """메모에서 사진을 뺀다(`unlinked_at = now`). 되돌리면 원래 자리, 차 있으면 가장 작은 빈 자리."""
        m = self._photo_memo(memo_id)
        if isinstance(m, dict):
            return m
        assert self.photos is not None
        conn = self.tasks.conn
        at = self.photos.memo_of(conn, photo_id) if _is_int(photo_id) else None
        if at is None or at[0] != m.id:  # 없는 사진, 뺀 사진, 다른 메모의 사진: 다른 낡은 대상처럼 일반 거절(422 `rejected`)
            return _err(MSG_NOT_ON_MEMO)
        with transaction(conn):
            self.photos.detach(conn, m.id, photo_id, self.clock.now())
            undo = {"memo_id": m.id, "photo_id": photo_id, "position": at[1]}
            self._record(ctx, "photo_detached", photo_target(photo_id), DETACHED, undo)
        log.info("photo_detached", extra={"memo_id": m.id, "photo_id": photo_id})
        return {"memo_id": m.id, "photo_id": photo_id, "detached": True}


def _undo_photo_detached(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """다시 붙인다. 메모가 없어졌거나(지움·완전 지움) 사진이 다른 메모에 붙었으면 superseded. 10장이면 거절."""
    memos, photos = tools.memos, tools.photos
    assert memos is not None and photos is not None
    conn = tools.tasks.conn
    pid = undo["photo_id"]
    if memos.get(undo["memo_id"]) is None or photos.get(conn, pid) is None:
        return SUPERSEDED
    at = photos.memo_of(conn, pid)
    if at is not None and at[0] != undo["memo_id"]:  # 메시지 연결은 보지 않는다: 채팅 사진도 원래 그 메모에 있었다
        return SUPERSEDED
    try:
        photos.attach(conn, undo["memo_id"], pid, position=undo["position"])
    except TooManyPhotos:
        raise UndoRefused(TOO_MANY_PHOTOS, MSG_TOO_MANY_PHOTOS) from None
    return None


register_undo("photo_detached", _undo_photo_detached)

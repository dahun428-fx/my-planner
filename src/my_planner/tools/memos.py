"""메모 도구와 메모 동작 (SP9 스펙 6장). `Tools`가 이 mixin을 상속한다.

- 두뇌 도구(앱 대화에만, `APP_ONLY_TOOLS`): `search_memos`, `read_memo`, `create_memo`. 고치기·지우기 도구는 없다(Q5):
  `update_memo`, `pin_memo`, `unpin_memo`, `delete_memo`는 즉시 갈래(`POST /actions`)만 부른다(`mcp_adapter` 목록에 없다).
- 두뇌에 주는 메모 글(제목, 미리보기, 본문)은 `redact()`를 거친다. 가린 뒤에 자른다(잘린 숫자열이 가리기를 빠져나가지 않게).
- 메모 본문은 로그, 활동(`summary`, `undo_json`), `tool_events_log`, 도구 이벤트에 넣지 않는다. 활동 `summary`의 제목은 앞
  20자만 쓴다. 로그에는 메모 id와 결과만 남긴다.
- 활동 `memo_created`/`memo_updated`/`memo_pinned`/`memo_unpinned`/`memo_deleted`, 대상 `memo:<id>`. 고치기는 되돌릴 수
  없다(이전 본문을 활동에 남기지 않는다). 만들기·고정·고정 풀기·지우기는 되돌릴 수 있다(상한은 지킨다).
- 바꾸면 `tool_events_log`에도 `{"memo_id", "title"(앞 20자)}`를 쓴다(다시 처리할 때 두뇌를 다시 부르지 않게).
- 두뇌의 `create_memo` 결과는 `{id, title, area}`, `/actions` 결과는 본문 없는 `memo_result`다.
- 오류 코드(`code`): `memo_conflict`(409), `too_many_memos`, `too_many_pinned`(422). `tools/actions.py`가 HTTP로 바꾼다.
- `create_memo`는 `photo_ids`를 받아 순서대로 붙인다: 앱은 메모 사진(SP10 5.3), 두뇌는 앱 대화에서 이번 대화의 채팅
  사진만(5.5, 그 밖은 `photo_not_in_conversation`). `update_memo`는 사진을 받지 않는다(11장).
  메모 지우기·되돌리기는 사진 연결을 그대로 둔다(살아 있는 사진 정의로 숨는다, 5.1).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.clock import from_iso, to_iso
from my_planner.domain import Area, RunContext, ToolEvent
from my_planner.harness.redact import redact
from my_planner.store.db import transaction
from my_planner.store.repos.memos import (
    Memo,
    MemoConflict,
    MemosRepo,
    memo_preview,
    memo_title,
)
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import SUPERSEDED, UndoRefused, register_undo
from my_planner.tools.confirmations import memo_line

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.photos import PhotosRepo
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

MEMO_BODY_MAX = 20000
MEMOS_MAX = 2000  # 살아 있는 메모(6.1)
PINNED_MAX = 10
SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX = 5, 20
SEARCH_PREVIEW = 200  # `search_memos`의 미리보기(6.3)
LIST_PREVIEW = 80  # `GET /memos`의 미리보기(6.4)
READ_MAX = 8000  # `read_memo`가 주는 본문(6.3)
SUMMARY_TITLE = 20  # 활동 `summary`에 넣는 제목 앞 글자 수(6.1)
DELETED_KEEP = timedelta(days=30)  # 지운 메모 보관(6.1)

CONFLICT = "memo_conflict"
TOO_MANY_MEMOS = "too_many_memos"
TOO_MANY_PINNED = "too_many_pinned"

MSG_NO_MEMOS = "메모를 다룰 수 없어요."
MSG_NOT_FOUND = "없는 메모예요."
MSG_EMPTY = "메모가 비어 있어요."
MSG_LONG = "메모는 20,000자까지 쓸 수 있어요."
MSG_TOO_MANY = "메모는 2,000개까지 둘 수 있어요. 안 쓰는 메모를 지우면 새로 만들 수 있어요."
MSG_TOO_MANY_PINNED = "고정은 10개까지예요. 다른 메모의 고정을 풀면 더 고정할 수 있어요."
MSG_CONFLICT = "다른 곳에서 바뀌었어요. 새로 불러올게요."  # 스펙 10장 "메모 충돌"
MSG_RUN_TURN = "사용자가 부탁한 메모만 만들 수 있어요."
MSG_AREA = "area는 career, finance, health, relationships, learning, quality_of_life 가운데 하나예요."
MSG_UPDATED_AT = "updated_at은 앞서 받은 메모의 updated_at 값으로 보내 주세요."
MSG_QUERY = "찾을 말(query)을 알려 주세요."
MSG_PHOTOS_APP_ONLY = "사진은 앱에서 붙일 수 있어요."
MSG_LIMIT = f"limit은 1~{SEARCH_LIMIT_MAX} 사이 정수예요."


def memo_target(memo_id: int) -> str:
    return f"memo:{memo_id}"


def _brain_result(m: Memo) -> dict[str, Any]:
    """두뇌의 `create_memo` 결과: 본문 없이 id, 가린 제목, 영역."""
    return {"id": m.id, "title": memo_title(redact(m.body)[0]), "area": m.area.value if m.area is not None else None}


def summary_title(body: str) -> str:
    """활동 `summary`용 제목(앞 20자)."""
    return memo_title(body)[:SUMMARY_TITLE]


def memo_dict(m: Memo) -> dict[str, Any]:
    """`Memo` 모양(`GET /memos/{id}`, 본문 포함). 시각은 저장 형식 그대로, API 경계에서 UTC `Z`로 바뀐다."""
    return {
        "id": m.id,
        "title": memo_title(m.body),
        "body": m.body,
        "area": m.area.value if m.area is not None else None,
        "pinned": m.pinned,
        "origin": m.origin,
        "created_at": to_iso(m.created_at),
        "updated_at": to_iso(m.updated_at),
    }


def memo_result(m: Memo) -> dict[str, Any]:
    """`/actions` 결과(만들기·고치기·고정·고정 풀기). 본문은 없다: 중복 방지 기록(`api_idempotency`)에 본문이 남지
    않게. 앱은 `updated_at`을 다음 `update_memo`에 쓰고, 본문은 자기가 보낸 것을 쓰거나 `GET /memos/{id}`로 읽는다."""
    return {
        "id": m.id,
        "title": memo_title(m.body),
        "area": m.area.value if m.area is not None else None,
        "pinned": m.pinned,
        "updated_at": to_iso(m.updated_at),
    }


def memo_item(m: Memo) -> dict[str, Any]:
    """`GET /memos` 목록 한 줄(6.4): 본문 없이 제목과 미리보기 80자."""
    return {
        "id": m.id,
        "title": memo_title(m.body),
        "preview": memo_preview(m.body, LIST_PREVIEW),
        "area": m.area.value if m.area is not None else None,
        "pinned": m.pinned,
        "origin": m.origin,
        "updated_at": to_iso(m.updated_at),
    }


_KEEP: Any = object()  # `update_memo`에서 `area`를 빼면 지금 영역 그대로(명시한 null은 영역 없음)


def _code(msg: str, code: str) -> dict[str, Any]:
    return {"error": msg, "code": code}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _body(v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(MSG_EMPTY)
    if len(v) > MEMO_BODY_MAX:
        raise ValueError(MSG_LONG)
    return v


def _area(v: Any) -> Area | None:
    if v is None:
        return None
    try:
        return Area(v)
    except ValueError:
        raise ValueError(MSG_AREA) from None


def _stamp(v: Any) -> datetime:
    """앱이 앞서 받은 `updated_at`(시간대 붙은 ISO 8601). 틀리면 `ValueError`."""
    try:
        dt = datetime.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        dt = None
    if dt is None or dt.tzinfo is None:
        raise ValueError(MSG_UPDATED_AT)
    return dt


class MemoTools:
    """메모 도구 셋(두뇌)과 메모 동작 넷(즉시 갈래만). `Tools`의 공통 부품(`_record`)을 쓴다."""

    memos: MemosRepo | None
    photos: PhotosRepo | None

    if TYPE_CHECKING:
        clock: Clock
        tasks: TasksRepo

        def _record(self, ctx: RunContext, kind: str, target: str | None, summary: str | None,
                    undo: dict[str, Any] | None, *, targets: list[str] | None = None) -> None: ...

        def check_photo_ids(self, photo_ids: Any) -> list[int] | dict[str, Any]: ...

        def check_chat_photo_ids(self, ctx: RunContext, photo_ids: Any) -> list[int] | dict[str, Any]: ...

    # --- 공통 ---

    def _memo(self, id: Any) -> Memo | str:
        assert self.memos is not None
        m = self.memos.get(id) if _is_int(id) else None
        return m if m is not None else MSG_NOT_FOUND

    def _memo_change(
        self, ctx: RunContext, kind: str, m: Memo, undo: dict[str, Any] | None, *, photos: int = 0
    ) -> None:
        """트랜잭션 안에서: 도구 호출 기록(`tool_events_log`), 활동 한 행, 확인 문구용 이벤트. 셋 다 제목 앞 20자만 쓰고
        본문은 넣지 않는다(6.1). 호출 기록이 있어야 두뇌 호출 도중 멈춘 메시지를 다시 처리할 때 두뇌를 다시 부르지 않고
        (같은 메모를 두 번 만들지 않고) 이 데이터로 확인 문구를 다시 만든다(`Dispatcher._finish_after_logged_tools`)."""
        # 두뇌가 바꾼 것은 가린 제목으로(메모 칩은 원문을 저장한다, SP9c 4.5). 앱(`/actions`)은 사용자 글 그대로
        data: dict[str, Any] = {
            "memo_id": m.id, "title": summary_title(redact(m.body)[0] if ctx.actor == "secretary" else m.body),
        }
        if photos:
            data["photos"] = photos  # 확인 문구의 `(사진 {n}장)`(SP10 8장). 사진 id는 연결 표에 있다
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, None, kind, inbound_id=ctx.inbound_id, data=data)
        if photos and undo is not None:
            # 되돌림 문구는 사진 수 없는 확인 문구에서 만든다(`_undo`가 `undo["summary"]`를 먼저 본다). 제목은 그대로
            undo = {**undo, "summary": memo_line(kind, data["title"])}
        self._record(ctx, kind, memo_target(m.id), memo_line(kind, data["title"], photos), undo)
        ctx.events.append(ToolEvent(kind, None, data))

    # --- 두뇌 도구 ---

    @_tool
    def search_memos(self, ctx: RunContext, query: Any = None, limit: Any = SEARCH_LIMIT_DEFAULT) -> dict[str, Any]:
        """검색어가 든 메모: 제목, 미리보기 200자, id, 고친 시각. 글은 `redact()`를 거친다(6.3)."""
        if self.memos is None:
            return _err(MSG_NO_MEMOS)
        if not isinstance(query, str) or not query.strip():
            return _err(MSG_QUERY)
        n = SEARCH_LIMIT_DEFAULT if limit is None else limit
        if not _is_int(n) or not 1 <= n <= SEARCH_LIMIT_MAX:
            return _err(MSG_LIMIT)
        items = []
        for m in self.memos.search(query, n):
            body, _ = redact(m.body)
            items.append({
                "id": m.id, "title": memo_title(body), "preview": memo_preview(body, SEARCH_PREVIEW),
                "updated_at": to_iso(m.updated_at),
            })
        log.info("memos_searched", extra={"count": len(items)})
        return {"items": items}

    @_tool
    def read_memo(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """메모 하나의 본문(`redact()` 뒤 8,000자까지, 6.3). 더 길면 `truncated: true`."""
        if self.memos is None:
            return _err(MSG_NO_MEMOS)
        m = self._memo(id)
        if isinstance(m, str):
            return _err(m)
        body, _ = redact(m.body)
        log.info("memo_read", extra={"memo_id": m.id})
        return {
            "id": m.id, "title": memo_title(body), "body": body[:READ_MAX], "truncated": len(body) > READ_MAX,
            "area": m.area.value if m.area is not None else None, "pinned": m.pinned, "origin": m.origin,
            "updated_at": to_iso(m.updated_at),
        }

    @_tool
    def create_memo(
        self, ctx: RunContext, body: Any = None, area: Any = None, photo_ids: Any = None
    ) -> dict[str, Any]:
        """메모를 만든다. 두뇌가 만들면 `origin = 'chat'`, 앱(`/actions`)이면 `'user'`. 되돌릴 수 있다.
        회차 차례(비서가 먼저 꺼낸 말)에서는 만들지 않는다: 사용자가 부탁할 때만(6.3).
        메모 칩 차례(`ctx.chip == "memo"`, SP9c 4.5)면 본문은 늘 `ctx.chip_text`(가리기·자르기 전 원문)다.
        `photo_ids`: 앱(`/actions`, SP10 5.3)은 붙지 않은 `origin=memo` 사진, 두뇌(앱 대화만, 5.5)는 이번 대화의 메시지에
        붙은 사진. 10장까지를 순서대로 붙인다. 메시지 연결은 그대로 두고, 되돌리기는 메모 지우기(연결은 남는다).
        사진만 보낸 앱 메시지(SP10 16장)는 디스패처가 `actor='user'`, `inbound_id`가 있는 맥락으로 부른다: 두뇌처럼 이번
        대화의 채팅 사진을 받고, `/actions`처럼 `origin='user'`다."""
        if self.memos is None:
            return _err(MSG_NO_MEMOS)
        if ctx.run_turn:
            return _err(MSG_RUN_TURN)
        if ctx.chip == "memo" and ctx.chip_text is not None:
            # 메모 칩 차례(SP9c 4.5): 두뇌가 본 글은 가리고 자른 글이라 원문 그대로를 저장한다(두뇌가 body를 넣어도).
            # 메모는 하나만: 이 차례에 이미 만들었으면 만들지 않고 그 메모를 돌려준다
            made = next((e.data for e in ctx.events if e.kind == "memo_created" and e.data), None)
            if made is not None:
                prev = self.memos.get(made["memo_id"])
                if prev is not None:
                    return _brain_result(prev)
            body = ctx.chip_text
        try:
            text, a = _body(body), _area(area)
        except ValueError as e:
            return _err(str(e))
        ids: list[int] = []
        if photo_ids is not None and photo_ids != []:
            if ctx.actor == "secretary" and ctx.channel != "app":  # 앱 통로에서만 받는다(SP10 5.5, Q14)
                return _err(MSG_PHOTOS_APP_ONLY)
            # 채팅 메시지 처리(두뇌, 사진만 메시지 16장)는 이번 대화의 채팅 사진만(5.5), 앱(`/actions`)은 붙지 않은
            # 메모 사진만(5.3). `/actions`의 맥락에는 `inbound_id`가 없다
            chat = ctx.actor == "secretary" or ctx.inbound_id is not None
            checked = self.check_chat_photo_ids(ctx, photo_ids) if chat else self.check_photo_ids(photo_ids)
            if isinstance(checked, dict):
                return checked
            ids = checked
        if self.memos.count_live() >= MEMOS_MAX:
            return _code(MSG_TOO_MANY, TOO_MANY_MEMOS)
        origin = "chat" if ctx.actor == "secretary" else "user"
        with transaction(self.memos.conn):
            m = self.memos.create(text, a, origin, self.clock.now())
            for pid in ids:
                assert self.photos is not None
                self.photos.attach(self.memos.conn, m.id, pid)  # 빈 메모라 0부터 차례로
            self._memo_change(ctx, "memo_created", m, {"memo_id": m.id}, photos=len(ids))
        log.info("memo_created", extra={"memo_id": m.id, "origin": origin})
        if ctx.actor == "secretary":  # 두뇌에는 본문을 돌려주지 않는다(6.3). 제목도 가린 글로
            return _brain_result(m)
        return memo_result(m)

    # --- 즉시 갈래 동작(두뇌 도구 목록에 없다) ---

    @_tool
    def update_memo(
        self, ctx: RunContext, id: Any = None, body: Any = None, area: Any = _KEEP, updated_at: Any = None,
    ) -> dict[str, Any]:
        """본문을 바꾼다. `area`를 빼면 지금 영역 그대로, null이면 영역 없음. `updated_at`이 지금 값과 다르면 `memo_conflict`(6.4).
        바뀌는 것이 없으면 쓰지 않고 `already`. 되돌릴 수 없다(이전 본문을 활동에 남기지 않는다)."""
        if self.memos is None:
            return _err(MSG_NO_MEMOS)
        m = self._memo(id)
        if isinstance(m, str):
            return _err(m)
        try:
            text, seen = _body(body), _stamp(updated_at)
            a = m.area if area is _KEEP else _area(area)
        except ValueError as e:
            return _err(str(e))
        if to_iso(seen) != to_iso(m.updated_at):
            log.info("memo_conflict", extra={"memo_id": m.id})
            return _code(MSG_CONFLICT, CONFLICT)
        if text == m.body and a == m.area:
            return {**memo_result(m), "already": True}
        try:
            with transaction(self.memos.conn):
                m = self.memos.update(m.id, text, a, seen, self.clock.now())
                self._memo_change(ctx, "memo_updated", m, None)
        except MemoConflict:
            log.info("memo_conflict", extra={"memo_id": m.id})
            return _code(MSG_CONFLICT, CONFLICT)
        log.info("memo_updated", extra={"memo_id": m.id})
        return memo_result(m)

    @_tool
    def pin_memo(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """고정(10개까지). 이미 고정했으면 `already`."""
        if self.memos is None:
            return _err(MSG_NO_MEMOS)
        m = self._memo(id)
        if isinstance(m, str):
            return _err(m)
        if m.pinned:
            return {**memo_result(m), "already": True}
        if self.memos.count_pinned() >= PINNED_MAX:
            return _code(MSG_TOO_MANY_PINNED, TOO_MANY_PINNED)
        with transaction(self.memos.conn):
            self.memos.pin(m.id, self.clock.now())
            self._memo_change(ctx, "memo_pinned", m, {"memo_id": m.id})
        log.info("memo_pinned", extra={"memo_id": m.id})
        got = self.memos.get(m.id)
        assert got is not None
        return memo_result(got)

    @_tool
    def unpin_memo(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """고정 풀기. 고정하지 않았으면 `already`. 되돌리면 이전 고정 시각 그대로 다시 고정한다."""
        if self.memos is None:
            return _err(MSG_NO_MEMOS)
        m = self._memo(id)
        if isinstance(m, str):
            return _err(m)
        if not m.pinned:
            return {**memo_result(m), "already": True}
        prev = self.memos.pinned_at(m.id)
        assert prev is not None
        with transaction(self.memos.conn):
            self.memos.unpin(m.id)
            self._memo_change(ctx, "memo_unpinned", m, {"memo_id": m.id, "pinned_at": to_iso(prev)})
        log.info("memo_unpinned", extra={"memo_id": m.id})
        got = self.memos.get(m.id)
        assert got is not None
        return memo_result(got)

    @_tool
    def delete_memo(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """지우기(소프트 삭제). 되돌릴 수 있고, 30일 뒤 하루 한 번 작업이 완전히 지운다."""
        if self.memos is None:
            return _err(MSG_NO_MEMOS)
        m = self._memo(id)
        if isinstance(m, str):
            return _err(m)
        with transaction(self.memos.conn):
            self.memos.delete(m.id, self.clock.now())
            self._memo_change(ctx, "memo_deleted", m, {"memo_id": m.id})
        log.info("memo_deleted", extra={"memo_id": m.id})
        return {"id": m.id, "deleted": True}


# --- 되돌리기. 상한을 지킨다: 살아 있는 메모가 2,000개면 지우기를 되돌리지 않고(`too_many_memos`), 고정이 10개면
# 고정 풀기를 되돌리지 않는다(`too_many_pinned`). 고정했던 메모의 지우기를 되돌릴 때 고정이 10개면 고정 없이 되살린다 ---


def _undo_memo_created(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """만든 메모를 지운다(소프트 삭제). 이미 없으면 superseded."""
    assert tools.memos is not None
    if tools.memos.get(undo["memo_id"]) is None:
        return SUPERSEDED
    tools.memos.delete(undo["memo_id"], tools.clock.now())
    return None


def _undo_memo_pinned(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.memos is not None
    if tools.memos.get(undo["memo_id"]) is None:
        return SUPERSEDED
    tools.memos.unpin(undo["memo_id"])
    return None


def _undo_memo_unpinned(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.memos is not None
    if tools.memos.get(undo["memo_id"]) is None:
        return SUPERSEDED
    if tools.memos.count_pinned() >= PINNED_MAX:
        raise UndoRefused(TOO_MANY_PINNED, MSG_TOO_MANY_PINNED)
    tools.memos.pin(undo["memo_id"], from_iso(undo["pinned_at"]))
    return None


def _undo_memo_deleted(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """되살린다. 이미 완전히 지워졌으면 superseded. 고정 자리가 없으면 고정을 풀고 되살린다."""
    memos = tools.memos
    assert memos is not None
    if memos.count_live() >= MEMOS_MAX:
        raise UndoRefused(TOO_MANY_MEMOS, MSG_TOO_MANY)
    unpin = memos.pinned_at(undo["memo_id"]) is not None and memos.count_pinned() >= PINNED_MAX
    return None if memos.restore(undo["memo_id"], unpin=unpin) else SUPERSEDED


for _kind, _handler in (
    ("memo_created", _undo_memo_created),
    ("memo_pinned", _undo_memo_pinned),
    ("memo_unpinned", _undo_memo_unpinned),
    ("memo_deleted", _undo_memo_deleted),
):
    register_undo(_kind, _handler)

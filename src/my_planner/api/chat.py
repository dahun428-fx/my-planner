"""`POST /api/v1/chat` (SP3-4 스펙 6.4.1, 7.5): 운영 앱 채팅을 두뇌 갈래로 넘기고 AI SDK UI message stream으로 답한다.

흐름(6.4.1):
1. 같은 `client_msg_id`의 처리가 끝났으면 저장한 답을 재생한다(두뇌 없이, `api_idempotency.response_json`).
2. 처리 중이면(큐에서 기다리거나 두뇌가 답하는 중) 새 요청을 그 처리의 스트림에 붙인다(M8).
3. 사진(`data-photo`, SP10 5.5)을 두뇌 부르기 전에 검사한다(400 `photo_not_found`, 422 `too_many_photos`).
   글도 사진도 없으면(그림 등) SP1 `NON_TEXT_REPLY`, `/`로 시작하면 텔레그램과 같은 명령(`bot.commands.run_command`).
   `/plan [주제]`만 앱 계획 대화를 열고 두뇌 갈래로 간다. 퀵 칩(`chip`, SP9c 4.1)이나 사진이 있으면 명령을 해석하지 않는다.
   사진만 있는 메시지는 두뇌로 간다.
4. 대화를 받을 때 고르고(`route_app_message`), 가린 글을 `inbound_pending`(통로 `app`, 음수 id, 고른 대화)에 먼저
   쓴 뒤 두뇌 갈래에 넣는다(`submit_message`). 사진 연결(`message_photos`)은 같은 트랜잭션이고 본문은
   `[사진 #12] {글}`이다. `start`와 `data-status: queued`는 여기서 쓴다.
5. 스트림을 연결에 흘려 보낸다. 15초 동안 새 조각이 없으면 `: ping`. 연결이 끊겨도 처리는 끝까지 간다(M7).
   멈추는 길은 연결 끊기가 아니라 `POST /chat/stop`(`post_chat_stop`) 하나다.

이 티켓은 두뇌 글을 끝난 뒤 글 블록 하나로 보낸다(S11 대체 경로, 조각 스트리밍은 06b). 로그에는 본문, 도구 인자,
토큰을 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiohttp import web
from pydantic import ValidationError

from my_planner.api.actions import BAD_BODY, read_json_object
from my_planner.api.cors import CORS_HEADERS_KEY
from my_planner.api.models import (
    ChatRequestBody,
    ChatStopBody,
    ChatStopped,
    ConversationsClosed,
    ErrorCode,
    dump,
    error_response,
)
from my_planner.bot.commands import (
    STATEFUL_COMMANDS,
    CommandDeps,
    command_of,
    plan_topic,
    run_command,
)
from my_planner.bot.telegram_io import NON_TEXT_MARK, NON_TEXT_REPLY
from my_planner.harness.chat_photos import MESSAGE_PHOTOS_MAX, photo_body
from my_planner.harness.dispatcher import FALLBACK_REPLY, Inbound
from my_planner.harness.redact import redact
from my_planner.harness.stream import (
    PING_INTERVAL_S,
    SSE_PING,
    QueueSink,
    UiMessageWriter,
    write_reply,
)
from my_planner.store.transcripts import app_secretary_message_id
from my_planner.tools.actions import REUSED_ID

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps
    from my_planner.harness.dispatcher import Dispatcher
    from my_planner.store.repos.activity import StoredResponse

log = logging.getLogger(__name__)

STREAM_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "x-vercel-ai-ui-message-stream": "v1",
}
IN_FLIGHT = "같은 메시지를 처리하고 있어요. 잠시 뒤에 다시 보내 주세요."


# SP10 8장: `400 photo_not_found`(채팅 `data-photo`)는 "올리지 못했어요", `422 too_many_photos`는 메시지 4장 상한
PHOTO_NOT_FOUND = "사진을 올리지 못했어요. 다시 보내 주세요."
TOO_MANY_PHOTOS = "한 번에 사진 4장까지 보낼 수 있어요."


class _PhotoRefused(Exception):
    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def message_text(parts: list[dict[str, Any]]) -> str:
    """`parts`의 `text`만 이어 붙인다(6.4.1)."""
    return "".join(p["text"] for p in parts if p.get("type") == "text" and isinstance(p.get("text"), str))


def message_photos(parts: list[dict[str, Any]]) -> list[int]:
    """`parts`의 `{"type": "data-photo", "data": {"photo_id": 12}}`(SP10 5.5)에서 사진 id를 고른다. 보낸 순서, 중복은
    처음 것 하나로.

    `photo_id`가 양의 정수가 아니면 400 `photo_not_found`, 5장 이상이면 422 `too_many_photos`(`_PhotoRefused`).
    DB 검사(있는 사진인가, `origin`, 이미 붙었나)는 `_check_photos`가 한다.
    """
    ids: dict[int, None] = {}  # 넣은 순서를 지키는 집합
    for p in parts:
        if p.get("type") != "data-photo":
            continue
        data = p.get("data")
        pid = data.get("photo_id") if isinstance(data, dict) else None
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise _PhotoRefused(400, "photo_not_found", PHOTO_NOT_FOUND)
        ids.setdefault(pid)
    if len(ids) > MESSAGE_PHOTOS_MAX:
        raise _PhotoRefused(422, "too_many_photos", TOO_MANY_PHOTOS)
    return list(ids)


def _check_photos(d: Dispatcher, photo_ids: list[int]) -> None:
    """모두 있는 `origin = 'chat'` 사진이고 아직 다른 메시지나 메모에 붙지 않았다(5.5). 아니면 400 `photo_not_found`."""
    tools = d.tools
    if not photo_ids:
        return
    if tools is None or tools.photos is None:
        raise _PhotoRefused(400, "photo_not_found", PHOTO_NOT_FOUND)
    conn = tools.tasks.conn
    if not all(tools.photos.free_chat_photo(conn, pid) for pid in photo_ids):
        raise _PhotoRefused(400, "photo_not_found", PHOTO_NOT_FOUND)


async def post_chat(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = ChatRequestBody.model_validate(body)
    except ValidationError:  # 무엇이 틀렸는지(요청 값)는 답에도 로그에도 넣지 않는다
        return error_response(400, "invalid_request", BAD_BODY)
    d = deps.dispatcher
    assert d is not None, "안전 모드가 아니면 디스패처가 있다"
    cmid = req.client_msg_id

    # 1. 끝난 처리의 재생
    stored = d.idempotency.get(cmid) if d.idempotency is not None else None
    if stored is not None:
        if stored.endpoint != "chat":
            return error_response(409, "conflict", REUSED_ID)
        return await _replay(request, deps, d, stored, req.checkin_id)

    # 2. 처리 중이면 그 스트림에 붙는다(M8)
    sink = QueueSink()
    if d.attach_stream(cmid, sink):
        row = d.state.pending_by_client_msg_id(cmid)
        log.info("chat_attached")
        return await stream_sink(request, deps, sink, row.conversation_id if row is not None else None)
    if d.has_inflight(cmid):  # 처리 중인데 붙을 수 없는 스트림: 두 번 처리하지 않는다
        return error_response(409, "conflict", IN_FLIGHT)
    row = d.state.pending_by_client_msg_id(cmid)
    if row is not None:
        # 행은 있는데 처리 자리가 없다(처리 중 예외 뒤): 시작 때 다시 넣기와 같은 규칙으로(3회 뒤 버림)
        if d.resubmit_app_row(row, sink, message_id=req.message.id):
            log.info("chat_resubmitted")
            return await stream_sink(request, deps, sink, row.conversation_id)
        d.record_chat_reply(cmid, FALLBACK_REPLY, conversation_id=row.conversation_id)
        return await _direct_reply(request, deps, d, sink, FALLBACK_REPLY, row.conversation_id, row.checkin_id)

    text = message_text(req.message.parts)
    now = deps.clock.now()

    # 3. 사진 검사(SP10 5.5): 모두 두뇌를 부르기 전. 검사와 연결 쓰기 사이에 다른 요청이 끼지 않는다(await 없음)
    try:
        photo_ids = message_photos(req.message.parts)
        _check_photos(d, photo_ids)
    except _PhotoRefused as e:
        log.info("chat_photo_refused", extra={"code": e.code})
        return error_response(e.status, e.code, e.message)

    # 글이 아닌 메시지(사진도 없음), 명령: 두뇌 없이 글 조각 하나
    if not text.strip() and not photo_ids:
        _transcribe_direct(deps, NON_TEXT_MARK, NON_TEXT_REPLY)
        d.record_chat_reply(cmid, NON_TEXT_REPLY)
        return await _direct_reply(request, deps, d, sink, NON_TEXT_REPLY, req.conversation_id, req.checkin_id)
    # 퀵 칩(SP9c 4.1)이면 명령을 해석하지 않는다: `/`로 시작해도 그대로 메시지다
    cmd = command_of(text) if d.tools is not None and req.chip is None and not photo_ids else None
    if cmd is not None and cmd != "/plan":
        assert d.tools is not None
        cdeps = CommandDeps(
            tasks=d.tools.tasks, conditions=d.conditions, state=d.state, router=d.router, clock=deps.clock,
            settings=deps.settings, apply=d.apply_action, status=d.tools.status, curve=d.tools.curve,
            habits=d.tools.habits,  # `/habits`는 글만(앱에는 습관 블록이 있다, SP7 5.7)
            events=d.tools.events,
        )
        reply = run_command(cmd, text, cdeps, channel="app", client_msg_id=cmid)
        if cmd not in STATEFUL_COMMANDS:  # 상태를 바꾸는 명령은 즉시 갈래가 이미 적었다
            d.record_chat_reply(cmid, reply)
        _transcribe_direct(deps, redact(text)[0], reply)
        log.info("chat_command", extra={"command": cmd})
        return await _direct_reply(request, deps, d, sink, reply, req.conversation_id, req.checkin_id)
    plan = cmd == "/plan"  # 앱 통로의 계획 대화를 연다(그 통로에 열린 것은 닫는다)
    if plan:
        text = plan_topic(text)

    # 4. 대화를 받을 때 고르고, 저장한 뒤 두뇌 갈래에 넣는다
    conv = d.route_app_message(
        now, conversation_id=req.conversation_id, checkin_id=req.checkin_id, plan=plan,
        resume_conversation_id=req.resume_conversation_id,
    )
    inbound_id = d.state.next_app_inbound_id()
    d.state.add_pending_inbound(
        inbound_id, photo_body(photo_ids, redact(text)[0]), now, now, channel="app", client_msg_id=cmid,
        checkin_id=req.checkin_id, conversation_id=conv.id, resume_conversation_id=req.resume_conversation_id,
        photo_ids=photo_ids,
    )
    writer = UiMessageWriter(sink, app_secretary_message_id(conv.id, inbound_id))
    writer.start({**d.chat_metadata(conv.id), "checkin_id": req.checkin_id})
    writer.status("queued")
    d.submit_message(Inbound(
        text=photo_body(photo_ids, text), at=now, sent_at=now, update_ids=[inbound_id], channel="app",
        client_msg_id=cmid, checkin_id=req.checkin_id, sink=sink, conversation_id=conv.id, message_id=req.message.id,
        resume_conversation_id=req.resume_conversation_id, chip=req.chip, photo_ids=photo_ids,
    ))
    log.info("chat_queued", extra={
        "conversation_id": conv.id, "inbound_id": inbound_id, "chip": req.chip, "photos": len(photo_ids),
    })
    return await stream_sink(request, deps, sink, conv.id)


async def post_chat_stop(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    """`POST /chat/stop`: 그 `client_msg_id`의 답을 멈춘다(`Dispatcher.stop_message`, 쓰기는 디스패처로만, ADR 0007).

    `{"state": "stopped" | "done" | "unknown"}`. 멈춘 답은 `STOPPED_REPLY`로 끝나고 같은 id의 `/chat`은 그것을
    재생한다(두뇌를 다시 부르지 않는다). 로그에는 상태만 남긴다.
    """
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = ChatStopBody.model_validate(body)
    except ValidationError:
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None, "안전 모드가 아니면 디스패처가 있다"
    state = deps.dispatcher.stop_message(req.client_msg_id)
    log.info("chat_stopped", extra={"state": state})
    return web.json_response(dump(ChatStopped, {"state": state}))


# --- 대화 목록의 쓰기 (SP9 7.3, 7.7). 쓰기는 디스패처로만(ADR 0007) ---

NO_CONVERSATION = "없는 대화예요."


async def post_new_conversation(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    """`POST /conversations/new`: 열린 앱 `chat`·`plan`을 닫는다. 다음 메시지는 새 대화다. `{"closed": [id…]}`."""
    assert deps.dispatcher is not None
    closed = deps.dispatcher.new_conversation()
    return web.json_response(dump(ConversationsClosed, {"closed": closed}))


async def delete_conversation(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    """`DELETE /conversations/{id}`: 앱 대화를 지운다(되돌릴 수 없다). 열린 대화면 먼저 닫는다. 없으면 404."""
    raw = request.match_info["id"]
    if not raw.isascii() or not raw.isdigit() or len(raw) > 18:
        return error_response(404, "not_found", NO_CONVERSATION)
    assert deps.dispatcher is not None
    if not deps.dispatcher.delete_conversation(int(raw)):
        return error_response(404, "not_found", NO_CONVERSATION)
    return web.Response(status=204)


def _message_id(conversation_id: int | None, inbound_id: int | None) -> str | None:
    if conversation_id is None or inbound_id is None:
        return None
    return app_secretary_message_id(conversation_id, inbound_id)


async def _replay(
    request: web.Request, deps: ApiDeps, d: Dispatcher, stored: StoredResponse, checkin_id: int | None
) -> web.StreamResponse:
    """저장한 답을 글 조각 하나로, 확인 문구가 있으면 `data-activity`(활동은 지금 시각으로 다시 판정)와 함께(6.4.1)."""
    body = stored.body or {}
    conv_id = body.get("conversation_id")
    inbound_id = body.get("inbound_id")
    confirmation = body.get("confirmation")
    ids: tuple[list[int], list[int]] = ([], [])
    if confirmation and isinstance(inbound_id, int):
        ids = d.activity_of(inbound_id)
    sink = QueueSink()
    # 처음 알린 `messageId` 그대로(다시 골라 대화가 바뀌었어도 같다, 6.4.1)
    writer = UiMessageWriter(sink, body.get("message_id") or _message_id(conv_id, inbound_id))
    meta = d.chat_metadata(conv_id)
    writer.start({**meta, "checkin_id": checkin_id})
    write_reply(
        writer, str(body.get("reply_text") or ""), activity_ids=ids[0], undo_ids=ids[1], confirmation=confirmation,
        metadata=meta,
    )
    log.info("chat_replayed")
    return await stream_sink(request, deps, sink, conv_id)


async def _direct_reply(
    request: web.Request, deps: ApiDeps, d: Dispatcher, sink: QueueSink, reply: str,
    conversation_id: int | None, checkin_id: int | None,
) -> web.StreamResponse:
    """두뇌를 거치지 않은 답(명령, 글 아닌 메시지). 새 대화는 열지 않는다.

    알리는 대화는 앱이 보낸 id가 열린 앱 대화일 때 그것, 아니면 지금 이어질 앱 대화(`current_app_conversation`)다.
    둘 다 없으면(아직 앱 대화가 없다) `conversation_id: null`이고 `x-conversation-id`는 보내지 않는다(알릴 대화가 없다).
    `inbound_id`가 없으므로 `messageId`도 없다(6.4.6).
    """
    current = d.current_app_conversation(conversation_id)
    conversation_id = current.id if current is not None else None
    writer = UiMessageWriter(sink, None)
    meta = d.chat_metadata(conversation_id)
    writer.start({**meta, "checkin_id": checkin_id})
    write_reply(writer, reply, metadata=meta)
    return await stream_sink(request, deps, sink, conversation_id)


def _transcribe_direct(deps: ApiDeps, user_text: str, reply: str) -> None:
    """명령과 글 아닌 메시지는 텔레그램처럼 대화 밖(`[-]`)으로, 앱 머리글(` @app`)로 남긴다."""
    t = deps.transcripts
    if t is None:
        return
    now = deps.clock.now()
    try:
        t.append(now, "사용자", None, None, user_text, channel="app")
        t.append(now, "비서", None, None, reply, channel="app")
    except OSError as e:
        log.warning("chat_transcript_failed", extra={"error_type": type(e).__name__})


async def stream_sink(
    request: web.Request, deps: ApiDeps, sink: QueueSink, conversation_id: int | None
) -> web.StreamResponse:
    """싱크의 조각을 연결에 흘려 보낸다. 끊기면 떼어 내기만 하고 처리는 그대로 둔다(M7)."""
    headers = dict(STREAM_HEADERS)
    if conversation_id is not None:
        headers["x-conversation-id"] = str(conversation_id)
    headers.update(request.get(CORS_HEADERS_KEY) or {})
    resp = web.StreamResponse(status=200, headers=headers)
    q = sink.attach()
    try:
        await resp.prepare(request)
        await _pump(resp, q, deps.sleep)
        await resp.write_eof()
    except (ConnectionResetError, ConnectionError) as e:
        log.info("chat_stream_disconnected", extra={"error_type": type(e).__name__})
    finally:
        sink.detach(q)
    return resp


async def _pump(
    resp: web.StreamResponse, q: asyncio.Queue[bytes | None], sleep: Callable[[float], Awaitable[None]]
) -> None:
    """큐가 끝(`None`)을 줄 때까지 쓴다. `PING_INTERVAL_S`초 동안 새 조각이 없으면 `: ping`(6.4.1)."""
    getter: asyncio.Task[bytes | None] | None = None
    try:
        while True:
            if getter is None:
                getter = asyncio.ensure_future(q.get())
            timer = asyncio.ensure_future(sleep(PING_INTERVAL_S))
            done, _ = await asyncio.wait({getter, timer}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                timer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await timer
                item = getter.result()
                getter = None
                if item is None:
                    return
                await resp.write(item)
            else:
                await resp.write(SSE_PING)
    finally:
        if getter is not None:
            getter.cancel()

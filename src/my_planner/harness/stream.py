"""앱 채팅의 AI SDK UI message stream (SP3-4 스펙 6.4.1, 7.5 M1·M4·M7·M8).

- `StreamSink`: 조각(dict)을 받는 곳. 앱 요청 하나에 하나(`Inbound.sink`).
- `QueueSink`: HTTP 연결(`attach()`가 준 큐)마다 SSE 바이트를 넣는다. 지난 조각을 모두 기억해 두었다가 나중에
  붙은 연결에도 처음부터 다시 넣는다(M8: 같은 `client_msg_id`가 처리 중에 다시 옴). 연결이 끊겨도 쓰기는 계속
  기억에만 남고 오류를 올리지 않는다(M7).
- `UiMessageWriter`: 조각 모양(`start`, `text-*`, `tool-*`, `data-activity`, `finish`)을 만든다. 싱크가 없어도
  (`sink=None`, 시작 때 다시 넣은 행) 상태만 따라가고 아무 데도 쓰지 않는다.
- `AppReplySender`: 디스패처가 앱 답을 보내는 곳(M4). 두뇌 글·도구 → 하네스 화면 조각(`h_draft_<n>`, `h_mdraft_<n>`, `h_cdraft_<n>`, `h_cond_<n>`)
  → `data-activity`(확인 문구 `confirmation`) → `finish`. 앱 통로에는 `h-confirm` 글 조각이 없다(6.4.1).

로그에는 조각 종류와 개수만 남기고 본문, 도구 인자, 결과는 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from my_planner.timefmt import to_api_times

if TYPE_CHECKING:
    from my_planner.harness.dispatcher import Outbound

log = logging.getLogger(__name__)

SSE_DONE = b"data: [DONE]\n\n"
SSE_PING = b": ping\n\n"
PING_INTERVAL_S = 15
TOOL_PREFIX = "mcp__planner__"


def encode_sse(chunk: dict[str, Any]) -> bytes:
    """`data: <JSON>\\n\\n`. 한글은 그대로, 공백 없이."""
    return b"data: " + json.dumps(chunk, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n\n"


class StreamSink(Protocol):
    def emit(self, chunk: dict[str, Any]) -> None: ...

    def ping(self) -> None: ...

    def close(self) -> None: ...

    @property
    def disconnected(self) -> bool: ...


class QueueSink:
    """연결마다 `asyncio.Queue[bytes | None]`. `None`은 끝(뒤에 `[DONE]`을 이미 넣었다)."""

    def __init__(self) -> None:
        self._history: list[bytes] = []
        self._queues: list[asyncio.Queue[bytes | None]] = []
        self._followers: list[QueueSink] = []
        self._closed = False
        self._ever_attached = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def disconnected(self) -> bool:
        """붙었던 연결이 모두 떨어졌다. 쓰기는 기억에 계속 남는다(나중에 붙는 연결이 받는다)."""
        return self._ever_attached and not self._queues and not self._followers

    def attach(self) -> asyncio.Queue[bytes | None]:
        """새 연결. 지난 조각을 모두 다시 넣고, 이미 끝났으면 끝 표시까지 넣는다."""
        q: asyncio.Queue[bytes | None] = asyncio.Queue()
        for b in self._history:
            q.put_nowait(b)
        if self._closed:
            q.put_nowait(None)
        else:
            self._queues.append(q)
        self._ever_attached = True
        return q

    def detach(self, q: asyncio.Queue[bytes | None]) -> None:
        if q in self._queues:
            self._queues.remove(q)

    def join(self, follower: QueueSink) -> None:
        """다른 요청의 싱크를 덧붙인다(M8). 지난 조각을 처음부터 넘기고, 이후 조각과 끝도 넘긴다."""
        for b in self._history:
            follower._push(b)
        if self._closed:
            follower._end()  # `[DONE]`은 지난 조각에 이미 있다
        else:
            self._followers.append(follower)
        self._ever_attached = True

    def _push(self, b: bytes) -> None:
        if self._closed:
            return
        self._history.append(b)
        for q in self._queues:
            q.put_nowait(b)
        for f in self._followers:
            f._push(b)

    def emit(self, chunk: dict[str, Any]) -> None:
        self._push(encode_sse(chunk))

    def ping(self) -> None:
        """기다리는 연결에 주석 줄. 기억에는 남기지 않는다(다시 붙는 연결에 줄 필요가 없다)."""
        if self._closed:
            return
        for q in self._queues:
            q.put_nowait(SSE_PING)
        for f in self._followers:
            f.ping()

    def close(self) -> None:
        """`[DONE]`을 넣고 끝낸다. 두 번 불러도 한 번만."""
        if self._closed:
            return
        self._push(SSE_DONE)  # 덧붙은 싱크에도 간다
        self._end()

    def _end(self) -> None:
        self._closed = True
        for q in self._queues:
            q.put_nowait(None)
        self._queues.clear()
        for f in self._followers:
            f._end()
        self._followers.clear()


class UiMessageWriter:
    """AI SDK UI message stream 조각을 만든다. `sink`가 None이면 상태만 따라간다(쓰지 않는다)."""

    def __init__(self, sink: StreamSink | None, message_id: str | None) -> None:
        self.sink = sink
        self.message_id = message_id
        self.metadata: dict[str, Any] = {}  # `finish`의 messageMetadata(디스패처가 대화를 고르면 채운다)
        self.step_open = False
        self.finished = False
        self._tool_seq = 0
        self._text_seq = 0
        self._streamed: list[str] = []
        self._blocks: dict[str, list[str]] = {}  # 글 id별 조각(보낸 순서). 재생용 글을 만든다(6.4.1)
        self._attempts = 0
        self.attempt_streamed = False  # 지금 두뇌 시도가 `text-delta`를 보냈는가

    def _emit(self, chunk: dict[str, Any]) -> None:
        if self.sink is None or self.finished:
            return
        try:
            self.sink.emit(chunk)
        except Exception as e:  # noqa: BLE001 - 끊긴 연결은 조용히 넘긴다(M7). 종류만 남긴다
            log.warning("chat_stream_write_error", extra={"error_type": type(e).__name__})

    # --- 이름 ---

    def next_tool_call_id(self) -> str:
        self._tool_seq += 1
        return f"tc_{self._tool_seq:02d}"

    def next_text_id(self) -> str:
        self._text_seq += 1
        return f"t{self._text_seq}"

    # --- 조각 ---

    def start(self, metadata: dict[str, Any]) -> None:
        chunk: dict[str, Any] = {"type": "start"}
        if self.message_id is not None:
            chunk["messageId"] = self.message_id
        chunk["messageMetadata"] = metadata
        self._emit(chunk)

    def status(self, state: str) -> None:
        self._emit({"type": "data-status", "data": {"state": state}, "transient": True})

    def start_step(self) -> None:
        if self.step_open:
            return
        self.step_open = True
        self._emit({"type": "start-step"})

    def finish_step(self) -> None:
        if not self.step_open:
            return
        self.step_open = False
        self._emit({"type": "finish-step"})

    def text_start(self, id: str) -> None:
        self._emit({"type": "text-start", "id": id})

    def begin_attempt(self) -> None:
        """두뇌 시도 하나가 시작한다(첫 시도, resume 실패 대체, 오류 재시도 모두).

        앞 시도가 글 조각을 이미 보냈으면 되돌릴 수 없다: 그 글은 그대로 두고 `finish-step`, `start-step`으로 이
        시도를 새 단계로 나눈다(글 id는 `next_text_id`가 새로 준다, 열린 글 블록은 두뇌가 이미 닫았다).
        그래야 재시도의 글이 정상 스트림으로 가고, 끝난 뒤 글 블록을 다시 보내지도 않는다(06b).
        """
        if self._attempts and self.attempt_streamed:
            self.finish_step()
            self.start_step()
        self._attempts += 1
        self.attempt_streamed = False

    def text_delta(self, id: str, delta: str) -> None:
        self._streamed.append(delta)
        self._blocks.setdefault(id, []).append(delta)
        self.attempt_streamed = True
        self._emit({"type": "text-delta", "id": id, "delta": delta})

    def text_end(self, id: str) -> None:
        self._emit({"type": "text-end", "id": id})

    def text(self, id: str, whole: str) -> None:
        """글 블록 하나를 한 번에(S11 대체 경로: 두뇌가 끝난 뒤 `text-delta` 하나)."""
        self.text_start(id)
        self.text_delta(id, whole)
        self.text_end(id)

    def tool_input(self, call_id: str, name: str, input: dict[str, Any]) -> None:
        self._emit({
            "type": "tool-input-available", "toolCallId": call_id,
            "toolName": name.removeprefix(TOOL_PREFIX), "input": input,
        })

    def tool_output(self, call_id: str, output: Any) -> None:
        self._emit({"type": "tool-output-available", "toolCallId": call_id, "output": output})

    def tool_error(self, call_id: str, error_text: str) -> None:
        self._emit({"type": "tool-output-error", "toolCallId": call_id, "errorText": error_text})

    def data_activity(self, activity_ids: list[int], undo_ids: list[int], confirmation: str | None) -> None:
        self._emit({
            "type": "data-activity",
            "data": {"activity_ids": list(activity_ids), "undo_ids": list(undo_ids), "confirmation": confirmation},
        })

    def finish(self, metadata: dict[str, Any] | None = None) -> None:
        """`finish` 조각, 그다음 `[DONE]`(싱크를 닫는다)."""
        if self.finished:
            return
        self._emit({"type": "finish", "messageMetadata": metadata if metadata is not None else self.metadata})
        self.finished = True
        if self.sink is not None:
            try:
                self.sink.close()
            except Exception as e:  # noqa: BLE001
                log.warning("chat_stream_close_error", extra={"error_type": type(e).__name__})

    @property
    def streamed_reply(self) -> str:
        """보낸 글 블록 전부를 스트림에서 보인 대로(블록 사이 빈 줄) 이은 글. 저장·재생의 글(6.4.1)."""
        parts = ("".join(b).strip() for b in self._blocks.values())
        return "\n\n".join(p for p in parts if p)

    @property
    def streamed_text(self) -> str:
        """지금까지 `text-delta`로 보낸 글(06b가 조각 스트리밍 뒤 남은 글을 가릴 때 쓴다)."""
        return "".join(self._streamed)


HarnessCard = tuple[str, str, dict[str, Any], dict[str, Any]]  # (toolCallId 앞머리, 컴포넌트, props, 출력)
MILESTONE_CARD_MAX = 10  # `ui_milestone_draft.milestone_ids` 상한(6.4.7)
CHAPTER_CARD_MAX = 5  # `ui_chapter_draft.chapter_ids` 상한


def _chunks(ids: list[int], n: int) -> list[list[int]]:
    return [list(ids[i:i + n]) for i in range(0, len(ids), n)]


def harness_cards(out: Outbound) -> list[HarnessCard]:
    """하네스 화면 조각(6.4.1, 6.4.7). 텔레그램 버튼 줄과 같은 재료, 같은 순서(할 일 초안 → 사건 → 챕터 → 컨디션).
    단 SP7 텔레그램의 습관 줄은 일부러 스트림에 없다: 습관 카드는 체크인 상세 `cards`와 두뇌가 그리는 `ui_habit_check`에만 있다.

    확인 카드 `ui_confirm`(`out.confirms`)은 여기서 만들지 않는다: 회차 차례에서만 생기고 앱은 체크인 상세 `cards`로
    받는다(10.1 A5, `harness.checkins.checkin_cards`). `/chat`은 늘 사용자 차례라 확인 토큰이 없다.

    초안 카드 `ui_todo_draft`의 출력은 `{"ok": true, "data": {"todos": [TodoRef]}}`(초안 포함, 디스패처가 채운
    `out.draft_todos`), 사건·챕터 초안 카드는 `{"ok": true, "data": {"milestones": […]}}`·`{"data": {"chapters": […]}}`
    (`out.draft_milestones`, `out.draft_chapters`), 컨디션 고르기는 `{"ok": true}`다.
    """
    cards: list[HarnessCard] = []
    if out.draft_task_ids:
        todos = list(out.draft_todos or [])
        cards.append(("h_draft", "ui_todo_draft", {"task_ids": list(out.draft_task_ids)},
                      {"ok": True, "data": {"todos": todos}}))
    # 사건·챕터 초안(11.3): 할 일 초안 다음, 텔레그램 `m:`·`h:` 줄과 같은 순서. props 상한(10개, 5개)마다 나눈다
    milestones = {m["id"]: m for m in out.draft_milestones or []}
    for ids in _chunks(out.draft_milestone_ids, MILESTONE_CARD_MAX):
        cards.append(("h_mdraft", "ui_milestone_draft", {"milestone_ids": ids},
                      {"ok": True, "data": {"milestones": [milestones[i] for i in ids if i in milestones]}}))
    chapters = {c["id"]: c for c in out.draft_chapters or []}
    for ids in _chunks(out.draft_chapter_ids, CHAPTER_CARD_MAX):
        cards.append(("h_cdraft", "ui_chapter_draft", {"chapter_ids": ids},
                      {"ok": True, "data": {"chapters": [chapters[i] for i in ids if i in chapters]}}))
    if out.ask_condition_for is not None:
        cards.append(("h_cond", "ui_condition_picker", {"date": out.ask_condition_for.isoformat()}, {"ok": True}))
    return cards


def write_reply(
    writer: UiMessageWriter, text: str, *, activity_ids: list[int] | None = None, undo_ids: list[int] | None = None,
    confirmation: str | None = None, metadata: dict[str, Any] | None = None, streamed: bool = False,
    cards: list[HarnessCard] | None = None,
) -> None:
    """글 블록 하나로 끝나는 답(고정 문구, 명령, 재생, 조각이 오지 않은 두뇌 답: S11 대체 경로).

    순서: start-step → 글 → 하네스 화면 조각 → finish-step → data-activity → finish. 하네스 조각의 `toolCallId`는
    `<앞머리>_<n>`이고 `n`은 그 답 안의 순번(1부터)이다. 활동도 확인 문구도 없으면 `data-activity`를 보내지 않는다(6.4.1).
    """
    writer.start_step()
    if text and not streamed:  # streamed: 두뇌 글이 이미 조각으로 나갔다(상태가 ok일 때만, 고정 안내는 늘 보낸다)
        writer.text(writer.next_text_id(), text)
    for n, (prefix, component, props, output) in enumerate(cards or [], start=1):
        call_id = f"{prefix}_{n}"
        writer.tool_input(call_id, component, props)
        writer.tool_output(call_id, to_api_times(output))  # `data.todos[].scheduled_at`도 UTC `Z`(6.1)
    writer.finish_step()
    if activity_ids or confirmation:
        writer.data_activity(list(activity_ids or []), list(undo_ids or []), confirmation)
    writer.finish(metadata)


class AppReplySender:
    """디스패처의 앱 답(M4). `Outbound.writer`에 쓴다. 싱크가 없거나 끊겼으면 조용히 그만둔다(M6·M7)."""

    async def send(self, out: Outbound) -> None:
        w = out.writer
        if w is None or w.finished:
            return
        try:
            write_reply(
                w, out.text, activity_ids=out.activity_ids, undo_ids=out.undo_ids, confirmation=out.confirmation,
                streamed=out.streamed, cards=harness_cards(out),
            )
        except Exception as e:  # noqa: BLE001 - 앱 답은 오류를 올리지 않는다(M7)
            log.warning("app_reply_error", extra={"error_type": type(e).__name__})

    async def typing(self) -> None:
        return None

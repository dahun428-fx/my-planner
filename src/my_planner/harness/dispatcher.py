"""직렬 디스패처: 메시지(와 이후 티켓의 회차) → 두뇌 → 응답 (스펙 4, 5.3)."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol

from my_planner.clock import Clock
from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.harness.brain import Brain, BrainResult
from my_planner.clock import logical_date
from my_planner.harness.context import build_notices, build_preamble
from my_planner.harness.redact import redact
from my_planner.tools.confirmations import render_confirmations

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.harness.conversations import ConversationRouter
    from my_planner.store.repos.conversations import ConversationsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.store.transcripts import TranscriptStore
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)


@dataclass
class Inbound:
    text: str
    at: datetime  # 하네스가 받은 시각(UTC)
    sent_at: datetime  # 텔레그램이 기록한 보낸 시각
    update_ids: list[int]


@dataclass
class Outbound:
    text: str
    draft_conversation_id: int | None = None
    draft_task_ids: list[int] = field(default_factory=list)
    ask_condition_for: date | None = None


class Sender(Protocol):
    async def send(self, out: Outbound) -> None: ...

    async def typing(self) -> None: ...


# 큐 우선순위(작을수록 먼저). 회차는 티켓 05에서 들어온다.
_PRIORITY_MESSAGE = 10
_PRIORITY_STOP = 1_000_000

TYPING_INTERVAL_S = 5

FALLBACK_REPLY = "지금 잠깐 생각이 안 돼요. 조금 뒤에 다시 말씀해 주세요."
MAX_TURNS_REPLY = "정리하다가 길어졌어요. 이어서 말씀해 주시면 계속할게요."


class Dispatcher:
    """작업자 하나가 `asyncio.PriorityQueue`에서 하나씩 꺼내 직렬로 처리한다."""

    def __init__(
        self,
        *,
        brain: Brain,
        sender: Sender,
        convs: ConversationsRepo,
        state: StateRepo,
        transcripts: TranscriptStore,
        clock: Clock,
        settings: Settings,
        router: ConversationRouter,
        tools: Tools | None = None,
        keep_awake: Callable[[], AbstractContextManager[Any]] = nullcontext,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.brain = brain
        self.sender = sender
        self.convs = convs
        self.state = state
        self.transcripts = transcripts
        self.clock = clock
        self.settings = settings
        self.router = router
        self.tools = tools
        self._keep_awake = keep_awake
        self._sleep = sleep
        self._queue: asyncio.PriorityQueue[tuple[int, int, Any]] = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._worker: asyncio.Task[None] | None = None

    # --- 수명 ---

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="dispatcher")

    async def stop(self, timeout: float = 30) -> None:
        """큐에 든 것까지 처리하고 멈춘다. `timeout`초 안에 끝나지 않으면 작업을 취소한다."""
        worker = self._worker
        if worker is None:
            return
        self._queue.put_nowait((_PRIORITY_STOP, next(self._seq), None))
        try:
            await asyncio.wait_for(asyncio.shield(worker), timeout)
        except TimeoutError:
            log.warning("dispatcher_stop_timeout", extra={"timeout_s": timeout})
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._worker = None

    def submit_message(self, m: Inbound) -> None:
        self._queue.put_nowait((_PRIORITY_MESSAGE, next(self._seq), m))

    async def _work(self) -> None:
        while True:
            _, _, item = await self._queue.get()
            if item is None:
                return
            batch = [item, *self._drain_messages()]
            try:
                await self._handle_messages(batch)
            except Exception:
                ids = [i for m in batch for i in m.update_ids]
                log.exception("message_handling_error", extra={"update_ids": ids})

    def _drain_messages(self) -> list[Inbound]:
        """쌓여 있는 메시지를 모두 꺼낸다(도착 순서). 메시지가 아닌 항목은 제자리로 돌려 놓는다."""
        taken: list[tuple[int, int, Any]] = []
        while True:
            try:
                taken.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        msgs: list[Inbound] = []
        for entry in taken:
            if isinstance(entry[2], Inbound):
                msgs.append(entry[2])
            else:
                self._queue.put_nowait(entry)
        return msgs

    # --- 메시지 처리 ---

    async def _handle_messages(self, batch: list[Inbound]) -> None:
        """쌓인 메시지를 두뇌 호출 한 번으로 처리한다. 본문은 두 줄 바꿈으로 잇고 update_id는 모두 기록한다."""
        update_ids = [i for m in batch for i in m.update_ids]
        redacted_parts = [redact(m.text) for m in batch]
        text = "\n\n".join(t for t, _ in redacted_parts)
        limits = self.settings.limits
        truncated = len(text) > limits.input_max_chars
        if truncated:
            text = text[: limits.input_max_chars]
        age = self.clock.now() - min(m.sent_at for m in batch)
        stale_hours = age.total_seconds() / 3600
        notices = build_notices(
            redacted=any(r for _, r in redacted_parts),
            stale_hours=stale_hours if stale_hours > limits.stale_message_hours else None,
            truncated=truncated,
        )
        conv = self.router.for_user_message(batch[0].at)

        run_ctx = RunContext(conversation_id=conv.id, run_id=None, events=[])
        body = f"## 메시지\n{text}"
        with self._keep_awake():
            fell_back = False
            for m in batch:
                self.transcripts.append(m.at, "사용자", conv.id, None, redact(m.text)[0])
            resumed = conv.session_id is not None
            prompt = _join(
                notices, "" if resumed else prompts.load("chat.md"), self._preamble(resumed), body
            )
            result = await self._call_brain(prompt, session_id=conv.session_id, run_ctx=run_ctx)
            if resumed and result.resume_failed:
                # 새 세션으로 다시 부른다. 이 대화의 최근 원문 20개를 붙인다(방금 기록한 지금 메시지는 뺀다).
                history = self.transcripts.recent(conv.id, 20, skip_last=len(batch))
                prompt = _join(
                    notices,
                    prompts.load("chat.md"),
                    self._preamble(False),
                    f"## 최근 대화\n{history}" if history else "",
                    body,
                )
                fell_back = True
                run_ctx = RunContext(conversation_id=conv.id, run_id=None, events=[])
                result = await self._call_brain(prompt, session_id=None, run_ctx=run_ctx)
            if result.session_id or fell_back:  # 대체 경로가 세션을 못 얻었으면 깨진 세션 ID를 지운다
                self.convs.set_session(conv.id, result.session_id)
            self.convs.touch(conv.id)

            reply = _reply_for(result)
            confirmations = render_confirmations(run_ctx.events, self._today())
            if confirmations:  # 두뇌 답, 빈 줄, 확인 문구. 도구를 안 불렀으면 빈 줄도 없다
                reply = f"{reply}\n\n{confirmations}"
            self.transcripts.append(
                self.clock.now(), "비서", conv.id, None, redact(reply)[0], tools=list(run_ctx.tool_names)
            )
            await self.sender.send(Outbound(text=reply))
        # 전송까지 끝난 뒤에만 처리 완료로 기록한다(전송 전에 죽으면 다시 처리될 수 있다).
        self.state.mark_updates_done(update_ids)
        log.info(
            "message_handled",
            extra={
                "conversation_id": conv.id,
                "update_ids": update_ids,
                "chars": sum(len(m.text) for m in batch),
            },
        )

    def _today(self) -> date:
        return logical_date(self.clock.now(), self.settings.timezone, self.settings.day_boundary)

    def _preamble(self, resumed: bool) -> str:
        """새 세션일 때만 붙인다: 지금 시각, 열린 할 일, 오늘 일정."""
        if resumed or self.tools is None:
            return ""
        return build_preamble(
            now=self.clock.now(),
            tz=self.settings.timezone,
            boundary=self.settings.day_boundary,
            tasks=self.tools.tasks,
            conditions=self.tools.conditions,
        )

    async def _call_brain(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext
    ) -> BrainResult:
        """두뇌를 부르는 동안 5초마다 '입력 중'을 보낸다."""
        typing = asyncio.create_task(self._typing_loop(), name="typing")
        started = time.monotonic()
        try:
            result = await self.brain.run(prompt, session_id=session_id, run_ctx=run_ctx)
        finally:
            typing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing
        # 본문과 도구 인자는 남기지 않는다. 소요 시간, 턴 수, 도구 이름, 결과 상태만.
        log.info(
            "brain_call",
            extra={
                "conversation_id": run_ctx.conversation_id,
                "run_id": run_ctx.run_id,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "turns": result.turns,
                "tool_names": list(run_ctx.tool_names),
                "status": result.status,
                "error": result.error,
                "resumed": session_id is not None,
            },
        )
        return result

    async def _typing_loop(self) -> None:
        while True:
            try:
                await self.sender.typing()
            except Exception as e:  # 입력 중 표시는 없어도 된다
                log.warning("typing_error", extra={"error_type": type(e).__name__})
            await self._sleep(TYPING_INTERVAL_S)


def _join(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


def _reply_for(result: BrainResult) -> str:
    """티켓 01은 정상 답과 턴 상한만 구분한다. 로그인·한도 문구는 티켓 10에서 붙인다."""
    if result.status == "ok" and result.text.strip():
        return result.text
    if result.status == "max_turns":
        return MAX_TURNS_REPLY
    return FALLBACK_REPLY

"""직렬 디스패처: 메시지와 회차 → 두뇌 → 응답 (스펙 4, 5.3, 5.4)."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, logical_date
from my_planner.domain import (
    ConversationKind,
    LoopKey,
    RunContext,
    RunStatus,
    SkipReason,
)
from my_planner.harness import prompts
from my_planner.harness.brain import Brain, BrainResult
from my_planner.harness.context import build_notices, build_preamble
from my_planner.harness.redact import redact
from my_planner.loop.schedule import Due, limit_for, reply_window_end
from my_planner.tools.confirmations import render_confirmations

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.harness.conversations import ConversationRouter
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.conversations import Conversation, ConversationsRepo
    from my_planner.store.repos.runs import Run, RunsRepo
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


@dataclass
class _RunJob:
    run: Run
    merged: list[Run]


@dataclass
class _ResendJob:
    """전송이 끝내 안 된 회차를 5분 뒤 전송만 한 번 더 한다. 두뇌는 다시 부르지 않는다."""

    run: Run
    merged: list[Run]
    tool_names: list[str]
    draft_task_ids: list[int] = field(default_factory=list)
    ask_condition_for: date | None = None


# 큐 우선순위(작을수록 먼저). 같은 우선순위는 들어온 순서.
_PRIORITY_MESSAGE = 0  # 사용자 메시지가 회차보다 먼저
_PRIORITY_RUN = 1
_PRIORITY_STOP = 1_000_000

# 루프별 지시문 파일 (스펙 5.3 "프롬프트 선택")
LOOP_PROMPTS = {
    LoopKey.morning_brief: "morning_brief.md",
    LoopKey.evening_checkin: "evening_checkin.md",
    LoopKey.review: "review_week.md",
    LoopKey.return_: "return.md",
}

TYPING_INTERVAL_S = 5
SEND_ATTEMPTS = 3  # 회차 전송은 바로 3회까지(스펙 5.4, 7)
SEND_RETRY_DELAYS_S = (1, 2, 4)  # 시도 사이 간격. 3회라 앞의 두 값(1, 2초)만 쓰인다
RESEND_DELAY_S = 5 * 60
MAX_RUN_ATTEMPTS = 2  # 회차당 두뇌 호출 최대 2회

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
        runs: RunsRepo | None = None,
        conditions: ConditionsRepo | None = None,
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
        self.runs = runs
        self.conditions = conditions
        self._keep_awake = keep_awake
        self._sleep = sleep
        self._queue: asyncio.PriorityQueue[tuple[int, int, Any]] = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._worker: asyncio.Task[None] | None = None
        self._timers: set[asyncio.Task[None]] = set()
        self._stopping = False

    # --- 수명 ---

    def start(self) -> None:
        self._stopping = False
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name="dispatcher")

    async def stop(self, timeout: float = 30) -> None:
        """큐에 든 것까지 처리하고 멈춘다. `timeout`초 안에 끝나지 않으면 작업을 취소한다."""
        # 아직 기다리는 5분 뒤 재전송은 취소하고, 멈추는 동안에는 새로 만들지 않는다.
        # 시작 시 복구(스펙 5.1 4단계, 티켓 12)가 이어받는다.
        self._stopping = True
        self._cancel_timers()
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
        self._cancel_timers()  # 혹시 남은 것까지
        self._worker = None

    def _cancel_timers(self) -> None:
        for t in list(self._timers):
            t.cancel()
        self._timers.clear()

    def submit_message(self, m: Inbound) -> None:
        self._queue.put_nowait((_PRIORITY_MESSAGE, next(self._seq), m))

    def submit_run(self, run: Run, merged: list[Run]) -> None:
        """러너가 `queued`로 바꾼 회차를 넣는다. `merged`는 이 회차에 합쳐 함께 처리할 회차다."""
        self._queue.put_nowait((_PRIORITY_RUN, next(self._seq), _RunJob(run, list(merged))))

    async def _work(self) -> None:
        while True:
            _, _, item = await self._queue.get()
            if item is None:
                return
            if isinstance(item, _RunJob):
                try:
                    await self._handle_run(item.run, item.merged)
                except Exception:
                    log.exception("run_handling_error", extra={"run_id": item.run.id})
                continue
            if isinstance(item, _ResendJob):
                try:
                    await self._resend_run(item)
                except Exception:
                    log.exception("run_resend_error", extra={"run_id": item.run.id})
                continue
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
        body = _join(self._recorded_condition(), f"## 메시지\n{text}")
        with self._keep_awake():
            fell_back = False
            for m in batch:
                self.transcripts.append(m.at, "사용자", conv.id, None, redact(m.text)[0])
            resumed = conv.session_id is not None
            # 회차 대화에 답할 때는 지시문 없이 메시지만 넘긴다(스펙 5.3 "프롬프트 선택").
            instructions = "" if conv.kind is ConversationKind.run else prompts.load("chat.md")
            history = ""
            if not resumed and conv.kind is ConversationKind.run:
                # 세션이 없는 회차 대화: 두뇌가 자기가 보낸 회차 메시지를 알도록 최근 원문을 붙인다.
                history = self.transcripts.recent(conv.id, 20, skip_last=len(batch))
            prompt = _join(
                notices,
                "" if resumed else instructions,
                self._preamble(resumed),
                f"## 최근 대화\n{history}" if history else "",
                body,
            )
            result = await self._call_brain(prompt, session_id=conv.session_id, run_ctx=run_ctx)
            if resumed and result.resume_failed:
                # 새 세션으로 다시 부른다. 이 대화의 최근 원문 20개를 붙인다(방금 기록한 지금 메시지는 뺀다).
                history = self.transcripts.recent(conv.id, 20, skip_last=len(batch))
                prompt = _join(
                    notices,
                    instructions,
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
            await self.sender.send(_outbound(reply, run_ctx))
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

    # --- 회차 실행 (스펙 5.4: 두 단계) ---

    async def _handle_run(self, run: Run, merged: list[Run]) -> None:
        assert self.runs is not None, "회차를 실행하려면 runs가 있어야 한다"
        runs = self.runs
        if self._past_limit(run):
            # 대기하는 동안 한계가 지났다(스펙 5.4 R5). 합친 회차도 함께 건너뛴다.
            for r in (run, *merged):
                runs.mark_skipped(r.id, SkipReason.late)
            log.info("run_skipped_late_at_start", extra={"run_id": run.id})
            return
        with self._keep_awake():
            # (a) 두뇌 호출 → 보낼 본문을 outbound_text에 저장. 예외가 나도 회차를 running에 두지 않는다.
            try:
                prepared = await self._prepare_run(run, merged)
            except Exception:
                log.exception("run_brain_exception", extra={"run_id": run.id})
                for r in (run, *merged):
                    runs.mark_failed(r.id, "exception")
                return
            if prepared is None:
                return
            conv, out, tool_names = prepared
            # (b) 전송: 바로 3회까지. 그래도 안 되면 failed로 두고 5분 뒤 전송만 한 번 더
            if await self._send_run(out, run.id, attempts=SEND_ATTEMPTS):
                self._run_delivered(run, merged, conv, out.text, tool_names)
                return
            for r in (run, *merged):
                runs.mark_failed(r.id, "send")
            self._later(
                RESEND_DELAY_S,
                _ResendJob(run, merged, tool_names, list(out.draft_task_ids), out.ask_condition_for),
            )

    async def _prepare_run(
        self, run: Run, merged: list[Run]
    ) -> tuple[Conversation, Outbound, list[str]] | None:
        """두뇌 단계. 보낼 것이 없으면(두뇌 실패) 회차를 failed로 두고 None."""
        assert self.runs is not None
        runs = self.runs
        runs.mark_running(run.id)
        conv = self.router.for_run(run)
        runs.set_conversation(run.id, conv.id)
        ask = self._ask_condition_for(run, merged)
        result, run_ctx = await self._run_brain(run, merged, conv, ask)
        if not _run_ok(result) and self._may_rerun(run, result):
            runs.mark_running(run.id)
            result, run_ctx = await self._run_brain(run, merged, conv, ask)
        if not _run_ok(result):
            # 사용자에게는 아무것도 보내지 않는다(스펙 5.4 재실행 규칙 4). 로그만 남긴다.
            for r in (run, *merged):
                runs.mark_failed(r.id, result.status)
            self.convs.close(conv.id)
            log.warning("run_brain_failed", extra={"run_id": run.id, "status": result.status})
            return None
        if result.session_id:
            self.convs.set_session(conv.id, result.session_id)
        text = result.text
        confirmations = render_confirmations(run_ctx.events, self._today())
        if confirmations:
            text = f"{text}\n\n{confirmations}"
        runs.save_outbound(run.id, text)
        out = _outbound(text, run_ctx)
        out.ask_condition_for = ask
        return conv, out, list(run_ctx.tool_names)

    async def _run_brain(
        self, run: Run, merged: list[Run], conv: Conversation, ask: date | None = None
    ) -> tuple[BrainResult, RunContext]:
        """루프 지시문(합친 회차의 지시문을 뒤에 이어 붙임)과 앞머리로 새 세션을 연다.

        컨디션 버튼을 붙이는 회차면 두뇌가 알고 쓰도록 `## 컨디션 버튼`을 덧붙인다.
        """
        run_ctx = RunContext(conversation_id=conv.id, run_id=run.id, events=[])
        prompt = _join(
            *(prompts.load(LOOP_PROMPTS[r.loop]) for r in (run, *merged)),
            self._preamble(False, merged=[m.loop.value for m in merged] or None),
            _condition_buttons_note(ask),
        )
        return await self._call_brain(prompt, session_id=None, run_ctx=run_ctx), run_ctx

    def _ask_condition_for(self, run: Run, merged: list[Run] | None = None) -> date | None:
        """컨디션 버튼의 날짜(스펙 5.4). 저녁 체크인은 그 회차의 논리적 날짜다.

        저녁 체크인이 다른 회차(예: 일요일 회고)에 합쳐졌어도 그 저녁 체크인의 날짜를 쓴다.
        """
        if self.conditions is None:
            return None
        s = self.settings
        for r in (run, *(merged or [])):
            if r.loop is LoopKey.evening_checkin:
                return logical_date(r.scheduled_for, s.timezone, s.day_boundary)
        today = logical_date(run.scheduled_for, s.timezone, s.day_boundary)
        if run.loop is LoopKey.morning_brief:
            # 어제 기록이 없고 어제 저녁 체크인이 done이 아니면(늦음, 복귀 인사, 멈춤 등 이유와 상관없이) 어제를 묻는다
            yesterday = today - timedelta(days=1)
            if self.conditions.get(yesterday) is None and not self._evening_done(yesterday):
                return yesterday
        return None

    def _recorded_condition(self) -> str:
        """오늘과 어제(논리적 날짜) 기록된 컨디션. 버튼은 두뇌를 거치지 않으니 매 호출 메시지 앞에 알린다."""
        if self.conditions is None:
            return ""
        today = self._today()
        lines = []
        for label, d in (("어제", today - timedelta(days=1)), ("오늘", today)):
            c = self.conditions.get(d)
            if c is not None:
                lines.append(f"- {label}({d.month}/{d.day}): {c.score}/5")
        return "## 기록된 컨디션\n" + "\n".join(lines) if lines else ""

    def _evening_done(self, d: date) -> bool:
        """그 논리적 날짜의 저녁 체크인 회차가 done인지. 회차가 없으면 done이 아니다."""
        assert self.runs is not None
        s = self.settings
        start = datetime.combine(d, s.day_boundary, ZoneInfo(s.timezone))
        runs = self.runs.between(start - timedelta(microseconds=1), start + timedelta(days=1))
        return any(
            r.loop is LoopKey.evening_checkin
            and r.status is RunStatus.done
            and logical_date(r.scheduled_for, s.timezone, s.day_boundary) == d
            for r in runs
        )

    def _may_rerun(self, run: Run, result: BrainResult) -> bool:
        """두뇌 단계 오류는 도구 이벤트가 하나도 없고 한계 안일 때만 한 번 다시 실행한다.

        `auth_error`, `rate_limited`, `max_turns`는 다시 실행하지 않는다(티켓 10이 따로 다룬다).
        """
        assert self.runs is not None
        if result.status != "error":
            return False
        current = self.runs.get(run.id)
        if current is None or current.attempt >= MAX_RUN_ATTEMPTS or self.runs.has_tool_events(run.id):
            return False
        return not self._past_limit(run)

    def _past_limit(self, run: Run) -> bool:
        s = self.settings
        due = Due(run.loop, run.scheduled_for, run.cadence)
        return self.clock.now() > limit_for(due, s, s.timezone, s.day_boundary)

    async def _send_run(self, out: Outbound, run_id: int, *, attempts: int) -> bool:
        for i in range(attempts):
            try:
                await self.sender.send(out)
                return True
            except Exception as e:  # noqa: BLE001 - 어떤 전송 오류든 다시 시도한다. 본문 없이 종류만 남긴다
                log.warning(
                    "run_send_error", extra={"run_id": run_id, "try": i + 1, "error_type": type(e).__name__}
                )
                if i + 1 < attempts:
                    await self._sleep(SEND_RETRY_DELAYS_S[i])
        return False

    def _later(self, delay: float, job: _ResendJob) -> None:
        if self._stopping:
            log.info("resend_deferred_to_restart", extra={"run_id": job.run.id})
            return
        async def wait_then_put() -> None:
            await self._sleep(delay)
            self._queue.put_nowait((_PRIORITY_RUN, next(self._seq), job))

        t = asyncio.create_task(wait_then_put(), name=f"resend-{job.run.id}")
        self._timers.add(t)
        t.add_done_callback(self._timers.discard)

    async def _resend_run(self, job: _ResendJob) -> None:
        assert self.runs is not None
        run = self.runs.get(job.run.id)
        if run is None or run.status != "failed" or not run.outbound_text or run.resent:
            return
        self.runs.mark_resent(run.id)
        s = self.settings
        due = Due(run.loop, run.scheduled_for, run.cadence)
        if self.clock.now() > reply_window_end(due, s.timezone, s.day_boundary, cfg=s):
            # 답장 창 밖이면 보내지 않는다(시작 시 복구와 같은 규칙, 스펙 5.1 4단계)
            log.info("resend_skipped_outside_reply_window", extra={"run_id": run.id})
            return
        conv = self.convs.get(run.conversation_id) if run.conversation_id is not None else None
        with self._keep_awake():
            out = Outbound(
                text=run.outbound_text,
                draft_conversation_id=run.conversation_id if job.draft_task_ids else None,
                draft_task_ids=list(job.draft_task_ids),
                ask_condition_for=job.ask_condition_for,
            )
            if await self._send_run(out, run.id, attempts=1) and conv is not None:
                self._run_delivered(run, job.merged, conv, run.outbound_text, job.tool_names)

    def _run_delivered(
        self, run: Run, merged: list[Run], conv: Conversation, text: str, tool_names: list[str]
    ) -> None:
        """전송이 끝난 회차: primary와 merged 모두 done, 먼저 보낸 메시지 수 +1, 그다음 원문 기록과 대화 갱신."""
        assert self.runs is not None
        # 사용자는 이미 받았다. 상태와 카운터를 먼저 기록해 다음 시작 때 다시 보내지 않게 한다.
        for r in (run, *merged):
            self.runs.mark_done(r.id)
        self.state.incr_usage(self._today(), "proactive_messages")
        try:
            self.transcripts.append(
                self.clock.now(), "비서", conv.id, run.loop.value, redact(text)[0], tools=tool_names
            )
        except Exception:
            log.exception("run_transcript_error", extra={"run_id": run.id})
        try:
            self.convs.touch(conv.id)
        except Exception:
            log.exception("run_touch_error", extra={"run_id": run.id})
        log.info("run_done", extra={"run_id": run.id, "loop": run.loop.value, "conversation_id": conv.id})

    def _today(self) -> date:
        return logical_date(self.clock.now(), self.settings.timezone, self.settings.day_boundary)

    def _preamble(self, resumed: bool, *, merged: list[str] | None = None) -> str:
        """새 세션일 때만 붙인다: 지금 시각, 열린 할 일, 오늘 일정(, 함께 처리하는 회차)."""
        if resumed or self.tools is None:
            return ""
        return build_preamble(
            now=self.clock.now(),
            tz=self.settings.timezone,
            boundary=self.settings.day_boundary,
            tasks=self.tools.tasks,
            conditions=self.tools.conditions,
            merged=merged,
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
            except Exception as e:  # noqa: BLE001 - 입력 중 표시는 없어도 된다
                log.warning("typing_error", extra={"error_type": type(e).__name__})
            await self._sleep(TYPING_INTERVAL_S)


def _outbound(text: str, run_ctx: RunContext) -> Outbound:
    """이번 호출에서 제안한 초안이 있으면 버튼을 붙이도록 id와 대화를 싣는다(스펙 5.7)."""
    confirmed = {e.task_id for e in run_ctx.events if e.kind == "tasks_confirmed"}
    ids = [
        i
        for e in run_ctx.events
        if e.kind == "tasks_proposed"
        for i in e.data.get("ids", [])
        if i not in confirmed  # 같은 턴에 이미 확정한 것에는 버튼을 붙이지 않는다
    ]
    return Outbound(
        text=text,
        draft_conversation_id=run_ctx.conversation_id if ids else None,
        draft_task_ids=ids,
    )


def _condition_buttons_note(d: date | None) -> str:
    if d is None:
        return ""
    return f"## 컨디션 버튼\n이 메시지 아래에 {d.month}/{d.day}({_WEEKDAY[d.weekday()]}) 컨디션 버튼(1~5)이 붙습니다."


_WEEKDAY = "월화수목금토일"


def _join(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


def _run_ok(result: BrainResult) -> bool:
    return result.status == "ok" and bool(result.text.strip())


def _reply_for(result: BrainResult) -> str:
    """티켓 01은 정상 답과 턴 상한만 구분한다. 로그인·한도 문구는 티켓 10에서 붙인다."""
    if result.status == "ok" and result.text.strip():
        return result.text
    if result.status == "max_turns":
        return MAX_TURNS_REPLY
    return FALLBACK_REPLY

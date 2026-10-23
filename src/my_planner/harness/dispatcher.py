"""직렬 디스패처: 메시지와 회차 → 두뇌 → 응답 (스펙 4, 5.3, 5.4)."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

from my_planner.clock import Clock, from_iso, local, logical_date, period_of, to_iso
from my_planner.domain import (
    Cadence,
    ConversationKind,
    LoopKey,
    RunContext,
    RunStatus,
    SkipReason,
    TaskStatus,
)
from my_planner.harness import prompts
from my_planner.harness.brain import RATE_LIMIT_FALLBACK, Brain, BrainResult
from my_planner.harness.context import build_notices, build_preamble
from my_planner.harness.redact import redact
from my_planner.loop.catchup import merge_order
from my_planner.loop.schedule import Due, limit_for, reply_window_end
from my_planner.store.repos.state import (
    CARRY_REVIEW_KEY,
    LAST_AUTH_NOTICE_KEY,
    LAST_RATE_LIMIT_NOTICE_KEY,
    LIMITED_UNTIL_KEY,
    PAUSE_UNTIL_KEY,
)
from my_planner.store.reviews import save_weekly_review
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
    carried_ids: frozenset[int] = frozenset()  # merged 가운데 R1로 넘겨 받은 회고(혼자 실행하지 않는다)


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

# 사용자가 연 대화의 지시문. 회차 대화에 답할 때는 지시문 없이 메시지만 넘긴다
CONVERSATION_PROMPTS = {
    ConversationKind.chat: "chat.md",
    ConversationKind.plan: "plan.md",
}

TYPING_INTERVAL_S = 5
SEND_ATTEMPTS = 3  # 회차 전송은 바로 3회까지(스펙 5.4, 7)
SEND_RETRY_DELAYS_S = (1, 2, 4)  # 시도 사이 간격. 3회라 앞의 두 값(1, 2초)만 쓰인다
RESEND_DELAY_S = 5 * 60
MAX_RUN_ATTEMPTS = 2  # 회차당 두뇌 호출 최대 2회
MESSAGE_RETRY_DELAYS_S = (2, 4, 8)  # 사용자 메시지 오류: 지수 백오프로 3회 더(스펙 5.3)

FALLBACK_REPLY = "지금 잠깐 생각이 안 돼요. 조금 뒤에 다시 말씀해 주세요."
MAX_TURNS_REPLY = "정리하다가 길어졌어요. 이어서 말씀해 주시면 계속할게요."
# 고정 안내(스펙 5.3, 7). 비서가 먼저 보내는 하루 3회에 세지 않는다.
DAILY_CAP_REPLY = "오늘은 여기까지 생각을 아껴 둘게요. 명령(/today)은 계속 쓸 수 있어요."
LOGIN_NOTICE = "Claude 로그인이 풀렸어요. PC에서 Claude Code에 다시 로그인해 주세요."
BILLING_NOTICE = "Claude 계정이나 결제 상태를 확인해야 해요. PC에서 Claude 계정을 살펴봐 주세요."


def rate_limit_notice(resume: str) -> str:
    return f"지금은 Claude 사용 한도에 닿았어요. {resume}쯤 다시 이야기할 수 있어요. 명령(/today)은 계속 쓸 수 있어요."


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
        data_dir: Path | None = None,
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
        self.data_dir = data_dir
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
        # 받은 때를 활동으로 기록한다. 앞선 두뇌 호출을 기다리는 동안 tick이 대화를 만료로 닫지 않는다
        self.router.keep_alive(m.at)
        self._queue.put_nowait((_PRIORITY_MESSAGE, next(self._seq), m))

    def submit_run(self, run: Run, merged: list[Run], *, carried_ids: Iterable[int] = ()) -> None:
        """러너가 `queued`로 바꾼 회차를 넣는다. `merged`는 이 회차에 합쳐 함께 처리할 회차다.

        `carried_ids`는 merged 가운데 넘겨 받은 회고다. primary가 늦으면 승격하지 않고 같이 건너뛴다.
        """
        job = _RunJob(run, list(merged), frozenset(carried_ids))
        self._queue.put_nowait((_PRIORITY_RUN, next(self._seq), job))

    def submit_resend(self, run: Run) -> None:
        """시작 시 복구: 전송이 끝내 안 된 회차(`failed`, `outbound_text` 있음)를 전송만 한 번 다시 한다.

        5분 뒤 재전송과 같은 길로 간다(답장 창, `resent` 확인). 버튼은 DB에서 다시 만든다: 그 대화에서 제안해
        아직 초안인 할 일, 그리고 그 회차의 컨디션 버튼 날짜.
        """
        assert self.runs is not None
        merged = [m for m in (self.runs.get(i) for i in run.merged_run_ids) if m is not None]
        drafts: list[int] = []
        if self.tools is not None and run.conversation_id is not None:
            tasks = self.tools.tasks
            drafts = [
                i
                for i in tasks.proposed_task_ids(run.conversation_id)
                if (t := tasks.get(i)) is not None and t.status is TaskStatus.draft
            ]
        job = _ResendJob(run, merged, [], drafts, self._ask_condition_for(run, merged))
        self._queue.put_nowait((_PRIORITY_RUN, next(self._seq), job))

    async def _work(self) -> None:
        while True:
            _, _, item = await self._queue.get()
            if item is None:
                return
            if isinstance(item, _RunJob):
                try:
                    await self._handle_run(item.run, item.merged, item.carried_ids)
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
        if self._capped():
            # 하루 두뇌 호출 상한: 두뇌를 부르지 않고 고정 문구로 답한다(스펙 7)
            await self._fixed_reply(batch, DAILY_CAP_REPLY)
            self.state.mark_updates_done(update_ids)
            log.info("message_daily_cap", extra={"update_ids": update_ids})
            return
        limited = self._state_time(LIMITED_UNTIL_KEY)
        if limited is not None and self.clock.now() < limited:
            # 사용 한도 구간 안: 두뇌를 부르지 않고 매번 답한다. 기록된 재개 시각을 쓰고,
            # 회차 안내의 구간 한 번 몫은 쓰지 않는다
            await self._fixed_reply(batch, rate_limit_notice(self._resume_text(limited)))
            self.state.mark_updates_done(update_ids)
            log.info("message_rate_limited_window", extra={"update_ids": update_ids})
            return
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
        # 두뇌가 답하는 동안 tick이 이 대화를 만료로 닫지 않도록 받은 즉시 활동으로 기록한다
        self.convs.touch(conv.id)

        run_ctx = RunContext(conversation_id=conv.id, run_id=None, events=[])
        body = _join(self._recorded_condition(), f"## 메시지\n{text}")
        with self._keep_awake():
            fell_back = False
            for m in batch:
                self.transcripts.append(m.at, "사용자", conv.id, None, redact(m.text)[0])
            resumed = conv.session_id is not None
            # 회차 대화에 답할 때는 지시문 없이 메시지만 넘긴다(스펙 5.3 "프롬프트 선택").
            instructions = "" if conv.kind is ConversationKind.run else prompts.load(CONVERSATION_PROMPTS[conv.kind])
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
            # 그 밖의 오류: 2, 4, 8초 간격으로 3회까지 다시 부른다(스펙 5.3). resume 실패 대체 경로가 먼저다
            capped = False
            for delay in MESSAGE_RETRY_DELAYS_S:
                if result.status != "error":
                    break
                if run_ctx.events:  # 도구가 이미 데이터를 바꿨다: 다시 부르지 않는다(중복 쓰기 방지, 스펙 5.4-3)
                    break
                if self._capped():  # 다시 부르기 전마다 하루 상한을 본다
                    capped = True
                    break
                await self._sleep(delay)
                # run_ctx는 그대로 쓴다(여기까지 온 호출들은 도구 이벤트가 없다)
                result = await self._call_brain(
                    prompt, session_id=None if fell_back else conv.session_id, run_ctx=run_ctx
                )
            if result.session_id or fell_back:  # 대체 경로가 세션을 못 얻었으면 깨진 세션 ID를 지운다
                self.convs.set_session(conv.id, result.session_id)
            self.convs.touch(conv.id)

            # 로그인·결제와 사용 한도: 사용자 메시지에는 매번 고정 문구로 답한다(하루·구간 한 번은 회차 안내에만)
            if result.status == "rate_limited":
                until = self._set_limited(result.retry_at)
                await self._fixed_reply([], rate_limit_notice(self._resume_text(until)))
                self.state.mark_updates_done(update_ids)
                log.info("message_rate_limited", extra={"conversation_id": conv.id, "update_ids": update_ids})
                return
            if result.status == "auth_error":
                await self._fixed_reply([], _auth_copy(result.error))
                self.state.mark_updates_done(update_ids)
                log.info("message_auth_error", extra={"conversation_id": conv.id, "update_ids": update_ids})
                return
            if capped:  # 백오프 중 하루 상한: 고정 안내로(대화 밖 `[-]`), 모인 확인 문구를 붙여 답한다
                confirmations = render_confirmations(run_ctx.events, self._today())
                await self._fixed_reply([], _join(DAILY_CAP_REPLY, confirmations))
                self.state.mark_updates_done(update_ids)
                log.info("message_daily_cap_during_backoff", extra={"conversation_id": conv.id})
                return
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

    async def _fixed_reply(self, batch: list[Inbound], text: str) -> None:
        """사용자 메시지에 고정 안내로 답한다. 원문 기록에는 대화 밖(`[-]`)으로 남긴다.

        `batch`의 메시지도 `[-]`로 기록한다(이미 대화에 기록했으면 빈 목록). 전송 오류는 그대로 올린다:
        호출한 쪽은 전송이 된 뒤에만 처리 완료로 기록한다.
        """
        for m in batch:
            self.transcripts.append(m.at, "사용자", None, None, redact(m.text)[0])
        await self.sender.send(Outbound(text=text))
        self.transcripts.append(self.clock.now(), "비서", None, None, text)

    def _capped(self) -> bool:
        return self.state.usage(self._today()).brain_calls >= self.settings.limits.daily_brain_calls

    async def _run_notice_auth(self, error: str | None) -> None:
        """회차가 보내는 로그인·결제 안내. 논리적 날짜마다 한 번만(스펙 5.3)."""
        today = self._today().isoformat()
        if self.state.get(LAST_AUTH_NOTICE_KEY) == today:
            return
        if await self._send_notice(_auth_copy(error)):
            self.state.set(LAST_AUTH_NOTICE_KEY, today)

    def _set_limited(self, retry_at: datetime | None) -> datetime:
        """`limited_until`을 기록하고 돌려준다. 없거나 이미 지난 재개 시각은 지금 + 1시간."""
        now = self.clock.now()
        if retry_at is None or retry_at <= now:
            retry_at = now + RATE_LIMIT_FALLBACK
        self.state.set(LIMITED_UNTIL_KEY, to_iso(retry_at))
        return retry_at

    async def _run_notice_rate_limit(self, until: datetime) -> None:
        """회차가 보내는 사용 한도 안내. 구간(`limited_until` 값)마다 한 번만."""
        key = to_iso(until)
        if self.state.get(LAST_RATE_LIMIT_NOTICE_KEY) == key:
            return
        if await self._send_notice(rate_limit_notice(self._resume_text(until))):
            self.state.set(LAST_RATE_LIMIT_NOTICE_KEY, key)

    def _resume_text(self, until: datetime) -> str:
        """`{재개}`: 오늘(논리적 날짜)이면 `HH:MM`, 아니면 `M월 D일 HH:MM` (한국 시간)."""
        s = self.settings
        lt = local(until, s.timezone)
        if logical_date(until, s.timezone, s.day_boundary) == self._today():
            return f"{lt:%H:%M}"
        return f"{lt.month}월 {lt.day}일 {lt:%H:%M}"

    async def _send_notice(self, text: str) -> bool:
        """고정 안내 전송. 원문 기록은 대화 밖(`[-]`). 먼저 보낸 메시지 수에는 세지 않는다."""
        try:
            await self.sender.send(Outbound(text=text))
        except Exception as e:  # noqa: BLE001 - 안내가 안 가도 다음 기회에 다시 보낸다
            log.warning("notice_send_error", extra={"error_type": type(e).__name__})
            return False
        try:
            self.transcripts.append(self.clock.now(), "비서", None, None, text)
        except Exception:
            log.exception("notice_transcript_error")
        return True

    # --- 회차 실행 (스펙 5.4: 두 단계) ---

    async def _handle_run(self, run: Run, merged: list[Run], carried_ids: frozenset[int] = frozenset()) -> None:
        assert self.runs is not None, "회차를 실행하려면 runs가 있어야 한다"
        runs = self.runs
        # 대기하는 동안 한계가 지난 회차는 저마다 따로 건너뛴다(스펙 5.4 R5). 남은 회차끼리 합쳐 실행한다.
        # 넘겨 받은 회고(R1)는 primary가 늦으면 승격하지 않고 같이 late가 된다(혼자 실행하지 않는다).
        primary_late = self._past_limit(run)
        live: list[Run] = []
        for r in (run, *merged):
            if self._past_limit(r) or (primary_late and r.id in carried_ids):
                runs.mark_skipped(r.id, SkipReason.late)
                self._release_carry([r])
                log.info("run_skipped_late_at_start", extra={"run_id": r.id})
            elif (blocked := self._run_blocked(r)) is not None:
                # 큐에 든 뒤에 생긴 멈춤, 하루 상한, 사용 한도도 다시 본다(판정은 tick 때 했다)
                runs.mark_skipped(r.id, blocked)
                self._release_carry([r])
                log.info("run_skipped_at_start", extra={"run_id": r.id, "reason": blocked.value})
            else:
                live.append(r)
        if not live:
            return
        if self.router.plan_open():
            # 큐에 든 뒤 계획 대화가 열렸다: 건너뛰지 않고 pending으로 돌려 놓는다. 다음 tick이 다시 판정한다
            # (닫힐 때까지 기다리고, 한계를 넘으면 late). 넘겨 받은 회고는 표시를 먼저 되돌린다: 되돌리기 도중
            # 멈춰도 회고가 표시 없이 pending이 되어 혼자 실행되는 일이 없다(queued 회고의 표시는 러너가 지우지 않는다)
            for r in live:
                if r.id in carried_ids:
                    self.state.set(CARRY_REVIEW_KEY, str(r.id))
            for r in live:
                runs.mark_pending(r.id)
            log.info("run_deferred_plan_open", extra={"run_ids": [r.id for r in live]})
            return
        if live[0] is not run:  # primary가 늦었으면 남은 회차 중 합치기 우선순위가 가장 높은 것이 primary
            live.sort(key=lambda r: merge_order(r.loop))
        run, merged = live[0], live[1:]
        if merged:  # 합쳐진 회차는 실행된 회차의 merged_run_ids에 기록한다(스펙 5.4 "합치기")
            runs.add_merged(run.id, [r.id for r in merged])
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
            blocked = self._run_blocked(run)
            if blocked is not None:  # 두 번째 호출 전에도 멈춤, 하루 상한, 사용 한도를 본다
                for r in (run, *merged):
                    runs.mark_skipped(r.id, blocked)
                self._release_carry([run, *merged])
                self.convs.close(conv.id)
                log.info("run_rerun_skipped", extra={"run_id": run.id, "reason": blocked.value})
                return None
            runs.mark_running(run.id)
            result, run_ctx = await self._run_brain(run, merged, conv, ask)
        if result.status in ("auth_error", "rate_limited"):
            # 로그인·결제는 skipped(auth), 사용 한도는 skipped(rate_limit). 다시 실행하지 않고 고정 안내만(스펙 5.3)
            reason = SkipReason.auth if result.status == "auth_error" else SkipReason.rate_limit
            for r in (run, *merged):
                runs.mark_skipped(r.id, reason)
            self._release_carry([run, *merged])
            self.convs.close(conv.id)
            log.warning("run_brain_skipped", extra={"run_id": run.id, "status": result.status})
            if result.status == "auth_error":
                await self._run_notice_auth(result.error)
            else:
                await self._run_notice_rate_limit(self._set_limited(result.retry_at))
            return None
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
            self._review_week_note(run, merged),
        )
        return await self._call_brain(prompt, session_id=None, run_ctx=run_ctx), run_ctx

    def _review_week_note(self, run: Run, merged: list[Run]) -> str:
        """회고가 함께 있으면 회고 주와 다음 주를 알린다. 다음 주는 `set_priorities(week, ...)`에 쓴다."""
        review = _review_of(run, merged)
        if review is None:
            return ""
        s = self.settings
        d = logical_date(review.scheduled_for, s.timezone, s.day_boundary)
        mon = d - timedelta(days=d.weekday())
        nxt = mon + timedelta(days=7)
        return (
            "## 회고 주\n"
            f"- 이번 회고: {_week_label(mon)}\n"
            f"- 다음 주: {_week_label(nxt)}"
        )

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

    def _run_blocked(self, run: Run) -> SkipReason | None:
        """지금 이 회차가 두뇌를 부를 수 없는 이유(R2 멈춤, R3 하루 상한, 사용 한도). 없으면 None."""
        paused_until = self._state_time(PAUSE_UNTIL_KEY)
        if paused_until is not None and run.scheduled_for < paused_until:
            return SkipReason.paused
        if self._capped():
            return SkipReason.daily_cap
        limited = self._state_time(LIMITED_UNTIL_KEY)
        if limited is not None and self.clock.now() < limited:
            return SkipReason.rate_limit
        return None

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

    def _release_carry(self, runs: Iterable[Run]) -> None:
        """넘겨 받은 회고가 끝났으면(보냄, 건너뜀) `carry_review_run_id`를 지운다. 러너는 합칠 때 지우지 않는다."""
        mark = self.state.get(CARRY_REVIEW_KEY)
        if mark is not None and mark in {str(r.id) for r in runs}:
            self.state.set(CARRY_REVIEW_KEY, None)

    def _run_delivered(
        self, run: Run, merged: list[Run], conv: Conversation, text: str, tool_names: list[str]
    ) -> None:
        """전송이 끝난 회차: primary와 merged 모두 done, 먼저 보낸 메시지 수 +1, 그다음 원문 기록, 대화 갱신, 회고 저장."""
        assert self.runs is not None
        # 사용자는 이미 받았다. 상태와 카운터를 먼저 기록해 다음 시작 때 다시 보내지 않게 한다.
        for r in (run, *merged):
            self.runs.mark_done(r.id)
        self._release_carry([run, *merged])
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
        self._save_review(run, merged, text)
        log.info("run_done", extra={"run_id": run.id, "loop": run.loop.value, "conversation_id": conv.id})

    def _save_review(self, run: Run, merged: list[Run], text: str) -> None:
        """회고가 primary이거나 merged에 있으면 보낸 답(가린 뒤)을 그 주의 파일에 쓴다.

        주는 회고 회차 `scheduled_for`의 논리적 날짜로 정한다. 저장이 안 돼도 회차 상태는 그대로 둔다.
        """
        if self.data_dir is None:
            return
        review = _review_of(run, merged)
        if review is None:
            return
        s = self.settings
        period = period_of(Cadence.week, logical_date(review.scheduled_for, s.timezone, s.day_boundary))
        try:
            save_weekly_review(self.data_dir, period, redact(text)[0])
        except Exception as e:  # noqa: BLE001 - 본문과 경로 없이 종류만 남긴다
            log.warning("review_save_error", extra={"run_id": review.id, "error_type": type(e).__name__})

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
            paused_until=self._state_time(PAUSE_UNTIL_KEY),
            merged=merged,
        )

    def _state_time(self, key: str) -> datetime | None:
        v = self.state.get(key)
        return from_iso(v) if v else None

    async def _call_brain(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext
    ) -> BrainResult:
        """두뇌를 부르는 동안 5초마다 '입력 중'을 보낸다."""
        self.state.incr_usage(self._today(), "brain_calls")  # 모든 호출이 하루 상한에 들어간다(스펙 7)
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


def _review_of(run: Run, merged: list[Run]) -> Run | None:
    return next((r for r in (run, *merged) if r.loop is LoopKey.review), None)


def _week_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return (
        f"{period_of(Cadence.week, monday)} "
        f"({monday.month}/{monday.day}~{sunday.month}/{sunday.day})"
    )


def _join(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


def _auth_copy(error: str | None) -> str:
    return BILLING_NOTICE if error == "billing" else LOGIN_NOTICE


def _run_ok(result: BrainResult) -> bool:
    return result.status == "ok" and bool(result.text.strip())


def _reply_for(result: BrainResult) -> str:
    """정상 답, 턴 상한, 그 밖(오류 백오프 뒤). 로그인·결제와 사용 한도는 고정 안내로 따로 처리한다."""
    if result.status == "ok" and result.text.strip():
        return result.text
    if result.status == "max_turns":
        return MAX_TURNS_REPLY
    return FALLBACK_REPLY

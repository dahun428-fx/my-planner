"""직렬 디스패처: 메시지와 회차 → 두뇌 → 응답 (스펙 4, 5.3, 5.4)."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import anyio

from my_planner.clock import Clock, from_iso, local, logical_date, period_of, to_iso
from my_planner.domain import (
    Cadence,
    Channel,
    ConversationKind,
    LoopKey,
    RunContext,
    SkipReason,
    TaskStatus,
    ToolEvent,
)
from my_planner.harness import moments as moments_job
from my_planner.harness import prompts, summaries
from my_planner.harness.brain import RATE_LIMIT_FALLBACK, Brain, BrainResult
from my_planner.harness.context import (
    ask_condition_for,
    build_notices,
    build_preamble,
    habit_week_block,
    moments_week_block,
    recent_areas_block,
)
from my_planner.harness.redact import MASK, redact
from my_planner.harness.review_steps import (
    NextStep,
    ReviewFlow,
    first_step,
    review_in,
    step_note,
)
from my_planner.harness.stream import (
    AppReplySender,
    QueueSink,
    StreamSink,
    UiMessageWriter,
    write_reply,
)
from my_planner.loop.catchup import merge_order
from my_planner.loop.schedule import Due, limit_for, reply_window_end
from my_planner.status.snapshot import status_snapshot
from my_planner.status.xp import (
    LABEL_CHECKIN_REPLY,
    LABEL_REVIEW_WEEK,
    LABEL_YEAR_REVIEW,
    XP_CHECKIN_REPLY,
    XP_REVIEW_WEEK,
    XP_YEAR_REVIEW,
    XpGain,
)
from my_planner.store.db import after_commit, transaction
from my_planner.store.repos.state import (
    BRAIN_AUTH_CHECKED_AT_KEY,
    BRAIN_AUTH_STATE_KEY,
    CARRY_REVIEW_KEY,
    LAST_AUTH_NOTICE_KEY,
    LAST_RATE_LIMIT_NOTICE_KEY,
    LIMITED_UNTIL_KEY,
    PAUSE_UNTIL_KEY,
)
from my_planner.store.reviews import save_weekly_review
from my_planner.store.transcripts import (
    app_secretary_message_id,
    app_user_message_id,
    erase_conversation,
)
from my_planner.store.views import chapter_refs, milestone_refs
from my_planner.tools.actions import ActionDeps, ActionRequest, ActionResult
from my_planner.tools.actions import apply_action as _apply_action
from my_planner.tools.activity import undoable_now
from my_planner.tools.confirmations import render_confirmations, with_level_up

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.harness.conversations import ConversationRouter
    from my_planner.harness.delivery import Delivery, DeliveryOutcome
    from my_planner.store.repos.activity import (
        ActivityRepo,
        ConfirmsRepo,
        IdempotencyRepo,
    )
    from my_planner.store.repos.channels import DeliveriesRepo
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.conversations import Conversation, ConversationsRepo
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.state import PendingInbound, StateRepo
    from my_planner.store.transcripts import TranscriptStore
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)


@dataclass
class Inbound:
    text: str
    at: datetime  # 하네스가 받은 시각(UTC)
    sent_at: datetime  # 텔레그램이 기록한 보낸 시각
    update_ids: list[int]
    recovered: bool = False  # 시작 때 `inbound_pending`에서 다시 넣은 메시지(본문은 이미 가린 글)
    # 통로(SP3-4 7.5 M1). 앱 메시지는 `POST /chat` 하나에 하나이고 묶지 않는다
    channel: Channel = "telegram"
    client_msg_id: str | None = None
    checkin_id: int | None = None
    sink: StreamSink | None = None  # 앱 요청의 스트림. 시작 때 다시 넣은 앱 행은 None(M6)
    conversation_id: int | None = None  # 앱: 받을 때 `route_app_message`가 고른 대화(6.4.1)
    message_id: str | None = None  # 앱: 받은 `message.id`(사용자 줄의 id, 6.4.6)
    # 앱: 목록에서 골라 이어 가는 대화(SP9 7.3 0번 규칙). 받은 대화가 처리 전에 닫혔으면 다시 고를 때 쓴다
    resume_conversation_id: int | None = None


@dataclass
class Outbound:
    text: str
    draft_conversation_id: int | None = None
    draft_task_ids: list[int] = field(default_factory=list)
    ask_condition_for: date | None = None
    # 회차 차례의 확인 토큰(SP3-4 10.1 A5): (토큰, 버튼 이름). 텔레그램 `k:` 버튼 줄(초안 줄 다음, 컨디션 줄 앞).
    # 확인 문구 전부는 메시지 글(`확인을 기다려요: …` 줄)에 있다.
    # 앱은 체크인 상세 `cards`의 `ui_confirm`으로 받는다(6.4.5). `/chat` 스트림에는 없다(사용자 차례뿐이라 생기지 않는다)
    confirms: list[tuple[str, str]] = field(default_factory=list)
    # 앱 대화(사용자 차례)의 확인 카드 `ui_confirm` props(SP9 8장 `set_checkin_time`): `/chat` 스트림의 하네스 조각
    confirm_cards: list[dict[str, Any]] = field(default_factory=list)
    # 앱 답(SP3-4 7.5 M4): 확인 문구는 글에 붙이지 않고 `data-activity.confirmation`으로 간다(6.4.1)
    channel: Channel = "telegram"
    confirmation: str | None = None
    writer: UiMessageWriter | None = None
    activity_ids: list[int] = field(default_factory=list)
    undo_ids: list[int] = field(default_factory=list)
    # 두뇌 글이 `text-delta`로 이미 나갔다(상태 ok일 때만): 앱 답이 글 블록을 다시 보내지 않는다(06b)
    streamed: bool = False
    # 앱 초안 카드 `ui_todo_draft`의 `data.todos`(지금 값 `TodoRef`, 초안 포함, 6.4.1). `_reply_out`이 채운다
    draft_todos: list[dict[str, Any]] | None = None
    # 이번 차례에 꺼낸 사건·챕터 초안(11.3). 텔레그램 `m:`·`h:` 버튼 줄(할 일 초안 줄 다음), 앱 `ui_milestone_draft`·
    # `ui_chapter_draft`. `전부 저장`(`m:all`)은 `draft_conversation_id`를 쓴다
    draft_milestone_ids: list[int] = field(default_factory=list)
    draft_chapter_ids: list[int] = field(default_factory=list)
    # 앱 사건·챕터 초안 카드의 `data.milestones`, `data.chapters`(6.4.7). `_reply_out`이 채운다
    draft_milestones: list[dict[str, Any]] | None = None
    draft_chapters: list[dict[str, Any]] | None = None
    # 회고 단계의 사다리 버튼 `(YYYY-MM, "n" | "f")`(SP3-4 11.1). 텔레그램 `l:` 줄(컨디션 줄 자리). 컨디션 줄과
    # 한 메시지에 같이 오지 않는다(한 메시지에 키보드 한 종류, 초안 줄은 함께 둘 수 있다)
    ladder: tuple[str, Literal["n", "f"]] | None = None
    # 습관 버튼의 날짜(SP7 5.7): 저녁 체크인(합친 회차 포함)이고 활성 습관이 있으면 그 체크인의 날짜. 텔레그램 `hb:`
    # 줄(확인 줄 다음, 컨디션·사다리 줄 앞). 사다리 때문에 `ask_condition_for`를 지워도 이 값은 그대로다
    habit_date: date | None = None


class Sender(Protocol):
    """`send`는 버튼이 붙은 마지막 조각의 메시지 id를 돌려줄 수 있다(텔레그램, 답한 뒤 버튼을 거둘 때 쓴다).

    `clear_buttons(message_id)`: 앱에서 먼저 답한 회차 메시지의 버튼을 거둔다(SP3-4 6.4.5). 메시지 id를 돌려주는
    전송에만 불린다(id를 돌려주지 않는 시험용 전송은 부를 일이 없다).
    """

    async def send(self, out: Outbound) -> object: ...

    async def clear_buttons(self, message_id: int) -> object: ...

    async def typing(self) -> None: ...


@dataclass
class _AppSlot:
    """처리를 기다리거나 처리 중인 앱 메시지 하나(M8: 같은 `client_msg_id`의 새 요청이 여기에 붙는다)."""

    inbound: Inbound
    writer: UiMessageWriter
    conversation_id: int | None  # 지금 고른 대화(닫혀 있어 다시 고르면 바뀐다)
    done: bool = False  # 처리 완료(M5)를 적었다

    @property
    def inbound_id(self) -> int:
        return self.inbound.update_ids[0]

    @property
    def id_conversation(self) -> int | None:
        """메시지 id를 만드는 대화: 받을 때 고른 대화(`start`에 이미 알렸다). 다시 골라도 바뀌지 않는다(6.4.1)."""
        return self.inbound.conversation_id if self.inbound.conversation_id is not None else self.conversation_id

    def secretary_id(self) -> str | None:
        """비서 줄 id = 이 답의 `start.messageId`. 다시 고른 대화로 가도 같다(6.4.1, 6.4.6)."""
        if self.writer.message_id is not None:
            return self.writer.message_id
        cid = self.id_conversation
        return app_secretary_message_id(cid, self.inbound_id) if cid is not None else None


def _secretary_id(conversation_id: int | None, inbound_id: int) -> str | None:
    return app_secretary_message_id(conversation_id, inbound_id) if conversation_id is not None else None


def _app_key(m: Inbound) -> str:
    return m.client_msg_id if m.client_msg_id is not None else f"inbound:{m.update_ids[0]}"


@dataclass
class _RunJob:
    run: Run
    merged: list[Run]
    carried_ids: frozenset[int] = frozenset()  # merged 가운데 R1로 넘겨 받은 회고(혼자 실행하지 않는다)


@dataclass
class _MomentsJob:
    """하루 끝 작업: 그날의 이룬 순간 정리(SP8 6.2). 가장 낮은 차례다."""

    date: date


@dataclass
class _SummaryJob:
    """닫힌 앱 대화 하나의 제목·요약(SP9 7.2). 메시지와 회차 다음 차례다."""

    conversation_id: int


@dataclass
class _ResendJob:
    """전송이 끝내 안 된 회차를 5분 뒤 전송만 한 번 더 한다. 두뇌는 다시 부르지 않는다."""

    run: Run
    merged: list[Run]
    tool_names: list[str]
    draft_task_ids: list[int] = field(default_factory=list)
    ask_condition_for: date | None = None
    confirms: list[tuple[str, str]] = field(default_factory=list)  # 회차 차례의 확인 토큰(10.1 A5)
    draft_milestone_ids: list[int] = field(default_factory=list)  # 사건·챕터 초안 버튼(11.3)
    draft_chapter_ids: list[int] = field(default_factory=list)
    ladder: tuple[str, Literal["n", "f"]] | None = None  # 회고 메시지에 바로 붙인 사다리 1단계(11.1-1 (c))
    habit_date: date | None = None  # 습관 버튼의 날짜(SP7 5.7)


# 큐 우선순위(작을수록 먼저). 같은 우선순위는 들어온 순서.
_PRIORITY_MESSAGE = 0  # 사용자 메시지가 회차보다 먼저
_PRIORITY_RUN = 1
_PRIORITY_MOMENTS = 2  # 하루 끝 순간: 기다리는 메시지와 회차가 먼저(SP8 6.2-4)
_PRIORITY_SUMMARY = 2  # 대화 요약(SP9 7.2): 같은 차례의 순간 정리와는 들어온 순서
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

HISTORY_LINES = 20  # 새 세션에 붙이는 최근 원문 수(SP1 resume 실패 대체 경로, S11)
REERASE_DAYS = 30  # 하루 한 번 작업이 원문을 다시 지우는 지운 대화의 범위(SP9 7.7, SP9-09 리뷰)
INBOUND_MAX_ATTEMPTS = 3  # 다시 넣기 상한(SP1 5.2-4, `loop.runner`와 같은 값)
_DEFAULT_APP_SENDER = AppReplySender()

FALLBACK_REPLY = "지금 잠깐 생각이 안 돼요. 조금 뒤에 다시 말씀해 주세요."
MAX_TURNS_REPLY = "정리하다가 길어졌어요. 이어서 말씀해 주시면 계속할게요."
# 고정 안내(스펙 5.3, 7). 비서가 먼저 보내는 하루 3회에 세지 않는다.
DAILY_CAP_REPLY = "오늘은 여기까지 생각을 아껴 둘게요. 명령(/today)은 계속 쓸 수 있어요."
LOGIN_NOTICE = "Claude 로그인이 풀렸어요. PC에서 Claude Code에 다시 로그인해 주세요."
BILLING_NOTICE = "Claude 계정이나 결제 상태를 확인해야 해요. PC에서 Claude 계정을 살펴봐 주세요."


def rate_limit_notice(resume: str) -> str:
    return f"지금은 Claude 사용 한도에 닿았어요. {resume}쯤 다시 이야기할 수 있어요. 명령(/today)은 계속 쓸 수 있어요."


class _AwakeRefs:
    """주입받은 `keep_awake`를 참조 카운트로 잡는다(스펙 5.1 "절전 방지").

    0→1에서 한 번 잡고, 마지막 holder가 놓을 때 한 번 푼다. 그때 큐에 일이 남아 있으면(회차를 처리하는 동안
    메시지가 들어왔으면) 바로 풀지 않고 이어 잡아 두었다가, 큐가 비면 작업자가 `settle()`로 푼다.
    """

    def __init__(self, factory: Callable[[], AbstractContextManager[Any]], more_work: Callable[[], bool]) -> None:
        self._factory = factory
        self._more_work = more_work
        self._refs = 0
        self._held: AbstractContextManager[Any] | None = None

    @contextmanager
    def hold(self) -> Iterator[None]:
        if self._held is None:
            cm = self._factory()
            cm.__enter__()
            self._held = cm
        self._refs += 1
        try:
            yield
        finally:
            self._refs -= 1
            if self._refs == 0 and not self._more_work():
                self.settle()

    def settle(self) -> None:
        """아무도 잡고 있지 않으면 푼다."""
        if self._refs == 0 and self._held is not None:
            cm, self._held = self._held, None
            cm.__exit__(None, None, None)


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
        deliveries: DeliveriesRepo | None = None,
        activity: ActivityRepo | None = None,
        idempotency: IdempotencyRepo | None = None,
        confirms: ConfirmsRepo | None = None,
        app_sender: AppReplySender | None = None,
        delivery: Delivery | None = None,
        claude_config_dir: Path | None = None,
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
        self.deliveries = deliveries  # None이면 SP1과 같다(전달 기록 없음)
        self.activity = activity
        self.idempotency = idempotency
        self.confirms = confirms
        self.app_sender = app_sender  # 앱 답을 보낼 곳(M4). None이면 기본 `AppReplySender`(쓰개에 쓴다)
        # 회차·고정 안내의 통로(7.3 D1~D8). None이면 SP1처럼 텔레그램(`sender`)만
        self.delivery = delivery
        # 순간 호출 뒤 세션 파일을 지울 CLI 설정 폴더(SP8 6.3, 결정 18). None이면 지우지 않는다(앞 SP 시험)
        self.claude_config_dir = claude_config_dir
        self._app: dict[str, _AppSlot] = {}
        self._cur: _AppSlot | None = None  # 지금 처리 중인 앱 메시지(작업자는 하나라 한 번에 하나)
        self._sleep = sleep
        self._queue: asyncio.PriorityQueue[tuple[int, int, Any]] = asyncio.PriorityQueue()
        self._awake = _AwakeRefs(keep_awake, lambda: not self._queue.empty())
        self._seq = itertools.count()
        self._worker: asyncio.Task[None] | None = None
        self._timers: set[asyncio.Task[None]] = set()
        self._background: set[asyncio.Task[None]] = set()  # 버튼 거두기(답한 회차, 즉시 갈래에서 걸어 둔다)
        # 가르기가 원래 세션 id를 돌려준(갈라지지 않은) 대화: 이 프로세스에서는 다시 가르지 않고 대체 경로로 간다.
        # 메모리에만 둔다(재시작 뒤 한 번은 다시 가르기를 시도한다. 받아들인 한계, S11 확인 전)
        self._no_fork: set[int] = set()
        self._stopping = False
        self._busy = False  # 작업자가 꺼낸 항목을 처리하는 중
        self._run_questions: dict[int, int] = {}  # 회차 id → 그 회고에 실은 열린 시드 질문 id(보내면 `asked`)
        # 요약 큐(SP9 7.2): 큐에 든 대화, 이 프로세스에서 이미 해 본 대화(tick마다 다시 넣지 않는다. 하루 한 번 작업이
        # 비우고 최근 7일을 다시 넣는다). 메모리에만 둔다: 재시작 뒤 첫 tick이 남은 것을 다시 넣는다
        self._summary_queued: set[int] = set()
        # 해 본 대화와 그때의 `last_message_at`: 다시 열어 말이 더 생기면 다시 해 본다(SP9-09 리뷰)
        self._summary_tried: dict[int, datetime | None] = {}
        # 회고 단계(SP3-4 11.1): 곡선 저장소가 있을 때만. 텔레그램 버튼 처리기도 같은 것을 쓴다
        curve = tools.curve if tools is not None else None
        self.review_flow: ReviewFlow | None = (
            ReviewFlow(
                runs=runs, state=state, curve=curve, settings=settings, clock=clock, transcripts=transcripts,
                send=lambda step: self.sender.send(Outbound(text=step.text, ladder=step.ladder)),
            )
            if runs is not None and curve is not None
            else None
        )

    @property
    def idle(self) -> bool:
        """큐가 비었고 처리 중인 항목이 없다(기다리는 5분 뒤 재전송 타이머는 세지 않는다)."""
        return self._queue.empty() and not self._busy

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
        if self._background:  # 걸어 둔 버튼 거두기는 끝까지(짧다. 안 되면 로그만 남긴다)
            await asyncio.gather(*self._background, return_exceptions=True)
        self._worker = None

    def _cancel_timers(self) -> None:
        for t in list(self._timers):
            t.cancel()
        self._timers.clear()

    # --- 즉시 갈래 (SP3-4 스펙 4.3) ---

    def apply_action(self, req: ActionRequest) -> ActionResult:
        """두뇌 없이 도구 함수 하나를 부른다. 동기 함수이고 안에서 `await`하지 않는다(`tools/actions.py`)."""
        assert self.tools is not None, "즉시 갈래에는 도구가 있어야 한다"
        deps = ActionDeps(
            tools=self.tools, clock=self.clock, activity=self.activity, idempotency=self.idempotency,
            confirms=self.confirms, state=self.state, router=self.router, runs=self.runs, settings=self.settings,
            mark_answered=self.mark_answered, pushes=self.delivery.pushes if self.delivery is not None else None,
        )
        return _apply_action(deps, req)

    async def push_test(self) -> tuple[int, int]:
        """`POST /push/test`(6.4.8): 시험 알림을 보내고(`to_thread`), 결과는 즉시 갈래(`push_test_result`)로 적는다.

        하루 3회 상한에 세지 않는다. 푸시가 꺼져 있으면 (0, 0).
        """
        if self.delivery is None:
            return 0, 0

        def record(results: list[dict[str, Any]]) -> None:
            self.apply_action(
                ActionRequest("push_test_result", {"results": results}, actor="user", channel="app", endpoint="push")
            )

        return await self.delivery.push_test(record=record)

    def mark_answered(
        self, run_id: int, channel: Channel, *, at: datetime | None = None, gain: XpGain | None = None
    ) -> bool:
        """그 회차(합쳐진 회차면 primary)에 처음 답한 통로와 시각을 적는다(6.4.5, 7.5 M3). 처음이면 True.

        처음 답이 **앱**에서 왔으면 텔레그램에 보낸 회차 메시지의 버튼을 거둔다(`clear_buttons`, Dahun 결정:
        텔레그램 글 답장과 버튼 누름은 SP1처럼 버튼을 그대로 둔다). 동기 함수라 거두기는 이벤트 루프에 걸어
        두고, 안 되면 `buttons_clear_error`만 남긴다(답 기록은 그대로).

        답 기록과 경험치 원장(X3/X5/X8, 9.1)은 한 트랜잭션이다(4.3). `apply_action`의 트랜잭션 안에서 불리면
        거기에 합류하고, 거두기는 가장 바깥 트랜잭션이 커밋된 뒤에 건다(`after_commit`: 롤백된 답의 버튼을 거두지
        않게). `gain`을 주면 이 답이 실제로 적은 경험치와 오른 레벨을 거기에 더한다(레벨 오름 문구는 그 경험치를
        적은 답·확인에만 붙는다, 9.2).
        """
        if self.runs is None:
            return False
        run = self.runs.get(run_id)
        if run is None:
            return False
        primary = self.runs.merged_into(run.id) or run
        at = at if at is not None else self.clock.now()
        conn = self.runs.conn
        with transaction(conn):
            if not self.runs.mark_answered(primary.id, channel, at):
                return False
            self._grant_answer_xp(primary, at, gain)
        log.info("run_answered", extra={"run_id": primary.id, "channel": channel})
        if channel != "app":
            return True
        message_id = self.deliveries.telegram_message_id(primary.id) if self.deliveries is not None else None
        if message_id is not None:
            after_commit(conn, lambda: self._clear_later(self.sender.clear_buttons, message_id, primary.id))
        return True

    def _grant_answer_xp(self, primary: Run, at: datetime, gain: XpGain | None = None) -> None:
        """답한 회차의 경험치(9.1): 묶음에 주간 회고가 있으면 X5 하나(X3 대신, 묶음 전체에 하나), 아니면 X3.
        연말 회고(12월 마지막 일요일 회고)면 X8도. `mark_answered`의 트랜잭션 안에서 부른다."""
        status = self.tools.status if self.tools is not None else None
        if status is None or self.runs is None:
            return
        group = [primary, *(r for i in primary.merged_run_ids if (r := self.runs.get(i)) is not None)]
        day = logical_date(at, self.settings.timezone, self.settings.day_boundary)
        of = review_in(group, self.settings)

        def grant(kind: str, ref: str, amount: int, label: str) -> None:
            status.grant(at=at, logical_date=day, source_kind=kind, source_ref=ref, amount=amount, label=label, gain=gain)

        if of is None:
            grant("checkin_reply", f"run:{primary.id}", XP_CHECKIN_REPLY, LABEL_CHECKIN_REPLY)
            return
        grant("review_week", f"run:{of.review.id}", XP_REVIEW_WEEK, LABEL_REVIEW_WEEK)
        if of.steps.year:
            grant("year_review", f"year:{of.day.year}", XP_YEAR_REVIEW, LABEL_YEAR_REVIEW)

    def _confirmations(self, ctx: RunContext, answer: XpGain | None = None) -> str:
        """확인 문구(SP1 5.5) + 이 차례가 적은 경험치(`ctx.xp`, 답 기록 `answer`)로 레벨이 올랐으면 끝에
        "레벨 {N}이 됐어요."(9.2). 다른 통로가 그 사이 적은 경험치는 보지 않는다. 없으면 빈 글."""
        gain = XpGain()
        gain.merge(ctx.xp)
        if answer is not None:
            gain.merge(answer)
        return with_level_up(render_confirmations(ctx.events, self._today()), gain.level_up) or ""

    def xp_total(self) -> int:
        """지금 경험치 합계. 상태창 저장소가 없으면 0(레벨 오름 판정에 쓴다)."""
        status = self.tools.status if self.tools is not None else None
        return status.total() if status is not None else 0

    def _clear_later(self, clear: Callable[[int], Awaitable[object]], message_id: int, run_id: int) -> None:
        async def go() -> None:
            try:
                await clear(message_id)
            except Exception as e:  # noqa: BLE001 - 버튼이 남아도 답은 기록됐다(누르면 그대로 처리된다)
                log.warning("buttons_clear_error", extra={"run_id": run_id, "error_type": type(e).__name__})

        try:
            t = asyncio.get_running_loop().create_task(go(), name=f"clear-buttons-{run_id}")
        except RuntimeError:  # 이벤트 루프 밖(시험의 동기 호출): 거둘 수 없다
            log.warning("buttons_clear_error", extra={"run_id": run_id, "error_type": "NoEventLoop"})
            return
        self._background.add(t)
        t.add_done_callback(self._background.discard)

    def submit_message(self, m: Inbound) -> None:
        if m.channel == "app":
            # 대화는 받을 때 이미 골랐고(`route_app_message`가 활동으로 기록했다) 스트림을 붙일 자리를 만든다(M8)
            self._register_app(m)
        else:
            # 받은 때를 활동으로 기록한다. 앞선 두뇌 호출을 기다리는 동안 tick이 대화를 만료로 닫지 않는다
            self.router.keep_alive(m.at)
        self._queue.put_nowait((_PRIORITY_MESSAGE, next(self._seq), m))

    # --- 앱 통로 (SP3-4 6.4.1, 7.5) ---

    def route_app_message(
        self, at: datetime, *, conversation_id: int | None, checkin_id: int | None, plan: bool = False,
        resume_conversation_id: int | None = None,
    ) -> Conversation:
        """앱 메시지의 대화를 받을 때 고른다(동기, 7.2). 필요하면 새 앱 대화를 연다(4.3: 앱이 여는 대화는 여기서만).

        `plan=True`(`/plan [주제]`): 앱 통로의 새 계획 대화를 연다(그 통로에 열려 있던 것은 닫는다).
        `resume_conversation_id`: 목록에서 고른 대화(SP9 7.3 0번 규칙).
        """
        if plan:
            return self.router.start_plan("app")
        return self.router.for_app_message(
            at, conversation_id=conversation_id, checkin_id=checkin_id, resume_conversation_id=resume_conversation_id,
        )

    def current_app_conversation(self, conversation_id: int | None) -> Conversation | None:
        """두뇌를 거치지 않는 앱 답(명령, 글 아닌 메시지)이 알릴 대화. 새 대화는 열지 않는다.

        앱이 보낸 id가 열린 앱 대화면 그것, 아니면 지금 이어질 앱 대화(열린 앱 `plan`, 30분 안의 앱 `chat`), 없으면 None.
        """
        now = self.clock.now()
        conv = self.convs.get(conversation_id) if conversation_id is not None else None
        # 보낸 id도 라우팅과 같은 규칙으로 본다(계획 2시간, chat 30분, 회차 답장 창. 06 리뷰 N1)
        if conv is not None and conv.channel == "app" and self.router.continues(conv, now):
            return conv
        return self.router.current_app(now)

    def has_inflight(self, client_msg_id: str) -> bool:
        """같은 `client_msg_id`의 앱 메시지가 큐에 있거나 처리 중이다."""
        slot = self._app.get(client_msg_id)
        return slot is not None and not slot.writer.finished

    def resubmit_app_row(self, row: PendingInbound, sink: StreamSink, *, message_id: str | None = None) -> bool:
        """행은 남았는데 처리 자리가 없는 앱 메시지(처리 중 예외 뒤)를 새 요청의 싱크로 다시 넣는다.

        시작 때 다시 넣기와 같은 규칙이다(SP1 5.2-4): 넣을 때마다 `attempts`를 1 올리고, 이미
        `INBOUND_MAX_ATTEMPTS`회 넣은 행은 버린다(False). 메시지 id는 처음 것 그대로다.
        """
        if row.attempts >= INBOUND_MAX_ATTEMPTS:
            self.state.drop_pending_inbound(row.update_id)
            log.warning(
                "inbound_dropped", extra={"update_id": row.update_id, "reason": "max_attempts", "attempts": row.attempts}
            )
            return False
        self.state.bump_inbound_attempts(row.update_id)
        writer = UiMessageWriter(sink, _secretary_id(row.conversation_id, row.update_id))
        writer.start({**self.chat_metadata(row.conversation_id), "checkin_id": row.checkin_id})
        writer.status("queued")
        self.submit_message(Inbound(
            text=row.text, at=row.received_at, sent_at=row.sent_at, update_ids=[row.update_id], recovered=True,
            channel="app", client_msg_id=row.client_msg_id, checkin_id=row.checkin_id, sink=sink,
            conversation_id=row.conversation_id, message_id=message_id,
            resume_conversation_id=row.resume_conversation_id,
        ))
        return True

    def chat_metadata(self, conversation_id: int | None) -> dict[str, Any]:
        conv = self.convs.get(conversation_id) if conversation_id is not None else None
        kind = conv.kind.value if conv is not None else ConversationKind.chat.value
        return {"conversation_id": conversation_id, "channel": "app", "kind": kind}

    def _register_app(self, m: Inbound) -> None:
        writer = UiMessageWriter(m.sink, _secretary_id(m.conversation_id, m.update_ids[0]))
        writer.metadata = self.chat_metadata(m.conversation_id)
        self._app[_app_key(m)] = _AppSlot(m, writer, m.conversation_id)

    def attach_stream(self, client_msg_id: str, sink: QueueSink) -> bool:
        """같은 `client_msg_id`가 처리 중(또는 큐에서 기다리는 중)이면 새 요청의 싱크를 그 처리에 붙인다(M8).

        스트림이 있는 처리면 지난 조각부터 같은 조각을 받는다. 시작 때 다시 넣어 싱크가 없는 처리(M6)면 그 처리의
        `start`와 `data-status: queued`부터 새로 쓴다. 그런 처리가 없으면 False.
        """
        slot = self._app.get(client_msg_id)
        if slot is None or slot.writer.finished:
            return False
        w = slot.writer
        if w.sink is None:
            fresh = UiMessageWriter(sink, w.message_id)
            fresh.start({**self.chat_metadata(slot.conversation_id), "checkin_id": slot.inbound.checkin_id})
            fresh.status("thinking" if w.step_open else "queued")
            if w.step_open:
                fresh.start_step()
            w.sink = sink
            slot.inbound.sink = sink
        elif isinstance(w.sink, QueueSink):
            w.sink.join(sink)
        else:
            return False  # 덧붙일 수 없는 싱크(시험용). 처리 중이라는 것은 `has_inflight`가 알린다
        log.info("chat_stream_attached", extra={"inbound_id": slot.inbound_id})
        return True

    def record_chat_reply(self, client_msg_id: str, reply_text: str, *, conversation_id: int | None = None) -> None:
        """두뇌를 거치지 않은 앱 답(읽기 명령, 글 아닌 메시지)을 재생할 수 있게 적는다(`endpoint='chat'`, 6.4.1)."""
        if self.idempotency is None:
            return
        body = {"conversation_id": conversation_id, "reply_text": reply_text, "confirmation": None, "inbound_id": None}
        try:
            self.idempotency.put(client_msg_id, "chat", 200, body, conversation_id=conversation_id)
        except sqlite3.IntegrityError:
            pass  # 이미 적었다(같은 client_msg_id)

    def _app_conversation(self, slot: _AppSlot) -> Conversation:
        """받을 때 고른 대화. 그 대화가 없어졌거나 닫혔으면 다시 고른다(M3, M6)."""
        conv = self.convs.get(slot.conversation_id) if slot.conversation_id is not None else None
        if conv is None or conv.closed_at is not None:
            conv = self.route_app_message(
                self.clock.now(), conversation_id=None, checkin_id=slot.inbound.checkin_id,
                resume_conversation_id=slot.inbound.resume_conversation_id,
            )
            slot.conversation_id = conv.id
            slot.writer.metadata = self.chat_metadata(conv.id)
        return conv

    def _release_app(self, slot: _AppSlot) -> None:
        """처리가 끝난 앱 메시지의 자리를 비운다. 처리 완료 전에 끝났으면(예외) 일반 문구로 스트림을 닫는다."""
        self._app.pop(_app_key(slot.inbound), None)
        if not slot.writer.finished and not slot.done:
            write_reply(slot.writer, FALLBACK_REPLY)
        elif not slot.writer.finished:
            slot.writer.finish()  # 답은 이미 썼다. 스트림만 닫는다

    def activity_of(self, inbound_id: int) -> tuple[list[int], list[int]]:
        """그 메시지가 만든 활동 id와, 지금 되돌릴 수 있는 것(6.4.1 재생, 6.4.4)."""
        if self.activity is None:
            return [], []
        rows = self.activity.by_inbound(inbound_id)
        now = self.clock.now()
        return [a.id for a in rows], [a.id for a in rows if undoable_now(a, self.activity, now)]

    def submit_run(self, run: Run, merged: list[Run], *, carried_ids: Iterable[int] = ()) -> None:
        """러너가 `queued`로 바꾼 회차를 넣는다. `merged`는 이 회차에 합쳐 함께 처리할 회차다.

        `carried_ids`는 merged 가운데 넘겨 받은 회고다. primary가 늦으면 승격하지 않고 같이 건너뛴다.
        """
        job = _RunJob(run, list(merged), frozenset(carried_ids))
        self._queue.put_nowait((_PRIORITY_RUN, next(self._seq), job))

    def submit_moments(self, day: date) -> None:
        """그날의 이룬 순간 정리를 넣는다(하루 한 번 작업 `queue_moments`, SP8 6.2). 대기열은 메모리에만 있다."""
        self._queue.put_nowait((_PRIORITY_MOMENTS, next(self._seq), _MomentsJob(day)))

    def submit_resend(self, run: Run) -> None:
        """시작 시 복구: 전송이 끝내 안 된 회차(`failed`, `outbound_text` 있음)를 전송만 한 번 다시 한다.

        5분 뒤 재전송과 같은 길로 간다(답장 창, `resent` 확인). 버튼은 DB에서 다시 만든다: 그 대화에서 제안해
        아직 초안인 할 일과 사건·챕터, 그리고 그 회차의 컨디션 버튼 날짜.
        """
        assert self.runs is not None
        merged = [m for m in (self.runs.get(i) for i in run.merged_run_ids) if m is not None]
        drafts: list[int] = []
        milestones: list[int] = []
        chapters: list[int] = []
        if self.tools is not None and run.conversation_id is not None:
            tasks, curve, cid = self.tools.tasks, self.tools.curve, run.conversation_id
            drafts = [
                i
                for i in tasks.proposed_task_ids(cid)
                if (t := tasks.get(i)) is not None and t.status is TaskStatus.draft
            ]
            if curve is not None:
                milestones = [
                    i for i in tasks.proposed_curve_ids("milestone_proposed", conversation_id=cid)
                    if (m := curve.get_milestone(i)) is not None and m.status == "draft"
                ]
                chapters = [
                    i for i in tasks.proposed_curve_ids("chapter_proposed", conversation_id=cid)
                    if (c := curve.get_chapter(i)) is not None and c.status == "draft"
                ]
        ask = self._ask_condition_for(run, merged)
        habit_date = self._habit_date(run, merged, ask)
        flow = self.review_flow
        ladder = None
        if flow is not None and flow.claimed(run.id):
            # 보내지 못한 회차의 표시는 회고 메시지에 바로 붙인 첫 단계뿐이다(11.1-1 (c)): 컨디션 줄 대신 그 단계.
            # 그 달 `now`가 아직 없으면 사다리 버튼을 다시 붙인다(글은 저장한 본문에 이미 있다)
            ask = None
            step = first_step(flow.of_run(run), flow.curve)
            ladder = step.ladder if step is not None else None
        job = _ResendJob(run, merged, [], drafts, ask,
                         draft_milestone_ids=milestones, draft_chapter_ids=chapters, ladder=ladder,
                         habit_date=habit_date)
        self._queue.put_nowait((_PRIORITY_RUN, next(self._seq), job))

    async def _work(self) -> None:
        try:
            await self._work_loop()
        finally:
            self._awake.settle()  # 멈출 때 이어 잡아 둔 절전 방지를 푼다

    async def _work_loop(self) -> None:
        while True:
            if self._queue.empty():
                self._awake.settle()  # 이어 잡아 둔 것은 큐가 비면 푼다
            _, _, item = await self._queue.get()
            if item is None:
                return
            self._busy = True
            try:
                await self._process(item)
            finally:
                self._busy = False

    async def _process(self, item: Any) -> None:
        """작업 하나: 회차, 재전송, 또는 쌓인 메시지 묶음."""
        if isinstance(item, _RunJob):
            try:
                await self._handle_run(item.run, item.merged, item.carried_ids)
            except Exception:
                log.exception("run_handling_error", extra={"run_id": item.run.id})
            return
        if isinstance(item, _ResendJob):
            try:
                await self._resend_run(item)
            except Exception:
                log.exception("run_resend_error", extra={"run_id": item.run.id})
            return
        if isinstance(item, _MomentsJob):
            try:
                await self._handle_moments(item)
            except Exception:
                log.exception("moments_handling_error", extra={"date": item.date.isoformat()})
            return
        if isinstance(item, _SummaryJob):
            try:
                await self._handle_summary(item)
            except Exception:
                log.exception("summary_handling_error", extra={"conversation_id": item.conversation_id})
            return
        # 시작 때 다시 넣은 메시지는 하나씩 처리한다(저장해 둔 답과 도구 기록이 그 행에 묶여 있다).
        # 앱 메시지도 묶지 않는다(요청마다 스트림이 하나다, M2)
        alone = item.recovered or item.channel == "app"
        batch = [item] if alone else [item, *self._drain_messages(item)]
        slot = self._app.get(_app_key(item)) if item.channel == "app" else None
        if item.channel == "app" and slot is None:  # 넣을 때 자리를 만든다. 없으면 여기서
            self._register_app(item)
            slot = self._app[_app_key(item)]
        self._cur = slot
        try:
            await self._handle_messages(batch)
        except Exception:
            ids = [i for m in batch for i in m.update_ids]
            log.exception("message_handling_error", extra={"update_ids": ids})
        finally:
            self._cur = None
            if slot is not None:
                self._release_app(slot)

    def _drain_messages(self, lead: Inbound) -> list[Inbound]:
        """쌓여 있는 메시지 가운데 `lead`와 같은 통로인 것을 모두 꺼낸다(도착 순서, M2). 나머지는 제자리로.

        텔레그램끼리만 묶는다. 앱 메시지와 다시 넣은 메시지는 묶지 않는다.
        """
        taken: list[tuple[int, int, Any]] = []
        while True:
            try:
                taken.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        msgs: list[Inbound] = []
        for entry in taken:
            m = entry[2]
            if (
                isinstance(m, Inbound) and not m.recovered and m.channel == lead.channel
                and lead.channel == "telegram"
            ):
                msgs.append(m)
            else:
                self._queue.put_nowait(entry)
        return msgs

    # --- 메시지 처리 ---

    async def _handle_messages(self, batch: list[Inbound]) -> None:
        """쌓인 메시지를 두뇌 호출 한 번으로 처리한다. 본문은 두 줄 바꿈으로 잇고 update_id는 모두 기록한다."""
        update_ids = [i for m in batch for i in m.update_ids]
        # 다시 넣어도 같은 일을 두 번 하지 않는다(회차의 두 단계 실행과 같다, 스펙 5.4-3). 묶음은 첫 행 하나로 합친다
        lead = update_ids[0]
        self.state.merge_pending_inbound(update_ids)
        pending = self.state.get_pending_inbound(lead)
        if pending is not None and pending.brain_done:
            # 두뇌 답을 저장한 뒤 보내지 못했다: 그 답만 다시 보낸다
            await self._resend_saved_reply(batch, pending, update_ids)
            return
        if (
            pending is not None
            and pending.user_logged  # 이 행으로 이미 처리를 시작했다. 새 메시지가 예전 update_id를 다시 받았으면 아니다
            and (logged := self.tools is not None and self.tools.tasks.inbound_tool_events(lead))
        ):
            # 두뇌 호출 도중 멈췄고 도구가 이미 썼다: 다시 부르지 않고 확인 문구와 일반 문구로 마친다
            await self._finish_after_logged_tools(batch, pending, update_ids, logged)
            return
        if self._capped():
            # 하루 두뇌 호출 상한: 두뇌를 부르지 않고 고정 문구로 답한다(스펙 7)
            if await self._fixed_reply(batch, DAILY_CAP_REPLY, update_ids):
                log.info("message_daily_cap", extra={"update_ids": update_ids})
            return
        limited = self._state_time(LIMITED_UNTIL_KEY)
        if limited is not None and self.clock.now() < limited:
            # 사용 한도 구간 안: 두뇌를 부르지 않고 매번 답한다. 기록된 재개 시각을 쓰고,
            # 회차 안내의 구간 한 번 몫은 쓰지 않는다
            if await self._fixed_reply(batch, rate_limit_notice(self._resume_text(limited)), update_ids):
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
        app = self._cur
        channel: Channel = "app" if app is not None else "telegram"
        if app is not None:
            # 앱: 받을 때 고른 대화로(닫혔으면 다시 고른다, M3)
            conv = self._app_conversation(app)
        else:
            # 답장 창은 보낸 시각으로 고른다(스펙 갭 7 결정). 묶음의 첫 메시지 기준
            conv = self.router.for_user_message(batch[0].at, sent_at=batch[0].sent_at)
        notices = build_notices(
            # 시작 때 다시 넣은 메시지는 저장해 둔 가린 글이라 `[가림]`이 남아 있는지로 본다
            redacted=any(r for _, r in redacted_parts) or any(m.recovered and MASK in m.text for m in batch),
            stale_hours=stale_hours if stale_hours > limits.stale_message_hours else None,
            truncated_to=limits.input_max_chars if truncated else None,
            elsewhere=self._elsewhere(conv, channel),
        )
        # 두뇌가 답하는 동안 tick이 이 대화를 만료로 닫지 않도록 받은 즉시 활동으로 기록한다
        self.convs.touch(conv.id)
        answer_xp = XpGain()  # 이 답 기록이 적은 경험치(레벨이 오르면 확인 문구 끝에 한 줄, 9.2)
        if conv.kind is ConversationKind.run and conv.run_id is not None:
            # 회차 대화에 들어온 사용자 메시지는 그 회차의 답이다(6.4.5, 7.5 M3). 처음 한 번만, 보낸 시각으로
            self._answer_by_message(conv.run_id, channel, batch[0].sent_at, answer_xp)
        # 회고 단계(SP3-4 11.1-1 (b), 11.1-3): 텔레그램 회고 대화의 글이면 답 끝에 다음 단계를 붙인다. 두뇌에게는
        # 지금 판정으로 알리고, 붙일 단계는 두뇌 차례 뒤에 다시 판정한다(그 글로 사다리를 기록했을 수 있다)
        review_run = self._review_reply_run(conv, batch[0].sent_at) if app is None else None
        flow = self.review_flow
        review_step = flow.reply_step(review_run) if flow is not None and review_run is not None else None

        run_ctx = self._message_ctx(conv.id, lead)
        body = _join(
            self._recorded_condition(), f"## 메시지\n{text}",
            step_note(review_step, where="답"),
        )
        with self._awake.hold():
            fell_back = False
            self._log_user_lines(batch, conv.id, pending, lead)
            # 말아 넣기(SP9 7.4): 앱 대화의 사용자 메시지가 31번째면 이 호출 전에 요약하고 새 세션으로(요약 + 최근 6줄)
            thinking = False
            if app is not None:
                def _thinking(writer: UiMessageWriter = app.writer) -> None:
                    nonlocal thinking
                    writer.status("thinking")  # 요약 호출이 길 수 있어 먼저 알린다(SP9-09 리뷰)
                    thinking = True

                conv, rolled = await self._roll_up(conv, len(batch), on_summarize=_thinking)
            else:
                rolled = ""
            # 갈라 연 회차 대화의 첫 호출: 원래 대화의 세션을 `fork_session`으로 갈라 이어 간다(7.2, S11)
            session_id, fork = conv.session_id, False
            origin_text = self._fork_origin_text(conv)
            if (
                session_id is None and conv.forked_from is not None and conv.id not in self._no_fork
                and not self._from_app_side(conv)
            ):
                origin = self.convs.get(conv.forked_from)
                if origin is not None and origin.session_id is not None:
                    session_id, fork = origin.session_id, True
            resumed = session_id is not None
            # 회차 대화에 답할 때는 지시문 없이 메시지만 넘긴다(스펙 5.3 "프롬프트 선택").
            instructions = "" if conv.kind is ConversationKind.run else prompts.load(CONVERSATION_PROMPTS[conv.kind])
            history = ""
            if not resumed and conv.kind is ConversationKind.run:
                # 세션이 없는 회차 대화: 두뇌가 자기가 보낸 회차 메시지를 알도록 최근 원문을 붙인다.
                history = self._history(conv, len(batch))
            # 새 세션에만: 고른 지난 대화의 요약(7.3), 말아 넣은 이 대화의 요약과 최근 줄(7.4). 다른 대화의 원문은
            # 붙이지 않는다(완료 조건 9)
            continued = "" if resumed else self._continued_text(conv)
            if not rolled and not resumed and app is not None and conv.kind is not ConversationKind.run:
                # 세션 없이 다시 연 앱 대화(앞선 호출이 세션을 못 얻었다): resume 실패와 같은 지난 내용. 새 대화는 빈 글
                rolled = self._past_text(conv, len(batch))
            prompt = _join(
                notices,
                "" if resumed else instructions,
                self._preamble(resumed, include_habits=True),
                "" if resumed else origin_text,
                continued,
                rolled,
                f"## 최근 대화\n{history}" if history else "",
                body,
            )
            if app is not None:
                if not thinking:
                    app.writer.status("thinking")  # 두뇌가 시작한다(6.4.1). 도구 조각은 이 단계 안에 온다
                app.writer.start_step()
            result = await self._call_brain(prompt, session_id=session_id, run_ctx=run_ctx, fork_session=fork)
            # 가르기가 답을 냈는데 원래 세션 id를 그대로 돌려줬다: 갈라지지 않고 원래 세션을 이었다. 가르기 실패로
            # 본다(그 세션은 쓰지 않고, 다음 메시지부터 대체 경로). 바로 대체 경로로 다시 부르는 것은 도구가 쓰지
            # 않았고 글이 아직 클라이언트에 나가지 않았을 때만이다(답이 둘이 되거나 같은 쓰기를 두 번 하지 않게).
            # 오류(`error`)는 여기서 보지 않는다: 메시지 없이 끝난 오류는 늘 원래 id를 돌려주므로 아래 재시도에 맡긴다
            if self._not_forked(fork, session_id, result):
                self._mark_no_fork(conv.id)
                if run_ctx.events or (app is not None and app.writer.attempt_streamed):
                    log.info("fork_fallback_deferred", extra={"conversation_id": conv.id})
                    not_forked_now = False
                else:
                    not_forked_now = True
            else:
                not_forked_now = False
            if resumed and (result.resume_failed or not_forked_now):
                # 새 세션으로 다시 부른다. 이 대화의 요약이 있으면 요약 + 최근 6줄, 없으면 최근 원문 20개를 붙인다
                # (SP9 7.3, 방금 기록한 지금 메시지는 뺀다). 가르기가 안 됐으면(S11 대체 경로) 원래 대화의 회차 본문과
                # 원래 대화의 최근 원문을 붙인다(7.2, 요약은 보지 않는다)
                prompt = _join(
                    notices,
                    instructions,
                    self._preamble(False, include_habits=True),
                    origin_text,
                    self._continued_text(conv),
                    self._past_text(conv, len(batch)),
                    body,
                )
                fell_back = True
                if fork:
                    log.warning("fork_session_failed", extra={"conversation_id": conv.id})
                run_ctx = self._message_ctx(conv.id, lead)
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
                    prompt, session_id=None if fell_back else session_id, run_ctx=run_ctx,
                    fork_session=fork and not fell_back,
                )
            if fork and not fell_back and self._not_forked(fork, session_id, result):
                self._mark_no_fork(conv.id)  # 재시도가 낸 답도 갈라지지 않았다
            if fork and not fell_back:
                # 갈라 얻은 새 세션만 적는다. 원래 세션 id가 그대로 오면(갈라지지 않았거나 오류) 적지 않는다:
                # 두 통로가 한 세션을 쓰지 않는다
                if result.session_id and result.session_id != session_id:
                    self.convs.set_session(conv.id, result.session_id)
            elif result.session_id or fell_back:  # 대체 경로가 세션을 못 얻었으면 깨진 세션 ID를 지운다
                self.convs.set_session(conv.id, result.session_id)
            self.convs.touch(conv.id)
            self._drop_if_deleted(conv.id, result.session_id)

            # 로그인·결제와 사용 한도: 사용자 메시지에는 매번 고정 문구로 답한다(하루·구간 한 번은 회차 안내에만)
            if result.status == "rate_limited":
                until = self._set_limited(result.retry_at)
                if await self._fixed_reply([], rate_limit_notice(self._resume_text(until)), update_ids, save=True):
                    log.info("message_rate_limited", extra={"conversation_id": conv.id, "update_ids": update_ids})
                return
            if result.status == "auth_error":
                if await self._fixed_reply([], _auth_copy(result.error), update_ids, save=True):
                    log.info("message_auth_error", extra={"conversation_id": conv.id, "update_ids": update_ids})
                return
            if capped:  # 백오프 중 하루 상한: 고정 안내로(대화 밖 `[-]`), 모인 확인 문구를 붙여 답한다
                confirmations = self._confirmations(run_ctx, answer_xp)
                if await self._fixed_reply(
                    [], DAILY_CAP_REPLY, update_ids, save=True, confirmation=confirmations, ctx=run_ctx
                ):
                    log.info("message_daily_cap_during_backoff", extra={"conversation_id": conv.id})
                return
            streamed = result.status == "ok" and app is not None and app.writer.attempt_streamed
            # 조각으로 나간 글이 있으면 저장·재생의 글도 클라이언트가 본 글 블록 전부(6.4.1)
            body_text = app.writer.streamed_reply if streamed else _reply_for(result)
            confirmations = self._confirmations(run_ctx, answer_xp)
            # 두뇌가 제대로 답했을 때만 첫 단계를 붙인다(일반 문구 아래에는 묻지 않는다)
            step = (
                flow.reply_step(review_run)
                if flow is not None and review_run is not None and _run_ok(result) else None
            )
            # 텔레그램: 두뇌 답, 빈 줄, 확인 문구(도구를 안 불렀으면 빈 줄도 없다), 회고 단계. 앱: 확인 문구는
            # `data-activity`로
            reply = _join(body_text, confirmations, step.text if step is not None else "")
            sent_text = body_text if app is not None else reply
            # 두 단계: 보내기 전에 답을 저장한다(brain_done). 바로 3회까지 보내고, 끝내 안 되면 처리 완료로 두지
            # 않는다. 다음 시작 때 저장한 답만 다시 보낸다(두뇌는 다시 부르지 않는다)
            self.state.save_inbound_reply(lead, redact(sent_text)[0], conv.id)
            out = self._reply_out(_outbound(sent_text, run_ctx), confirmations, run_ctx.activity_ids, run_ctx.undo_ids)
            out.streamed = streamed
            if step is not None:
                out.ladder = step.ladder
            if not await self._send_reply(out, update_ids, conv.id):
                return
            if step is not None:
                self._claim_review_step(step, "message")
            # 보낸 뒤에만 처리 완료, 그다음 비서 원문 기록(기록이 안 돼도 다시 답하지 않는다)
            self._messages_done(update_ids, reply=sent_text, confirmation=confirmations, conversation_id=conv.id)
            self._transcribe_reply(conv.id, reply, list(run_ctx.tool_names))
        log.info(
            "message_handled",
            extra={
                "conversation_id": conv.id,
                "update_ids": update_ids,
                "chars": sum(len(m.text) for m in batch),
            },
        )

    async def _fixed_reply(
        self, batch: list[Inbound], text: str, update_ids: list[int], *, save: bool = False,
        confirmation: str = "", ctx: RunContext | None = None,
    ) -> bool:
        """사용자 메시지에 고정 안내로 답한다. 원문 기록에는 대화 밖(`[-]`)으로 남긴다.

        `batch`의 메시지도 `[-]`로 기록한다(이미 대화에 기록했으면 빈 목록). 바로 3회까지 보내고, 보낸 뒤에만
        `update_ids`를 처리 완료로 기록하고 비서 줄을 남긴다. 끝내 안 보냈으면 False.
        `save`: 두뇌를 부른 뒤의 안내다. 보내기 전에 저장해 다음 시작 때 두뇌를 다시 부르지 않게 한다.
        `confirmation`: 그 전에 도구가 바꾼 것의 확인 문구. 텔레그램은 글 뒤에 붙이고, 앱은 `data-activity`로 보낸다.
        """
        lead = update_ids[0] if update_ids else None
        app = self._cur is not None
        full = _join(text, confirmation)
        sent = text if app else full
        if batch and lead is not None:
            self._log_user_lines(batch, None, self.state.get_pending_inbound(lead), lead)
        if save and lead is not None:
            self.state.save_inbound_reply(lead, redact(sent)[0], None)
        ids = (ctx.activity_ids, ctx.undo_ids) if ctx is not None else ([], [])
        if not await self._send_reply(self._reply_out(Outbound(text=sent), confirmation, *ids), update_ids, None):
            return False
        self._messages_done(update_ids, reply=sent, confirmation=confirmation)
        self._transcribe_reply(None, full, [])
        return True

    def _elsewhere(self, conv: Conversation, channel: Channel) -> list[str] | None:
        """이 대화의 마지막 메시지 뒤에 다른 통로에서 생긴 활동의 `summary`(최대 5줄, 7.1 "다른 곳에서 바뀐 것").

        기준은 받기 직전 그 대화의 `last_message_at`이다(`ConversationRouter.notice_base`, 메모리에만 있다: 재시작을
        넘긴 메시지는 받을 때 갱신된 값을 써서 한 번은 몇 줄 빠질 수 있다. 받아들인 한계, 두뇌는 도구로 다시 읽는다).
        갈라 연 회차 대화의 첫 호출은 회차를 보낸 때부터 본다. 가르기는 원래 세션 전체를 복사하므로 원래 통로의
        대화에서 이미 본 줄이 겹칠 수 있지만, 버튼 누름처럼 세션 밖에서 바뀐 것을 빠뜨리지 않는다(보수적인 기준).
        """
        if self.activity is None:
            return None
        base = self.router.notice_base(conv)
        if (
            conv.forked_from is not None and conv.session_id is None and conv.run_id is not None
            and self.runs is not None
        ):
            run = self.runs.get(conv.run_id)
            if run is not None and run.finished_at is not None:
                base = min(base, run.finished_at)
        return [a.summary for a in self.activity.other_channel_since(base, channel, limit=5)] or None

    @staticmethod
    def _not_forked(fork: bool, session_id: str | None, result: BrainResult) -> bool:
        """가르기 호출이 답(`ok`, `max_turns`)을 냈는데 원래 세션 id를 돌려줬다."""
        return (
            fork and not result.resume_failed and result.session_id == session_id
            and result.status in ("ok", "max_turns")
        )

    def _mark_no_fork(self, conversation_id: int) -> None:
        if conversation_id not in self._no_fork:
            log.warning("fork_session_not_forked", extra={"conversation_id": conversation_id})
        self._no_fork.add(conversation_id)

    def _continued_text(self, conv: Conversation) -> str:
        """고른 지난 대화(계획, 창이 지난 회차)에서 새로 연 `chat`이면 그 대화의 요약(`redact()` 거침, 7.3). 원문은 없다."""
        if conv.continued_from is None:
            return ""
        src = self.convs.get(conv.continued_from)
        if src is None or src.deleted_at is not None:
            return ""
        return summaries.summary_block(summaries.CONTINUED_HEADING, src)

    def _past_text(self, conv: Conversation, skip_last: int) -> str:
        """새 세션에 붙이는 이 대화의 지난 내용(SP9 7.3): 요약이 있으면 `## 이 대화의 지난 내용` + 최근 6줄, 없으면
        지금처럼 최근 원문 20줄(`_history`). 갈라 연 회차 대화는 요약을 보지 않는다(가르기 대체 경로 그대로)."""
        fresh = self.convs.get(conv.id) or conv
        if fresh.summary and fresh.forked_from is None:
            tail = self.transcripts.recent_entries(conv.id, self.settings.limits.rollup_tail_lines, skip_last=skip_last)
            return _join(
                summaries.summary_block(summaries.PAST_HEADING, fresh),
                "## 최근 대화\n" + "\n".join(tail) if tail else "",
            )
        history = self._history(conv, skip_last)
        return f"## 최근 대화\n{history}" if history else ""

    async def _roll_up(
        self, conv: Conversation, skip_last: int, *, on_summarize: Callable[[], None] | None = None,
    ) -> tuple[Conversation, str]:
        """말아 넣기(SP9 7.4). 앱 `chat`·`plan`의 사용자 메시지 수를 올리고, `rollup_user_messages + 1`(31) 이상이면
        이 메시지 전까지로 요약을 갱신하고 세션을 비운다(수는 1로). 돌려주는 글은 새 세션에 붙일 요약 + 최근 6줄.

        요약을 못 만들면(상한, 두뇌 오류) 미룬다: 지금 세션을 그대로 잇고 다음 메시지에서 다시 해 본다(옛 요약으로
        말아 넣지 않는다). 회차 대화는 세지 않는다(답장 창 안에서만 이어지고 가르기 규칙이 세션을 맡는다).
        `on_summarize`: 요약을 부르기 직전에 한 번(앱 스트림에 "thinking"을 먼저 보낸다). `summary_through`는 요약이
        덮는 마지막 줄(이번 메시지 바로 앞 줄)의 시각이다.
        """
        if conv.channel != "app" or conv.kind is ConversationKind.run:
            return conv, ""
        n = self.convs.bump_user_messages(conv.id)
        if n < self.settings.limits.rollup_user_messages + 1:
            return conv, ""
        if on_summarize is not None:
            on_summarize()
        got = await self._summarize(conv, skip_last=skip_last)
        if got is None:
            log.info("rollup_deferred", extra={"conversation_id": conv.id, "user_messages": n})
            return conv, ""
        covered = self.transcripts.messages(conv.id)
        covered = covered[:-skip_last] if skip_last else covered
        through = covered[-1].at if covered else self.clock.now()
        self.convs.set_summary(conv.id, got.title, got.summary, through)
        self.convs.reset_session(conv.id)
        rolled = self.convs.get(conv.id)
        assert rolled is not None
        log.info("rollup", extra={"conversation_id": conv.id, "user_messages": n})
        return rolled, self._past_text(rolled, skip_last)

    def _history(self, conv: Conversation, skip_last: int) -> str:
        """새 세션에 붙이는 최근 원문 20개(S11 대체 경로: "원문 기록 20개").

        갈라 연 대화면 이 대화의 최근 것을 먼저 채우고, 남는 자리를 원래 대화의 최근 것으로 앞에 채운다(합쳐 20개).
        """
        own = self.transcripts.recent_entries(conv.id, HISTORY_LINES, skip_last=skip_last)
        if conv.forked_from is None or self._from_app_side(conv):
            return "\n".join(own)
        origin = self.transcripts.recent_entries(conv.forked_from, HISTORY_LINES - len(own))
        return "\n".join([*origin, *own])

    def _from_app_side(self, conv: Conversation) -> bool:
        """텔레그램 쪽 회차 대화를 앱 쪽 회차 대화에서 갈라 열었다(SP8 6.7, 11장). 앱 대화의 `get_status`는 순간의 글을
        주므로 그 세션을 갈라 잇지 않고(`fork_session` 없음) 원래 대화의 원문도 붙이지 않는다. 회차 본문(`## 회차 메시지`,
        회차 차례는 순간을 개수로만 본다)과 이 대화의 원문만으로 시작한다. 텔레그램 → 앱 방향은 그대로 갈라 잇는다."""
        if conv.channel != "telegram" or conv.forked_from is None:
            return False
        origin = self.convs.get(conv.forked_from)
        return origin is not None and origin.channel == "app"

    def _fork_origin_text(self, conv: Conversation) -> str:
        """갈라 연 회차 대화가 새 세션으로 시작할 때 앞에 붙이는 원래 회차 본문(`## 회차 메시지`, 7.2)."""
        if conv.forked_from is None or conv.run_id is None or self.runs is None:
            return ""
        run = self.runs.get(conv.run_id)
        if run is None or not run.outbound_text:
            return ""
        return f"## 회차 메시지\n{run.outbound_text}"

    def _answer_by_message(
        self, run_id: int, channel: Channel, sent_at: datetime, gain: XpGain | None = None
    ) -> None:
        """회차 대화에 온 메시지가 보낸 시각 기준 답장 창 안이면 답으로 적는다. 안 돼도 답은 계속한다."""
        assert self.runs is not None
        run = self.runs.get(run_id)
        if run is None:
            return
        primary = self.runs.merged_into(run.id) or run
        if not self.router.run_in_window(primary, sent_at):
            return
        try:
            self.mark_answered(primary.id, channel, at=sent_at, gain=gain)
        except Exception as e:  # noqa: BLE001 - 답 표시가 안 돼도 메시지에는 답한다
            log.warning("run_answer_record_error", extra={"run_id": run_id, "error_type": type(e).__name__})

    def _message_ctx(self, conversation_id: int, lead: int) -> RunContext:
        """사용자 메시지 처리의 도구 맥락. 앱이면 통로 `app`과 스트림 쓰개(도구 조각, 6.4.1)를 싣는다."""
        app = self._cur
        if app is None:
            return RunContext(conversation_id=conversation_id, run_id=None, events=[], inbound_id=lead)
        return RunContext(
            conversation_id=conversation_id, run_id=None, events=[], inbound_id=lead, channel="app",
            stream=app.writer,
        )

    def _reply_out(
        self, out: Outbound, confirmation: str, activity_ids: list[int], undo_ids: list[int]
    ) -> Outbound:
        """앱 답이면 통로, 쓰개, 확인 문구, 활동 id를 싣는다(M4). 텔레그램은 그대로(확인 문구는 이미 글에 있다)."""
        app = self._cur
        if app is None:
            return out
        out.channel = "app"
        out.writer = app.writer
        out.confirmation = confirmation or None
        out.activity_ids = list(activity_ids)
        out.undo_ids = list(undo_ids)
        if out.draft_task_ids and self.tools is not None:
            out.draft_todos = self.tools.ui_todo_refs(out.draft_task_ids, drafts=True)
        curve = self.tools.curve if self.tools is not None else None
        if curve is not None:
            if out.draft_milestone_ids:
                out.draft_milestones = milestone_refs(out.draft_milestone_ids, curve)
            if out.draft_chapter_ids:
                out.draft_chapters = chapter_refs(out.draft_chapter_ids, curve)
        return out

    def _log_user_lines(
        self, batch: list[Inbound], conversation_id: int | None, pending: PendingInbound | None, lead: int
    ) -> None:
        """사용자 줄을 원문 기록에 쓴다(가린 뒤). 다시 넣은 메시지가 이미 썼으면(`user_logged`) 건너뛴다."""
        if pending is not None and pending.user_logged:
            return
        app = self._cur
        for m in batch:
            if app is not None:
                # 앱 머리글: `#<사용자 줄 id> @app`(7.4). id는 받을 때 고른 대화로 만든다(다시 골라도 그대로)
                cid = app.id_conversation
                mid = app_user_message_id(cid, lead, m.message_id) if cid is not None else None
                self.transcripts.append(
                    m.at, "사용자", conversation_id, None, redact(m.text)[0], channel="app", message_id=mid
                )
            else:
                self.transcripts.append(m.at, "사용자", conversation_id, None, redact(m.text)[0])
        self.state.mark_inbound_user_logged(lead)

    async def _resend_saved_reply(self, batch: list[Inbound], pending: PendingInbound, update_ids: list[int]) -> None:
        """저장해 둔 답(`reply_text`)만 다시 보낸다. 초안 버튼은 이 메시지의 도구 기록에서 다시 만든다."""
        self._log_user_lines(batch, pending.conversation_id, pending, pending.update_id)
        text = pending.reply_text or ""
        if not text:  # 답이 없는 행은 처리 완료로만 둔다
            self._messages_done(update_ids)
            return
        ctx = self._logged_context(pending.update_id, pending.conversation_id)
        # 앱 행의 저장한 답에는 확인 문구가 없다(앱은 `data-activity`로 보낸다): 도구 기록에서 다시 만든다
        confirmation = render_confirmations(ctx.events, self._today()) if self._cur is not None else ""
        acts = self.activity_of(pending.update_id) if self._cur is not None else ([], [])
        with self._awake.hold():
            out = self._reply_out(_outbound(text, ctx), confirmation, *acts)
            if not await self._send_reply(out, update_ids, pending.conversation_id):
                return
            self._messages_done(
                update_ids, reply=text, confirmation=confirmation, conversation_id=pending.conversation_id
            )
            self._transcribe_reply(pending.conversation_id, _join(text, confirmation), [])
        if pending.conversation_id is not None:
            self.convs.touch(pending.conversation_id)
        log.info("inbound_reply_resent", extra={"update_ids": update_ids, "conversation_id": pending.conversation_id})

    async def _finish_after_logged_tools(
        self,
        batch: list[Inbound],
        pending: PendingInbound,
        update_ids: list[int],
        logged: list[tuple[str, int | None, dict[str, Any], int | None]],
    ) -> None:
        """도구가 이미 쓴 메시지: 기록된 도구 호출의 확인 문구와 일반 문구로 답하고 마친다(두뇌는 부르지 않는다)."""
        conv_id = next((c for *_, c in logged if c is not None), None)
        self._log_user_lines(batch, conv_id, pending, pending.update_id)
        ctx = self._logged_context(pending.update_id, conv_id)
        confirmation = render_confirmations(ctx.events, self._today())
        text = _join(FALLBACK_REPLY, confirmation)
        sent = FALLBACK_REPLY if self._cur is not None else text
        self.state.save_inbound_reply(pending.update_id, redact(sent)[0], conv_id)  # 두 단계: 저장 뒤 보낸다
        log.warning("inbound_tools_already_ran", extra={"update_ids": update_ids, "conversation_id": conv_id})
        acts = self.activity_of(pending.update_id) if self._cur is not None else ([], [])
        with self._awake.hold():
            out = self._reply_out(_outbound(sent, ctx), confirmation, *acts)
            if not await self._send_reply(out, update_ids, conv_id):
                return
            self._messages_done(update_ids, reply=sent, confirmation=confirmation, conversation_id=conv_id)
            self._transcribe_reply(conv_id, text, [])
        if conv_id is not None:
            self.convs.touch(conv_id)

    def _logged_context(self, inbound_id: int, conversation_id: int | None) -> RunContext:
        """도구 호출 기록에서 이 메시지의 이벤트를 다시 만든다(확인 문구, 초안 버튼)."""
        events = (
            [ToolEvent(kind=k, task_id=t, data=d) for k, t, d, _ in self.tools.tasks.inbound_tool_events(inbound_id)]
            if self.tools is not None
            else []
        )
        return RunContext(conversation_id=conversation_id, run_id=None, events=events, inbound_id=inbound_id)

    async def _send_reply(self, out: Outbound, update_ids: list[int], conversation_id: int | None) -> bool:
        """사용자 메시지에 답하는 전송. 바로 3회까지(1초, 2초 간격). 끝내 안 되면 `message_send_failed`.

        앱 답은 `app_sender`로 한 번만 쓴다. 끊겼거나 싱크가 없어도 보낸 것으로 본다(M6·M7: 답은 원문 기록과
        `api_idempotency`에 남는다).
        """
        if out.channel == "app":
            await (self.app_sender or _DEFAULT_APP_SENDER).send(out)
            return True
        err = await send_with_retry(
            lambda: self.sender.send(out), sleep=self._sleep, event="message_send_error",
            extra={"update_ids": update_ids},
        )
        if err is None:
            return True
        log.warning(
            "message_send_failed",
            extra={"update_ids": update_ids, "conversation_id": conversation_id, "error_type": type(err).__name__},
        )
        return False

    def _messages_done(
        self, update_ids: list[int], *, reply: str = "", confirmation: str = "", conversation_id: int | None = None
    ) -> None:
        """답을 보낸 메시지를 처리 완료로 기록한다.

        텔레그램: `telegram_updates` + `inbound_pending` 삭제(SP1). 앱(M5): `api_idempotency`(`reply_text`,
        `confirmation`) + `inbound_pending` 삭제를 한 트랜잭션으로. `telegram_updates`에는 쓰지 않는다.
        """
        app = self._cur
        if app is None:
            self.state.mark_updates_done(update_ids)
            return
        cid = conversation_id if conversation_id is not None else app.conversation_id
        self.state.finish_app_inbound(
            app.inbound_id, client_msg_id=app.inbound.client_msg_id, conversation_id=cid,
            reply_text=redact(reply)[0], confirmation=confirmation or None, message_id=app.secretary_id(),
        )
        app.done = True
        # 이제부터 같은 `client_msg_id`는 저장한 답 재생이다(6.4.1)
        self._app.pop(_app_key(app.inbound), None)

    def _deleted(self, conversation_id: int | None) -> bool:
        conv = self.convs.get(conversation_id) if conversation_id is not None else None
        return conv is not None and conv.deleted_at is not None

    def _drop_if_deleted(self, conversation_id: int, session_id: str | None) -> None:
        """두뇌가 답하는 사이 그 대화를 지웠다(SP9 7.7): 이 호출이 만든 세션 파일도 지운다. 답 줄은 쓰지 않는다."""
        if not self._deleted(conversation_id):
            return
        log.info("conversation_deleted_while_answering", extra={"conversation_id": conversation_id})
        if self.claude_config_dir is not None and session_id:
            moments_job.remove_session_file(
                session_id, config_dir=self.claude_config_dir, event="conversation_session_cleanup",
            )

    def _transcribe_reply(self, conversation_id: int | None, text: str, tools: list[str]) -> None:
        """보낸 답을 원문 기록에 남긴다. 기록이 안 돼도 사용자는 이미 받았으니 종류만 로그에 남긴다.

        앱 답은 머리글에 `#m-<대화>-<|inbound_id|> @app`(그 답의 `start.messageId`, 6.4.6)을 붙인다.
        답하는 사이 지운 대화(SP9 7.7)에는 쓰지 않는다.
        """
        if self._deleted(conversation_id):
            return
        app = self._cur
        try:
            if app is not None:
                mid = app.secretary_id()  # 그 답의 `start.messageId`(다시 고른 대화로 가도 같다)
                self.transcripts.append(
                    self.clock.now(), "비서", conversation_id, None, redact(text)[0], tools=tools, channel="app",
                    message_id=mid,
                )
            else:
                self.transcripts.append(self.clock.now(), "비서", conversation_id, None, redact(text)[0], tools=tools)
        except Exception as e:  # noqa: BLE001 - 본문과 경로 없이 종류만 남긴다
            log.warning("reply_transcript_error", extra={"error_type": type(e).__name__})

    def _capped(self) -> bool:
        return self.state.usage(self._today()).brain_calls >= self.settings.limits.daily_brain_calls

    async def _run_notice_auth(self, error: str | None) -> None:
        """회차가 보내는 로그인·결제 안내. 논리적 날짜마다 한 번만(스펙 5.3)."""
        today = self._today().isoformat()
        if self.state.get(LAST_AUTH_NOTICE_KEY) == today:
            return
        if await self.send_notice(_auth_copy(error)) is not None:
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
        if await self.send_notice(rate_limit_notice(self._resume_text(until))) is not None:
            self.state.set(LAST_RATE_LIMIT_NOTICE_KEY, key)

    def _resume_text(self, until: datetime) -> str:
        """`{재개}`: 오늘(논리적 날짜)이면 `HH:MM`, 아니면 `M월 D일 HH:MM` (한국 시간)."""
        s = self.settings
        lt = local(until, s.timezone)
        if logical_date(until, s.timezone, s.day_boundary) == self._today():
            return f"{lt:%H:%M}"
        return f"{lt.month}월 {lt.day}일 {lt:%H:%M}"

    async def send_notice(self, text: str) -> Channel | None:
        """고정 안내 전송(7.3 D8: 실제 통로로). 받은 통로를 돌려준다(못 보냈으면 None).

        원문 기록은 대화 밖(`[-]`). 먼저 보낸 메시지 수에는 세지 않는다. 자동 복구 알림(`/internal/notify`)도 이 길을 쓴다.
        """
        channel: Channel = "telegram"
        if self.delivery is not None:
            got = await self.delivery.deliver_notice(text)
            if got is None:
                return None
            channel = got
        else:
            try:
                await self.sender.send(Outbound(text=text))
            except Exception as e:  # noqa: BLE001 - 안내가 안 가도 다음 기회에 다시 보낸다
                log.warning("notice_send_error", extra={"error_type": type(e).__name__})
                return None
        try:
            self.transcripts.append(self.clock.now(), "비서", None, None, text, channel=channel)
        except Exception:
            log.exception("notice_transcript_error")
        return channel

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
        with self._awake.hold():
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
            outcome = await self._send_run(out, run, attempts=SEND_ATTEMPTS)
            if outcome.sent:
                self._run_delivered(run, merged, conv, out.text, tool_names, outcome=outcome)
                return
            self._record_not_sent(run, outcome)
            for r in (run, *merged):
                runs.mark_failed(r.id, "send")
            self._later(
                RESEND_DELAY_S,
                _ResendJob(run, merged, tool_names, list(out.draft_task_ids), out.ask_condition_for,
                           list(out.confirms), list(out.draft_milestone_ids), list(out.draft_chapter_ids),
                           out.ladder, habit_date=out.habit_date),
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
        habit_date = self._habit_date(run, merged, ask)  # 사다리 때문에 `ask`를 지우기 전의 값(SP7 5.7)
        step, question = self._review_extras(run, merged, ask)
        if step is not None:
            ask = None  # 컨디션 줄 대신 첫 단계 줄(한 메시지에 숫자 키보드 한 종류)
        result, run_ctx = await self._run_brain(
            run, merged, conv, ask, step=step, question=question, habit_date=habit_date
        )
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
            result, run_ctx = await self._run_brain(
                run, merged, conv, ask, step=step, question=question, habit_date=habit_date
            )
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
        # 턴 상한이어도 도구가 이미 바꾼 것이 있으면 알린다: 턴 상한 문구 + 확인 문구, 초안·컨디션 버튼.
        # 같은 두 단계(저장 → 전송)로 보내고 done으로 둔다(최종 리뷰 Minor 3 결정). 도구 이벤트가 없으면 failed
        partial = result.status == "max_turns" and bool(run_ctx.events)
        if not _run_ok(result) and not partial:
            # 사용자에게는 아무것도 보내지 않는다(스펙 5.4 재실행 규칙 4). 로그만 남긴다.
            for r in (run, *merged):
                runs.mark_failed(r.id, result.status)
            self.convs.close(conv.id)
            log.warning("run_brain_failed", extra={"run_id": run.id, "status": result.status})
            return None
        if partial:
            log.warning("run_max_turns_after_tools", extra={"run_id": run.id})
        if result.session_id:
            self.convs.set_session(conv.id, result.session_id)
        text = MAX_TURNS_REPLY if partial else result.text
        confirmations = self._confirmations(run_ctx)
        if confirmations:
            text = f"{text}\n\n{confirmations}"
        if step is not None:
            # 컨디션 줄이 없는 회고 메시지(11.1-1 (c)): 첫 단계를 글 끝에 붙이고 회차마다 한 번으로 표시한다
            text = f"{text}\n\n{step.text}"
            self._claim_review_step(step, "run")
        runs.save_outbound(run.id, text)
        out = _outbound(text, run_ctx)
        out.ask_condition_for = ask
        out.ladder = step.ladder if step is not None else None
        out.habit_date = habit_date
        if question is not None:
            self._run_questions[run.id] = question[0]  # 보낸 뒤에 `asked`(11.1-5, `_run_delivered`)
        return conv, out, list(run_ctx.tool_names)

    def _review_extras(
        self, run: Run, merged: list[Run], ask: date | None
    ) -> tuple[NextStep | None, tuple[int, str] | None]:
        """월말 회고의 (회고 메시지에 바로 붙일 첫 단계, 두뇌에게 줄 열린 시드 질문 `(id, 글)`).

        첫 단계는 컨디션 줄이 없을 때만 붙인다: 컨디션 버튼 날짜가 없거나 그 날짜 컨디션이 이미 있을 때(11.1-1 (c)).
        그때는 SP1과 달리 컨디션 줄을 다시 붙이지 않는다(한 메시지에 숫자 키보드 한 종류).
        """
        flow = self.review_flow
        of = review_in([run, *merged], self.settings)
        if flow is None or of is None or not of.steps:
            return None, None
        recorded = ask is not None and self.conditions is not None and self.conditions.get(ask) is not None
        step = flow.pending_step(run) if ask is None or recorded else None
        q = flow.curve.next_open_question()
        return step, ((q.id, q.text) if q is not None else None)

    def _review_reply_run(self, conv: Conversation, sent_at: datetime) -> Run | None:
        """텔레그램 회차 대화에 보낸 시각 기준 답장 창 안에서 들어온 글이면 그 회차(primary). 단계는
        `ReviewFlow.reply_step`이 정한다(월말 회고가 아니면 없다)."""
        flow = self.review_flow
        if flow is None or self.runs is None or conv.kind is not ConversationKind.run or conv.run_id is None:
            return None
        run = self.runs.get(conv.run_id)
        if run is None:
            return None
        primary = self.runs.merged_into(run.id) or run
        return primary if self.router.run_in_window(primary, sent_at) else None

    def _claim_review_step(self, step: NextStep, where: str) -> None:
        """보낸(보낼) 단계를 적는다: 첫 단계면 회차마다 한 번 표시, 다음 단계면 그 회차의 단계."""
        flow = self.review_flow
        if flow is None or step.run_id is None:
            return
        if step.first:
            flow.claim(step.run_id, step.stage)
        else:
            flow.set_stage(step.run_id, step.stage)
        log.info("review_step_prompted", extra={"run_id": step.run_id, "stage": step.stage, "where": where})

    async def _run_brain(
        self, run: Run, merged: list[Run], conv: Conversation, ask: date | None = None, *,
        step: NextStep | None = None, question: tuple[int, str] | None = None, habit_date: date | None = None,
    ) -> tuple[BrainResult, RunContext]:
        """루프 지시문(합친 회차의 지시문을 뒤에 이어 붙임)과 앞머리로 새 세션을 연다.

        컨디션 버튼을 붙이는 회차면 두뇌가 알고 쓰도록 `## 컨디션 버튼`을 덧붙인다. 월말·분기·연말 회고면
        `review_week.md` 바로 뒤에 `review_{month,quarter,year}.md`를 차례로 붙이고(11.1), 하네스가 메시지 끝에
        붙일 질문과 열린 시드 질문(`## 이번에 물을 질문`)을 알린다.
        """
        # 회차 첫 호출의 활동 통로는 `scheduler`다(6.4.4)
        run_ctx = RunContext(
            conversation_id=conv.id, run_id=run.id, events=[], activity_channel="scheduler", kind="run"
        )
        of = review_in([run, *merged], self.settings)
        loop_prompts: list[str] = []
        for r in (run, *merged):
            loop_prompts.append(prompts.load(LOOP_PROMPTS[r.loop]))
            if r.loop is LoopKey.review and of is not None:
                loop_prompts.extend(prompts.load(f) for f in of.steps.prompt_files())
        prompt = _join(
            *loop_prompts,
            self._preamble(
                False,
                merged=[m.loop.value for m in merged] or None,
                include_habits=any(r.loop is LoopKey.evening_checkin for r in (run, *merged)),  # 오늘 블록(5.7). 주간 블록은 아래
                habit_day=habit_date,
            ),
            self._habit_week_block(run, merged),
            self._review_records_blocks(run, merged),
            _condition_buttons_note(ask),
            _habit_buttons_note(habit_date),
            self._review_week_note(run, merged),
            step_note(step, where="메시지"),
            f"## 이번에 물을 질문\n{question[1]}" if question is not None else "",
        )
        return await self._call_brain(prompt, session_id=None, run_ctx=run_ctx), run_ctx

    def _habit_week_block(self, run: Run, merged: list[Run]) -> str:
        """주간 회고 회차에만 `## 이번 주 습관`(SP7 5.7)."""
        review = _review_of(run, merged)
        habits = self.tools.habits if self.tools is not None else None
        if review is None or habits is None:
            return ""
        s = self.settings
        return habit_week_block(habits, logical_date(review.scheduled_for, s.timezone, s.day_boundary))

    def _review_records_blocks(self, run: Run, merged: list[Run]) -> str:
        """주간 회고 회차에만 `## 이번 주 이룬 순간`(날짜와 개수만, 어느 통로든: 계획 결정 10)과 `## 요즘 손이 간 영역`
        (SP8 10.3). 전달 통로(`delivery.effective()`)는 보지 않는다."""
        review = _review_of(run, merged)
        t = self.tools
        if review is None or t is None:
            return ""
        s = self.settings
        day = logical_date(review.scheduled_for, s.timezone, s.day_boundary)
        moments = moments_week_block(t.moments, day) if t.moments is not None else ""
        areas = ""
        if t.status is not None and t.curve is not None and t.conditions is not None:
            snap = status_snapshot(
                now=self.clock.now(), tz=s.timezone, boundary=s.day_boundary, status=t.status, curve=t.curve,
                tasks=t.tasks, conditions=t.conditions,
            )
            areas = recent_areas_block(snap["stats"])
        return _join(moments, areas)

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

    def _habit_date(self, run: Run, merged: list[Run], ask: date | None) -> date | None:
        """습관 버튼의 날짜(SP7 5.7): 저녁 체크인(합친 회차 포함)이고 활성 습관이 하나 이상이면 `ask`(그 체크인의
        날짜), 아니면 None. 아침 브리핑의 어제 컨디션 날짜에는 습관 줄을 붙이지 않는다."""
        habits = self.tools.habits if self.tools is not None else None
        if habits is None or not any(r.loop is LoopKey.evening_checkin for r in (run, *merged)):
            return None
        return ask if habits.list() else None

    def _ask_condition_for(self, run: Run, merged: list[Run] | None = None) -> date | None:
        """컨디션 버튼의 날짜. 판정은 `harness.context.ask_condition_for`(앱 카드와 같은 함수)."""
        assert self.runs is not None
        return ask_condition_for(
            run, merged, conditions=self.conditions, runs=self.runs, settings=self.settings
        )

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

    async def _send_run(self, out: Outbound, run: Run, *, attempts: int) -> DeliveryOutcome:
        """회차 전송(7.3 D2~D4). `telegram_message_id`는 텔레그램 전송이 돌려준 정수일 때만."""
        from my_planner.harness.delivery import DeliveryOutcome

        if self.delivery is not None:
            s = self.settings
            until = reply_window_end(Due(run.loop, run.scheduled_for, run.cadence), s.timezone, s.day_boundary, cfg=s)
            return await self.delivery.deliver_run(run, out, reply_until=until, attempts=attempts)
        sent, mid = await send_run_telegram(self.sender, out, sleep=self._sleep, attempts=attempts, run_id=run.id)
        return DeliveryOutcome("telegram", "full", sent, mid)

    def _record_not_sent(self, run: Run, outcome: DeliveryOutcome) -> None:
        """끝내 아무 데도 못 보낸 회차의 시도(7.3 D4). 기록이 안 돼도 회차 처리는 그대로 간다."""
        if self.deliveries is None:
            return
        try:
            with transaction(self.runs.conn if self.runs is not None else self.state.conn):
                self._record_deliveries(run, outcome)
        except Exception as e:  # noqa: BLE001 - 종류만 남긴다
            log.warning("run_delivery_record_error", extra={"run_id": run.id, "error_type": type(e).__name__})

    def _record_deliveries(self, run: Run, outcome: DeliveryOutcome) -> None:
        """`run_deliveries`는 `harness/delivery.py`가 쓴다(4.3). 회차 상태와 같은 트랜잭션 안에서 부른다."""
        from my_planner.harness.delivery import record_deliveries

        assert self.deliveries is not None
        record_deliveries(self.deliveries, run.id, outcome)

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
        with self._awake.hold():
            out = Outbound(
                text=run.outbound_text,
                draft_conversation_id=(
                    run.conversation_id if job.draft_task_ids or job.draft_milestone_ids else None
                ),
                draft_task_ids=list(job.draft_task_ids),
                ask_condition_for=job.ask_condition_for,
                confirms=list(job.confirms),
                draft_milestone_ids=list(job.draft_milestone_ids),
                draft_chapter_ids=list(job.draft_chapter_ids),
                ladder=job.ladder,
                habit_date=job.habit_date,
            )
            # 전달이 하나도 안 된 회차(failed)만 여기 온다. 같은 D2~D4 순서로 한 번(7.3 D7)
            outcome = await self._send_run(out, run, attempts=1)
            if outcome.sent and conv is not None:
                self._run_delivered(run, job.merged, conv, run.outbound_text, job.tool_names, outcome=outcome)
            elif not outcome.sent:
                self._record_not_sent(run, outcome)

    def _release_carry(self, runs: Iterable[Run]) -> None:
        """넘겨 받은 회고가 끝났으면(보냄, 건너뜀) `carry_review_run_id`를 지운다. 러너는 합칠 때 지우지 않는다."""
        mark = self.state.get(CARRY_REVIEW_KEY)
        if mark is not None and mark in {str(r.id) for r in runs}:
            self.state.set(CARRY_REVIEW_KEY, None)

    def _run_delivered(
        self, run: Run, merged: list[Run], conv: Conversation, text: str, tool_names: list[str], *,
        outcome: DeliveryOutcome,
    ) -> None:
        """전송이 끝난 회차: primary와 merged 모두 done, 먼저 보낸 메시지 수 +1(통로가 몇이든 회차마다 한 번, 7.3 D6),
        전달 기록, 회차 대화의 통로(전체 본문을 받은 통로, D5), 그다음 원문 기록, 대화 갱신, 회고 저장."""
        assert self.runs is not None
        # 사용자는 이미 받았다. 상태, 카운터, 전달 기록을 한 트랜잭션에 먼저 적어 다음 시작 때 다시 보내지 않게 한다.
        try:
            with transaction(self.runs.conn):
                for r in (run, *merged):
                    self.runs.mark_done(r.id)
                self._release_carry([run, *merged])
                self.state.incr_usage(self._today(), "proactive_messages")
                if self.deliveries is not None:
                    self._record_deliveries(run, outcome)
                if conv.channel != outcome.channel:
                    self.convs.set_channel(conv.id, outcome.channel)
        except Exception:
            # 한 트랜잭션이 안 됐다(디스크, 잠금 등). 회차가 running으로 남으면 다음 시작 때 다시 보낼 수 있으니
            # done만 따로 적는다(중복 전송 방지). 카운터와 전달 기록은 비운 채 둔다. 이것도 안 되면 그대로 올린다
            log.exception("run_delivered_record_error", extra={"run_id": run.id})
            for r in (run, *merged):
                self.runs.mark_done(r.id)
            self._release_carry([run, *merged])
        try:
            self.transcripts.append(
                self.clock.now(), "비서", conv.id, run.loop.value, redact(text)[0], tools=tool_names,
                channel=outcome.channel,
            )
        except Exception:
            log.exception("run_transcript_error", extra={"run_id": run.id})
        try:
            self.convs.touch(conv.id)
        except Exception:
            log.exception("run_touch_error", extra={"run_id": run.id})
        self._save_review(run, merged, text)
        question = self._run_questions.pop(run.id, None)
        if question is not None and self.tools is not None:
            try:
                self.tools.mark_question_asked(question)  # 열린 시드 질문은 월말 회고마다 하나(11.1-5)
            except Exception as e:  # noqa: BLE001 - 질문 표시가 안 되면 다음 월말 회고가 다시 싣는다
                log.warning("curve_question_mark_error", extra={"error_type": type(e).__name__})
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
        day = logical_date(review.scheduled_for, s.timezone, s.day_boundary)
        period = period_of(Cadence.week, day)
        of = review_in([review], s)
        included = of.steps.included_line(day) if of is not None else None
        try:
            save_weekly_review(self.data_dir, period, redact(text)[0], included=included)
        except Exception as e:  # noqa: BLE001 - 본문과 경로 없이 종류만 남긴다
            log.warning("review_save_error", extra={"run_id": review.id, "error_type": type(e).__name__})

    def _today(self) -> date:
        return logical_date(self.clock.now(), self.settings.timezone, self.settings.day_boundary)

    def _preamble(
        self, resumed: bool, *, merged: list[str] | None = None, include_habits: bool = False,
        habit_day: date | None = None,
    ) -> str:
        """새 세션일 때만 붙인다: 지금 시각, 열린 할 일, 오늘 일정(, 함께 처리하는 회차, 오늘 습관)."""
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
            habits=self.tools.habits,
            include_habits=include_habits,
            habit_day=habit_day,
            events=getattr(self.tools, "events", None),  # `## 오늘 일정`(SP9 5.5)
        )

    def _state_time(self, key: str) -> datetime | None:
        v = self.state.get(key)
        return from_iso(v) if v else None

    async def _call_brain(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext, fork_session: bool = False,
        system_prompt: str | None = None, max_turns: int | None = None, persist_session: bool = True,
    ) -> BrainResult:
        """두뇌를 부르는 동안 5초마다 '입력 중'을 보낸다. `fork_session`: `session_id`를 갈라 새 세션으로(7.2).

        `system_prompt`, `max_turns`, `persist_session`: 하루 끝 순간 호출(SP8 6.3). 순간 호출은 '입력 중'이 없다.
        """
        if run_ctx.stream is not None:
            run_ctx.stream.begin_attempt()  # 앞 시도가 글을 보냈으면 새 단계로 나눈다(06b)
        self.state.incr_usage(self._today(), "brain_calls")  # 모든 호출이 하루 상한에 들어간다(스펙 7, 두 통로가 함께)
        # '입력 중'은 텔레그램에만. 앱은 `data-status`와 `: ping`이 대신한다(6.4.1). 순간 호출은 아무 데도 보내지 않는다
        quiet = run_ctx.channel == "app" or run_ctx.kind in ("moments", "summary")
        typing = asyncio.create_task(self._typing_loop() if not quiet else _idle(), name="typing")
        started = time.monotonic()
        try:
            # 한 호출이 멈춰 직렬 작업자 전체가 서지 않도록 상한을 둔다. 넘으면 error(timeout)로 보고
            # 메시지 백오프와 회차 재실행 규칙을 그대로 따른다(도구가 이미 썼으면 다시 부르지 않는다).
            # anyio 취소 범위를 쓴다: SDK가 CLI 자식을 정리하는 차폐 구간(close())이 끝까지 돈다.
            # asyncio.wait_for의 날 취소는 그 차폐 안의 다음 await에서 터져 자식이 고아로 남을 수 있다
            with anyio.fail_after(self.settings.limits.brain_timeout_s):
                # 기본값이 아닐 때만 넘긴다: SP1의 두뇌 구현(시험용 포함)은 이 인자들을 모른다
                extra: dict[str, Any] = {"fork_session": True} if fork_session else {}
                if system_prompt is not None:
                    extra["system_prompt"] = system_prompt
                if max_turns is not None:
                    extra["max_turns"] = max_turns
                if not persist_session:
                    extra["persist_session"] = False
                result = await self.brain.run(prompt, session_id=session_id, run_ctx=run_ctx, **extra)
        except TimeoutError:
            result = BrainResult(text="", session_id=session_id, turns=0, status="error", error="timeout")
        finally:
            typing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing
        self._record_brain_auth(result)
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
                "forked": fork_session,
            },
        )
        return result

    # --- 대화 요약 (SP9 7.2) ---

    def queue_summaries(self, *, retry: bool = False) -> int:
        """요약할 닫힌 앱 대화를 큐에 넣는다. 넣은 수를 돌려준다.

        tick(`retry=False`): 닫혔는데 제목·요약이 없거나 요약 뒤에 말이 더 있는 것. 이 프로세스에서 이미 해 본 것은 빼고.
        하루 한 번 작업(`retry=True`): 해 본 표시를 지우고, 최근 7일 안의 요약 없는 것(대체 제목뿐)을 다시 넣는다.
        """
        if retry:
            self._summary_tried.clear()
            ids = self.convs.summary_retry(self.clock.now() - timedelta(days=summaries.RETRY_DAYS))
            ids += [i for i in self.convs.summary_pending() if i not in ids]
        else:
            ids = [i for i in self.convs.summary_pending() if not self._tried(i)]
        now = self.clock.now()
        # 앱 쪽 회차 대화는 닫히지 않는다: 답장 창이 끝나면 닫힌 것처럼 요약한다(7.2 "앱에서 답한 회차")
        ids += [
            c.id for c in self.convs.open_app_runs_unsummarized()
            if not self._tried(c.id, c) and c.id not in ids and not self.router.continues(c, now)
        ]
        new = [i for i in ids if i not in self._summary_queued]
        for i in new:
            self._summary_queued.add(i)
            self._queue.put_nowait((_PRIORITY_SUMMARY, next(self._seq), _SummaryJob(i)))
        if new:
            log.info("summaries_queued", extra={"count": len(new), "retry": retry})
        return len(new)

    def _tried(self, cid: int, conv: Conversation | None = None) -> bool:
        """이 프로세스에서 지금의 마지막 말까지 이미 요약을 해 본 대화인가."""
        if cid not in self._summary_tried:
            return False
        conv = conv or self.convs.get(cid)
        return conv is None or self._summary_tried[cid] == conv.last_message_at

    async def _handle_summary(self, job: _SummaryJob) -> None:
        """닫힌 앱 대화 하나를 요약해 적는다. 안 되면 제목이 없을 때만 대체 제목(첫 사용자 메시지 앞 20자, 요약 NULL)."""
        cid = job.conversation_id
        self._summary_queued.discard(cid)
        if self._stopping:  # 멈추는 중: 다음 실행의 첫 tick이 다시 넣는다
            return
        conv = self.convs.get(cid)
        if conv is None or not self._summarizable(conv):
            return
        self._summary_tried[cid] = conv.last_message_at
        got = await self._summarize(conv)
        conv = self.convs.get(cid)  # 요약하는 동안 지웠거나 다시 열었을 수 있다
        if conv is None or conv.deleted_at is not None:
            return
        if got is not None:
            self.convs.set_summary(cid, got.title, got.summary, conv.last_message_at)
            state = "done" if got.summary else "title_only"
        elif conv.title is None:
            self.convs.set_summary(cid, summaries.fallback_title(self.transcripts.messages(cid)), None, None)
            state = "fallback"
        else:
            state = "kept"  # 앞서 만든 제목·요약을 그대로 둔다
        log.info("summary_job", extra={"conversation_id": cid, "state": state})

    # --- 대화 목록 (SP9 7.3, 7.7) ---

    def new_conversation(self) -> list[int]:
        """`POST /conversations/new`: 열린 앱 `chat`·`plan`을 닫는다(요약은 다음 tick이 큐에 넣는다). 닫은 id."""
        closed = self.router.new_app_conversation()
        log.info("conversation_new", extra={"closed": len(closed)})
        return closed

    def delete_conversation(self, conversation_id: int) -> bool:
        """`DELETE /conversations/{id}`(7.7): 즉시 갈래로 지우고(활동 "대화를 지웠어요", 되돌리기 없음), 커밋 뒤
        원문 기록의 그 대화 줄을 `[지운 대화]`로 바꾸고 그 대화의 두뇌 세션 파일을 모두 지운다. 없으면 False."""
        if self.tools is None:
            return False
        res = self.apply_action(ActionRequest(
            "conversation_delete", {"id": conversation_id}, actor="user", channel="app", endpoint="conversations",
        ))
        if res.status != "applied":
            return False
        out = res.body["result"]
        self._summary_queued.discard(conversation_id)
        erased, failed, removed = self._erase_deleted(
            conversation_id, datetime.fromisoformat(out["opened_at"]), datetime.fromisoformat(out["last_message_at"]),
            out["sessions"],
        )
        log.info("conversation_deleted", extra={
            "conversation_id": conversation_id, "erased": erased, "failed_days": failed,
            "sessions": len(out["sessions"]), "removed": removed,
        })
        return True

    def reerase_deleted(self, *, days: int = REERASE_DAYS) -> int:
        """하루 한 번 작업(7.7): 최근 `days`일 안에 지운 대화의 원문 줄과 세션 파일을 다시 지운다. 지우던 때 파일이
        잡혀 있었거나 커밋 뒤 프로세스가 멈췄어도 남지 않게. 여러 번 해도 결과가 같다. 새로 지운 항목 수."""
        total = 0
        for conv in self.convs.deleted_since(self.clock.now() - timedelta(days=days)):
            erased, _, _ = self._erase_deleted(
                conv.id, conv.opened_at, conv.last_message_at, self.convs.sessions(conv.id),
            )
            total += erased
        log.info("conversations_reerased", extra={"erased": total})
        return total

    def _erase_deleted(
        self, conversation_id: int, opened_at: datetime, last_message_at: datetime, sessions: list[str],
    ) -> tuple[int, int, int]:
        """원문 기록의 그 대화 줄을 `[지운 대화]`로, 그 대화의 두뇌 세션 파일을 모두 지운다. (지운 항목, 못 바꾼 날, 지운 파일)."""
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        start = logical_date(opened_at, tz, boundary)
        # 답 줄은 `last_message_at`보다 조금 늦게 쓰일 수 있어 하루 더 본다(그 대화의 줄만 바꾼다)
        end = logical_date(last_message_at, tz, boundary) + timedelta(days=1)
        result = erase_conversation(self.transcripts.root, conversation_id, start, end)
        removed = 0
        if self.claude_config_dir is not None:
            for sid in sessions:
                removed += moments_job.remove_session_file(
                    sid, config_dir=self.claude_config_dir, event="conversation_session_cleanup",
                )
        return result.erased, len(result.failed), removed

    def _summarizable(self, conv: Conversation) -> bool:
        """앱 대화이고 지우지 않았고 끝났다(닫힘, 회차 대화는 답장 창이 끝남)."""
        if conv.channel != "app" or conv.deleted_at is not None:
            return False
        if conv.closed_at is not None:
            return True
        return conv.kind is ConversationKind.run and not self.router.continues(conv, self.clock.now())

    def _summary_blocked(self) -> bool:
        """두뇌를 부르지 않을 때: 요약 하루 상한, 두뇌 호출 하루 상한, 사용 한도 대기, 로그인·결제 문제."""
        usage = self.state.usage(self._today())
        limits = self.settings.limits
        if usage.summaries >= limits.daily_summaries or usage.brain_calls >= limits.daily_brain_calls:
            return True
        if self.state.get(BRAIN_AUTH_STATE_KEY) in ("login", "billing"):
            return True
        limited = self._state_time(LIMITED_UNTIL_KEY)
        return limited is not None and self.clock.now() < limited

    async def _summarize(self, conv: Conversation, *, skip_last: int = 0) -> summaries.Summary | None:
        """그 대화의 원문 줄(맨 뒤 `skip_last`개 뺌)과 이전 요약으로 요약한다. 상한이면 두뇌 없이 None."""
        lines = self.transcripts.messages(conv.id)
        if skip_last:
            lines = lines[:-skip_last]
        if summaries.needs_brain(lines) and self._summary_blocked():
            log.info("summary_blocked", extra={"conversation_id": conv.id})
            return None
        return await summaries.summarize(
            conv, lines, conv.summary or None, _SummaryCaller(self), max_chars=self.settings.limits.input_max_chars,
        )

    # --- 하루 끝 순간 (SP8 6.2~6.3) ---

    def _moments_blocked(self) -> bool:
        """두뇌를 부르지 않고 그대로 둘 때(6.2-5): 사용자 몫 10회가 남지 않음, 로그인·결제 문제, 사용 한도 대기.

        `brain.auth`는 `login`·`billing`일 때만 멈춘다(설치 뒤 아직 모르면 막지 않는다, 계획 결정 5). 안전 모드에서는
        디스패처가 없다(결정 6). 멈춤(`/pause`)은 보지 않는다(6.2-7).
        """
        limit = self.settings.limits.daily_brain_calls - moments_job.MOMENTS_RESERVE_CALLS
        if self.state.usage(self._today()).brain_calls >= limit:
            return True
        if self.state.get(BRAIN_AUTH_STATE_KEY) in ("login", "billing"):
            return True
        limited = self._state_time(LIMITED_UNTIL_KEY)
        return limited is not None and self.clock.now() < limited

    async def _handle_moments(self, job: _MomentsJob) -> None:
        """그날의 이룬 순간을 정리한다. 원문 기록에 쓰지 않고 알리지 않는다. 로그는 `moments_job` 한 줄(글 없음)."""
        if self._stopping:  # 멈추는 중: 두뇌를 부르지 않고 `pending` 그대로(다음 날 다시 고른다, Review Focus 1)
            return
        tools = self.tools
        if tools is None or tools.moments is None:
            return
        repo, d = tools.moments, job.date
        row = repo.day(d)
        if row is not None and row.state != "pending":  # 실행 직전에 다시 읽는다(6.2-4)
            return
        started = time.monotonic()
        s = self.settings
        inp = moments_job.build_moments_input(
            d, tasks=tools.tasks, habits=tools.habits, conditions=tools.conditions, transcripts=self.transcripts,
            tz=s.timezone, boundary=s.day_boundary,
        )
        if not inp.has_data:
            moments_job.mark_empty(repo, d, self.clock.now())
            self._log_moments(d, "empty", 0, 0, started)
            return
        if self._moments_blocked():
            log.info("moments_job_waiting", extra={"date": d.isoformat()})
            return
        run_ctx = RunContext(
            None, None, kind="moments", actor="secretary", activity_channel="scheduler", moments_date=d,
            moments_refs=inp.refs,
        )
        result: BrainResult | None = None
        try:
            result = await self._call_brain(
                inp.text, session_id=None, run_ctx=run_ctx, system_prompt=moments_job.moments_system_prompt(),
                max_turns=moments_job.MOMENTS_MAX_TURNS, persist_session=False,
            )
        finally:
            # 결과가 무엇이든(시간 초과·취소 포함) 그 세션 파일을 지운다(플래그와 두 겹, 결정 18). 결과에 id가 없으면
            # 두뇌가 호출 중에 본 id를 쓴다. 둘 다 없으면 id를 모른다
            if self.claude_config_dir is not None:
                sid = (result.session_id if result is not None else None) or run_ctx.brain_session_id
                if sid is None:
                    log.info("moments_session_cleanup", extra={"removed": False, "reason": "no_session_id"})
                else:
                    moments_job.remove_session_file(sid, config_dir=self.claude_config_dir)
        if result.status == "rate_limited":
            self._set_limited(result.retry_at)
        state = moments_job.settle(repo, d, result, "save_moments" in run_ctx.tool_names, self.clock.now())
        saved = 0
        if state == "done":
            got = repo.day(d)
            saved = got.saved if got is not None else 0
        rejected = sum(int(e.data.get("rejected", 0)) for e in run_ctx.events if e.kind == "moments_saved")
        self._log_moments(d, state, saved, rejected, started)

    @staticmethod
    def _log_moments(d: date, state: str, saved: int, rejected: int, started: float) -> None:
        log.info("moments_job", extra={
            "date": d.isoformat(), "state": state, "saved": saved, "rejected": rejected,
            "duration_ms": round((time.monotonic() - started) * 1000),
        })

    def _record_brain_auth(self, result: BrainResult) -> None:
        """`GET /health`의 `brain.auth`(SP3-4 6.3.1): 로그인·결제 문제면 그 종류, 두뇌가 답했으면 `ok`.

        그 밖의 오류(시간 초과, 연결 오류)는 인증 상태를 알려 주지 않으므로 지난 값을 그대로 둔다.
        """
        if result.status == "auth_error":
            auth = "billing" if result.error == "billing" else "login"
        elif result.status == "error":
            return
        else:
            auth = "ok"
        try:
            with transaction(self.state.conn):
                self.state.set(BRAIN_AUTH_STATE_KEY, auth)
                self.state.set(BRAIN_AUTH_CHECKED_AT_KEY, to_iso(self.clock.now()))
        except Exception as e:  # noqa: BLE001 - 상태 표시일 뿐이다. 답은 그대로 간다
            log.warning("brain_auth_record_error", extra={"error_type": type(e).__name__})

    async def _typing_loop(self) -> None:
        while True:
            try:
                await self.sender.typing()
            except Exception as e:  # noqa: BLE001 - 입력 중 표시는 없어도 된다
                log.warning("typing_error", extra={"error_type": type(e).__name__})
            await self._sleep(TYPING_INTERVAL_S)


class _SummaryCaller:
    """요약 호출을 디스패처의 두뇌 호출(시간 상한, 하루 상한 셈)로 잇는다. 요약 하루 셈도 올리고, 끝나면 세션 파일을 지운다."""

    def __init__(self, d: Dispatcher) -> None:
        self._d = d

    async def run(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext, system_prompt: str | None = None,
        max_turns: int | None = None, persist_session: bool = True,
    ) -> BrainResult:
        d = self._d
        d.state.incr_usage(d._today(), "summaries")
        result: BrainResult | None = None
        try:
            result = await d._call_brain(
                prompt, session_id=session_id, run_ctx=run_ctx, system_prompt=system_prompt, max_turns=max_turns,
                persist_session=persist_session,
            )
        finally:
            if d.claude_config_dir is not None:  # 이어 쓰지 않는 세션이다(플래그와 두 겹, SP8 6.3과 같다)
                sid = (result.session_id if result is not None else None) or run_ctx.brain_session_id
                moments_job.remove_session_file(sid, config_dir=d.claude_config_dir, event="summary_session_cleanup")
        if result.status == "rate_limited":
            d._set_limited(result.retry_at)
        return result


async def send_with_retry(
    send: Callable[[], Awaitable[object]],
    *,
    sleep: Callable[[float], Awaitable[None]],
    event: str,
    extra: dict[str, Any],
    attempts: int = SEND_ATTEMPTS,
) -> Exception | None:
    """`send()`를 바로 `attempts`회까지 부른다. 시도 사이 1초, 2초(…) 쉰다. 된 즉시 None, 끝내 안 되면 마지막 예외.

    실패마다 `event` 경고를 남긴다(본문 없이 시도 번호와 예외 종류만). 텔레그램 쪽 명령 답과 글이 아닌 메시지 답도 쓴다.
    """
    err: Exception | None = None
    for i in range(attempts):
        try:
            await send()
            return None
        except Exception as e:  # noqa: BLE001 - 어떤 전송 오류든 다시 시도한다. 본문 없이 종류만 남긴다
            err = e
            log.warning(event, extra={**extra, "try": i + 1, "error_type": type(e).__name__})
            if i + 1 < attempts:
                await sleep(SEND_RETRY_DELAYS_S[i])
    return err


async def send_run_telegram(
    sender: Sender, out: Outbound, *, sleep: Callable[[float], Awaitable[None]], attempts: int, run_id: int
) -> tuple[bool, int | None]:
    """회차 본문을 텔레그램에 보낸다(바로 `attempts`회까지). (보냈나, 버튼이 붙은 마지막 조각의 메시지 id).

    id는 전송이 돌려준 정수일 때만이다. 디스패처(전달 없음)와 `harness/delivery.py`(D2, D4)가 함께 쓴다.
    """
    got: list[object] = []

    async def send() -> None:
        got.append(await sender.send(out))

    err = await send_with_retry(send, sleep=sleep, attempts=attempts, event="run_send_error", extra={"run_id": run_id})
    mid = got[-1] if got else None
    return err is None, mid if isinstance(mid, int) and not isinstance(mid, bool) else None


async def _idle() -> None:
    await asyncio.Event().wait()


def _outbound(text: str, run_ctx: RunContext) -> Outbound:
    """이번 호출에서 제안한 초안이 있으면 버튼을 붙이도록 id와 대화를 싣는다(스펙 5.7). 확인 토큰도(10.1 A5)."""
    confirmed = {e.task_id for e in run_ctx.events if e.kind == "tasks_confirmed"}
    ids = [
        i
        for e in run_ctx.events
        if e.kind == "tasks_proposed"
        for i in e.data.get("ids", [])
        if i not in confirmed  # 같은 턴에 이미 확정한 것에는 버튼을 붙이지 않는다
    ]
    milestones = _curve_drafts(run_ctx.events, "milestone_proposed", ("milestones_confirmed", "milestone_dropped"))
    chapters = _curve_drafts(run_ctx.events, "chapter_proposed", ("chapters_confirmed", "chapter_dropped"))
    return Outbound(
        text=text,
        draft_conversation_id=run_ctx.conversation_id if ids or milestones else None,
        draft_task_ids=ids,
        draft_milestone_ids=milestones,
        draft_chapter_ids=chapters,
        # 회차 차례에서만 생긴다(10.1 A2). 사용자 차례의 답에는 늘 비어 있다
        confirms=[
            (e.data["confirm_token"], e.data["button"]) for e in run_ctx.events
            if e.kind == "confirm_requested" and not e.data.get("card")
        ],
        # 앱 대화의 사용자 차례에서 두뇌가 물은 확인(SP9 8장): 답 스트림에 확인 카드로 붙는다
        confirm_cards=[
            {"summary": e.data["summary"], "confirm_token": e.data["confirm_token"], "action": e.data["action"],
             "args": e.data["args"]}
            for e in run_ctx.events if e.kind == "confirm_requested" and e.data.get("card")
        ],
    )


def _curve_drafts(events: list[ToolEvent], proposed: str, settled: tuple[str, ...]) -> list[int]:
    """이번 차례에 꺼낸 사건·챕터 초안 번호(꺼낸 순서). 같은 차례에 이미 확정하거나 뺀 것은 버튼을 붙이지 않는다."""
    done = {e.data.get("id") for e in events if e.kind in settled}
    out = [e.data["id"] for e in events if e.kind == proposed and isinstance(e.data.get("id"), int)]
    return [i for i in dict.fromkeys(out) if i not in done]


def _condition_buttons_note(d: date | None) -> str:
    if d is None:
        return ""
    return f"## 컨디션 버튼\n이 메시지 아래에 {d.month}/{d.day}({_WEEKDAY[d.weekday()]}) 컨디션 버튼(1~5)이 붙습니다."


def _habit_buttons_note(day: date | None) -> str:
    """메시지에 습관 버튼 줄이 붙을 때만(`Outbound.habit_date`) 두뇌에게 알린다(SP7 5.7, 부록 A)."""
    if day is None:
        return ""
    return (
        "## 습관 버튼\n메시지 아래에 오늘 습관 버튼이 붙습니다. 습관을 글로 하나하나 묻지 말고, "
        "'오늘 챙긴 습관은 아래에서 눌러 주세요'처럼 한 줄로 부탁합니다."
    )


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

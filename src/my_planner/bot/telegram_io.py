"""텔레그램 입출력 (스펙 5.2). 봇은 판단하지 않는다."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Literal, Protocol

from telegram import (
    Bot,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, ContextTypes, TypeHandler

from my_planner.bot.commands import (
    CommandDeps,
    LocalTime,
    command_of,
    plan_topic,
    run_command,
)
from my_planner.clock import Clock, SystemClock
from my_planner.config import Settings
from my_planner.harness.conversations import ConversationRouter
from my_planner.harness.dispatcher import Inbound, Outbound, send_with_retry
from my_planner.harness.redact import redact
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.habits import Habit, HabitsRepo
from my_planner.store.repos.state import StateRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.actions import ActionRequest, ActionResult
from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

Verdict = Literal["accept", "ignore", "duplicate", "non_text", "command", "callback"]

# 버튼 누름 처리기: `functools.partial(bot.callbacks.handle_callback, owner_id=…, tools=…, …)`
CallbackHandler = Callable[[CallbackQuery], Awaitable[str]]
# 즉시 갈래(`Dispatcher.apply_action`): 상태를 바꾸는 명령(/pause /unpause /done)이 지난다. 없으면 바로 바꾼다(SP1 시험)
ActionApplier = Callable[[ActionRequest], ActionResult]

NON_TEXT_REPLY = "지금은 글로만 이야기할 수 있어요."
NON_TEXT_MARK = "[글이 아닌 메시지]"


class _Submitter(Protocol):
    def submit_message(self, m: Inbound) -> None: ...


class _MessageBot(Protocol):
    async def send_message(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> object: ...


def accept_update(update: Update, owner_id: int, state: StateRepo) -> Verdict:
    """받을지 판정만 한다. DB에 쓰지 않는다."""
    if state.is_seen_update(update.update_id) or state.is_pending_inbound(update.update_id):
        return "duplicate"  # 처리를 마쳤거나, 이미 받아 저장해 둔 메시지(시작 때 다시 넣는다)
    if update.callback_query is not None:
        return "callback"  # 보낸 사람 확인은 handle_callback이 한다
    msg = update.message
    if msg is None:
        # 편집된 메시지, 채널 글 등
        return _ignore(update, "not_message")
    sender = msg.from_user
    if sender is None or sender.id != owner_id:
        return _ignore(update, "other_user")
    if msg.chat.type != ChatType.PRIVATE:
        return _ignore(update, "not_private")
    if msg.text is None:
        return "non_text"
    return "accept"


def _ignore(update: Update, reason: str) -> Verdict:
    """버린 업데이트는 발신자 ID만 남긴다. 본문, 이름, 사용자명은 남기지 않는다."""
    user = update.effective_user
    log.info("update_ignored", extra={"from_id": user.id if user else None, "reason": reason})
    return "ignore"


async def handle_update(
    update: Update,
    *,
    bot: _MessageBot,
    owner_id: int,
    state: StateRepo,
    dispatcher: _Submitter,
    transcripts: TranscriptStore,
    clock: Clock,
    tools: Tools | None = None,
    callbacks: CallbackHandler | None = None,
    router: ConversationRouter | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    apply: ActionApplier | None = None,
) -> Verdict:
    """업데이트 하나를 판정하고 처리한다. 받은 글은 디스패처로 넘긴다. /today /week /help는 바로 답한다.

    `/plan [주제]`는 계획 대화를 열고(열려 있던 것은 닫는다) 주제를 디스패처로 넘긴다. 답은 두뇌가 한다.

    버튼 누름은 `callbacks`가 처리하고(두뇌를 거치지 않는다), 끝나면 처리 완료로 기록한다.

    명령과 글이 아닌 메시지의 답은 바로 3회까지 보낸다(1초, 2초 간격, `sleep`). 끝내 안 되면 처리 완료로도,
    원문 기록에도 남기지 않는다.
    """
    verdict = accept_update(update, owner_id, state)
    if verdict == "callback":
        query = update.callback_query
        assert query is not None
        if callbacks is None:
            await query.answer()
        else:
            await callbacks(query)
        state.mark_updates_done([update.update_id])
    elif verdict == "accept":
        msg = update.message
        assert msg is not None and msg.text is not None
        cmd = command_of(msg.text) if tools is not None else None
        if cmd in ("/plan", "/done") and router is None:
            cmd = None  # 계획 모드를 쓸 수 없으면 보통 글로 넘긴다
        if cmd == "/plan":
            assert router is not None
            router.start_plan()
            # 처리 완료 기록은 디스패처가 답을 보낸 뒤에 한다
            _persist_and_submit(dispatcher, state, update.update_id, plan_topic(msg.text), msg.date, clock.now())
            return "command"
        if cmd is not None:
            assert tools is not None
            done = [update.update_id]
            await _answer_command(
                msg.chat.id, msg.text, cmd, bot, tools, transcripts, clock, state,
                lambda: state.mark_updates_done(done), router, sleep,
                apply=apply,
            )
            return "command"
        _persist_and_submit(dispatcher, state, update.update_id, msg.text, msg.date, clock.now())
    elif verdict == "non_text":
        msg = update.message
        assert msg is not None
        if not await _send_text(bot, msg.chat.id, NON_TEXT_REPLY, sleep, update.update_id):
            return verdict
        now = clock.now()
        transcripts.append(now, "사용자", None, None, NON_TEXT_MARK)
        transcripts.append(now, "비서", None, None, NON_TEXT_REPLY)
        state.mark_updates_done([update.update_id])
    elif verdict == "ignore":
        state.mark_updates_done([update.update_id])
    return verdict


def _persist_and_submit(
    dispatcher: _Submitter, state: StateRepo, update_id: int, text: str, sent_at: datetime, now: datetime
) -> None:
    """디스패처에 넣기 전에 `inbound_pending`에 먼저 쓴다(가린 글만). 텔레그램은 받아 간 업데이트를 다시 주지
    않으므로, 답하기 전에 프로세스가 죽어도 다음 시작 때 이 행으로 다시 처리한다. 답을 보내 처리 완료로
    기록할 때 지운다."""
    state.add_pending_inbound(update_id, redact(text)[0], sent_at, now)
    dispatcher.submit_message(Inbound(text=text, at=now, sent_at=sent_at, update_ids=[update_id]))


async def _answer_command(
    chat_id: int,
    text: str,
    cmd: str,
    bot: _MessageBot,
    tools: Tools,
    transcripts: TranscriptStore,
    clock: Clock,
    state: StateRepo,
    on_sent: Callable[[], None],
    router: ConversationRouter | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    *,
    apply: ActionApplier | None = None,
) -> None:
    """명령에 답하고, 보낸 뒤에 명령과 응답을 원문 기록(`[-]`)에 남긴다. 답은 앱과 같은 `run_command`가 만든다."""
    now = clock.now()
    deps = CommandDeps(
        tasks=tools.tasks, conditions=tools.conditions, state=state, router=router, clock=clock,
        settings=LocalTime(tools.tz, tools.boundary), apply=apply, status=tools.status, curve=tools.curve,
        habits=tools.habits,
    )
    reply = run_command(cmd, text, deps, channel="telegram")
    markup = _habits_markup(tools) if cmd == "/habits" else None
    parts = split_message(reply)
    for n, part in enumerate(parts, start=1):
        if not await _send_text(bot, chat_id, part, sleep, None, markup=markup if n == len(parts) else None):
            return  # 처리 완료로 두지 않고 원문 기록도 남기지 않는다
    on_sent()  # 보낸 뒤에 먼저 처리 완료로 기록한다: 원문 기록이 실패해도 다시 받았을 때 두 번 답하지 않는다
    try:
        transcripts.append(now, "사용자", None, None, redact(text)[0])
        transcripts.append(now, "비서", None, None, reply)
    except OSError as e:
        log.warning("command_transcript_failed", extra={"error_type": type(e).__name__})


def _habits_markup(tools: Tools) -> InlineKeyboardMarkup | None:
    """`/habits` 답에 붙이는 오늘(논리적 날짜) 습관 버튼(SP7 5.7). 활성 습관이 없으면 None."""
    if tools.habits is None:
        return None
    today = tools.today()
    rows = habit_keyboard(tools.habits.list(), tools.habits.checked_on(today), today)
    return InlineKeyboardMarkup(rows) if rows else None


async def _send_text(
    bot: _MessageBot, chat_id: int, text: str, sleep: Callable[[float], Awaitable[None]], update_id: int | None,
    *, markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """글 하나를 바로 3회까지 보낸다(`markup`이 있으면 버튼을 붙여). 끝내 안 되면 `message_send_failed`(예외 종류만)를
    남기고 False."""
    err = await send_with_retry(
        lambda: (
            bot.send_message(chat_id=chat_id, text=text, reply_markup=markup) if markup is not None
            else bot.send_message(chat_id=chat_id, text=text)
        ),
        sleep=sleep, event="message_send_error",
        extra={"update_ids": [update_id] if update_id is not None else []},
    )
    if err is None:
        return True
    log.warning("message_send_failed", extra={"update_id": update_id, "error_type": type(err).__name__})
    return False


TELEGRAM_LIMIT = 4096


def utf16_len(s: str) -> int:
    """텔레그램이 세는 길이(UTF-16 코드 단위). 이모지 같은 BMP 밖 글자는 2로 센다."""
    return len(s.encode("utf-16-le")) // 2


def _fit(s: str, limit: int) -> int:
    """앞에서부터 UTF-16 `limit` 단위 안에 들어가는 글자 수."""
    units = 0
    for i, ch in enumerate(s):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > limit:
            return i
    return len(s)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """긴 답을 UTF-16 `limit` 단위 이하 조각으로 나눈다. 빈 줄, 줄바꿈, 글자 순서로 자를 곳을 찾는다.

    구분자는 앞 조각 끝에 남겨 두어, 조각을 이어 붙이면 원문이 된다.
    """
    parts: list[str] = []
    rest = text
    while utf16_len(rest) > limit:
        fit = _fit(rest, limit)
        cut = fit
        for sep in ("\n\n", "\n"):
            i = rest.rfind(sep, 0, fit)
            if i > 0:
                cut = i + len(sep)
                break
        parts.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        parts.append(rest)
    return parts


ADD_LABEL = "✓ 추가"
DROP_LABEL = "✗ 빼기"
ALL_LABEL = "전부 추가"
CONFIRM_APPLY_MARK = "✓"  # 회차 차례의 확인 버튼(SP3-4 10.1 A5): `✓ {동작 이름: 대상, 16자}`(`내려놓기: 운동`)
CONFIRM_KEEP_LABEL = "✗ 그대로 두기"
BUTTON_TITLE_MAX = 16  # 버튼에 보이는 제목 글자 수. 넘으면 줄임표
SAVE_LABEL = "✓ 저장"  # 사건·챕터 초안(부록 A 사건 초안 버튼)
SAVE_ALL_LABEL = "전부 저장"


def _short(title: str) -> str:
    return title if len(title) <= BUTTON_TITLE_MAX else title[: BUTTON_TITLE_MAX - 1].rstrip() + "…"


def draft_keyboard(
    task_ids: list[int], conversation_id: int | None, titles: dict[int, str]
) -> InlineKeyboardMarkup | None:
    """초안마다 `✓ 추가` `✗ 빼기` 한 줄, 맨 아래 `전부 추가` 한 줄 (스펙 5.7). 초안이 없으면 None.

    콜백 데이터: `d:c:<task_id>`, `d:x:<task_id>`, `d:all:<conversation_id>` (모두 64바이트 이하).
    """
    if not task_ids:
        return None
    rows = []
    for i in task_ids:
        title = titles.get(i)
        add = f"{ADD_LABEL}: {_short(title)}" if title else ADD_LABEL
        rows.append(
            [
                InlineKeyboardButton(add, callback_data=f"d:c:{i}"),
                InlineKeyboardButton(DROP_LABEL, callback_data=f"d:x:{i}"),
            ]
        )
    if conversation_id is not None:
        rows.append([InlineKeyboardButton(ALL_LABEL, callback_data=f"d:all:{conversation_id}")])
    return InlineKeyboardMarkup(rows)


def _curve_rows(prefix: str, ids: list[int], titles: dict[int, str]) -> list[list[InlineKeyboardButton]]:
    rows = []
    for i in ids:
        title = titles.get(i)
        save = f"{SAVE_LABEL}: {_short(title)}" if title else SAVE_LABEL
        rows.append([
            InlineKeyboardButton(save, callback_data=f"{prefix}:c:{i}"),
            InlineKeyboardButton(DROP_LABEL, callback_data=f"{prefix}:x:{i}"),
        ])
    return rows


def milestone_keyboard(
    ids: list[int], conversation_id: int | None, titles: dict[int, str]
) -> list[list[InlineKeyboardButton]]:
    """사건 초안마다 `✓ 저장: {제목 16자}` `✗ 빼기` 한 줄, 맨 아래 `전부 저장`(SP3-4 10장, 부록 A). 없으면 빈 목록.

    콜백 데이터 `m:c:<id>`, `m:x:<id>`, `m:all:<대화 id>`(그 대화에서 꺼낸 남은 초안 전부). 모두 64바이트 이하.
    """
    if not ids:
        return []
    rows = _curve_rows("m", ids, titles)
    if conversation_id is not None:
        rows.append([InlineKeyboardButton(SAVE_ALL_LABEL, callback_data=f"m:all:{conversation_id}")])
    return rows


def chapter_keyboard(ids: list[int], titles: dict[int, str]) -> list[list[InlineKeyboardButton]]:
    """챕터 초안마다 `✓ 저장: {제목 16자}` `✗ 빼기` 한 줄. 콜백 데이터 `h:c:<id>`, `h:x:<id>`(전부 저장은 없다)."""
    return _curve_rows("h", ids, titles)


def condition_keyboard(d: date | None) -> list[list[InlineKeyboardButton]]:
    """그날 컨디션 버튼 `1 2 3 4 5` 한 줄. 콜백 데이터 `c:<YYYY-MM-DD>:<1-5>`(그 날짜에 기록한다)."""
    if d is None:
        return []
    return [[InlineKeyboardButton(str(n), callback_data=f"c:{d.isoformat()}:{n}") for n in range(1, 6)]]


LADDER_SKIP_LABEL = "건너뛰기"  # 사다리 2단계(5년 뒤)만


def ladder_keyboard(period: str, field: Literal["n", "f"]) -> list[list[InlineKeyboardButton]]:
    """회고 단계의 사다리 버튼(SP3-4 11.1): `0`~`5`, `6`~`10` 두 줄, `f`(5년 뒤)면 맨 아래 `건너뛰기`.

    콜백 데이터 `l:<YYYY-MM>:n:<0-10>`, `l:<YYYY-MM>:f:<0-10>`, `l:<YYYY-MM>:f:skip`(모두 17바이트 이하).
    """
    rows = [
        [InlineKeyboardButton(str(v), callback_data=f"l:{period}:{field}:{v}") for v in vs]
        for vs in (range(6), range(6, 11))
    ]
    if field == "f":
        rows.append([InlineKeyboardButton(LADDER_SKIP_LABEL, callback_data=f"l:{period}:f:skip")])
    return rows


HABIT_LABEL_MAX = 10  # 습관 버튼 제목 글자 수(코드포인트, SP7 5.7). 넘으면 9자 + `…`
HABIT_OFF, HABIT_ON = "☐", "✓"


def habit_label(title: str, checked: bool) -> str:
    """`☐ {제목 10자}` / `✓ {제목 10자}`. 코드포인트로 센다(이모지도 한 글자)."""
    short = title if len(title) <= HABIT_LABEL_MAX else title[: HABIT_LABEL_MAX - 1] + "…"
    return f"{HABIT_ON if checked else HABIT_OFF} {short}"


def habit_keyboard(habits: list[Habit], checked: set[int], day: date) -> list[list[InlineKeyboardButton]]:
    """습관 버튼(SP7 5.7): 한 줄에 둘. 콜백 데이터 `hb:<habit_id>:<YYYY-MM-DD>`(20바이트 남짓, 64바이트 이하).
    습관이 없으면 빈 목록."""
    buttons = [
        InlineKeyboardButton(habit_label(h.title, h.id in checked), callback_data=f"hb:{h.id}:{day.isoformat()}")
        for h in habits
    ]
    return [buttons[i : i + 2] for i in range(0, len(buttons), 2)]


def confirm_keyboard(confirms: list[tuple[str, str]]) -> list[list[InlineKeyboardButton]]:
    """(토큰, 버튼 이름)마다 `✓ {버튼 이름 16자}` `✗ 그대로 두기` 한 줄(10.1 A5). 확인 문구 전부는 메시지 글에 있다.

    콜백 데이터 `k:a:<token>`, `k:x:<token>`. 토큰은 `ct_` + 22자라 29바이트(64바이트 이하).
    """
    return [
        [
            InlineKeyboardButton(f"{CONFIRM_APPLY_MARK} {_short(label)}", callback_data=f"k:a:{token}"),
            InlineKeyboardButton(CONFIRM_KEEP_LABEL, callback_data=f"k:x:{token}"),
        ]
        for token, label in confirms
    ]


def message_keyboard(
    out: Outbound, titles: dict[int, str], milestone_titles: dict[int, str] | None = None,
    chapter_titles: dict[int, str] | None = None, *, habits: list[Habit] | None = None,
    checked: set[int] | None = None,
) -> InlineKeyboardMarkup | None:
    """메시지 아래 버튼: 할 일 초안 줄 → 사건 초안 줄 → 챕터 초안 줄 → 확인 줄(회차 차례의 확인) → 습관 줄
    (`out.habit_date`가 있을 때, `habits`는 활성 습관, `checked`는 그날 체크한 id, SP7 5.7) → 컨디션 1~5 줄
    또는 사다리 0~10 줄(SP3-4 11.1: 한 메시지에 숫자 키보드는 한 종류라 사다리가 있으면 컨디션 줄은 없다).
    모두 없으면 None."""
    drafts = draft_keyboard(out.draft_task_ids, out.draft_conversation_id, titles)
    habit_rows = (
        habit_keyboard(habits, checked or set(), out.habit_date) if out.habit_date is not None and habits else []
    )
    rows = [
        *(drafts.inline_keyboard if drafts else ()),
        *milestone_keyboard(out.draft_milestone_ids, out.draft_conversation_id, milestone_titles or {}),
        *chapter_keyboard(out.draft_chapter_ids, chapter_titles or {}),
        *confirm_keyboard(out.confirms),
        *habit_rows,
        *(ladder_keyboard(*out.ladder) if out.ladder is not None else condition_keyboard(out.ask_condition_for)),
    ]
    return InlineKeyboardMarkup(rows) if rows else None


class DisabledTelegramSender:
    """role = "dev"의 Sender(릴리스 흐름 스펙 5.2): 텔레그램에 보내지 않고 로그 한 줄만 남긴다(본문 없이).

    메시지 id를 돌려주지 않으므로 버튼 거두기도 불리지 않는다.
    """

    async def send(self, out: Outbound) -> None:
        log.info("telegram_disabled_dev", extra={"chars": len(out.text)})

    async def clear_buttons(self, message_id: int) -> None:
        return None

    async def typing(self) -> None:
        return None


class TelegramSender:
    """디스패처의 Sender. 앱보다 먼저 `telegram.Bot(token)`으로 만든 봇을 받는다.

    `tasks`를 주면 초안 버튼에 제목을 붙인다. `curve`를 주면 사건·챕터 초안 버튼에도. `habits`를 주면
    `out.habit_date`가 있는 메시지에 습관 줄을 붙인다(SP7 5.7, 보낼 때의 DB 상태).
    """

    def __init__(
        self, bot: Bot, chat_id: int, *, tasks: TasksRepo | None = None, curve: CurveRepo | None = None,
        habits: HabitsRepo | None = None,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.tasks = tasks
        self.curve = curve
        self.habits = habits

    def _titles(self, ids: list[int]) -> dict[int, str]:
        if self.tasks is None:
            return {}
        found = (self.tasks.get(i) for i in ids)
        return {t.id: t.title for t in found if t is not None}

    def _curve_titles(self, out: Outbound) -> tuple[dict[int, str], dict[int, str]]:
        """사건·챕터 초안 버튼의 제목. 사용자 본인에게 보내는 확정 버튼이라 민감 사건도 제목 그대로다."""
        if self.curve is None:
            return {}, {}
        ms = (self.curve.get_milestone(i) for i in out.draft_milestone_ids)
        cs = (self.curve.get_chapter(i) for i in out.draft_chapter_ids)
        return {m.id: m.title for m in ms if m is not None}, {c.id: c.title for c in cs if c is not None}

    def _habits(self, day: date | None) -> tuple[list[Habit], set[int]]:
        """습관 줄의 재료: 활성 습관과 그날 체크한 id. 날짜나 저장소가 없으면 빈 것."""
        if self.habits is None or day is None:
            return [], set()
        return self.habits.list(), self.habits.checked_on(day)

    async def send(self, out: Outbound) -> int | None:
        """조각마다 보낸다. 버튼이 붙었으면 그 마지막 조각의 메시지 id(답한 뒤 버튼을 거둘 때 쓴다), 없으면 None."""
        habits, checked = self._habits(out.habit_date)
        markup = message_keyboard(
            out, self._titles(out.draft_task_ids), *self._curve_titles(out), habits=habits, checked=checked
        )
        parts = split_message(out.text)
        message_id: int | None = None
        for n, part in enumerate(parts, start=1):
            last = n == len(parts)  # 버튼은 마지막 조각 아래에만
            sent = await self.bot.send_message(chat_id=self.chat_id, text=part, reply_markup=markup if last else None)
            if last and markup is not None:
                mid = getattr(sent, "message_id", None)
                message_id = mid if isinstance(mid, int) else None
        return message_id

    async def clear_buttons(self, message_id: int) -> None:
        """답한 회차 메시지의 버튼을 거둔다(`editMessageReplyMarkup`, SP3-4 6.4.5)."""
        await self.bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=message_id, reply_markup=None)

    async def typing(self) -> None:
        await self.bot.send_chat_action(chat_id=self.chat_id, action=ChatAction.TYPING)


def build_application(
    settings: Settings,
    dispatcher: _Submitter,
    state: StateRepo,
    transcripts: TranscriptStore,
    *,
    bot: Bot | None = None,
    clock: Clock | None = None,
    tools: Tools | None = None,
    callbacks: CallbackHandler | None = None,
    router: ConversationRouter | None = None,
    apply: ActionApplier | None = None,
) -> Application:
    """롱폴링 앱. `bot`을 주면 Sender와 같은 봇을 쓴다(한 번만 초기화된다)."""
    builder = Application.builder()
    if bot is not None:
        builder = builder.bot(bot)
    else:
        builder = builder.token(settings.telegram_bot_token.get_secret_value())
    app = builder.build()
    clk = clock or SystemClock()

    async def on_update(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not isinstance(update, Update):
            return
        await handle_update(
            update,
            bot=context.bot,
            owner_id=settings.owner_telegram_id,
            state=state,
            dispatcher=dispatcher,
            transcripts=transcripts,
            clock=clk,
            tools=tools,
            callbacks=callbacks,
            router=router,
            apply=apply,
        )

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        # 업데이트 내용은 남기지 않는다.
        err = context.error
        log.error(
            "telegram_handler_error",
            exc_info=(type(err), err, err.__traceback__) if err else None,
        )

    app.add_handler(TypeHandler(Update, on_update))
    app.add_error_handler(on_error)
    return app

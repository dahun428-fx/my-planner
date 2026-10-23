"""텔레그램 입출력 (스펙 5.2). 봇은 판단하지 않는다."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
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
    HELP_TEXT,
    NOT_PAUSED_REPLY,
    PAUSE_USAGE,
    UNPAUSE_REPLY,
    command_of,
    pause_days,
    pause_reply,
    today_text,
    week_text,
)
from my_planner.clock import Clock, SystemClock, from_iso, to_iso
from my_planner.config import Settings
from my_planner.harness.dispatcher import Inbound, Outbound
from my_planner.harness.redact import redact
from my_planner.store.repos.state import PAUSE_UNTIL_KEY, StateRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

Verdict = Literal["accept", "ignore", "duplicate", "non_text", "command", "callback"]

# 버튼 누름 처리기: `functools.partial(bot.callbacks.handle_callback, owner_id=…, tools=…, …)`
CallbackHandler = Callable[[CallbackQuery], Awaitable[str]]

NON_TEXT_REPLY = "지금은 글로만 이야기할 수 있어요."
NON_TEXT_MARK = "[글이 아닌 메시지]"


class _Submitter(Protocol):
    def submit_message(self, m: Inbound) -> None: ...


class _MessageBot(Protocol):
    async def send_message(self, chat_id: int, text: str) -> object: ...


def accept_update(update: Update, owner_id: int, state: StateRepo) -> Verdict:
    """받을지 판정만 한다. DB에 쓰지 않는다."""
    if state.is_seen_update(update.update_id):
        return "duplicate"
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
) -> Verdict:
    """업데이트 하나를 판정하고 처리한다. 받은 글은 디스패처로 넘긴다. /today /week /help는 바로 답한다.

    버튼 누름은 `callbacks`가 처리하고(두뇌를 거치지 않는다), 끝나면 처리 완료로 기록한다.
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
        if cmd is not None:
            assert tools is not None
            done = [update.update_id]
            await _answer_command(
                msg.chat.id, msg.text, cmd, bot, tools, transcripts, clock, state,
                lambda: state.mark_updates_done(done),
            )
            return "command"
        dispatcher.submit_message(
            Inbound(text=msg.text, at=clock.now(), sent_at=msg.date, update_ids=[update.update_id])
        )
    elif verdict == "non_text":
        msg = update.message
        assert msg is not None
        await bot.send_message(chat_id=msg.chat.id, text=NON_TEXT_REPLY)
        now = clock.now()
        transcripts.append(now, "사용자", None, None, NON_TEXT_MARK)
        transcripts.append(now, "비서", None, None, NON_TEXT_REPLY)
        state.mark_updates_done([update.update_id])
    elif verdict == "ignore":
        state.mark_updates_done([update.update_id])
    return verdict


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
) -> None:
    """명령에 답하고, 보낸 뒤에 명령과 응답을 원문 기록(`[-]`)에 남긴다."""
    now = clock.now()
    if cmd == "/help":
        reply = HELP_TEXT
    elif cmd == "/pause":
        days = pause_days(text)
        if days is None:
            reply = PAUSE_USAGE
        else:
            until = now + timedelta(days=days)  # 지금부터 N×24시간(스펙 5.6)
            state.set(PAUSE_UNTIL_KEY, to_iso(until))
            reply = pause_reply(until, tools.tz)
    elif cmd == "/unpause":
        v = state.get(PAUSE_UNTIL_KEY)
        state.set(PAUSE_UNTIL_KEY, None)
        reply = UNPAUSE_REPLY if v and from_iso(v) > now else NOT_PAUSED_REPLY
    else:
        render = today_text if cmd == "/today" else week_text
        reply = render(tools.tasks, now, tools.tz, tools.boundary)
    for part in split_message(reply):
        await bot.send_message(chat_id=chat_id, text=part)
    on_sent()  # 보낸 뒤에 먼저 처리 완료로 기록한다: 원문 기록이 실패해도 다시 받았을 때 두 번 답하지 않는다
    try:
        transcripts.append(now, "사용자", None, None, redact(text)[0])
        transcripts.append(now, "비서", None, None, reply)
    except OSError as e:
        log.warning("command_transcript_failed", extra={"error_type": type(e).__name__})


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
BUTTON_TITLE_MAX = 16  # 버튼에 보이는 제목 글자 수. 넘으면 줄임표


def _short(title: str) -> str:
    return title if len(title) <= BUTTON_TITLE_MAX else title[: BUTTON_TITLE_MAX - 1] + "…"


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


def condition_keyboard(d: date | None) -> list[list[InlineKeyboardButton]]:
    """그날 컨디션 버튼 `1 2 3 4 5` 한 줄. 콜백 데이터 `c:<YYYY-MM-DD>:<1-5>`(그 날짜에 기록한다)."""
    if d is None:
        return []
    return [[InlineKeyboardButton(str(n), callback_data=f"c:{d.isoformat()}:{n}") for n in range(1, 6)]]


def message_keyboard(out: Outbound, titles: dict[int, str]) -> InlineKeyboardMarkup | None:
    """메시지 아래 버튼: 초안 줄이 먼저, 그다음 컨디션 1~5 줄. 둘 다 없으면 None."""
    drafts = draft_keyboard(out.draft_task_ids, out.draft_conversation_id, titles)
    rows = [*(drafts.inline_keyboard if drafts else ()), *condition_keyboard(out.ask_condition_for)]
    return InlineKeyboardMarkup(rows) if rows else None


class TelegramSender:
    """디스패처의 Sender. 앱보다 먼저 `telegram.Bot(token)`으로 만든 봇을 받는다.

    `tasks`를 주면 초안 버튼에 제목을 붙인다.
    """

    def __init__(self, bot: Bot, chat_id: int, *, tasks: TasksRepo | None = None) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.tasks = tasks

    def _titles(self, ids: list[int]) -> dict[int, str]:
        if self.tasks is None:
            return {}
        found = (self.tasks.get(i) for i in ids)
        return {t.id: t.title for t in found if t is not None}

    async def send(self, out: Outbound) -> None:
        markup = message_keyboard(out, self._titles(out.draft_task_ids))
        parts = split_message(out.text)
        for n, part in enumerate(parts, start=1):
            last = n == len(parts)  # 버튼은 마지막 조각 아래에만
            await self.bot.send_message(chat_id=self.chat_id, text=part, reply_markup=markup if last else None)

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

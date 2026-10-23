"""텔레그램 입출력 (스펙 5.2). 봇은 판단하지 않는다."""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from telegram import Bot, Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, ContextTypes, TypeHandler

from my_planner.clock import Clock, SystemClock
from my_planner.config import Settings
from my_planner.harness.dispatcher import Inbound, Outbound
from my_planner.store.repos.state import StateRepo
from my_planner.store.transcripts import TranscriptStore

log = logging.getLogger(__name__)

Verdict = Literal["accept", "ignore", "duplicate", "non_text"]

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
    msg = update.message
    if msg is None:
        # 편집된 메시지, 채널 글 등. (버튼 누름은 티켓 06에서 따로 다룬다.)
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
) -> Verdict:
    """업데이트 하나를 판정하고 처리한다. 받은 글은 디스패처로 넘긴다."""
    verdict = accept_update(update, owner_id, state)
    if verdict == "accept":
        msg = update.message
        assert msg is not None and msg.text is not None
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


class TelegramSender:
    """디스패처의 Sender. 앱보다 먼저 `telegram.Bot(token)`으로 만든 봇을 받는다."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id

    async def send(self, out: Outbound) -> None:
        for part in split_message(out.text):
            await self.bot.send_message(chat_id=self.chat_id, text=part)

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

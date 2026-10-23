"""대화 규칙 (스펙 5.3): 사용자 메시지가 어느 대화에 속하는지 정한다."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.clock import logical_date
from my_planner.domain import ConversationKind

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.config import Settings
    from my_planner.store.repos.conversations import Conversation, ConversationsRepo


class ConversationRouter:
    """회차 대화 규칙(티켓 05)과 계획 대화 규칙(티켓 11)은 `for_user_message` 앞에 들어온다."""

    def __init__(
        self,
        convs: ConversationsRepo,
        runs: Any = None,
        *,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self.convs = convs
        self.runs = runs
        self.clock = clock
        self.settings = settings

    def _idle(self) -> timedelta:
        return timedelta(minutes=self.settings.limits.chat_resume_minutes)

    def for_user_message(self, at: datetime) -> Conversation:
        """30분 이내의 `chat` 대화가 있으면 잇고, 없으면 새 `chat`을 연다."""
        cur = self.convs.latest_open(ConversationKind.chat)
        if cur is not None and at - cur.last_message_at <= self._idle():
            return cur
        if cur is not None:
            self.convs.close(cur.id)
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.chat, logical_date(at, tz, boundary))

    def close_expired(self) -> None:
        """마지막 메시지 후 30분이 지난 `chat` 대화를 닫는다."""
        cur = self.convs.latest_open(ConversationKind.chat)
        if cur is not None and self.clock.now() - cur.last_message_at > self._idle():
            self.convs.close(cur.id)

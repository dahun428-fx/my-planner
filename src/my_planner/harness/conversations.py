"""대화 규칙 (스펙 5.3): 사용자 메시지가 어느 대화에 속하는지 정한다."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from my_planner.clock import logical_date
from my_planner.domain import ConversationKind, RunStatus
from my_planner.loop.schedule import Due, reply_window_end

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.config import Settings
    from my_planner.store.repos.conversations import Conversation, ConversationsRepo
    from my_planner.store.repos.runs import Run, RunsRepo


class ConversationRouter:
    """회차 대화 규칙(답장 창)이 30분 규칙보다 먼저다. 계획 대화 규칙(티켓 11)은 그보다 앞에 들어온다."""

    def __init__(
        self,
        convs: ConversationsRepo,
        runs: RunsRepo | None = None,
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
        """가장 최근 `run` 대화가 그 회차의 답장 창 안이면 잇는다(30분 규칙보다 먼저).

        아니면 30분 이내의 `chat` 대화를 잇고, 그것도 없으면 새 `chat`을 연다.
        """
        run_conv = self._run_conversation_in_window(at)
        if run_conv is not None:
            return run_conv
        cur = self.convs.latest_open(ConversationKind.chat)
        if cur is not None and at - cur.last_message_at <= self._idle():
            return cur
        if cur is not None:
            self.convs.close(cur.id)
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.chat, logical_date(at, tz, boundary))

    def _run_conversation_in_window(self, at: datetime) -> Conversation | None:
        if self.runs is None:
            return None
        conv = self.convs.latest_open(ConversationKind.run)
        if conv is None or conv.run_id is None:
            return None
        run = self.runs.get(conv.run_id)
        if run is None or run.status is not RunStatus.done:  # 보내지 않은 회차에는 답할 것이 없다
            return None
        s = self.settings
        end = reply_window_end(Due(run.loop, run.scheduled_for, run.cadence), s.timezone, s.day_boundary, cfg=s)
        return conv if at <= end else None

    def for_run(self, run: Run) -> Conversation:
        """회차 실행은 늘 새 `run` 대화를 연다. 날짜는 실제로 보내는 때의 논리적 날짜다."""
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.run, logical_date(self.clock.now(), tz, boundary), run_id=run.id)

    def close_expired(self) -> None:
        """마지막 메시지 후 30분이 지난 `chat` 대화를 닫는다."""
        cur = self.convs.latest_open(ConversationKind.chat)
        if cur is not None and self.clock.now() - cur.last_message_at > self._idle():
            self.convs.close(cur.id)

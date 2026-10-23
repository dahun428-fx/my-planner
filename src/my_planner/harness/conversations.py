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
    """계획 대화 규칙(2시간)이 가장 먼저, 그다음 회차 대화 규칙(답장 창), 그다음 30분 규칙이다."""

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

    def _plan_idle(self) -> timedelta:
        return timedelta(hours=self.settings.limits.plan_idle_hours)

    def _open_plan(self, at: datetime) -> Conversation | None:
        """마지막 메시지 후 2시간 이내의 열린 `plan` 대화. 2시간이 지났으면 닫고 None(만료는 볼 때 확인한다)."""
        cur = self.convs.latest_open(ConversationKind.plan)
        if cur is None:
            return None
        if at - cur.last_message_at <= self._plan_idle():
            return cur
        self.convs.close(cur.id)
        return None

    def start_plan(self) -> Conversation:
        """새 `plan` 대화를 연다. 열려 있던 다른 계획 대화는 닫는다."""
        while (cur := self.convs.latest_open(ConversationKind.plan)) is not None:
            self.convs.close(cur.id)
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.plan, logical_date(self.clock.now(), tz, boundary))

    def end_plan(self) -> bool:
        """열린 계획 대화를 닫는다. 2시간 안에 열려 있던 것이 있었으면 True."""
        was_open = self._open_plan(self.clock.now()) is not None
        while (cur := self.convs.latest_open(ConversationKind.plan)) is not None:
            self.convs.close(cur.id)
        return was_open

    def plan_open(self) -> bool:
        return self._open_plan(self.clock.now()) is not None

    def keep_alive(self, at: datetime) -> None:
        """사용자 메시지가 도착했다: 아직 만료 전인 `plan`·`chat` 대화를 활동으로 기록한다.

        메시지가 큐에서 기다리는 동안 tick이 그 대화를 만료로 닫지 않게 한다. 새 대화는 열지 않는다.
        """
        plan = self._open_plan(at)
        if plan is not None:
            self.convs.touch(plan.id)
        chat = self.convs.latest_open(ConversationKind.chat)
        if chat is not None and at - chat.last_message_at <= self._idle():
            self.convs.touch(chat.id)

    def touch_plan(self, conversation_id: int | None) -> None:
        """그 대화가 만료 전의 열린 `plan` 대화면 활동으로 기록한다(계획 대화의 초안 버튼 누름)."""
        plan = self._open_plan(self.clock.now())
        if plan is not None and plan.id == conversation_id:
            self.convs.touch(plan.id)

    def for_user_message(self, at: datetime) -> Conversation:
        """2시간 이내의 열린 `plan` 대화가 있으면 그것을 잇는다(가장 먼저).

        아니면 가장 최근 `run` 대화가 그 회차의 답장 창 안이면 잇는다(30분 규칙보다 먼저).
        아니면 30분 이내의 `chat` 대화를 잇고, 그것도 없으면 새 `chat`을 연다.
        """
        plan = self._open_plan(at)
        if plan is not None:
            return plan
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
        # 합쳐 보낸 회차(merged_run_ids)가 있으면 그 가운데 가장 늦은 답장 창 끝까지 잇는다
        # (예: 일요일 저녁 + 회고 → 회고의 24시간).
        s = self.settings
        bundled = [run, *(r for i in run.merged_run_ids if (r := self.runs.get(i)) is not None)]
        end = max(
            reply_window_end(Due(r.loop, r.scheduled_for, r.cadence), s.timezone, s.day_boundary, cfg=s)
            for r in bundled
        )
        return conv if at <= end else None

    def for_run(self, run: Run) -> Conversation:
        """회차 실행은 늘 새 `run` 대화를 연다. 날짜는 실제로 보내는 때의 논리적 날짜다."""
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.run, logical_date(self.clock.now(), tz, boundary), run_id=run.id)

    def close_expired(self) -> None:
        """마지막 메시지 후 30분이 지난 `chat` 대화와 2시간이 지난 `plan` 대화를 닫는다. 러너가 tick마다 부른다."""
        now = self.clock.now()
        cur = self.convs.latest_open(ConversationKind.chat)
        if cur is not None and now - cur.last_message_at > self._idle():
            self.convs.close(cur.id)
        self._open_plan(now)

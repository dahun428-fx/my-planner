"""대화 규칙 (스펙 5.3): 사용자 메시지가 어느 대화에 속하는지 정한다."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from my_planner.clock import logical_date
from my_planner.domain import Channel, ConversationKind, RunStatus
from my_planner.loop.schedule import Due, reply_window_end

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.config import Settings
    from my_planner.store.repos.conversations import Conversation, ConversationsRepo
    from my_planner.store.repos.runs import Run, RunsRepo


CHANNELS: tuple[Channel, ...] = ("telegram", "app")


class ConversationRouter:
    """계획 대화 규칙(2시간)이 가장 먼저, 그다음 회차 대화 규칙(답장 창), 그다음 30분 규칙이다.

    대화와 그 규칙은 통로마다 따로다(SP3-4 7.1): 텔레그램에서 연 `chat`을 앱이 잇지 않고, 계획 모드도 통로마다 하나다.
    통로를 받는 함수의 기본값은 `telegram`이다(SP1 동작 그대로).
    """

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
        # 받은 메시지가 대화를 활동으로 기록하기 직전의 `last_message_at`(대화마다 처음 것). 다른 통로 변경 알림의
        # 기준이다(7.1): 기다리는 동안 tick이 닫지 않게 받자마자 기록하므로, 처리할 때의 값은 이미 받은 시각이다
        self._notice_base: dict[int, datetime] = {}

    def _idle(self) -> timedelta:
        return timedelta(minutes=self.settings.limits.chat_resume_minutes)

    def _plan_idle(self) -> timedelta:
        return timedelta(hours=self.settings.limits.plan_idle_hours)

    def _open_plan(self, at: datetime, channel: Channel = "telegram") -> Conversation | None:
        """마지막 메시지 후 2시간 이내의 열린 `plan` 대화. 2시간이 지났으면 닫고 None(만료는 볼 때 확인한다)."""
        cur = self.convs.latest_open(ConversationKind.plan, channel)
        if cur is None:
            return None
        if at - cur.last_message_at <= self._plan_idle():
            return cur
        self.convs.close(cur.id)
        return None

    def start_plan(self, channel: Channel = "telegram") -> Conversation:
        """그 통로에 새 `plan` 대화를 연다. 그 통로에 열려 있던 다른 계획 대화는 닫는다."""
        while (cur := self.convs.latest_open(ConversationKind.plan, channel)) is not None:
            self.convs.close(cur.id)
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.plan, logical_date(self.clock.now(), tz, boundary), channel=channel)

    def end_plan(self, channel: Channel = "telegram") -> bool:
        """그 통로의 열린 계획 대화를 닫는다. 2시간 안에 열려 있던 것이 있었으면 True."""
        was_open = self._open_plan(self.clock.now(), channel) is not None
        while (cur := self.convs.latest_open(ConversationKind.plan, channel)) is not None:
            self.convs.close(cur.id)
        return was_open

    def plan_open(self) -> bool:
        """**어느 통로든** 계획 대화가 열려 있다(회차가 기다리는 규칙, SP3-4 7.1)."""
        now = self.clock.now()
        found = [self._open_plan(now, ch) for ch in CHANNELS]  # 통로마다 본다(만료된 것은 닫는다)
        return any(c is not None for c in found)

    def keep_alive(self, at: datetime, channel: Channel = "telegram") -> None:
        """사용자 메시지가 도착했다: 그 통로에서 아직 만료 전인 `plan`·`chat` 대화를 활동으로 기록한다.

        메시지가 큐에서 기다리는 동안 tick이 그 대화를 만료로 닫지 않게 한다. 새 대화는 열지 않는다.
        """
        plan = self._open_plan(at, channel)
        if plan is not None:
            self._touch(plan)
        chat = self.convs.latest_open(ConversationKind.chat, channel)
        if chat is not None and at - chat.last_message_at <= self._idle():
            self._touch(chat)

    def _touch(self, conv: Conversation) -> None:
        self._notice_base.setdefault(conv.id, conv.last_message_at)
        self.convs.touch(conv.id)

    def notice_base(self, conv: Conversation) -> datetime:
        """다른 통로 변경 알림의 기준(7.1): 받기 직전 그 대화의 마지막 메시지 시각. 꺼내면 지운다.

        메모리에만 둔다. 재시작을 넘긴 메시지는 받을 때 갱신된 `last_message_at`을 기준으로 써서 그 한 번의 호출에서
        몇 줄 빠질 수 있다. 받아들인 한계다(최대 5줄, 두뇌는 도구로 지금 상태를 다시 읽는다. 티켓 07 리뷰 Minor 4).
        """
        return self._notice_base.pop(conv.id, conv.last_message_at)

    def touch_plan(self, conversation_id: int | None) -> None:
        """그 대화가 만료 전의 열린 `plan` 대화면 활동으로 기록한다(계획 대화의 초안 버튼 누름)."""
        plan = self._open_plan(self.clock.now())
        if plan is not None and plan.id == conversation_id:
            self.convs.touch(plan.id)

    def for_user_message(
        self, at: datetime, *, sent_at: datetime | None = None, channel: Channel = "telegram",
        checkin_id: int | None = None, asked_id: int | None = None,
    ) -> Conversation:
        """사용자 메시지의 대화(SP3-4 7.2, SP1 5.3 표에 통로를 더한 것). 위에서부터 처음 맞는 것:

        1. `checkin_id`(앱)가 보낸 시각 기준 답장 창 안의 회차면 그 회차의 이 통로 쪽 회차 대화(없으면 가르기).
        2. 같은 통로에 열린 `plan` 대화(2시간).
        3. 보낸 시각 이전에 열린 가장 최근 `run` 대화(**통로와 상관없이**)가 답장 창 안이면 그 회차의 이 통로 쪽
           회차 대화(없으면 가르기).
        4. 같은 통로의 30분 이내 `chat` 대화. `asked_id`(앱이 보낸 대화 id)가 그런 대화면 그것이 먼저다.
        5. 새 `chat` 대화(이 통로).

        답장 창은 보낸 시각 `sent_at`으로 본다(노트북이 잠든 동안 보낸 답도 그 회차에 잇는다). 2·4·5는 받은 시각
        `at`으로 본다. 텔레그램만 쓰면 SP1과 같다.
        """
        when = sent_at if sent_at is not None else at
        if checkin_id is not None:
            run = self._checkin_run(checkin_id, when)
            if run is not None:
                return self._run_side(run, channel)
        plan = self._open_plan(at, channel)
        if plan is not None:
            return plan
        run = self._run_in_window_by(when)
        if run is not None:
            return self._run_side(run, channel)
        if asked_id is not None:
            asked = self.convs.get(asked_id)
            if (
                asked is not None and asked.channel == channel and asked.kind is ConversationKind.chat
                and asked.closed_at is None and at - asked.last_message_at <= self._idle()
            ):
                return asked
        cur = self.convs.latest_open(ConversationKind.chat, channel)
        if cur is not None and at - cur.last_message_at <= self._idle():
            return cur
        if cur is not None:
            self.convs.close(cur.id)
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.chat, logical_date(at, tz, boundary), channel=channel)

    def run_in_window(self, run: Run, at: datetime) -> bool:
        """보낸(`done`) 회차이고, `at`(보낸 시각)이 보낸 뒤이고 답장 창(합친 회차는 가장 늦은 끝) 안이다."""
        if self.runs is None or run.status is not RunStatus.done:  # 보내지 않은 회차에는 답할 것이 없다
            return False
        if run.finished_at is not None and run.finished_at > at:
            return False
        # 합쳐 보낸 회차(merged_run_ids)가 있으면 그 가운데 가장 늦은 답장 창 끝까지 잇는다
        # (예: 일요일 저녁 + 회고 → 회고의 24시간).
        s = self.settings
        bundled = [run, *(r for i in run.merged_run_ids if (r := self.runs.get(i)) is not None)]
        end = max(
            reply_window_end(Due(r.loop, r.scheduled_for, r.cadence), s.timezone, s.day_boundary, cfg=s)
            for r in bundled
        )
        return at <= end

    def _primary(self, run: Run) -> Run:
        """합쳐진 회차면 그것을 보낸 primary(답과 대화는 primary에 붙는다)."""
        assert self.runs is not None
        primary = self.runs.merged_into(run.id)
        return primary if primary is not None else run

    def _checkin_run(self, checkin_id: int, at: datetime) -> Run | None:
        """규칙 1: 앱이 고른 회차가 보낸 시각 기준 답장 창 안이면 그 회차(primary). 아니면 None(규칙 2부터)."""
        if self.runs is None:
            return None
        run = self.runs.get(checkin_id)
        if run is None:
            return None
        run = self._primary(run)
        return run if self.run_in_window(run, at) else None

    def _run_in_window_by(self, at: datetime) -> Run | None:
        """규칙 3: 보낸 시각 이전에 열린 가장 최근 회차 대화(통로와 상관없이)의 회차가 답장 창 안이면 그 회차."""
        if self.runs is None:
            return None
        # 보낸 시각 이전에 열린 가장 최근 회차 대화만 본다. 늦게 받아 온 답이 그 사이 먼저 보낸 따라잡기 회차에
        # 붙지 않는다(최종 재리뷰 Important 1). 그 회차를 보낸 뒤에 쓴 글이어야 그 회차에 대한 답이다
        conv = self.convs.latest_open_run_opened_by(at)
        if conv is None or conv.run_id is None:
            return None
        run = self.runs.get(conv.run_id)
        return run if run is not None and self.run_in_window(run, at) else None

    def _run_side(self, run: Run, channel: Channel) -> Conversation:
        """그 회차의 이 통로 쪽 회차 대화. 없으면 원래 대화에서 갈라 연다(`forked_from`, 첫 호출은 `fork_session`)."""
        own = self.convs.run_conversation(run.id, channel)
        if own is not None:
            return own
        origin = self.convs.get(run.conversation_id) if run.conversation_id is not None else None
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(
            ConversationKind.run, logical_date(self.clock.now(), tz, boundary), run_id=run.id, channel=channel,
            forked_from=origin.id if origin is not None else None,
        )

    def for_app_message(self, at: datetime, *, conversation_id: int | None, checkin_id: int | None) -> Conversation:
        """앱 메시지의 대화(SP3-4 7.2, 6.4.1). 받을 때 고른다(`for_user_message`의 규칙, 앱의 보낸 시각은 받은 시각).

        고른 대화는 활동으로 기록해 큐에서 기다리는 동안 tick이 닫지 않게 한다.
        """
        conv = self.for_user_message(
            at, sent_at=at, channel="app", checkin_id=checkin_id, asked_id=conversation_id
        )
        self._touch(conv)
        touched = self.convs.get(conv.id)
        assert touched is not None
        return touched

    def continues(self, conv: Conversation, at: datetime) -> bool:
        """그 대화가 지금 메시지를 이을 수 있다(열려 있고, 그 종류의 규칙 안: 계획 2시간, chat 30분, 회차 답장 창)."""
        if conv.closed_at is not None:
            return False
        if conv.kind is ConversationKind.plan:
            return at - conv.last_message_at <= self._plan_idle()
        if conv.kind is ConversationKind.chat:
            return at - conv.last_message_at <= self._idle()
        run = self.runs.get(conv.run_id) if self.runs is not None and conv.run_id is not None else None
        return run is not None and self.run_in_window(self._primary(run), at)

    def current_app(self, at: datetime) -> Conversation | None:
        """지금 앱 메시지가 이어질 대화(열린 앱 `plan`, 30분 안의 앱 `chat`). 새 대화는 열지 않는다."""
        conv = self._open_plan(at, "app")
        if conv is not None:
            return conv
        cur = self.convs.latest_open(ConversationKind.chat, "app")
        return cur if cur is not None and at - cur.last_message_at <= self._idle() else None

    def for_run(self, run: Run) -> Conversation:
        """회차 실행은 늘 새 `run` 대화를 연다. 날짜는 실제로 보내는 때의 논리적 날짜다."""
        tz, boundary = self.settings.timezone, self.settings.day_boundary
        return self.convs.open(ConversationKind.run, logical_date(self.clock.now(), tz, boundary), run_id=run.id)

    def close_expired(self) -> None:
        """마지막 메시지 후 30분이 지난 `chat` 대화와 2시간이 지난 `plan` 대화를 닫는다. 러너가 tick마다 부른다."""
        now = self.clock.now()
        for ch in CHANNELS:
            cur = self.convs.latest_open(ConversationKind.chat, ch)
            if cur is not None and now - cur.last_message_at > self._idle():
                self.convs.close(cur.id)
            self._open_plan(now, ch)

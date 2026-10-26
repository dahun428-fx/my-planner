"""요청·응답 pydantic 모델(JSON 스키마의 정본, SP3-4 스펙 4.2, 6)과 API 경계의 공통 도구.

- 응답의 시각은 UTC ISO 8601(`2026-10-24T09:00:00Z`)이다. 저장소와 도구 결과는 오프셋 붙은 ISO(`+00:00`,
  `+09:00`)를 주므로 `to_api_times`가 경계에서 바꾼다. 날짜(`2026-10-24`)와 기간은 그대로 둔다.
- 오류 모양은 `{"error": {"code", "message"}}` 하나다(6.1).
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from aiohttp import web
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

# 시각 변환의 정본은 `my_planner.timefmt`다. API 쪽 가져오기가 그대로 되도록 다시 내보낸다
from my_planner.domain import SkipReason
from my_planner.timefmt import TIME_KEYS, api_time, is_time_key, to_api_times  # noqa: F401 - 다시 내보냄

log = logging.getLogger(__name__)

ErrorCode = Literal[
    "invalid_request", "unauthorized", "not_found", "conflict", "superseded", "undo_expired", "too_large",
    "rejected", "not_undoable", "too_many_auth_failures", "safe_mode", "internal", "unavailable",
    "checkin_time_invalid", "memo_conflict", "too_many_memos", "too_many_pinned",
    "remind_invalid", "start_not_in_weekdays", "too_many_events", "range_too_long", "digest_time_invalid",
    "bad_code",
    "too_many_photos", "photo_not_found", "photo_in_use",  # SP10 5.3
]


class ApiError(Exception):
    """처리기가 던지면 `read_handler`가 6.1 오류 모양으로 바꾼다. `message`에는 요청 값을 넣지 않는다."""

    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        super().__init__(code)
        self.status = status
        self.code: ErrorCode = code
        self.message = message


def error_response(status: int, code: ErrorCode, message: str) -> web.Response:
    """오류 응답. `message`는 사람용 한 줄이고 토큰, 본문, 경로 값을 넣지 않는다."""
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


_HTTP_CODES: dict[int, tuple[ErrorCode, str]] = {
    400: ("invalid_request", "요청 형식이 맞지 않아요."),
    404: ("not_found", "없는 경로예요."),
    405: ("invalid_request", "이 경로에서 쓸 수 없는 메서드예요."),
    413: ("too_large", "요청 본문이 너무 커요."),
}


async def call_json(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]], request: web.Request
) -> web.StreamResponse:
    """처리기를 부르고, aiohttp 예외(없는 경로 등)와 예상 못 한 예외를 6.1 오류 모양으로 바꾼다.

    예상 못 한 예외는 로그에 종류와 프레임만 남긴다(본문, 경로 값, 토큰, 예외 메시지 없이).
    """
    try:
        return await handler(request)
    except web.HTTPException as e:
        if e.status < 400:
            raise
        code, message = _HTTP_CODES.get(e.status, ("invalid_request", "요청을 처리할 수 없어요."))
        return error_response(e.status, code, message)
    except Exception as e:  # 무엇이든 500으로. 예외 메시지는 남기지 않는다
        # 예외 종류와 프레임(파일:줄 함수)만 남는다(logging_setup). medic이 이것으로 장애 지문을 만든다
        log.exception("api_internal_error", extra={"error_type": type(e).__name__})
        return error_response(500, "internal", "잠시 뒤에 다시 해 주세요.")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(_Model):
    code: ErrorCode
    message: str


class ErrorBody(_Model):
    error: ErrorDetail


class HealthVersion(_Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    app: str
    api: Literal["v1"]
    schema_: int | None = Field(alias="schema")  # BaseModel.schema와 겹쳐 별칭을 쓴다. 안전 모드면 None
    ui_catalog: str


class HealthBrain(_Model):
    auth: Literal["ok", "login", "billing", "unknown"]
    checked_at: str | None
    limited_until: str | None
    calls_today: int
    calls_cap: int


class HealthProactive(_Model):
    sent_today: int
    cap: int


class HealthNotify(_Model):
    primary: Literal["telegram", "app"]
    effective: Literal["telegram", "app"]


class HealthRun(_Model):
    id: int
    loop: Literal["morning_brief", "evening_checkin", "review", "return"]
    cadence: Literal["day", "week", "month", "quarter", "year"]
    scheduled_for: str
    status: str
    skip_reason: SkipReason | None  # 스키마에 `SkipReason` 열거가 들어간다(대시보드 사유 표시, 티켓 16)
    delivered_via: list[Literal["telegram", "app"]]
    checkin_state: Literal["pending", "answered", "missed"] | None


class HealthErrors(_Model):
    window_hours: int
    since: str
    total: int
    by_event: dict[str, int]


class HealthPush(_Model):
    subscriptions: int
    last_success_at: str | None


class Health(_Model):
    """`GET /health` (6.3.1)."""

    status: Literal["ok", "degraded"]
    version: HealthVersion
    now: str
    started_at: str
    last_tick_at: str | None
    polling: Literal["running", "down", "stopped"]
    brain: HealthBrain
    proactive: HealthProactive
    paused_until: str | None
    plan_open: bool
    notify: HealthNotify
    inbound_pending_oldest_at: str | None
    runs_today: list[HealthRun]
    errors: HealthErrors
    push: HealthPush


class SafeModeHealth(_Model):
    """안전 모드의 `GET /health`: 상태, 판, 지금만."""

    status: Literal["safe_mode"]
    version: HealthVersion
    now: str


# --- 읽기 (6.3, 6.4.5~6.4.7) ---

AreaName = Literal["career", "finance", "health", "relationships", "learning", "quality_of_life"]
CadenceName = Literal["day", "week", "month", "quarter", "year"]
LoopName = Literal["morning_brief", "evening_checkin", "review", "return"]
ChannelName = Literal["telegram", "app"]
TodoStatus = Literal["draft", "open", "done", "dropped"]


class TodoPriority(_Model):
    cadence: CadenceName
    period: str
    rank: int


class Todo(_Model):
    """공통 할 일 모양 (6.3). 초안은 `GET /drafts`에서만 `status: "draft"`로 나온다."""

    id: int
    title: str
    status: TodoStatus
    planned_for: str | None
    scheduled_at: str | None
    parent_id: int | None
    areas: list[AreaName]
    note: str
    priority: TodoPriority | None
    completed_at: str | None


class TodoRef(_Model):
    """화면 조각이 붙이는 할 일 요약 (6.3): `ui_todo_list`·`ui_todo_draft`의 `data.todos`, 체크인 `cards[].data.todos`.

    `planned_for`는 논리적 날짜, `scheduled_at`은 UTC 시각이다(없으면 `null`, SP6 10.2)."""

    id: int
    title: str
    cadence: CadenceName | None
    area: AreaName | None
    status: TodoStatus
    planned_for: str | None
    scheduled_at: str | None


class TodoRefs(_Model):
    """화면 조각 `data`의 모양 `{"todos": [TodoRef]}` (6.4.1 도구 출력, 6.4.5)."""

    todos: list[TodoRef]


class ConditionItem(_Model):
    date: str
    score: int
    note: str | None


class TodayBrief(_Model):
    run_id: int
    loop: LoopName
    text: str
    sent_at: str | None


class TodayTodo(_Model):
    group: Literal["priority", "scheduled", "open"]  # "scheduled"는 SP9부터 죽은 갈래(열린 할 일에 시각이 없다)
    todo: Todo


class AppCard(_Model):
    """고정 카드 (6.3.2 `cards`, 운영 앱용). `data`는 props에 `task_ids`가 있을 때만(`TodoRefs`, 초안·삭제 뺌)."""

    id: int
    component: str
    order: int
    pinned_at: str
    props: dict[str, Any]
    data: dict[str, Any] | None = None


class CheckinConversationIds(_Model):
    app: int | None
    telegram: int | None


class CheckinSummary(_Model):
    """답할 회차 요약 (6.4.5). `state`의 `missed` 화면 문구는 "지나감"이다."""

    id: int
    loop: LoopName
    cadence: CadenceName
    scheduled_for: str
    sent_at: str | None
    delivered_via: list[ChannelName]
    state: Literal["pending", "answered", "missed"]
    answered_via: ChannelName | None
    answered_at: str | None
    reply_until: str
    conversation_ids: CheckinConversationIds


class CheckinCard(_Model):
    toolCallId: str
    component: str
    props: dict[str, Any]
    data: dict[str, Any] | None = None  # 할 일(`todos`), 사건(`milestones`), 챕터(`chapters`) 초안 카드만


class CheckinDetail(CheckinSummary):
    text: str
    cards: list[CheckinCard]


class CheckinList(_Model):
    items: list[CheckinSummary]


class Habit(_Model):
    """공통 습관 모양 (SP7 스펙 5.5). `checked`: 요청 날짜(기본 오늘)에 체크했는가. `week_count`: 그 날짜가 든
    ISO 주(`%G-W%V`)의 체크 수. 주 목표를 채웠는지는 앱이 계산한다(보상은 없다)."""

    id: int
    title: str
    area: AreaName
    kind: Literal["daily", "weekly"]
    target_per_week: int | None
    status: Literal["active", "paused", "archived"]
    checked: bool
    week_count: int


class HabitsList(_Model):
    """`GET /habits?date=&status=` (SP7 5.5). `week`는 `date`가 든 ISO 주."""

    date: str
    week: str
    items: list[Habit]


class HabitWeek(_Model):
    week: str
    count: int


class HabitHistory(_Model):
    """`GET /habits/{id}?weeks=` (SP7 5.5). 체크한 날, 체크가 있는 주만(빈 날·빈 주는 0이 아니라 없음)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    habit: Habit
    from_: str = Field(alias="from")
    to: str
    checked_dates: list[str]
    weeks: list[HabitWeek]


class MemoItem(_Model):
    """`GET /memos` 한 줄 (SP9 6.4). `title`: 첫 줄 서식 뺀 앞 40자(없으면 "제목 없는 메모"). `preview`: 제목 줄 다음부터
    서식 뺀 줄들을 공백으로 이은 앞 80자(제목뿐이면 빈 문자열). 본문은 없다."""

    id: int
    title: str
    preview: str
    area: AreaName | None
    pinned: bool
    origin: Literal["user", "chat"]
    updated_at: str


class MemoList(_Model):
    """`GET /memos?q=&limit=&before=` (SP9 6.4). 첫 쪽은 고정 메모 전부가 먼저, 그다음 고정 아닌 메모가 고친 시각
    최근순. `limit`(1~100, 기본 50)은 고정 아닌 메모만 센다(고정 10개까지는 첫 쪽에 더 붙는다). `next_before`는 고정
    아닌 메모가 더 있을 때만(다음 쪽에는 고정 메모가 없다), 아니면 null."""

    items: list[MemoItem]
    next_before: str | None


class Memo(_Model):
    """`GET /memos/{id}`와 메모 동작 결과 (SP9 6.4). `updated_at`은 `update_memo`에 그대로 돌려보낸다(다르면 409 `memo_conflict`)."""

    id: int
    title: str
    body: str
    area: AreaName | None
    pinned: bool
    origin: Literal["user", "chat"]
    created_at: str
    updated_at: str


RemindMin = Literal[0, 10, 30, 60, 1440]
WeekdayName = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class EventItem(_Model):
    """그날 일정 한 줄 (SP9 5.6, `GET /events`, `/today.events`). `date`는 현지 날짜, `start`·`end`는 UTC(하루 종일은
    null, 길이가 없으면 `end`는 null). `remind_min`: 0 정시(하루 종일은 그날 09:00), 10·30·60분 전, 1440 하루 전,
    null 알림 없음."""

    event_id: int
    date: str
    start: str | None
    end: str | None
    all_day: bool
    title: str
    area: AreaName | None
    remind_min: RemindMin | None
    repeat: Literal["none", "daily", "weekly", "monthly"]
    origin: Literal["user", "chat", "migrated"]


class EventList(_Model):
    """`GET /events?start=&end=` (SP9 5.6): 기간(현지 날짜, 포함, 최대 62일, 넘으면 422 `range_too_long`) 안의 그날
    일정. 날짜, 하루 종일 먼저, 시작 시각순. 건너뛴 날은 없다."""

    start: str
    end: str
    items: list[EventItem]


class EventDetail(_Model):
    """`GET /events/{id}` (SP9 5.6): 정의 하나. `date`는 첫 날(현지), `time`은 현지 `HH:MM`(하루 종일은 null),
    `weekdays`는 매주 반복의 요일(그 밖에는 null), `repeat_until`은 마지막이 될 수 있는 날(포함, null이면 끝없음).
    `skipped_dates`: 이번만 건너뛴 날. 동작(`create_event`, `update_event`)의 칸 이름과 같다."""

    id: int
    title: str
    date: str
    time: str | None
    all_day: bool
    duration_min: int | None
    repeat: Literal["none", "daily", "weekly", "monthly"]
    weekdays: list[WeekdayName] | None
    repeat_until: str | None
    remind_min: RemindMin | None
    area: AreaName | None
    note: str
    origin: Literal["user", "chat", "migrated"]
    skipped_dates: list[str]
    created_at: str
    updated_at: str


class MissedReminder(_Model):
    """오늘 화면의 놓친 알림 줄 (SP9 5.3, 9.3): 오늘(논리적 날짜) 일정 가운데 `missed`(놓친 알림), `failed`·`skipped`
    (알림을 못 보냈어요)이고 닫지 않은 것. `start`는 UTC(하루 종일은 null)."""

    event_id: int
    date: str
    start: str | None
    title: str
    outcome: Literal["missed", "failed", "skipped"]


class Today(_Model):
    """`GET /today` (6.3.2). `habits`: 활성 습관, `sort_order` 순(SP7 5.5). 없으면 `[]`. `events`: 오늘(논리적 날짜)의
    그날 일정(SP9 5.6, 새벽 00:00~03:59에 시작하는 일정은 전날에 든다). `missed_reminders`: SP9 5.3."""

    date: str
    weekday: str
    day_boundary: str = Field(pattern=r"^\d{2}:\d{2}$")  # 논리적 날짜가 바뀌는 시각 `HH:MM`(설정, 기본 04:00)
    brief: TodayBrief | None
    condition: ConditionItem | None
    todos: list[TodayTodo]
    checkins: list[CheckinSummary]
    cards: list[AppCard]
    habits: list[Habit]
    events: list[EventItem] = Field(default_factory=list)  # 기본값: 앞선 BE에는 없어서 앱이 required로 읽지 않게
    missed_reminders: list[MissedReminder] = Field(default_factory=list)  # 기본값: 위와 같다(스펙 14)


class WeekDay(_Model):
    date: str
    weekday: str
    is_today: bool
    todos: list[Todo]


class Week(_Model):
    """`GET /week` (6.3.3): 할 일이 없는 날도 `days`에 7일 모두 든다. `undated`는 날짜 없는 열린 할 일이다(초안, 첫 걸음,
    이번 주 우선순위는 뺀다)."""

    week: str
    start: str
    end: str
    priorities: list[Todo]
    days: list[WeekDay]
    undated: list[Todo] = Field(default_factory=list)  # 기본값: 앞선 BE에는 없어서 앱이 required로 읽지 않게


class Conditions(_Model):
    """`GET /conditions` (6.3.4)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    items: list[ConditionItem]
    days_logged: int
    average: float | None


class Priorities(_Model):
    """`GET /priorities` (6.3.7). `todos`는 그 기간에 하려는 열린 할 일(날짜순, 초안 뺌)이다.
    날짜가 그 기간에 있는 우선순위 할 일은 `items`와 `todos`에 둘 다 나온다."""

    cadence: Literal["week", "month", "quarter", "year"]
    period: str
    items: list[Todo]
    todos: list[Todo] = Field(default_factory=list)  # 기본값: 앞선 BE에는 없어서 앱이 required로 읽지 않게


class DraftItem(_Model):
    todo: Todo
    proposed_at: str
    expires_at: str
    run_id: int | None
    conversation_id: int | None


class Drafts(_Model):
    """`GET /drafts` (6.3.8): 만료 전 초안만."""

    items: list[DraftItem]


class ConversationItem(_Model):
    """대화 한 줄(6.4.6). SP9 7.6: 비서가 붙인 `title`(20자)과 `summary`(앞 120자). 앱 대화에만 있고 없으면 null."""

    id: int
    kind: Literal["run", "chat", "plan"]
    channel: ChannelName
    run_id: int | None
    opened_at: str
    last_message_at: str
    closed_at: str | None
    # 늘 보내지만 스키마에서는 선택 칸이다: SP9 전의 BE 응답도 앱의 검사를 지난다(SP9 14장 관대한 읽기)
    title: str | None = None
    summary: str | None = None


class Conversations(_Model):
    """`GET /conversations?channel=&q=&before=&limit=`(SP9 7.6). 지운 대화는 없다. `next_before`: 다음 쪽 커서."""

    items: list[ConversationItem]
    next_before: str | None = None


class ConversationsClosed(_Model):
    """`POST /conversations/new`(SP9 7.3): 닫은 앱 `chat`·`plan` 대화 id."""

    closed: list[int]


class MessageItem(_Model):
    """대화 줄 (6.4.6). `id`는 바뀌지 않는다: `m-/u-<대화>-<n>`(앱 `inbound_id` 줄) 또는 `l-<대화>-<n>`."""

    id: str
    at: str
    speaker: Literal["user", "secretary"]
    text: str
    tools: list[str]
    channel: ChannelName


class Messages(_Model):
    items: list[MessageItem]


# --- 인생 곡선, 상태창 (6.3.5, 6.3.6) ---


class CurveChapter(_Model):
    id: int
    title: str
    theme: str | None
    start: str
    end: str | None
    sketch: str | None
    certainty: Literal["fact", "estimate"]
    ladder_remembered: int | None  # SP8 8.1: 그 시기를 돌아보며 기억하는 사다리 칸(0~10)


CurveOrigin = Literal["seed", "chat", "review"]
Certainty = Literal["fact", "estimate"]
MilestoneKind = Literal["high", "low", "turning_point"]


class CurveMilestone(_Model):
    id: int
    date: str
    precision: Literal["year", "month", "day"]
    kind: Literal["high", "low", "turning_point"]
    title: str
    note: str | None
    chapter_id: int | None
    sensitive: bool
    certainty: Literal["fact", "estimate"]
    kind_certainty: Certainty  # SP8 8.2
    area: AreaName | None
    origin: CurveOrigin


class CurveLadder(_Model):
    period: str
    now: int | None
    future: int | None
    note: str | None


class CurveAreas(_Model):
    period: str
    scores: dict[AreaName, int]


class CurveCondition(_Model):
    bucket: str
    start: str
    end: str
    average: float | None
    days_logged: int


class CurveReassurance(_Model):
    period: str
    ladder_now: int
    condition_average: float | None
    condition_scaled: float | None
    days_logged: int
    gap: float | None


class Curve(_Model):
    """`GET /curve` (6.3.5)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    zoom: CadenceName
    from_: str = Field(alias="from")
    to: str
    chapters: list[CurveChapter]
    milestones: list[CurveMilestone]
    ladder: list[CurveLadder]
    areas: list[CurveAreas]
    condition: list[CurveCondition]
    reassurance: list[CurveReassurance]


# --- 인생 히스토리 (SP8 8.2) ---


class HistoryLadder(_Model):
    """`remembered`는 기억한 정수, `recorded`는 그 기간 월별 사다리 평균(소수 한 자리). 둘 다 `float` 하나다(결정 16)."""

    value: float
    source: Literal["remembered", "recorded"]


class HiddenSensitive(_Model):
    """가린 민감 사건의 개수와 해(오름차순, 중복 없음). 제목·메모는 본문에 없다(8.5)."""

    count: int
    years: list[int]


class HistoryEvent(_Model):
    id: int
    date: str
    precision: Literal["year", "month", "day"]
    kind: MilestoneKind
    kind_certainty: Certainty
    title: str
    note: str | None
    area: AreaName | None
    origin: CurveOrigin
    certainty: Certainty
    sensitive: bool


class HistoryChapter(_Model):
    id: int
    title: str
    theme: str | None
    start: str
    end: str | None
    sketch: str | None
    certainty: Certainty
    ladder: HistoryLadder | None
    events: list[HistoryEvent]
    hidden_sensitive: HiddenSensitive


class HistoryUnassigned(_Model):
    """확정한 챕터에 들지 않은 사건("시기를 정하지 않은 사건")."""

    events: list[HistoryEvent]
    hidden_sensitive: HiddenSensitive


class HistoryHighest(_Model):
    chapter_id: int
    title: str
    ladder: float


class HistoryTurningPoints(_Model):
    count: int
    years: list[int]


class HistoryLongest(_Model):
    chapter_id: int
    title: str
    years: int


class HistorySummary(_Model):
    chapters: int
    events: int
    highest: HistoryHighest | None
    turning_points: HistoryTurningPoints
    longest: HistoryLongest | None
    records_since: int | None


class CurveHistory(_Model):
    """`GET /curve/history` (SP8 8.2). 챕터는 `start` 최근부터, 사건은 `sort_date` 최근부터."""

    since_year: int | None
    chapters: list[HistoryChapter]
    unassigned: HistoryUnassigned
    summary: HistorySummary


class StatusHp(_Model):
    date: str
    score: int | None


class StatActivity(_Model):
    """지난 28일 그 영역의 가중하지 않은 개수(SP8 5.6). `body_days`는 건강만, 다른 영역은 0."""

    tasks: int
    habit_checks: int
    body_days: int


class StatusStat(_Model):
    area: AreaName
    label: str
    score: int | None
    period: str | None
    prev_score: int | None
    prev_period: str | None
    debuff: bool
    recovery_quest: str | None
    bonus: float  # 0.0~2.0, 소수 한 자리. 바탕(`score`) 위에 따로 얹는다(SP8 5.3)
    effective_score: float | None  # min(10, score + bonus). `score`가 없으면 null
    activity: StatActivity


class FirstSteps(_Model):
    open: int
    done: int


class MainQuest(_Model):
    task_id: int
    title: str
    rank: int
    period: str
    first_steps: FirstSteps


class DailyQuest(_Model):
    task_id: int
    title: str
    parent_id: int
    parent_title: str | None
    planned_for: str | None


class StatusTitle(_Model):
    milestone_id: int
    title: str
    kind: Literal["high", "turning_point"]
    date: str
    granted_at: str


class RecentXp(_Model):
    at: str
    label: str
    amount: int


class Moment(_Model):
    """이룬 순간 하나(SP8 6.5). `sources`는 참조의 종류만(id 없음)."""

    id: int
    date: str
    text: str
    area: AreaName | None
    sources: list[Literal["task", "habit", "condition", "chat"]]
    hidden: bool


class MomentsList(_Model):
    """`GET /moments` (SP8 6.5). `to` = `before`의 전날(없으면 오늘), `from` = `to − (days − 1)`."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    items: list[Moment]


class StatusBody(_Model):
    """`GET /status`의 `body` (SP8 7.5): 지난 7일 몸 기록. 지난 56일에 행이 없으면 `body`가 null이다.

    `days_7`: 지난 7일 중 행이 있는 날 수. 평균은 그 값이 있는 날만의 정수 평균(없으면 null)."""

    last_date: str
    days_7: int
    steps_avg_7: int | None
    sleep_avg_7: int | None


class Status(_Model):
    """`GET /status` (6.3.6). `moments`·`moments_hidden`은 SP8 6.5, `body`는 SP8 7.5."""

    level: int
    xp_total: int
    xp_into_level: int
    xp_for_next: int
    hp: StatusHp
    stats: list[StatusStat]
    main_quests: list[MainQuest]
    daily_quests: list[DailyQuest]
    titles: list[StatusTitle]
    recent_xp: list[RecentXp]
    moments: list[Moment]
    moments_hidden: int
    body: StatusBody | None


class UiComponent(_Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    origin: Literal["brain", "harness"]
    schema_: dict[str, Any] = Field(alias="schema")


class UiCatalog(_Model):
    """`GET /ui/catalog` (6.4.7)."""

    version: str
    components: dict[str, UiComponent]


class SchemaBundle(_Model):
    """`GET /schema` (6.4): 모든 모델의 JSON 스키마."""

    api: Literal["v1"]
    models: dict[str, dict[str, Any]]


class ActionRequestBody(_Model):
    """`POST /actions` 요청 (6.4.2). `client_msg_id`는 필수다(6.1 중복 방지)."""

    action: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    client_msg_id: str = Field(min_length=1, max_length=200)
    confirm_token: str | None = None


def _no_default(schema: dict[str, Any]) -> None:
    schema.pop("default", None)


class BodyDayIn(_Model):
    """몸 기록 하루(SP8 7.3). `date`는 한국 달력의 오늘 이하, 오늘 − 13일 이상. 둘 중 하나는 있어야 하고 `null`은 받지
    않는다(빼면 그 값은 그대로 둔다). 검증은 `api/body.parse_body_days`가 한다(이 모델은 스키마 문서다)."""

    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    # 빠질 수 있지만 `null`은 아니다: 스키마에는 기본값을 적지 않는다(`steps?: number`)
    steps: StrictInt = Field(default=None, ge=0, le=100_000, json_schema_extra=_no_default)  # type: ignore[assignment]
    sleep_minutes: StrictInt = Field(  # type: ignore[assignment]
        default=None, ge=0, le=1_440, json_schema_extra=_no_default,
    )


class BodyPostBody(_Model):
    """`POST /body` 요청 (SP8 7.3, 아이폰 단축어). 최상위 키는 `days` 하나. `client_msg_id`는 없다(7.2)."""

    days: list[BodyDayIn] = Field(min_length=1, max_length=7)


class BodySaved(_Model):
    """`POST /body` 응답: 저장한 날 수. 값은 돌려주지 않는다."""

    saved: int


class ChatMessage(BaseModel):
    """AI SDK `UIMessage`(마지막 사용자 메시지 하나). `parts`의 `text`만 읽는다(6.4.1). 모르는 필드는 버린다."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, max_length=200)
    role: Literal["user"]
    parts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


# 입력창의 퀵 칩(SP9c 4.1). 두뇌 차례 본문에 `## 버튼` 블록(`harness/prompts/chip_<키>.md`)을 붙인다
ChipKey = Literal["todo", "event", "memo", "today", "next"]


class ChatRequestBody(_Model):
    """`POST /chat` 요청 (6.4.1). `client_msg_id`는 필수다(6.1 중복 방지).

    `chip`(SP9c 4.1)이 있으면 명령 해석을 하지 않는다. 회차 답(`checkin_id`)과 같이 오면 거절한다(400).
    """

    client_msg_id: str = Field(min_length=1, max_length=200)
    conversation_id: int | None = None
    checkin_id: int | None = None
    # 목록에서 골라 연 대화(SP9 7.3 0번 규칙). 앱은 그 화면을 떠나거나 "새 대화"를 누를 때까지 모든 메시지에 싣는다
    resume_conversation_id: int | None = None
    message: ChatMessage
    chip: ChipKey | None = None

    @model_validator(mode="after")
    def _chip_not_with_checkin(self) -> ChatRequestBody:
        if self.chip is not None and self.checkin_id is not None:
            raise ValueError("chip과 checkin_id는 같이 올 수 없다")
        return self


class ChatStopBody(_Model):
    """`POST /chat/stop` 요청: 멈출 메시지의 `client_msg_id`(`POST /chat`에 보낸 것)."""

    client_msg_id: str = Field(min_length=1, max_length=200)


class ChatStopped(_Model):
    """`POST /chat/stop` 응답. `stopped`: 기다리거나 답하던 것을 멈췄다. `done`: 이미 답을 마쳤다(그대로 둔다).
    `unknown`: 받은 적 없는 id다."""

    state: Literal["stopped", "done", "unknown"]


class ActionXp(_Model):
    """이 요청에서 쌓인 경험치(9.1)와, 레벨이 올랐으면 새 레벨(9.2). 오르지 않았으면 `level_up`은 null."""

    gained: int
    level_up: int | None


class ActionApplied(_Model):
    """적용(200). `undo_id`는 되돌릴 수 있을 때만 있고 값은 `activity_id`와 같다."""

    status: Literal["applied"]
    activity_id: int | None
    undo_id: int | None = None
    result: dict[str, Any]
    confirmation: str | None
    xp: ActionXp


class ActionNeedsConfirm(_Model):
    """확인 필요(200). 같은 요청에 `confirm_token`을 넣어 다시 보내면 적용한다(10분)."""

    status: Literal["needs_confirm"]
    confirm_token: str
    summary: str
    expires_at: str


class ActionRejected(_Model):
    """거절(422). `error.message`는 도구의 오류 문구다."""

    status: Literal["rejected"]
    activity_id: None
    error: ErrorDetail


class UndoRequestBody(_Model):
    """`POST /activity/{id}/undo` 요청 (6.4.3). `client_msg_id`는 필수다(6.1 중복 방지)."""

    client_msg_id: str = Field(min_length=1, max_length=200)


class UndoResponse(_Model):
    """되돌림(200). `undone`: 되돌린 활동 id. `already_undone`(U4)이면 `activity_id`는 앞선 되돌리기 활동이고
    `undone`, `confirmation`은 없다."""

    status: Literal["undone", "already_undone"]
    activity_id: int | None
    undone: int | None = None
    confirmation: str | None = None


class ActivityItem(_Model):
    id: int
    at: str
    actor: Literal["secretary", "user"]
    channel: Literal["app", "telegram", "scheduler"]
    kind: str
    summary: str
    risk: Literal["low", "confirm"]
    undo_id: int | None  # 지금 되돌릴 수 있을 때만(U1~U3을 지금 시각으로), 값은 `id`와 같다
    undone_at: str | None


class ActivityResponse(_Model):
    """`GET /activity` (6.4.4). `next_before`는 `desc`이고 더 앞선 행이 남았을 때만, 아니면 null."""

    items: list[ActivityItem]
    next_since: str | None
    next_before: str | None


class VapidPublicKey(_Model):
    """`GET /push/vapid-public-key` (6.4.8)."""

    public_key: str


def _b64url(v: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", v):
        raise ValueError("base64url이 아니다")
    return base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))


class PushKeys(BaseModel):
    """구독 키. `p256dh`는 비압축 P-256 공개점 65바이트, `auth`는 16바이트(둘 다 base64url). repr에 나오지 않는다.

    오류 문구에 값이 들어가지 않게 처리기는 `ValidationError`를 고정 문구 400으로 바꾼다(`api/push.py`).
    """

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    p256dh: str = Field(min_length=1, max_length=512, repr=False)
    auth: str = Field(min_length=1, max_length=512, repr=False)

    @field_validator("p256dh")
    @classmethod
    def _p256dh(cls, v: str) -> str:
        from cryptography.hazmat.primitives.asymmetric import ec

        raw = _b64url(v)
        if len(raw) != 65 or raw[0] != 0x04:
            raise ValueError("p256dh는 비압축 P-256 점 65바이트여야 한다")
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)  # 곡선 위의 점이 아니면 ValueError
        return v

    @field_validator("auth")
    @classmethod
    def _auth(cls, v: str) -> str:
        if len(_b64url(v)) != 16:
            raise ValueError("auth는 16바이트여야 한다")
        return v


class PushSubscribeBody(BaseModel):
    """`POST /push/subscriptions` 요청: 브라우저 `PushSubscription.toJSON()` + `label` (6.4.8). 모르는 필드는 버린다.

    `endpoint`와 키는 비밀값처럼 다룬다: repr과 검증 오류에 넣지 않는다.
    """

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    endpoint: str = Field(min_length=1, max_length=2048, pattern=r"^https://", repr=False)
    expirationTime: int | float | None = None
    keys: PushKeys
    label: str | None = Field(default=None, max_length=100)


class PushSubscribed(_Model):
    """`201` 구독 id. 같은 `endpoint`면 같은 id."""

    id: int


DeviceClient = Literal["app", "dashboard"]


class PairCreated(_Model):
    """`POST /devices/pair` `201`: 연결 코드(숫자 6자리)와 만료 시각 (기기 연결 스펙 4.5)."""

    code: str
    expires_at: str


class DeviceRef(_Model):
    id: int
    label: str


class PairStatus(_Model):
    """`GET /devices/pair`: 지금 코드의 상태. `used`면 그 코드로 연결한 기기."""

    state: Literal["waiting", "used", "expired", "none"]
    device: DeviceRef | None = None


class PairBody(BaseModel):
    """`POST /pair` 요청. 모르는 필드는 거절한다. 검증 오류에 입력값을 넣지 않는다(코드가 들어 있다)."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    code: str = Field(pattern=r"^[0-9]{6}$", repr=False)
    client: DeviceClient
    # C0·C1 제어 문자, 줄·문단 구분자, 방향 제어 문자를 막는다(목록에 그대로 보인다)
    label: str = Field(
        min_length=1, max_length=40, pattern=r"^[^\x00-\x1f\x7f-\x9f\u200e\u200f\u2028-\u202e\u2066-\u2069]+$"
    )


class PairedDevice(_Model):
    id: int
    label: str
    client: DeviceClient


class PairResult(_Model):
    """`POST /pair` `201`: 기기 토큰(이 응답에만 한 번 나온다)과 기기."""

    token: str
    device: PairedDevice


class DeviceItem(_Model):
    id: int
    label: str
    client: DeviceClient
    created_at: str
    last_used_at: str | None
    this_device: bool


class DeviceList(_Model):
    """`GET /devices`: 끊지 않은 기기, 만든 순서. API 토큰은 나오지 않는다."""

    devices: list[DeviceItem]


class PushTestResult(_Model):
    """`POST /push/test`: 받은 구독 수, 못 받은 구독 수."""

    ok: int
    failed: int


class NotifySettings(_Model):
    """`GET`/`PUT /settings/notify` (6.4.9). `effective`는 7.3 D1a."""

    primary: Literal["telegram", "app"]
    effective: Literal["telegram", "app"]
    push_subscriptions: int


class NotifyPutBody(_Model):
    primary: Literal["telegram", "app"]


class CalendarSettings(_Model):
    """`GET`/`POST /settings/calendar` (SP9 5.7). `url`은 구독 주소(비밀: 키가 들어 있다). 아직 안 만들었으면 null."""

    url: str | None


class CalendarPutBody(_Model):
    rotate: bool = False


CheckinLoop = Literal["morning_brief", "evening_checkin"]
CheckinDayType = Literal["weekday", "weekend"]


class CheckinTimeItem(_Model):
    """체크인 시간 한 칸(SP9 8장). `time`은 앞으로의 값("HH:MM"), `from`은 그 값이 적용되는 첫 날(논리적 날짜,
    바꾼 적이 없으면 null), `effective_today`는 오늘(논리적 날짜) 적용되는 값."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    loop: CheckinLoop
    day_type: CheckinDayType
    time: str
    from_: str | None = Field(alias="from")
    effective_today: str


class CheckinTimes(_Model):
    """`GET /settings/checkin-times`: 네 칸(평일 아침, 평일 저녁, 주말 아침, 주말 저녁)과, 마지막 깨우기 작업 다시
    등록이 됐는지(`wake_updated`: PUT, 확인 카드, 되돌리기 어느 쪽에서 바꿨든 같은 값)."""

    items: list[CheckinTimeItem]
    wake_updated: bool  # 마지막 깨우기 작업 다시 등록이 됐는지(안 됐으면 설정 화면에 안내 줄)


class CheckinTimePutBody(_Model):
    """`PUT /settings/checkin-times`: 바꿀 칸 하나. 아침 05:00~11:30, 저녁 15:00~23:30, 10분 단위."""

    loop: CheckinLoop
    day_type: CheckinDayType
    time: str


class CheckinTimesUpdated(CheckinTimes):
    """`PUT /settings/checkin-times`의 답: 지금 네 칸(과 `wake_updated`), 바꾼 칸의 적용 시점, 되돌리기 id(`undo_id`, 활동 id와 같다)."""

    applies: Literal["today", "tomorrow"]
    activity_id: int | None
    undo_id: int | None


DigestKindName = Literal["morning", "night"]


class DigestSlot(_Model):
    """일정 정리 알림 한 종류(SP9b 5장). `time`은 현지 시각 "HH:MM"(04:00 경계와 상관없다)."""

    on: bool
    time: str


class DigestSettings(_Model):
    """`GET /settings/digests`: 아침 알림(오늘 일정), 밤 알림(내일 일정), 마지막 깨우기 작업 다시 등록이 됐는지
    (`wake_updated`: 체크인 시간과 같은 값)."""

    morning: DigestSlot
    night: DigestSlot
    wake_updated: bool


class DigestSettingPutBody(_Model):
    """`PUT /settings/digests`: 바꿀 종류 하나. 아침 04:00~11:50, 밤 18:00~23:50, 10분 단위(벗어나거나 모르는 종류면
    `422 digest_time_invalid`). 멱등 키는 없다(같은 값이면 아무것도 적지 않는다)."""

    kind: DigestKindName
    on: bool = Field(strict=True)
    time: str


class DigestSettingsUpdated(DigestSettings):
    """`PUT /settings/digests`의 답: 지금 두 종류(와 `wake_updated`), 적용 시점, 되돌리기 id(`undo_id`, 활동 id와 같다).
    같은 값이라 바뀐 것이 없으면 `applies`, `activity_id`, `undo_id`가 모두 null이다."""

    applies: Literal["today", "tomorrow"] | None
    activity_id: int | None
    undo_id: int | None


class ClientErrorBody(_Model):
    """`POST /client-errors` 요청 (SP6 3.3). 에러 메시지는 받지 않는다(모르는 키는 거부)."""

    app: Literal["app", "dashboard"]
    version: str = Field(max_length=40, pattern=r"^[A-Za-z0-9._+\-]+$")
    route: str = Field(max_length=120, pattern=r"^/[A-Za-z0-9_\-/\[\]]*$")
    name: str = Field(max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_.]*$")
    # 청크 이름 + 줄:열만 (스펙 3.3). URL·절대 경로·글은 틀에서 걸러 이슈까지 가지 않게 한다.
    frames: list[
        Annotated[str, Field(max_length=160, pattern=r"^[A-Za-z0-9_\-][A-Za-z0-9_.\-/\[\]]*\.js:\d+:\d+$")]
    ] = Field(max_length=10)
    at: datetime


class RecoveryNoticeBody(_Model):
    """`POST /internal/notify` 요청 (SP6 6장). 복구 감시자가 결과 알림을 보낼 때 쓴다."""

    text: str = Field(min_length=1, max_length=500)
    kind: Literal["recovery"]


class RecoveryNoticeSent(_Model):
    """`POST /internal/notify` 응답: 알림이 간 통로."""

    channel: Literal["telegram", "app"]


def dump(model: type[BaseModel], body: Any) -> dict[str, Any]:
    """응답 본문을 UTC로 바꾸고 모델로 검증한 뒤 JSON 값으로 돌려준다(모양이 틀리면 예외 → 500 `internal`)."""
    return model.model_validate(to_api_times(body)).model_dump(mode="json", by_alias=True, exclude_unset=True)


MODELS: dict[str, type[BaseModel]] = {
    "Error": ErrorBody,
    "Health": Health,
    "SafeModeHealth": SafeModeHealth,
    "Todo": Todo,
    "TodoRef": TodoRef,
    "TodoRefs": TodoRefs,
    "Today": Today,
    "Week": Week,
    "Conditions": Conditions,
    "Priorities": Priorities,
    "Drafts": Drafts,
    "Curve": Curve,
    "CurveHistory": CurveHistory,
    "Status": Status,
    "Moment": Moment,
    "MomentsList": MomentsList,
    "BodyPostBody": BodyPostBody,
    "BodySaved": BodySaved,
    "CheckinList": CheckinList,
    "CheckinSummary": CheckinSummary,
    "CheckinDetail": CheckinDetail,
    "Conversations": Conversations,
    "ConversationsClosed": ConversationsClosed,
    "Messages": Messages,
    "UiCatalog": UiCatalog,
    "SchemaBundle": SchemaBundle,
    "ActionRequestBody": ActionRequestBody,
    "ChatRequestBody": ChatRequestBody,
    "ChatStopBody": ChatStopBody,
    "ChatStopped": ChatStopped,
    "ActionApplied": ActionApplied,
    "ActionNeedsConfirm": ActionNeedsConfirm,
    "ActionRejected": ActionRejected,
    "UndoRequestBody": UndoRequestBody,
    "UndoResponse": UndoResponse,
    "ActivityResponse": ActivityResponse,
    "VapidPublicKey": VapidPublicKey,
    "PushSubscribeBody": PushSubscribeBody,
    "PushSubscribed": PushSubscribed,
    "PairCreated": PairCreated,
    "PairStatus": PairStatus,
    "PairBody": PairBody,
    "PairResult": PairResult,
    "DeviceList": DeviceList,
    "PushTestResult": PushTestResult,
    "NotifySettings": NotifySettings,
    "NotifyPutBody": NotifyPutBody,
    "CalendarSettings": CalendarSettings,
    "CalendarPutBody": CalendarPutBody,
    "CheckinTimes": CheckinTimes,
    "CheckinTimePutBody": CheckinTimePutBody,
    "CheckinTimesUpdated": CheckinTimesUpdated,
    "DigestSlot": DigestSlot,
    "DigestSettings": DigestSettings,
    "DigestSettingPutBody": DigestSettingPutBody,
    "DigestSettingsUpdated": DigestSettingsUpdated,
    "Habit": Habit,
    "HabitsList": HabitsList,
    "HabitHistory": HabitHistory,
    "Memo": Memo,
    "MemoItem": MemoItem,
    "MemoList": MemoList,
    "EventItem": EventItem,
    "EventList": EventList,
    "EventDetail": EventDetail,
    "MissedReminder": MissedReminder,
    "ClientErrorBody": ClientErrorBody,
    "RecoveryNoticeBody": RecoveryNoticeBody,
    "RecoveryNoticeSent": RecoveryNoticeSent,
}


def schema_bundle() -> dict[str, Any]:
    """`GET /schema`와 `python -m my_planner schema`의 본문: `{"api": "v1", "models": {이름: JSON 스키마}}` (6.4)."""
    return {
        "api": "v1",
        "models": {name: model.model_json_schema(by_alias=True) for name, model in sorted(MODELS.items())},
    }

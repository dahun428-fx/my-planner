"""요청·응답 pydantic 모델(JSON 스키마의 정본, SP3-4 스펙 4.2, 6)과 API 경계의 공통 도구.

- 응답의 시각은 UTC ISO 8601(`2026-10-24T09:00:00Z`)이다. 저장소와 도구 결과는 오프셋 붙은 ISO(`+00:00`,
  `+09:00`)를 주므로 `to_api_times`가 경계에서 바꾼다. 날짜(`2026-10-24`)와 기간은 그대로 둔다.
- 오류 모양은 `{"error": {"code", "message"}}` 하나다(6.1).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field

# 시각 변환의 정본은 `my_planner.timefmt`다. API 쪽 가져오기가 그대로 되도록 다시 내보낸다
from my_planner.timefmt import TIME_KEYS, api_time, is_time_key, to_api_times  # noqa: F401 - 다시 내보냄

log = logging.getLogger(__name__)

ErrorCode = Literal[
    "invalid_request", "unauthorized", "not_found", "conflict", "superseded", "undo_expired", "too_large",
    "rejected", "not_undoable", "too_many_auth_failures", "safe_mode", "internal",
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

    예상 못 한 예외는 로그에 종류만 남긴다(본문, 경로 값, 토큰 없이).
    """
    try:
        return await handler(request)
    except web.HTTPException as e:
        if e.status < 400:
            raise
        code, message = _HTTP_CODES.get(e.status, ("invalid_request", "요청을 처리할 수 없어요."))
        return error_response(e.status, code, message)
    except Exception as e:  # noqa: BLE001 - 무엇이든 500으로. 예외 메시지는 남기지 않는다
        log.error("api_internal_error", extra={"error_type": type(e).__name__})
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
    skip_reason: str | None
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
    """화면 조각이 붙이는 할 일 요약 (6.3): `ui_todo_list`·`ui_todo_draft`의 `data.todos`, 체크인 `cards[].data.todos`."""

    id: int
    title: str
    cadence: CadenceName | None
    area: AreaName | None
    status: TodoStatus


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
    group: Literal["priority", "scheduled", "open"]
    todo: Todo


class AppCard(_Model):
    """고정 카드 (6.3.2 `cards`, 운영 앱용). 티켓 09 전에는 목록이 비어 있다."""

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
    data: dict[str, Any] | None = None  # 할 일을 가리키는 카드만(`TodoRefs`)


class CheckinDetail(CheckinSummary):
    text: str
    cards: list[CheckinCard]


class CheckinList(_Model):
    items: list[CheckinSummary]


class Today(_Model):
    """`GET /today` (6.3.2)."""

    date: str
    weekday: str
    brief: TodayBrief | None
    condition: ConditionItem | None
    todos: list[TodayTodo]
    checkins: list[CheckinSummary]
    cards: list[AppCard]


class WeekDay(_Model):
    date: str
    weekday: str
    is_today: bool
    todos: list[Todo]


class Week(_Model):
    """`GET /week` (6.3.3): 할 일이 없는 날도 `days`에 7일 모두 든다."""

    week: str
    start: str
    end: str
    priorities: list[Todo]
    days: list[WeekDay]


class Conditions(_Model):
    """`GET /conditions` (6.3.4)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    items: list[ConditionItem]
    days_logged: int
    average: float | None


class Priorities(_Model):
    """`GET /priorities` (6.3.7)."""

    cadence: Literal["week", "month", "quarter", "year"]
    period: str
    items: list[Todo]


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
    id: int
    kind: Literal["run", "chat", "plan"]
    channel: ChannelName
    run_id: int | None
    opened_at: str
    last_message_at: str
    closed_at: str | None


class Conversations(_Model):
    items: list[ConversationItem]


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


class StatusHp(_Model):
    date: str
    score: int | None


class StatusStat(_Model):
    area: AreaName
    label: str
    score: int | None
    period: str | None
    prev_score: int | None
    prev_period: str | None
    debuff: bool
    recovery_quest: str | None


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


class Status(_Model):
    """`GET /status` (6.3.6)."""

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


class ActionXp(_Model):
    gained: int
    level_up: None  # 티켓 15 전까지 늘 null


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
    "Status": Status,
    "CheckinList": CheckinList,
    "CheckinSummary": CheckinSummary,
    "CheckinDetail": CheckinDetail,
    "Conversations": Conversations,
    "Messages": Messages,
    "UiCatalog": UiCatalog,
    "SchemaBundle": SchemaBundle,
    "ActionRequestBody": ActionRequestBody,
    "ActionApplied": ActionApplied,
    "ActionNeedsConfirm": ActionNeedsConfirm,
    "ActionRejected": ActionRejected,
}


def schema_bundle() -> dict[str, Any]:
    """`GET /schema`와 `python -m my_planner schema`의 본문: `{"api": "v1", "models": {이름: JSON 스키마}}` (6.4)."""
    return {
        "api": "v1",
        "models": {name: model.model_json_schema(by_alias=True) for name, model in sorted(MODELS.items())},
    }

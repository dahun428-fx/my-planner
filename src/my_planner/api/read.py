"""읽기 경로 (SP3-4 스펙 6.3.2~6.3.4, 6.3.7, 6.3.8, 6.4.5~6.4.7, 6.4 `/schema`, SP7 5.5 습관).

모든 처리기는 읽기 전용 연결(`deps.read_conn()`) 하나만 받는다(스펙 4.3). 응답은 `to_api_times`로 UTC `Z`로 바꾼 뒤
모델로 검증한다. 오류 문구에는 쿼리 값, 경로 값, 본문을 넣지 않는다.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner.api.models import (
    ApiError,
    CheckinDetail,
    CheckinList,
    Conditions,
    Conversations,
    Curve,
    Drafts,
    HabitHistory,
    HabitsList,
    Messages,
    Priorities,
    SchemaBundle,
    Status,
    Today,
    UiCatalog,
    Week,
    dump,
    schema_bundle,
)
from my_planner.clock import logical_date, period_of, to_iso
from my_planner.curve.model import ZOOMS, TooManyBuckets, curve_view, default_range
from my_planner.domain import Cadence, LoopKey, RunStatus, TaskStatus
from my_planner.harness.checkins import checkin_detail, checkin_summaries
from my_planner.status.snapshot import status_snapshot
from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo
from my_planner.store.repos.cards import CardsRepo
from my_planner.store.repos.channels import DeliveriesRepo
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.views import (
    condition_dict,
    conditions_view,
    draft_expiry,
    draft_live,
    habit_history,
    habits_view,
    today_view,
    todo_dict,
    todo_refs,
    week_view,
)
from my_planner.tools.ui import catalog

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

MAX_CONDITION_DAYS = 366
DEFAULT_CONDITION_DAYS = 30
CONVERSATIONS_DEFAULT_LIMIT, CONVERSATIONS_MAX_LIMIT = 20, 200
HABIT_WEEKS_DEFAULT, HABIT_WEEKS_MAX = 4, 12  # `GET /habits/{id}?weeks=` (SP7 5.5)
HABIT_STATUS_FILTERS: dict[str, tuple[str, ...]] = {
    "active": ("active",), "paused": ("paused",), "archived": ("archived",), "all": ("active", "paused", "archived"),
}

# `priorities.period` 형식 (SP1 5.5, `clock.period_of`)
_PERIOD_PATTERNS = {
    "week": re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$"),
    "month": re.compile(r"^\d{4}-(0[1-9]|1[0-2])$"),
    "quarter": re.compile(r"^\d{4}-Q[1-4]$"),
    "year": re.compile(r"^\d{4}$"),
}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT = re.compile(r"^[0-9]{1,18}$")


def _bad(message: str) -> ApiError:
    return ApiError(400, "invalid_request", message)


def _query_date(request: web.Request, name: str) -> date | None:
    raw = request.query.get(name)
    if raw is None:
        return None
    if not _DATE.match(raw):
        raise _bad(f"{name}은 YYYY-MM-DD 형식이어야 해요.")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _bad(f"{name}은 없는 날짜예요.") from None


def _path_id(request: web.Request) -> int:
    raw = request.match_info["id"]
    if not _INT.match(raw):
        raise _bad("id는 정수여야 해요.")
    return int(raw)


def _today(deps: ApiDeps) -> date:
    s = deps.settings
    return logical_date(deps.clock.now(), s.timezone, s.day_boundary)


def _tasks(conn: sqlite3.Connection, deps: ApiDeps) -> TasksRepo:
    s = deps.settings
    return TasksRepo(conn, deps.clock, tz=s.timezone, boundary=s.day_boundary)


# --- 할 일 ---


def get_today(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    s = deps.settings
    now = deps.clock.now()
    tasks = _tasks(conn, deps)
    conditions = ConditionsRepo(conn, deps.clock)
    runs = RunsRepo(conn, deps.clock)
    view = today_view(tasks, conditions, now, s.timezone, s.day_boundary)
    checkins = checkin_summaries(
        runs=runs, convs=ConversationsRepo(conn, deps.clock), deliveries=DeliveriesRepo(conn, deps.clock),
        d=view.date, now=now, settings=s,
    )
    body = {
        "date": view.date.isoformat(),
        "weekday": view.weekday,
        "day_boundary": f"{s.day_boundary:%H:%M}",  # 논리적 날짜가 바뀌는 시각(설정, 기본 04:00)
        "brief": _brief(runs, view.date, deps),
        "condition": condition_dict(view.condition) if view.condition else None,
        "todos": [
            {"group": g.name, "todo": todo_dict(t, tasks, view.date)} for g in view.groups for t in g.tasks
        ],
        "checkins": checkins,
        "cards": today_cards(CardsRepo(conn, deps.clock), tasks, view.date),
        # 활성 습관, `sort_order` 순(SP7 5.5). 없으면 []
        "habits": habits_view(HabitsRepo(conn, deps.clock), view.date, ("active",))["items"],
    }
    return dump(Today, body)


def today_cards(cards: CardsRepo, tasks: TasksRepo, today: date) -> list[dict[str, Any]]:
    """고정 카드(6.3.2 `cards`): `sort_order` 순. props에 `task_ids`가 있으면 지금 값 `data.todos`(초안·소프트 삭제 뺌)."""
    out: list[dict[str, Any]] = []
    for c in cards.active():
        card: dict[str, Any] = {
            "id": c.id, "component": c.component, "order": c.sort_order, "pinned_at": to_iso(c.pinned_at),
            "props": c.props,
        }
        if isinstance(c.props.get("task_ids"), list):
            card["data"] = {"todos": todo_refs(c.props["task_ids"], tasks, today, drafts=False)}
        out.append(card)
    return out


def _brief(runs: RunsRepo, today: date, deps: ApiDeps) -> dict[str, Any] | None:
    """오늘 논리적 날짜에 보낸(`done`) `morning_brief` 또는 `return` 회차의 본문. 가장 나중 것, 없으면 None."""
    s = deps.settings
    found = [
        r
        for r in runs.on_logical_date(today, s.timezone, s.day_boundary)
        if r.status is RunStatus.done and r.loop in (LoopKey.morning_brief, LoopKey.return_) and r.outbound_text
    ]
    if not found:
        return None
    r = found[-1]
    return {
        "run_id": r.id,
        "loop": r.loop.value,
        "text": r.outbound_text,
        "sent_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def get_week(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    s = deps.settings
    tasks = _tasks(conn, deps)
    now = deps.clock.now()
    today = _today(deps)
    view = week_view(tasks, now, s.timezone, s.day_boundary)
    body = {
        "week": view.week,
        "start": view.start.isoformat(),
        "end": view.end.isoformat(),
        "priorities": [todo_dict(t, tasks, today) for t in view.priorities],
        "days": [
            {
                "date": d.date.isoformat(),
                "weekday": d.weekday,
                "is_today": d.is_today,
                "todos": [todo_dict(t, tasks, today) for t in d.tasks],
            }
            for d in view.days
        ],
    }
    return dump(Week, body)


def get_priorities(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    """`cadence`는 필수(week|month|quarter|year), `period`는 선택(없으면 지금 기간)."""
    cadence = request.query.get("cadence")
    if cadence not in ("week", "month", "quarter", "year"):
        raise _bad("cadence는 week, month, quarter, year 중 하나여야 해요.")
    today = _today(deps)
    period = request.query.get("period")
    if period is None:
        period = period_of(cadence, today)
    if not _PERIOD_PATTERNS[cadence].match(period):
        raise _bad("period가 cadence와 맞지 않아요.")
    tasks = _tasks(conn, deps)
    items = [t for t in tasks.priorities(Cadence(cadence), period) if t.status is not TaskStatus.draft]
    return dump(Priorities, {"cadence": cadence, "period": period, "items": [todo_dict(t, tasks, today) for t in items]})


def get_drafts(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    """아직 만료되지 않은 초안만. `proposed_at`은 가장 최근 `proposed` 이벤트 시각(없으면 만든 시각)."""
    now = deps.clock.now()
    today = _today(deps)
    ttl_days = deps.settings.limits.draft_ttl_days
    tasks = _tasks(conn, deps)
    rows = []
    for t in tasks.list(status=TaskStatus.draft):
        if not draft_live(t, tasks, ttl_days, now):
            continue
        proposed_at, expires_at = draft_expiry(t, tasks, ttl_days)
        run_id, conversation_id = tasks.proposal_origin(t.id)
        rows.append(
            (proposed_at, t.id, {
                "todo": todo_dict(t, tasks, today), "proposed_at": proposed_at.isoformat(),
                "expires_at": expires_at.isoformat(), "run_id": run_id, "conversation_id": conversation_id,
            })
        )
    rows.sort(key=lambda r: (r[0], r[1]))
    return dump(Drafts, {"items": [r[2] for r in rows]})


def get_conditions(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    """기본은 오늘을 포함한 지난 30일, 최대 366일. `from <= to`."""
    today = _today(deps)
    to = _query_date(request, "to") or today
    from_ = _query_date(request, "from") or to - timedelta(days=DEFAULT_CONDITION_DAYS - 1)
    if from_ > to:
        raise _bad("from은 to보다 늦을 수 없어요.")
    if (to - from_).days + 1 > MAX_CONDITION_DAYS:
        raise _bad(f"기간은 {MAX_CONDITION_DAYS}일 이하여야 해요.")
    return dump(Conditions, conditions_view(ConditionsRepo(conn, deps.clock), from_, to))


# --- 습관 (SP7 5.5) ---


def get_habits(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    """`date` 기본은 오늘, `status` 기본은 `active`(`all`은 세 상태 모두). 소프트 삭제한 습관은 없다."""
    d = _query_date(request, "date") or _today(deps)
    status = request.query.get("status", "active")
    if status not in HABIT_STATUS_FILTERS:
        raise _bad("status는 active, paused, archived, all 중 하나여야 해요.")
    return dump(HabitsList, habits_view(HabitsRepo(conn, deps.clock), d, HABIT_STATUS_FILTERS[status]))


def get_habit(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    """`weeks`는 1~12(기본 4). 없는·소프트 삭제한 습관은 404(규칙 H3), 그만둔 습관은 기록을 준다."""
    habit_id = _path_id(request)
    raw = request.query.get("weeks")
    weeks = HABIT_WEEKS_DEFAULT
    if raw is not None:
        if not _INT.match(raw) or not 1 <= int(raw) <= HABIT_WEEKS_MAX:
            raise _bad(f"weeks는 1~{HABIT_WEEKS_MAX} 사이 정수여야 해요.")
        weeks = int(raw)
    habits = HabitsRepo(conn, deps.clock)
    h = habits.get(habit_id)
    if h is None:
        raise ApiError(404, "not_found", "없는 습관이에요.")
    return dump(HabitHistory, habit_history(habits, h, _today(deps), weeks))


# --- 인생 곡선, 상태창 ---


def _include_sensitive(request: web.Request) -> bool:
    raw = request.query.get("include_sensitive")
    if raw is None or raw == "false":
        return False
    if raw == "true":
        return True
    raise _bad("include_sensitive는 true 또는 false여야 해요.")


def get_curve(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    zoom = request.query.get("zoom", "month")
    if zoom not in ZOOMS:
        raise _bad("zoom은 day, week, month, quarter, year 중 하나여야 해요.")
    include_sensitive = _include_sensitive(request)
    today = _today(deps)
    curve = CurveRepo(conn, deps.clock)
    earliest = curve.earliest_chapter_start()
    from_, to = _query_date(request, "from"), _query_date(request, "to")
    try:
        if from_ is None or to is None:
            # 하나만 주면 다른 쪽은 그 기준일의 기본 범위에서 가져온다
            base = to if from_ is None and to is not None else today
            dfrom, dto = default_range(zoom, base, earliest)
            from_, to = from_ or dfrom, to or dto
        if from_ > to:
            raise _bad("from은 to보다 늦을 수 없어요.")
        body = curve_view(
            curve, ConditionsRepo(conn, deps.clock), zoom=zoom, from_=from_, to=to,
            include_sensitive=include_sensitive, today=today,
        )
    except TooManyBuckets:
        raise _bad("범위를 줄이거나 확대 단위를 키워 주세요") from None
    except (OverflowError, ValueError):
        raise _bad("범위가 맞지 않아요.") from None
    return dump(Curve, body)


def get_status(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    s = deps.settings
    body = status_snapshot(
        now=deps.clock.now(), tz=s.timezone, boundary=s.day_boundary, status=StatusRepo(conn, deps.clock),
        curve=CurveRepo(conn, deps.clock), tasks=_tasks(conn, deps), conditions=ConditionsRepo(conn, deps.clock),
        include_sensitive=_include_sensitive(request),
    )
    return dump(Status, body)


# --- 답할 회차 ---


def get_checkins(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    d = _query_date(request, "date") or _today(deps)
    items = checkin_summaries(
        runs=RunsRepo(conn, deps.clock), convs=ConversationsRepo(conn, deps.clock),
        deliveries=DeliveriesRepo(conn, deps.clock), d=d, now=deps.clock.now(), settings=deps.settings,
    )
    return dump(CheckinList, {"items": items})


def get_checkin(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    run_id = _path_id(request)
    body = checkin_detail(
        run_id, runs=RunsRepo(conn, deps.clock), convs=ConversationsRepo(conn, deps.clock),
        deliveries=DeliveriesRepo(conn, deps.clock), tasks=_tasks(conn, deps),
        conditions=ConditionsRepo(conn, deps.clock), now=deps.clock.now(), settings=deps.settings,
        confirms=ConfirmsRepo(conn, deps.clock),  # 열린 확인 토큰마다 `ui_confirm`(10.1 A5). 읽기만 한다
        activity=ActivityRepo(conn, deps.clock),  # 대상이 그 뒤 바뀐 토큰은 카드를 뺀다
        curve=CurveRepo(conn, deps.clock),  # 남은 사건·챕터 초안 카드(11.3)
    )
    if body is None:
        raise ApiError(404, "not_found", "없는 회차예요.")
    return dump(CheckinDetail, body)


# --- 대화 ---


def get_conversations(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    channel = request.query.get("channel")
    if channel is not None and channel not in ("telegram", "app"):
        raise _bad("channel은 telegram 또는 app이어야 해요.")
    raw = request.query.get("limit")
    limit = CONVERSATIONS_DEFAULT_LIMIT
    if raw is not None:
        if not _INT.match(raw) or not 1 <= int(raw) <= CONVERSATIONS_MAX_LIMIT:
            raise _bad(f"limit은 1~{CONVERSATIONS_MAX_LIMIT} 사이 정수여야 해요.")
        limit = int(raw)
    convs = ConversationsRepo(conn, deps.clock).recent(channel=channel, limit=limit)
    items = [
        {
            "id": c.id, "kind": c.kind.value, "channel": c.channel, "run_id": c.run_id,
            "opened_at": to_iso(c.opened_at), "last_message_at": to_iso(c.last_message_at),
            "closed_at": to_iso(c.closed_at) if c.closed_at else None,
        }
        for c in convs
    ]
    return dump(Conversations, {"items": items})


def get_conversation_messages(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    conversation_id = _path_id(request)
    if ConversationsRepo(conn, deps.clock).get(conversation_id) is None or deps.transcripts is None:
        raise ApiError(404, "not_found", "없는 대화예요.")
    items = [
        {
            "id": m.id, "at": m.at, "speaker": "user" if m.speaker == "사용자" else "secretary",
            "text": m.text, "tools": m.tools, "channel": m.channel,
        }
        for m in deps.transcripts.messages(conversation_id)
    ]
    return dump(Messages, {"items": items})


# --- 카탈로그와 스키마 ---


def get_ui_catalog(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    return dump(UiCatalog, catalog())


def get_schema(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    return dump(SchemaBundle, schema_bundle())

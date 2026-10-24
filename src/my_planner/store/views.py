"""읽기 뷰: 오늘, 이번 주, 컨디션, 할 일 모양 (SP3-4 스펙 6.3, 6.3.2~6.3.4).

텔레그램 `/today`·`/week`(`bot/commands.py`)와 `GET /today`·`/week`가 같은 뷰 함수에서 나온다. 뷰는 값만 만들고 글이나
JSON으로 바꾸는 일은 부르는 쪽이 한다. 읽기만 한다(읽기 전용 연결로 만든 저장소를 받아도 된다).
초안(`draft`)과 소프트 삭제한 할 일은 어느 뷰에도 나오지 않는다(초안은 `/drafts`와 체크인 카드뿐, 6.3).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from my_planner.clock import from_iso, logical_date, period_of
from my_planner.domain import Area, Cadence, TaskStatus
from my_planner.store.exports import week_bounds
from my_planner.store.repos.conditions import Condition, ConditionsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.tasks import Task, TasksRepo

WEEKDAY = "월화수목금토일"
AREA_ORDER = {a: i for i, a in enumerate(Area)}


@dataclass
class TodoGroup:
    name: str  # priority | scheduled | open
    tasks: list[Task]


@dataclass
class TodayView:
    date: date
    weekday: str
    groups: list[TodoGroup]
    condition: Condition | None


@dataclass
class DayView:
    date: date
    weekday: str
    is_today: bool
    tasks: list[Task] = field(default_factory=list)


@dataclass
class WeekView:
    week: str
    start: date
    end: date
    priorities: list[Task]
    days: list[DayView]  # 할 일이 없는 날도 포함, 7일


def today_view(
    tasks: TasksRepo, conditions: ConditionsRepo | None, now: datetime, tz: str | tzinfo, boundary: time
) -> TodayView:
    """묶음 순서: 우선순위 → 일정 → 열린 할 일(이미 나온 것은 뺀다, 전에 잡은 일 포함)."""
    today = logical_date(now, tz, boundary)
    groups: list[TodoGroup] = []

    prios = [t for t in tasks.priorities(Cadence.day, period_of(Cadence.day, today)) if t.status is TaskStatus.open]
    shown = {t.id for t in prios}
    if prios:
        groups.append(TodoGroup("priority", prios))

    open_tasks = tasks.list(status=TaskStatus.open)
    scheduled = sorted(
        (t for t in open_tasks if t.scheduled_at and logical_date(t.scheduled_at, tz, boundary) == today),
        key=lambda t: t.scheduled_at,  # type: ignore[arg-type,return-value]
    )
    if scheduled:
        groups.append(TodoGroup("scheduled", scheduled))
        shown |= {t.id for t in scheduled}

    # 오늘 하려는 일과 그 전에 잡았지만 아직 열려 있는 일
    rest = [t for t in open_tasks if t.id not in shown and t.planned_for and t.planned_for <= today]
    if rest:
        groups.append(TodoGroup("open", rest))

    cond = conditions.get(today) if conditions is not None else None
    return TodayView(today, WEEKDAY[today.weekday()], groups, cond)


def week_view(tasks: TasksRepo, now: datetime, tz: str | tzinfo, boundary: time) -> WeekView:
    today = logical_date(now, tz, boundary)
    mon, sun = week_bounds(today)
    prios = [t for t in tasks.priorities(Cadence.week, period_of(Cadence.week, today)) if t.status is TaskStatus.open]
    open_tasks = tasks.list(status=TaskStatus.open, from_=mon, to=sun)
    days = []
    for i in range(7):
        d = mon + timedelta(days=i)
        # 시각이 있는 일이 먼저 나오도록 repo가 정렬해 준다
        days.append(DayView(d, WEEKDAY[d.weekday()], d == today, [t for t in open_tasks if t.planned_for == d]))
    return WeekView(period_of(Cadence.week, today), mon, sun, prios, days)


def conditions_view(conditions: ConditionsRepo, from_: date, to: date) -> dict[str, Any]:
    """기록 없는 날은 넣지 않는다(빈 날은 0이 아니다). 평균은 기록한 날만, 소수 첫째 자리."""
    items = conditions.between(from_, to)
    scores = [c.score for c in items]
    return {
        "from": from_.isoformat(),
        "to": to.isoformat(),
        "items": [condition_dict(c) for c in items],
        "days_logged": len(items),
        "average": round(sum(scores) / len(scores), 1) if scores else None,
    }


def condition_dict(c: Condition) -> dict[str, Any]:
    return {"date": c.date.isoformat(), "score": c.score, "note": c.note}


def draft_expiry(t: Task, tasks: TasksRepo, ttl_days: int) -> tuple[datetime, datetime]:
    """초안의 (`proposed_at`, `expires_at`). `GET /drafts`와 체크인 초안 카드가 같은 판정을 쓴다(6.3.8, 6.4.5)."""
    proposed_at = tasks.proposed_at(t.id, t.created_at)
    return proposed_at, proposed_at + timedelta(days=ttl_days)


def draft_live(t: Task, tasks: TasksRepo, ttl_days: int, now: datetime) -> bool:
    """아직 `draft`이고 `expires_at`이 지금 이후다(밤 작업이 아직 지우지 않은 지난 초안은 아니다)."""
    return t.status is TaskStatus.draft and draft_expiry(t, tasks, ttl_days)[1] > now


def _areas(t: Task) -> list[str]:
    return [a.value for a in sorted(t.areas, key=lambda a: AREA_ORDER[a])]


def priority_dict(tasks: TasksRepo, t: Task, today: date) -> dict[str, Any] | None:
    """그 할 일이 지금 기간의 우선순위이면 가장 큰 주기 하나(6.3 `priority`), 아니면 None."""
    got = tasks.current_priority(t.id, today)
    if got is None:
        return None
    cadence, period, rank = got
    return {"cadence": cadence.value, "period": period, "rank": rank}


def todo_dict(t: Task, tasks: TasksRepo, today: date) -> dict[str, Any]:
    """공통 할 일 모양 `Todo` (6.3). 시각은 오프셋 붙은 ISO로 두고 API 경계가 UTC `Z`로 바꾼다."""
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status.value,
        "planned_for": t.planned_for.isoformat() if t.planned_for else None,
        "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
        "parent_id": t.parent_id,
        "areas": _areas(t),
        "note": t.note,
        "priority": priority_dict(tasks, t, today),
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


def todo_ref(t: Task, tasks: TasksRepo, today: date) -> dict[str, Any]:
    """화면 조각이 붙이는 할 일 요약 `TodoRef` (6.3): `cadence`는 지금 기간 우선순위의 주기, `area`는 첫 영역."""
    p = priority_dict(tasks, t, today)
    areas = _areas(t)
    return {
        "id": t.id,
        "title": t.title,
        "cadence": p["cadence"] if p else None,
        "area": areas[0] if areas else None,
        "status": t.status.value,
    }


def todo_refs(ids: Iterable[int], tasks: TasksRepo, today: date, *, drafts: bool = True) -> list[dict[str, Any]]:
    """`ids` 순서대로 `TodoRef`. 없거나 소프트 삭제한 할 일은 뺀다(`dropped`는 행이 남아 있어 넣는다).

    `drafts=False`면 초안도 뺀다(두뇌의 `ui_todo_list`, 고정 카드: 초안은 초안 카드와 `/drafts`에만, 6.3)."""
    return [
        todo_ref(t, tasks, today)
        for i in ids
        if (t := tasks.get(i)) is not None and (drafts or t.status is not TaskStatus.draft)
    ]


# --- 사건·챕터 초안 카드 (SP3-4 6.4.7 `ui_milestone_draft`, `ui_chapter_draft`의 `data`) ---


def milestone_refs(ids: Iterable[int], curve: CurveRepo) -> list[dict[str, Any]]:
    """`ids` 순서대로 `{id, title, date, area, sensitive}`. 없는 사건(빼거나 만료돼 지운 초안)은 뺀다.

    `date`는 저장한 그대로(`YYYY` | `YYYY-MM` | `YYYY-MM-DD`). 사건에는 영역이 없어 `area`는 늘 null이다(6.4.7 계약의
    자리). 초안 카드는 사용자 본인이 보는 확정·빼기 화면이라 민감 사건도 제목을 보인다(`sensitive`로 표시)."""
    return [
        {"id": m.id, "title": m.title, "date": m.date_text, "area": None, "sensitive": m.sensitive}
        for i in ids
        if (m := curve.get_milestone(i)) is not None
    ]


def chapter_refs(ids: Iterable[int], curve: CurveRepo) -> list[dict[str, Any]]:
    """`ids` 순서대로 `{id, title, start_month, end_month}`(`end_month`가 null이면 지금까지). 없는 챕터는 뺀다."""
    return [
        {"id": c.id, "title": c.title, "start_month": c.start_month, "end_month": c.end_month}
        for i in ids
        if (c := curve.get_chapter(i)) is not None
    ]


def curve_draft_live(status: str, draft_since: str | None, ttl_days: int, now: datetime) -> bool:
    """아직 초안이고 `draft_since`에서 `ttl_days`가 지나지 않았다(하루 한 번 작업이 아직 지우지 않은 지난 초안은 아니다)."""
    if status != "draft" or draft_since is None:
        return False
    return from_iso(draft_since) + timedelta(days=ttl_days) > now

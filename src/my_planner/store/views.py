"""읽기 뷰: 오늘, 이번 주, 컨디션, 할 일 모양 (SP3-4 스펙 6.3, 6.3.2~6.3.4).

텔레그램 `/today`·`/week`(`bot/commands.py`)와 `GET /today`·`/week`가 같은 뷰 함수에서 나온다. 뷰는 값만 만들고 글이나
JSON으로 바꾸는 일은 부르는 쪽이 한다. 읽기만 한다(읽기 전용 연결로 만든 저장소를 받아도 된다).
초안(`draft`)과 소프트 삭제한 할 일은 어느 뷰에도 나오지 않는다(초안은 `/drafts`와 체크인 카드뿐, 6.3).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from my_planner.clock import from_iso, logical_date, period_of
from my_planner.domain import Area, Cadence, TaskStatus
from my_planner.store.exports import week_bounds
from my_planner.store.repos.conditions import Condition, ConditionsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.habits import Habit, HabitsRepo
from my_planner.store.repos.moments import Moment
from my_planner.store.repos.tasks import Task, TasksRepo

WEEKDAY = "월화수목금토일"
AREA_ORDER = {a: i for i, a in enumerate(Area)}


@dataclass
class TodoGroup:
    name: str  # priority | scheduled(SP9부터 죽은 갈래) | open
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
    undated: list[Task] = field(default_factory=list)  # 날짜 없는 열린 일(비서가 날짜 없이 추가한 일 포함)


def today_view(
    tasks: TasksRepo, conditions: ConditionsRepo | None, now: datetime, tz: str | tzinfo, boundary: time
) -> TodayView:
    """묶음 순서: 우선순위 → 일정 → 열린 할 일(이미 나온 것은 뺀다, 전에 잡은 일 포함).

    SP9 5.4: "일정" 묶음(`group = "scheduled"`)은 이제 죽은 갈래다. 017 훅이 시각 있는 열린 할 일을 일정으로 옮겼고,
    도구·다시 열기·되돌리기는 열린 할 일에 `scheduled_at`을 두지 않는다. 대시보드가 이 묶음을 읽어 남겨 둔다.
    그날 일정은 스케줄(`/today.events`)에 있다."""
    today = logical_date(now, tz, boundary)
    groups: list[TodoGroup] = []

    prios = [t for t in tasks.priorities(Cadence.day, period_of(Cadence.day, today)) if t.status is TaskStatus.open]
    shown = {t.id for t in prios}
    if prios:
        groups.append(TodoGroup("priority", prios))

    open_tasks = tasks.list(status=TaskStatus.open)
    scheduled = sorted(  # 죽은 갈래(위 설명)
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
    # 날짜 없는 열린 할 일. 이번 주 우선순위(이미 위에 나온다)와 첫 걸음(부모 목표 아래 것)은 뺀다.
    shown = {t.id for t in prios}
    undated = [t for t in tasks.list(status=TaskStatus.open)
               if t.planned_for is None and t.parent_id is None and t.id not in shown]
    return WeekView(period_of(Cadence.week, today), mon, sun, prios, days, undated)


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
    """화면 조각이 붙이는 할 일 요약 `TodoRef` (6.3): `cadence`는 지금 기간 우선순위의 주기, `area`는 첫 영역.

    `planned_for`는 논리적 날짜, `scheduled_at`은 `todo_dict`처럼 오프셋 붙은 ISO이고 API·스트림 경계의 `to_api_times`가
    UTC `Z`로 바꾼다(SP6 10.2)."""
    p = priority_dict(tasks, t, today)
    areas = _areas(t)
    return {
        "id": t.id,
        "title": t.title,
        "cadence": p["cadence"] if p else None,
        "area": areas[0] if areas else None,
        "status": t.status.value,
        "planned_for": t.planned_for.isoformat() if t.planned_for else None,
        "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
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


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def habit_dict(h: Habit, *, checked: bool, week_count: int) -> dict[str, Any]:
    """공통 `Habit` 모양 (SP7 스펙 5.5)."""
    return {
        "id": h.id,
        "title": h.title,
        "area": str(h.area),
        "kind": h.kind,
        "target_per_week": h.target_per_week,
        "status": h.status,
        "checked": checked,
        "week_count": week_count,
    }


def habits_view(habits: HabitsRepo, day: date, statuses: Sequence[str]) -> dict[str, Any]:
    """`GET /habits`: 그 날짜의 체크 여부와 그 ISO 주의 체크 수를 붙인 목록."""
    checked = habits.checked_on(day)
    counts = habits.week_counts(_monday(day))
    return {
        "date": day.isoformat(),
        "week": period_of(Cadence.week, day),
        "items": [
            habit_dict(h, checked=h.id in checked, week_count=counts.get(h.id, 0)) for h in habits.list(statuses)
        ],
    }


def habit_history(habits: HabitsRepo, h: Habit, today: date, weeks: int) -> dict[str, Any]:
    """`GET /habits/{id}`: 오늘이 든 주의 `weeks - 1`주 전 월요일부터 오늘까지. 체크가 없는 날·주는 넣지 않는다."""
    start = _monday(today) - timedelta(weeks=weeks - 1)
    days = habits.checks_between(h.id, start, today)
    per_week: dict[str, int] = {}
    for d in days:
        w = period_of(Cadence.week, d)
        per_week[w] = per_week.get(w, 0) + 1
    return {
        "habit": habit_dict(
            h,
            checked=today in set(days),
            week_count=per_week.get(period_of(Cadence.week, today), 0),
        ),
        "from": start.isoformat(),
        "to": today.isoformat(),
        "checked_dates": [d.isoformat() for d in days],
        "weeks": [{"week": w, "count": n} for w, n in per_week.items()],
    }


# --- 이룬 순간 (SP8 스펙 6.5) ---

MOMENT_SOURCE_KINDS = ("task", "habit", "condition", "chat")


def moment_dict(m: Moment) -> dict[str, Any]:
    """공통 `Moment` 모양(6.5). `sources`는 참조의 종류만 중복 없이 준다(id는 주지 않는다: 그 사이 지운 할 일일 수 있다)."""
    kinds = dict.fromkeys(k for s in m.sources if (k := s.split(":", 1)[0]) in MOMENT_SOURCE_KINDS)
    return {
        "id": m.id,
        "date": m.date.isoformat(),
        "text": m.text,
        "area": m.area,
        "sources": list(kinds),
        "hidden": m.hidden_at is not None,
    }


def moment_counts(ms: Sequence[Moment]) -> list[dict[str, Any]]:
    """날짜와 개수만(`[{"date", "count"}]`, 최근 날짜부터). 텔레그램 통로 두뇌와 회고 앞머리가 쓴다: 글은 없다(6.7, 10.3)."""
    counts: dict[date, int] = {}
    for m in ms:
        counts[m.date] = counts.get(m.date, 0) + 1
    return [{"date": d.isoformat(), "count": n} for d, n in sorted(counts.items(), reverse=True)]

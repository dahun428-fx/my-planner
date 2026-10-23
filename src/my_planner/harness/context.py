"""두뇌에 넘기는 컨텍스트 조각: 매 호출 맨 앞의 알림과 새 세션의 앞머리 (스펙 5.3)."""

from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from my_planner.clock import local, logical_date, period_of
from my_planner.domain import Cadence, TaskStatus
from my_planner.store.exports import format_task

if TYPE_CHECKING:
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.tasks import Task, TasksRepo

OPEN_TASKS_MAX = 30
NO_CONDITION = "기록 없음"
_WEEKDAY = "월화수목금토일"


def build_notices(*, redacted: bool, stale_hours: float | None, truncated: bool) -> str:
    """`## 알림` 섹션. 해당하는 것이 없으면 빈 문자열."""
    lines: list[str] = []
    if redacted:
        lines.append("- 인증·식별 정보를 가렸어요.")
    if stale_hours is not None:
        lines.append(f"- 약 {max(1, round(stale_hours))}시간 전에 보낸 메시지예요.")
    if truncated:
        lines.append("- 메시지가 길어 앞 8000자만 넘겼어요.")
    if not lines:
        return ""
    return "## 알림\n" + "\n".join(lines)


def build_preamble(
    *,
    now: datetime,
    tz: str | tzinfo,
    boundary: time,
    tasks: TasksRepo,
    conditions: ConditionsRepo | None = None,
    paused_until: datetime | None = None,
    merged: list[str] | None = None,
) -> str:
    """새 세션의 앞머리. 빈 섹션은 뺀다. 멈춤(10)은 그 티켓에서 채운다."""
    today = logical_date(now, tz, boundary)
    lt = local(now, tz)
    sections = [
        f"## 지금\n{lt:%Y-%m-%d} ({_WEEKDAY[lt.weekday()]}) {lt:%H:%M}, 오늘(논리적 날짜)은 {today.isoformat()}"
    ]

    prio_lines = []
    for cadence, label in ((Cadence.day, "오늘"), (Cadence.week, "이번 주")):
        picked = [t for t in tasks.priorities(cadence, period_of(cadence, today)) if t.status is TaskStatus.open]
        if picked:
            items = " ".join(f"{i}. {t.title} (#{t.id})" for i, t in enumerate(picked, start=1))
            prio_lines.append(f"- {label}: {items}")
    if prio_lines:
        sections.append("## 우선순위\n" + "\n".join(prio_lines))

    open_tasks = tasks.list(status=TaskStatus.open)
    mon = today - timedelta(days=today.weekday())
    sun = mon + timedelta(days=6)

    def rank(t: Task) -> int:
        if t.planned_for == today:
            return 0
        return 1 if t.planned_for and mon <= t.planned_for <= sun else 2

    ordered = sorted(open_tasks, key=rank)  # 안정 정렬: 같은 묶음 안에서는 날짜, 시각, id 순
    if ordered:
        lines = [format_task(t, tasks, checkbox=False) for t in ordered[:OPEN_TASKS_MAX]]
        if len(ordered) > OPEN_TASKS_MAX:
            lines.append(f"- … 외 {len(ordered) - OPEN_TASKS_MAX}개")
        sections.append("## 열린 할 일\n" + "\n".join(lines))

    scheduled = sorted(
        (t for t in open_tasks if t.scheduled_at and logical_date(t.scheduled_at, tz, boundary) == today),
        key=lambda t: t.scheduled_at,  # type: ignore[arg-type,return-value]
    )
    if scheduled:
        sections.append(
            "## 오늘 일정\n"
            + "\n".join(f"- {local(t.scheduled_at, tz):%H:%M} {t.title} (#{t.id})" for t in scheduled)  # type: ignore[arg-type]
        )

    if conditions is not None:
        y = conditions.get(today - timedelta(days=1))
        if y is None:
            line = NO_CONDITION
        else:
            line = f"{y.score}/5" + (f" (메모: {y.note})" if y.note else "")
        sections.append(f"## 어제 컨디션\n{line}")
    return "\n\n".join(sections)

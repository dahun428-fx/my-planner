"""텔레그램 명령 /today /week /help (스펙 5.6). 두뇌를 거치지 않고 하네스가 바로 답한다.

문구는 모두 읽기 전용이다. 초안(`draft`)과 내려놓은 것, 끝낸 것은 보여 주지 않는다.
"""

from __future__ import annotations

from datetime import date, time, timedelta, tzinfo
from datetime import datetime as _datetime

from my_planner.clock import local, logical_date, period_of
from my_planner.domain import Cadence, TaskStatus
from my_planner.store.exports import week_bounds
from my_planner.store.repos.tasks import Task, TasksRepo

_WEEKDAY = "월화수목금토일"

HELP_TEXT = (
    "쓸 수 있는 명령이에요.\n"
    "/today  오늘 우선순위, 일정, 열린 할 일\n"
    "/week  이번 주 우선순위와 할 일\n"
    "/help  이 안내\n"
    "\n"
    "그 밖에는 그냥 말씀해 주세요. 할 일 추가, 옮기기, 완료, 우선순위 정하기를 도와 드려요."
)

COMMANDS = ("/today", "/week", "/help")


def command_of(text: str) -> str | None:
    """`/today`, `/today@봇이름 인자`처럼 오는 글에서 우리가 직접 답하는 명령 이름. 아니면 None."""
    words = text.strip().split(None, 1)
    if not words or not words[0].startswith("/"):
        return None
    name = words[0].split("@", 1)[0].lower()
    return name if name in COMMANDS else None


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _numbered(items: list[Task]) -> str:
    return "\n".join(f"{i}. {t.title}" for i, t in enumerate(items, start=1))


def today_text(tasks: TasksRepo, now: _datetime, tz: str | tzinfo, boundary: time) -> str:
    today = logical_date(now, tz, boundary)
    out = [f"오늘 ({_md(today)} {_WEEKDAY[today.weekday()]})"]

    prios = tasks.priorities(Cadence.day, period_of(Cadence.day, today))
    prios = [t for t in prios if t.status is TaskStatus.open]
    shown = {t.id for t in prios}
    if prios:
        out.append("우선순위\n" + _numbered(prios))

    open_tasks = tasks.list(status=TaskStatus.open)
    scheduled = sorted(
        (t for t in open_tasks if t.scheduled_at and logical_date(t.scheduled_at, tz, boundary) == today),
        key=lambda t: t.scheduled_at,  # type: ignore[arg-type,return-value]
    )
    if scheduled:
        out.append("일정\n" + "\n".join(f"- {local(t.scheduled_at, tz):%H:%M} {t.title}" for t in scheduled))  # type: ignore[arg-type]
        shown |= {t.id for t in scheduled}

    # 오늘 하려는 일과 그 전에 잡았지만 아직 열려 있는 일. 이미 위에 나온 것은 뺀다.
    rest = [t for t in open_tasks if t.id not in shown and t.planned_for and t.planned_for <= today]
    if rest:
        lines = [f"- {t.title}" + (f" ({_md(t.planned_for)})" if t.planned_for < today else "") for t in rest]  # type: ignore[operator]
        out.append("열린 할 일\n" + "\n".join(lines))

    if len(out) == 1:
        out.append("아직 비어 있어요. 하고 싶은 일을 말씀해 주세요.")
    return "\n\n".join(out)


def week_text(tasks: TasksRepo, now: _datetime, tz: str | tzinfo, boundary: time) -> str:
    today = logical_date(now, tz, boundary)
    mon, sun = week_bounds(today)
    out = [f"이번 주 ({_md(mon)}~{_md(sun)})"]

    prios = tasks.priorities(Cadence.week, period_of(Cadence.week, today))
    prios = [t for t in prios if t.status is TaskStatus.open]
    if prios:
        out.append("우선순위\n" + _numbered(prios))

    open_tasks = tasks.list(status=TaskStatus.open, from_=mon, to=sun)
    for i in range(7):
        d = mon + timedelta(days=i)
        day_tasks = [t for t in open_tasks if t.planned_for == d]
        if not day_tasks:
            continue
        lines = []
        for t in day_tasks:  # 시각이 있는 일이 먼저 나오도록 repo가 정렬해 준다
            at = f"{local(t.scheduled_at, tz):%H:%M} " if t.scheduled_at else ""
            lines.append(f"- {at}{t.title}")
        mark = " (오늘)" if d == today else ""
        out.append(f"{_md(d)} {_WEEKDAY[d.weekday()]}{mark}\n" + "\n".join(lines))

    if len(out) == 1:
        out.append("아직 비어 있어요. 하고 싶은 일을 말씀해 주세요.")
    return "\n\n".join(out)

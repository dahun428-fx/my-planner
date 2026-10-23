"""사람이 읽는 내보내기 `data/exports/tasks.md` (ADR 0003). 변경 도구가 부를 때마다 다시 만든다."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from my_planner.domain import TaskStatus
from my_planner.store.repos.tasks import Task, TasksRepo


def format_task(t: Task, repo: TasksRepo, *, checkbox: bool = True) -> str:
    box = "- [x] " if t.status == TaskStatus.done else "- [ ] " if checkbox else "- "
    bits = [f"{box}#{t.id} {t.title}"]
    if t.scheduled_at:
        at = repo.local(t.scheduled_at)
        bits.append(f"{at.month}/{at.day} {at:%H:%M}")
    elif t.planned_for:
        bits.append(f"{t.planned_for.month}/{t.planned_for.day}")
    if t.areas:
        bits.append(", ".join(a.value for a in t.areas))
    return " · ".join(bits)


def week_bounds(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def export_tasks(repo: TasksRepo, path: Path, today: date) -> None:
    """오늘, 이번 주, 열린 할 일, 이번 주 완료를 쓴다. 초안과 내려놓은 것은 뺀다.

    쓰기에 실패하면 다음 변경 때까지 tasks.md가 예전 내용으로 남는다(도구는 실패를 로그만 남기고 넘어간다).
    """
    mon, sun = week_bounds(today)
    open_tasks = repo.list(status=TaskStatus.open)
    todays = [t for t in open_tasks if t.planned_for == today]
    this_week = [t for t in open_tasks if t.planned_for and mon <= t.planned_for <= sun]
    done = repo.list(status=TaskStatus.done, from_=mon, to=sun)

    def section(title: str, tasks: list[Task]) -> list[str]:
        return [f"## {title}", "", *([format_task(t, repo) for t in tasks] or ["(없음)"]), ""]

    now = repo.local(repo.clock.now())
    lines = [
        "# 할 일",
        "",
        f"_{now:%Y-%m-%d %H:%M} 기준. 이 파일은 자동으로 다시 만들어져요. 직접 고치지 마세요._",
        "",
        *section("오늘", todays),
        *section("이번 주", this_week),
        *section("열린 할 일", open_tasks),
        *section("이번 주 완료", done),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    os.replace(tmp, path)

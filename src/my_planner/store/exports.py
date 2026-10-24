"""사람이 읽는 내보내기 `data/exports/tasks.md` (ADR 0003), `data/curve/chapters.md` (SP3-4 스펙 5.4).

변경 도구가 부를 때마다 다시 만든다."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from my_planner.domain import TaskStatus
from my_planner.store.repos.curve import CurveRepo, Milestone
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
    _write(path, lines)


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


SENSITIVE_MASK = "(민감)"
_KIND = {"high": "고점", "low": "저점", "turning_point": "전환점"}


def _milestone_line(m: Milestone) -> str:
    """메모는 넣지 않는다. 민감 사건은 제목 대신 "(민감)"(5.4)."""
    return f"- {m.date_text} · {_KIND.get(m.kind, m.kind)} · {SENSITIVE_MASK if m.sensitive else m.title}"


def export_curve(curve: CurveRepo, path: Path) -> None:
    """챕터와 확정 사건(5.4). 초안은 넣지 않는다. 사건은 자기 챕터 아래에, 챕터가 없으면 맨 끝 "챕터 밖 사건"에.

    시각 줄은 두지 않는다(같은 데이터면 같은 파일). 쓰기에 실패하면 다음 변경 때 다시 만든다.
    """
    chapters = curve.confirmed_chapters()
    milestones = curve.confirmed_milestones()
    known = {c.id for c in chapters}
    lines = ["# 인생 곡선", "", "_이 파일은 자동으로 다시 만들어져요. 직접 고치지 마세요._", ""]
    for c in chapters:
        lines += [f"## {c.title} ({c.start_month}~{c.end_month or '지금'})", ""]
        if c.theme:
            lines += [c.theme, ""]
        mine = [_milestone_line(m) for m in milestones if m.chapter_id == c.id]
        lines += [*(mine or ["(사건 없음)"]), ""]
    loose = [_milestone_line(m) for m in milestones if m.chapter_id not in known]
    if loose or not chapters:
        lines += ["## 챕터 밖 사건", "", *(loose or ["(없음)"]), ""]
    _write(path, lines)

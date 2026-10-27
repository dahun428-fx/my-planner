"""사람이 읽는 내보내기 `data/exports/tasks.md` (ADR 0003), `data/curve/chapters.md` (SP3-4 스펙 5.4),
`data/exports/habits.md` (SP7 스펙 5.8), `data/exports/memos.md` (SP9 스펙 6.1).

변경 도구가 부를 때마다 다시 만든다. 메모만 하루 한 번 작업이 만든다."""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from my_planner.domain import TaskStatus
from my_planner.store.repos.curve import CurveRepo, Milestone
from my_planner.store.repos.habits import Habit, HabitsRepo
from my_planner.store.repos.memos import Memo, MemosRepo, memo_title
from my_planner.store.repos.photos import PhotosRepo
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
_KIND = {"high": "높은 때", "low": "힘든 때", "turning_point": "전환점"}  # `confirmations.KIND_LABELS`와 같다(SP8 8.7)


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


HABIT_EXPORT_WEEKS = 4
_HABIT_GROUPS = (("active", "챙기는 습관"), ("paused", "쉬는 습관"), ("archived", "그만둔 습관"))
_AREA_LABELS = {  # `status.xp.AREA_LABELS`와 같다(저장소 층은 status를 가져오지 않는다)
    "career": "커리어", "finance": "경제", "health": "건강", "relationships": "관계", "learning": "배움",
    "quality_of_life": "삶의 질",
}


def _habit_export_line(h: Habit, count: int) -> str:
    cadence = "매일" if h.kind == "daily" else f"주 {h.target_per_week}회"
    return f"- {h.title} · {cadence} · {_AREA_LABELS[str(h.area)]} · 지난 {HABIT_EXPORT_WEEKS}주 {count}번"


def export_habits(habits: HabitsRepo, path: Path, today: date) -> None:
    """활성·쉬는·그만둔 묶음(`sort_order` 순)과 습관마다 지난 4주 체크 수(5.8). 지난 4주는 `GET /habits/{id}`처럼
    오늘이 든 주의 3주 전 월요일부터 오늘까지다. 지운 습관(되돌린 추가)은 넣지 않는다. 시각 줄은 두지 않는다."""
    start, _ = week_bounds(today - timedelta(weeks=HABIT_EXPORT_WEEKS - 1))
    lines = ["# 습관", "", "_이 파일은 자동으로 다시 만들어져요. 직접 고치지 마세요._", ""]
    for status, heading in _HABIT_GROUPS:
        rows = [_habit_export_line(h, len(habits.checks_between(h.id, start, today))) for h in habits.list((status,))]
        lines += [f"## {heading}", "", *(rows or ["(없음)"]), ""]
    _write(path, lines)


def _memo_heading(m: Memo) -> str:
    bits = [f"### #{m.id} {memo_title(m.body)}"]
    if m.area is not None:
        bits.append(_AREA_LABELS[m.area.value])
    if m.origin == "chat":
        bits.append("비서")
    return " · ".join(bits)


def export_memos(memos: MemosRepo, path: Path, *, photos: PhotosRepo | None = None) -> None:
    """살아 있는 메모 전체(SP9 6.1, ADR 0003 사람이 읽는 사본): "고정됨" 묶음 먼저, 그다음 "메모", 고친 시각 최근순.
    하루 한 번 작업만 부른다. 지운 메모는 넣지 않는다. 시각 줄은 두지 않는다(같은 데이터면 같은 파일).
    `photos`가 있으면 메모 본문 아래에 붙은 사진마다 `![사진](../photos/<경로>)` 줄(위치 순, 큰 사진만, SP10 5.6 5번)."""
    live = memos.all_live()

    def photo_lines(memo_id: int) -> list[str]:
        if photos is None:
            return []
        try:
            got = photos.for_memo(memos.conn, memo_id)
        except sqlite3.OperationalError:  # SP10 14장 되돌림: 020 표를 지웠다. 사진 줄 없이 메모만 쓴다
            return []
        lines = [f"![사진](../photos/{p.path})" for p in got]
        return [*lines, ""] if lines else []

    lines = ["# 메모", "", "_이 파일은 자동으로 다시 만들어져요. 직접 고치지 마세요._", ""]
    for heading, group in (("고정됨", [m for m in live if m.pinned]), ("메모", [m for m in live if not m.pinned])):
        if heading == "고정됨" and not group:
            continue
        lines += [f"## {heading}", ""]
        for m in group:
            lines += [_memo_heading(m), "", m.body.rstrip("\n"), "", *photo_lines(m.id)]
        if not group:
            lines += ["(없음)", ""]
    _write(path, lines)

"""두뇌에 넘기는 컨텍스트 조각: 매 호출 맨 앞의 알림과 새 세션의 앞머리 (스펙 5.3)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from my_planner.clock import local, logical_date, period_of
from my_planner.domain import Cadence, LoopKey, RunStatus, TaskStatus
from my_planner.store.exports import format_task

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.habits import Habit, HabitsRepo
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.tasks import Task, TasksRepo

OPEN_TASKS_MAX = 30
NO_CONDITION = "기록 없음"
_WEEKDAY = "월화수목금토일"


ELSEWHERE_MAX = 5  # "다른 곳에서 바뀐 것" 줄 수 상한(SP3-4 7.1)


def build_notices(
    *, redacted: bool, stale_hours: float | None, truncated_to: int | None, elsewhere: list[str] | None = None
) -> str:
    """`## 알림` 섹션. 해당하는 것이 없으면 빈 문자열. `truncated_to`는 앞에서 자른 글자 수(`limits.input_max_chars`).

    `elsewhere`: 이 대화의 마지막 메시지 뒤 다른 통로에서 생긴 활동의 `summary`(시간순). 있으면 그 뒤에
    `## 다른 곳에서 바뀐 것` 섹션을 최대 5줄로 붙인다(SP3-4 7.1, 매 호출).
    """
    other = ""
    if elsewhere:
        other = "## 다른 곳에서 바뀐 것\n" + "\n".join(f"- {s}" for s in elsewhere[-ELSEWHERE_MAX:])
    lines: list[str] = []
    if redacted:
        lines.append("- 인증·식별 정보를 가렸어요.")
    if stale_hours is not None:
        lines.append(f"- 약 {max(1, round(stale_hours))}시간 전에 보낸 메시지예요.")
    if truncated_to is not None:
        lines.append(f"- 메시지가 길어 앞 {truncated_to}자만 넘겼어요.")
    notes = "## 알림\n" + "\n".join(lines) if lines else ""
    return "\n\n".join(p for p in (notes, other) if p)


def build_preamble(
    *,
    now: datetime,
    tz: str | tzinfo,
    boundary: time,
    tasks: TasksRepo,
    conditions: ConditionsRepo | None = None,
    paused_until: datetime | None = None,
    merged: list[str] | None = None,
    habits: HabitsRepo | None = None,
    include_habits: bool = False,
) -> str:
    """새 세션의 앞머리. 빈 섹션은 뺀다. `paused_until`이 지금 뒤면 `## 멈춤`(한국 시간)을 붙인다.

    `include_habits`가 참이고 활성 습관이 있으면 `## 오늘 습관`을 붙인다(SP7 5.7, 아침 브리핑과 복귀 인사는 거짓).
    """
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

    if include_habits and habits is not None:
        active = habits.list()
        if active:
            done = habits.checked_on(today)
            counts = habits.week_counts(today - timedelta(days=today.weekday()))
            sections.append("## 오늘 습관\n" + "\n".join(_today_habit_line(h, done, counts) for h in active))

    if paused_until is not None and now < paused_until:
        pt = local(paused_until, tz)
        sections.append(
            f"## 멈춤\n{pt.month}월 {pt.day}일 {pt:%H:%M}까지 사용자가 쉬기로 했어요. "
            "그때까지 비서가 먼저 연락하지 않아요(묻는 말에는 답합니다)."
        )
    return "\n\n".join(sections)


def _habit_label(h: Habit) -> str:
    return f"{h.title} (매일)" if h.kind == "daily" else f"{h.title} (주 {h.target_per_week}회)"


def _today_habit_line(h: Habit, done: set[int], counts: dict[int, int]) -> str:
    if h.kind == "daily":
        return f"- {_habit_label(h)}" + (": 오늘 ✓" if h.id in done else "")
    return f"- {_habit_label(h)}: 이번 주 {counts.get(h.id, 0)}번"


def habit_week_block(habits: HabitsRepo, review_day: date) -> str:
    """주간 회고 회차의 `## 이번 주 습관`(SP7 5.7). 활성 습관마다 이번 주 체크 수와 지난 4주 수(오래된 주부터).

    지난 4주는 이번 주 앞의 온전한 4주이고 0인 주도 쓴다. 이 숫자는 두뇌에게만 주는 맥락이다(원칙 13).
    활성 습관이 없으면 빈 문자열.
    """
    active = habits.list()
    if not active:
        return ""
    monday = review_day - timedelta(days=review_day.weekday())
    this_week = habits.week_counts(monday)
    past = [habits.week_counts(monday - timedelta(days=7 * i)) for i in (4, 3, 2, 1)]
    lines = [
        f"- {_habit_label(h)}: 이번 주 {this_week.get(h.id, 0)}번 · 지난 4주 "
        + "·".join(str(w.get(h.id, 0)) for w in past)
        + "번"
        for h in active
    ]
    return "## 이번 주 습관\n" + "\n".join(lines)


def evening_done(d: date, *, runs: RunsRepo, settings: Settings) -> bool:
    """그 논리적 날짜의 저녁 체크인 회차가 done인지. 회차가 없으면 done이 아니다."""
    start = datetime.combine(d, settings.day_boundary, ZoneInfo(settings.timezone))
    got = runs.between(start - timedelta(microseconds=1), start + timedelta(days=1))
    return any(
        r.loop is LoopKey.evening_checkin
        and r.status is RunStatus.done
        and logical_date(r.scheduled_for, settings.timezone, settings.day_boundary) == d
        for r in got
    )


def ask_condition_for(
    run: Run, merged: list[Run] | None, *, conditions: ConditionsRepo | None, runs: RunsRepo, settings: Settings
) -> date | None:
    """컨디션 버튼의 날짜(스펙 5.4). 저녁 체크인은 그 회차의 논리적 날짜다.

    저녁 체크인이 다른 회차(예: 일요일 회고)에 합쳐졌어도 그 저녁 체크인의 날짜를 쓴다. 텔레그램 버튼과
    앱의 `ui_condition_picker` 카드(6.4.5)가 같은 판정을 쓰도록 디스패처에서 옮겼다. 읽기만 한다.
    """
    if conditions is None:
        return None
    for r in (run, *(merged or [])):
        if r.loop is LoopKey.evening_checkin:
            return logical_date(r.scheduled_for, settings.timezone, settings.day_boundary)
    today = logical_date(run.scheduled_for, settings.timezone, settings.day_boundary)
    if run.loop is LoopKey.morning_brief:
        # 어제 기록이 없고 어제 저녁 체크인이 done이 아니면(늦음, 복귀 인사, 멈춤 등 이유와 상관없이) 어제를 묻는다
        yesterday = today - timedelta(days=1)
        if conditions.get(yesterday) is None and not evening_done(yesterday, runs=runs, settings=settings):
            return yesterday
    return None

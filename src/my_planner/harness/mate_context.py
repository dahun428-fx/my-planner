"""메이트의 새 두뇌 세션 앞머리 (SP12 스펙 5.5). 모두 DB에서 읽는다(ADR 0014). 원문은 넣지 않는다.

비서 앞머리(`context.build_preamble`) 대신 이 섹션들만 받는다. 섹션마다 줄 수 상한을 둔다: 일정 8, 몸 메모 30, 최근 기록
14일·8개. 빈 섹션은 빼지 않고 빈 문구("기록 없음", "없음", "아직 없음")를 쓴다. `get_mate_context` 도구도 이 글을 준다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from my_planner.clock import local, logical_date

if TYPE_CHECKING:
    from my_planner.store.repos.body import BodyRepo
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.events import EventsRepo
    from my_planner.store.repos.workout import (
        LogItem,
        PlanItem,
        WorkoutLog,
        WorkoutRepo,
    )

TODAY_EVENTS_MAX = 8
BODY_NOTES_LINES = 30
RECENT_LOG_DAYS = 14  # 오늘 포함
RECENT_LOGS_MAX = 8
STEPS_DAYS = 7  # 오늘 포함, 기록한 날만 평균

NO_RECORD = "기록 없음"
NO_EVENTS = "없음"
NOT_YET = "아직 없음"
WEEKDAY = "월화수목금토일"
BODY_KIND_LABELS = {
    "equipment": "장비", "injury": "부상·통증", "preference": "선호", "availability": "가능한 때", "other": "기타",
}


def _num(v: float) -> str:
    """16.0 → `16`, 2.5 → `2.5`."""
    return str(int(v)) if float(v).is_integer() else str(v)


def _sets_reps(sets: int | None, reps: int | str | None) -> str:
    if sets is not None and reps is not None:
        return f"{sets}x{reps}"
    if sets is not None:
        return f"{sets}세트"
    return str(reps) if reps is not None else ""


def plan_item_text(i: PlanItem) -> str:
    """`고블릿 스쿼트 3x8-10 @16kg`, `걷기 30분`."""
    parts = [i.name, _sets_reps(i.sets, i.reps)]
    if i.weight_kg is not None:
        parts.append(f"@{_num(i.weight_kg)}kg")
    if i.minutes is not None:
        parts.append(f"{i.minutes}분")
    return " ".join(p for p in parts if p)


def log_item_text(i: LogItem) -> str:
    """`덤벨 프레스 3x10 @14kg`, `걷기 30분 3km`."""
    parts = [i.name, _sets_reps(i.sets, i.reps)]
    if i.weight_kg is not None:
        parts.append(f"@{_num(i.weight_kg)}kg")
    if i.minutes is not None:
        parts.append(f"{i.minutes}분")
    if i.distance_km is not None:
        parts.append(f"{_num(i.distance_km)}km")
    return " ".join(p for p in parts if p)


def _sleep_text(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h else f"{m}분"


def _log_line(g: WorkoutLog) -> str:
    line = f"- {g.date:%m-%d} ({WEEKDAY[g.date.weekday()]}) {g.title}"
    if g.items:
        line += " — " + ", ".join(log_item_text(i) for i in g.items)
    if g.effort is not None:
        line += f" · 힘듦 {g.effort}"
    return f"{line} (#{g.id})"


def build_mate_preamble(
    *,
    now: datetime,
    tz: str | tzinfo,
    boundary: time,
    conditions: ConditionsRepo | None,
    body: BodyRepo | None,
    events: EventsRepo | None,
    workout: WorkoutRepo | None,
) -> str:
    """스펙 5.5 형식 그대로. 저장소가 없으면 그 섹션은 빈 문구다."""
    today = logical_date(now, tz, boundary)
    sections = [f"## 오늘\n{today.isoformat()} ({WEEKDAY[today.weekday()]}), 논리적 날짜"]

    cond = conditions.get(today) if conditions is not None else None
    sleep = steps = NO_RECORD
    if body is not None:
        days = body.between(today - timedelta(days=STEPS_DAYS - 1), today)
        last = next((d for d in days if d.date == today), None)
        if last is not None and last.sleep_minutes is not None:  # 그 날 아침에 끝난 밤(SP8 7.2)
            sleep = _sleep_text(last.sleep_minutes)
        counted = [d.steps for d in days if d.steps is not None]
        if counted:
            avg = (2 * sum(counted) + len(counted)) // (2 * len(counted))  # `BodyRepo.summary`와 같은 반올림
            steps = f"하루 평균 {avg:,}"
    sections.append(
        "## 오늘 몸\n"
        f"- 컨디션: {cond.score if cond is not None else NO_RECORD}\n"
        f"- 지난밤 잠: {sleep}\n"
        f"- 최근 7일 걸음: {steps}"
    )

    todays = events.on_logical_date(today, boundary)[:TODAY_EVENTS_MAX] if events is not None else []
    lines = [
        f"- {'하루 종일' if o.all_day else format(local(o.start, tz), '%H:%M')} {o.title}"  # type: ignore[arg-type]
        for o in todays
    ]
    sections.append("## 오늘 일정\n" + ("\n".join(lines) or NO_EVENTS))

    notes = workout.notes()[:BODY_NOTES_LINES] if workout is not None else []
    sections.append("## 몸 메모\n" + (
        "\n".join(f"- [{BODY_KIND_LABELS[n.kind]}] {n.text} (#{n.id})" for n in notes) or NOT_YET
    ))

    plan = workout.current_plan() if workout is not None else None
    if plan is None:
        sections.append(f"## 지금 플랜\n{NOT_YET}")
    else:
        since = logical_date(plan.created_at, tz, boundary)
        plan_lines = [f"{plan.title} (#{plan.id}, {since.isoformat()}부터)"]
        for s in plan.sessions:
            days_text = f" ({'·'.join(WEEKDAY[w] for w in s.weekdays)})" if s.weekdays else ""
            plan_lines.append(f"{s.position}. {s.label}{days_text} — " + ", ".join(plan_item_text(i) for i in s.items))
        sections.append("## 지금 플랜\n" + "\n".join(plan_lines))

    logs = workout.logs(today - timedelta(days=RECENT_LOG_DAYS - 1), today)[:RECENT_LOGS_MAX] if workout is not None else []
    sections.append(
        f"## 최근 기록 ({RECENT_LOG_DAYS}일, 최대 {RECENT_LOGS_MAX}개)\n"
        + ("\n".join(_log_line(g) for g in logs) or NOT_YET)
    )
    return "\n\n".join(sections)

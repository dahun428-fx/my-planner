"""메이트의 새 두뇌 세션 앞머리 (SP12 스펙 5.5). 모두 DB에서 읽는다(ADR 0014). 원문은 넣지 않는다.

비서 앞머리(`context.build_preamble`) 대신 이 섹션들만 받는다. 섹션마다 줄 수 상한을 둔다: 일정 8, 몸 메모 30, 최근 기록
14일·8개. 빈 섹션은 빼지 않고 빈 문구("기록 없음", "없음", "아직 없음")를 쓴다. `get_mate_context` 도구도 이 글을 준다.

운동 흔적(`workout_traces`): 메이트 대화로 남긴 운동 기록 말고, 비서 쪽에 남은 운동의 흔적(건강 영역이거나 운동 낱말이
든 습관 체크와 끝낸 할 일)이다. 메이트는 이것을 읽기만 한다(할 일·습관은 비서 몫). 최근 14일·10줄.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Literal

from my_planner.clock import local, logical_date

if TYPE_CHECKING:
    from my_planner.store.repos.body import BodyRepo
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.events import EventsRepo
    from my_planner.store.repos.habits import HabitsRepo
    from my_planner.store.repos.tasks import TasksRepo
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
TRACE_DAYS = 14  # 오늘 포함
TRACES_MAX = 10
TRACE_KIND_LABELS = {"habit": "습관 체크", "task": "할 일 끝냄"}
# 건강 영역이 아니어도 제목에 이 낱말이 있으면 운동 흔적으로 본다
WORKOUT_WORDS = (
    "운동", "헬스", "러닝", "런닝", "달리기", "조깅", "걷기", "산책", "수영", "요가", "필라테스", "스쿼트", "자전거",
    "사이클", "등산", "홈트", "스트레칭", "클라이밍", "크로스핏", "축구", "농구", "테니스", "배드민턴", "골프",
    "풋살", "줄넘기", "플랭크", "푸시업", "턱걸이", "workout", "gym", "running",
)
# 운동을 한 일이 아닌 것(산 것, 본 것, 예약·등록한 것)과 건강 영역의 운동 아닌 습관. 이 낱말이 있으면 흔적이 아니다
NOT_WORKOUT_WORDS = (
    "운동화", "경기", "중계", "관람", "예약", "등록", "신청", "수리", "환불", "구매", "주문", "결제", "보기", "알아보",
    "약", "영양제", "비타민", "물 ", "물마시", "물 마시", "수면", "잠", "병원", "진료", "치과", "검진", "체중", "식단",
)

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


@dataclass(frozen=True)
class Trace:
    """비서 쪽에 남은 운동 흔적 하나. `ref`는 `habit:<번호>` 또는 `task:<번호>`."""

    date: date
    kind: Literal["habit", "task"]
    title: str
    ref: str


def is_workout_like(title: str, area_values: tuple[str, ...]) -> bool:
    """제목에 운동 아닌 낱말이 없고, 건강 영역이거나 제목에 운동 낱말이 있다."""
    low = title.lower() + " "
    if any(w in low for w in NOT_WORKOUT_WORDS):
        return False
    return "health" in area_values or any(w in low for w in WORKOUT_WORDS)


def workout_traces(
    *,
    tasks: TasksRepo | None,
    habits: HabitsRepo | None,
    since: date,
    until: date,
    tz: str | tzinfo,
    boundary: time,
) -> list[Trace]:
    """`since..until`(논리적 날짜, 양끝 포함)의 운동 흔적, 최근 날짜부터. 같은 날은 끝낸 할 일이 먼저."""
    out: list[Trace] = []
    if habits is not None:
        for h, d in habits.checks_in(since, until):
            if is_workout_like(h.title, (h.area.value,)):
                out.append(Trace(d, "habit", h.title, f"habit:{h.id}"))
    if tasks is not None:
        for t in tasks.list(status="done", from_=since, to=until):
            if t.completed_at is None or not is_workout_like(t.title, tuple(a.value for a in t.areas)):
                continue
            out.append(Trace(logical_date(t.completed_at, tz, boundary), "task", t.title, f"task:{t.id}"))
    out.sort(key=lambda x: (x.date, x.kind == "task"), reverse=True)  # 안정 정렬: 같은 날·종류는 원래 순서
    return out


def trace_dict(x: Trace) -> dict[str, str]:
    return {"date": x.date.isoformat(), "kind": x.kind, "title": x.title, "ref": x.ref}


def build_mate_preamble(
    *,
    now: datetime,
    tz: str | tzinfo,
    boundary: time,
    conditions: ConditionsRepo | None,
    body: BodyRepo | None,
    events: EventsRepo | None,
    workout: WorkoutRepo | None,
    tasks: TasksRepo | None = None,
    habits: HabitsRepo | None = None,
) -> str:
    """스펙 5.5 형식 그대로. 저장소가 없으면 그 섹션은 빈 문구다."""
    today = logical_date(now, tz, boundary)
    sections = [f"## 오늘\n{today.isoformat()} ({WEEKDAY[today.weekday()]}) {local(now, tz):%H:%M}, 논리적 날짜"]

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

    traces = workout_traces(
        tasks=tasks, habits=habits, since=today - timedelta(days=TRACE_DAYS - 1), until=today, tz=tz, boundary=boundary,
    )[:TRACES_MAX]
    sections.append(
        f"## 비서 쪽 운동 흔적 ({TRACE_DAYS}일, 최대 {TRACES_MAX}개)\n"
        + ("\n".join(
            f"- {x.date:%m-%d} ({WEEKDAY[x.date.weekday()]}) {TRACE_KIND_LABELS[x.kind]}: {x.title} ({x.ref})"
            for x in traces
        ) or NO_EVENTS)
    )
    return "\n\n".join(sections)

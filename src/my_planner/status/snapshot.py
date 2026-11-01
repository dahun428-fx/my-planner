"""상태창 스냅샷 (SP3-4 스펙 6.3.6, 9.3). 레벨, 스탯, 디버프, 퀘스트는 저장하지 않고 매번 계산한다.

`GET /status`와 텔레그램 `/status`가 같은 함수를 쓴다. 쓰지 않는다. 로그에 제목, 메모를 남기지 않는다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from my_planner.clock import logical_date, period_of
from my_planner.domain import Area, Cadence, TaskStatus
from my_planner.status.activity import (
    WINDOW_DAYS,
    Bonus,
    activity_counts,
    area_bonus,
    area_points,
    effective_score,
    window_start,
)
from my_planner.status.xp import (
    AREA_LABELS,
    DEFAULT_RECOVERY_QUESTS,
    progress,
    title_name,
)
from my_planner.store.repos.body import BodyRepo
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.moments import MomentsRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import Task, TasksRepo
from my_planner.store.views import moment_dict

RECENT_XP = 5
MOMENTS_DAYS = 14  # `GET /status`의 `moments`: 오늘을 포함한 지난 14일(SP8 6.5)
MOMENTS_MAX = 20


def _prev_quarter(period: str) -> str:
    year, q = int(period[:4]), int(period[-1])
    return f"{year}-Q{q - 1}" if q > 1 else f"{year - 1}-Q4"


def _bonuses(status: StatusRepo, today: date, tz: str | tzinfo, boundary: time) -> dict[str, Bonus]:
    """지난 28일 활동 보너스(SP8 스펙 5장). 할 일은 `T − 28`의 하루 시작부터 넉넉히 읽고 창은 순수 함수가 거른다."""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    from_utc = datetime.combine(today - timedelta(days=WINDOW_DAYS), boundary, tzinfo=zone).astimezone(UTC)
    rows = status.activity_rows(from_utc, window_start(today), today)
    points = area_points(
        rows.tasks, rows.checks, rows.body, today, tz=tz, boundary=boundary, workout_days=rows.workout_days
    )
    counts = activity_counts(
        rows.tasks, rows.checks, rows.body, today, tz=tz, boundary=boundary, workout_days=rows.workout_days
    )
    return area_bonus(points, today, counts)


def _stats(curve: CurveRepo, today: date, bonuses: dict[str, Bonus]) -> list[dict[str, Any]]:
    """영역마다 자기 가장 최근 분기 점수(9.3). 디버프는 같은 영역의 바로 앞 분기 점수가 있고 더 높을 때만.

    보너스는 바탕(`score`) 위에 따로 얹는다(SP8 5.1): `score`의 뜻과 디버프 계산은 그대로다.
    """
    latest = curve.latest_area_scores(period_of(Cadence.quarter, today))
    out = []
    for area in Area:
        cur = latest.get(area.value)
        prev = curve.area_score(_prev_quarter(cur.period), area.value) if cur is not None else None
        debuff = cur is not None and prev is not None and cur.score < prev.score
        out.append({
            "area": area.value, "label": AREA_LABELS[area.value],
            "score": cur.score if cur else None, "period": cur.period if cur else None,
            "prev_score": prev.score if prev else None, "prev_period": prev.period if prev else None,
            "debuff": debuff,
            "recovery_quest": (
                (cur.recovery_quest or curve.area_default(area.value) or DEFAULT_RECOVERY_QUESTS[area.value])
                if debuff and cur else None
            ),
            **_bonus_fields(cur.score if cur else None, bonuses[area.value]),
        })
    return out


def _bonus_fields(base: int | None, b: Bonus) -> dict[str, Any]:
    eff = effective_score(base, b.bonus)
    return {
        "bonus": float(b.bonus),
        "effective_score": float(eff) if eff is not None else None,
        "activity": {
            "tasks": b.counts.tasks, "habit_checks": b.counts.habit_checks, "body_days": b.counts.body_days,
            "workout_days": b.counts.workout_days,
        },
    }


def _quests(
    tasks: TasksRepo, status: StatusRepo, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    period = period_of(Cadence.quarter, today)
    # `priorities.rank`를 그대로 쓴다: 열린 것만 남겨도 다시 매기지 않는다
    ranked = tasks.priority_ranks(Cadence.quarter, period)
    main = [t for _, t in ranked if t.status is TaskStatus.open]
    main_quests = []
    for rank, t in ((r, t) for r, t in ranked if t.status is TaskStatus.open):
        open_n, done_n = tasks.first_steps(t.id)
        main_quests.append({
            "task_id": t.id, "title": t.title, "rank": rank, "period": period,
            "first_steps": {"open": open_n, "done": done_n},
        })

    def daily(step: Task, parent_id: int, planned: date | None) -> dict[str, Any]:
        parent = tasks.get(parent_id)
        return {
            "task_id": step.id, "title": step.title, "parent_id": parent_id,
            "parent_title": parent.title if parent else None,
            "planned_for": planned.isoformat() if planned else None,
        }

    steps = [t for t in tasks.list(status=TaskStatus.open, from_=today, to=today) if t.parent_id is not None]
    daily_quests = []
    if steps:
        for t in steps:
            assert t.parent_id is not None
            daily_quests.append(daily(t, t.parent_id, t.planned_for))
    else:
        for t in main:
            step_id = tasks.next_undated_step(t.id)
            step = tasks.get(step_id) if step_id is not None else None
            if step is not None:
                daily_quests.append(daily(step, t.id, None))
    return main_quests, daily_quests


def status_snapshot(
    *, now: datetime, tz: str | tzinfo, boundary: time, status: StatusRepo, curve: CurveRepo, tasks: TasksRepo,
    conditions: ConditionsRepo, include_sensitive: bool = False, moments: MomentsRepo | None = None,
    body: BodyRepo | None = None,
) -> dict[str, Any]:
    today = logical_date(now, tz, boundary)
    xp_total = status.total()
    level, into, for_next = progress(xp_total)
    todays = conditions.get(today)
    main_quests, daily_quests = _quests(tasks, status, today)
    return {
        "level": level, "xp_total": xp_total, "xp_into_level": into, "xp_for_next": for_next,
        "hp": {"date": today.isoformat(), "score": todays.score if todays else None},
        "stats": _stats(curve, today, _bonuses(status, today, tz, boundary)),
        "main_quests": main_quests,
        "daily_quests": daily_quests,
        "titles": [
            {"milestone_id": t.milestone_id, "title": title_name(t.kind, t.title, t.title_label), "kind": t.kind,
             "date": t.date_text, "granted_at": t.granted_at}
            for t in status.titles(include_sensitive=include_sensitive)
        ],
        "recent_xp": [{"at": x.at, "label": x.label, "amount": x.amount} for x in status.recent(RECENT_XP)],
        **_moments(moments, today),
        "body": body.summary(today) if body is not None else None,  # 지난 7일 몸 기록(SP8 7.5). 56일에 행이 없으면 None
    }


def _moments(repo: MomentsRepo | None, today: date) -> dict[str, Any]:
    """`moments`(지난 14일, 숨기지 않은 것, 최근 날짜부터, 최대 20)와 `moments_hidden`(같은 14일의 숨긴 수, SP8 6.5)."""
    if repo is None:
        return {"moments": [], "moments_hidden": 0}
    from_ = today - timedelta(days=MOMENTS_DAYS - 1)
    shown = repo.between(from_, today, include_hidden=False)[:MOMENTS_MAX]
    return {"moments": [moment_dict(m) for m in shown], "moments_hidden": repo.hidden_count(from_, today)}

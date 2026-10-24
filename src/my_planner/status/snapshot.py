"""상태창 스냅샷 (SP3-4 스펙 6.3.6, 9.3). 레벨, 스탯, 디버프, 퀘스트는 저장하지 않고 매번 계산한다.

`GET /status`와 텔레그램 `/status`가 같은 함수를 쓴다. 쓰지 않는다. 로그에 제목, 메모를 남기지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, time, tzinfo
from typing import Any

from my_planner.clock import logical_date, period_of
from my_planner.domain import Area, Cadence, TaskStatus
from my_planner.status.xp import (
    AREA_LABELS,
    DEFAULT_RECOVERY_QUESTS,
    progress,
    title_name,
)
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import Task, TasksRepo

RECENT_XP = 5


def _prev_quarter(period: str) -> str:
    year, q = int(period[:4]), int(period[-1])
    return f"{year}-Q{q - 1}" if q > 1 else f"{year - 1}-Q4"


def _stats(curve: CurveRepo, today: date) -> list[dict[str, Any]]:
    """영역마다 자기 가장 최근 분기 점수(9.3). 디버프는 같은 영역의 바로 앞 분기 점수가 있고 더 높을 때만."""
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
        })
    return out


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
    conditions: ConditionsRepo, include_sensitive: bool = False,
) -> dict[str, Any]:
    today = logical_date(now, tz, boundary)
    xp_total = status.total()
    level, into, for_next = progress(xp_total)
    todays = conditions.get(today)
    main_quests, daily_quests = _quests(tasks, status, today)
    return {
        "level": level, "xp_total": xp_total, "xp_into_level": into, "xp_for_next": for_next,
        "hp": {"date": today.isoformat(), "score": todays.score if todays else None},
        "stats": _stats(curve, today),
        "main_quests": main_quests,
        "daily_quests": daily_quests,
        "titles": [
            {"milestone_id": t.milestone_id, "title": title_name(t.kind, t.title, t.title_label), "kind": t.kind,
             "date": t.date_text, "granted_at": t.granted_at}
            for t in status.titles(include_sensitive=include_sensitive)
        ],
        "recent_xp": [{"at": x.at, "label": x.label, "amount": x.amount} for x in status.recent(RECENT_XP)],
    }

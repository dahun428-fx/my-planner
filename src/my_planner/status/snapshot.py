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


def _stats(curve: CurveRepo) -> list[dict[str, Any]]:
    """영역마다 가장 최근 분기 점수(이번 분기에 없으면 지난 분기 값과 그 분기). 디버프는 두 분기 모두 있고 내려갔을 때만."""
    periods = curve.latest_area_periods(2)
    latest = {s.area: s for s in curve.area_scores(periods[0])} if periods else {}
    before = {s.area: s for s in curve.area_scores(periods[1])} if len(periods) > 1 else {}
    out = []
    for area in Area:
        cur, prev = latest.get(area.value), before.get(area.value)
        item: dict[str, Any] = {
            "area": area.value, "label": AREA_LABELS[area.value], "score": None, "period": None,
            "prev_score": None, "prev_period": None, "debuff": False, "recovery_quest": None,
        }
        if cur is not None:
            item.update(score=cur.score, period=cur.period)
            if prev is not None:
                item.update(prev_score=prev.score, prev_period=prev.period)
                if cur.score < prev.score:
                    item["debuff"] = True
                    item["recovery_quest"] = (
                        cur.recovery_quest or curve.area_default(area.value) or DEFAULT_RECOVERY_QUESTS[area.value]
                    )
        elif prev is not None:
            item.update(score=prev.score, period=prev.period)
        out.append(item)
    return out


def _quests(
    tasks: TasksRepo, status: StatusRepo, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main = [
        t for t in tasks.priorities(Cadence.quarter, period_of(Cadence.quarter, today)) if t.status is TaskStatus.open
    ]
    period = period_of(Cadence.quarter, today)
    main_quests = []
    for rank, t in enumerate(main, start=1):
        open_n, done_n = status.first_steps(t.id)
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
            step_id = status.next_undated_step(t.id)
            step = tasks.get(step_id) if step_id is not None else None
            if step is not None:
                daily_quests.append(daily(step, t.id, None))
    return main_quests, daily_quests


def status_snapshot(
    *, now: datetime, tz: str | tzinfo, boundary: time, status: StatusRepo, curve: CurveRepo, tasks: TasksRepo,
    conditions: ConditionsRepo, include_sensitive: bool = False,
) -> dict[str, Any]:
    today = logical_date(now, tz, boundary)
    level, into, for_next = progress(status.total())
    todays = conditions.get(today)
    main_quests, daily_quests = _quests(tasks, status, today)
    return {
        "level": level, "xp_total": status.total(), "xp_into_level": into, "xp_for_next": for_next,
        "hp": {"date": today.isoformat(), "score": todays.score if todays else None},
        "stats": _stats(curve),
        "main_quests": main_quests,
        "daily_quests": daily_quests,
        "titles": [
            {"milestone_id": t.milestone_id, "title": title_name(t.kind, t.title, t.title_label), "kind": t.kind,
             "date": t.date_text, "granted_at": t.granted_at}
            for t in status.titles(include_sensitive=include_sensitive)
        ],
        "recent_xp": [{"at": x.at, "label": x.label, "amount": x.amount} for x in status.recent(RECENT_XP)],
    }

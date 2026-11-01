"""`GET /api/v1/workout` (SP12 스펙 11.3): 지금 플랜, 최근 28일 기록, 몸 메모. 읽기 전용 연결 하나만 쓴다."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from my_planner.api.models import Workout, dump
from my_planner.clock import logical_date
from my_planner.store.repos.workout import WorkoutRepo

if TYPE_CHECKING:
    from aiohttp import web

    from my_planner.api.server import ApiDeps

LOG_DAYS = 28  # 최근 기록 창(오늘 포함)


def get_workout(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    repo = WorkoutRepo(conn, deps.clock)
    s = deps.settings
    today = logical_date(deps.clock.now(), s.timezone, s.day_boundary)
    plan = repo.current_plan()
    body = {
        "plan": None if plan is None else {
            "id": plan.id, "title": plan.title, "note": plan.note, "created_at": plan.created_at,
            "sessions": [
                {
                    "id": se.id, "position": se.position, "label": se.label,
                    "weekdays": None if se.weekdays is None else list(se.weekdays),
                    "items": [
                        {k: getattr(i, k) for k in ("name", "sets", "reps", "weight_kg", "minutes", "note")}
                        for i in se.items
                    ],
                }
                for se in plan.sessions
            ],
        },
        "logs": [
            {
                "id": lg.id, "date": lg.date.isoformat(), "title": lg.title, "session_id": lg.session_id,
                "effort": lg.effort, "note": lg.note,
                "items": [
                    {k: getattr(i, k) for k in ("name", "sets", "reps", "weight_kg", "minutes", "distance_km")}
                    for i in lg.items
                ],
            }
            for lg in repo.logs(today - timedelta(days=LOG_DAYS - 1), today)
        ],
        "notes": [
            {"id": n.id, "kind": n.kind, "text": n.text, "updated_at": n.updated_at} for n in repo.notes()
        ],
    }
    return dump(Workout, body)

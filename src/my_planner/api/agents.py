"""`GET /agents/{agent}/inbox/count`, `GET /agents/notes` (SP14 스펙 9장). 읽기 전용 연결만 쓰고 두뇌를 부르지 않는다.

관찰 문구는 응답 본문에만 있다. 로그에는 아무것도 남기지 않는다.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner.api.models import AgentNotes, ApiError, InboxCount, dump
from my_planner.api.standing import FORBIDDEN_MESSAGE, dashboard_device
from my_planner.clock import logical_date, to_iso
from my_planner.domain import INBOX_AGENTS
from my_planner.harness.inbox import INBOX_WINDOW_DAYS
from my_planner.store.repos.agents import AgentsRepo

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

NOTES_DEFAULT_DAYS = 7
NOTES_MAX_DAYS = 30


def _today(deps: ApiDeps):
    return logical_date(deps.clock.now(), deps.settings.timezone, deps.settings.day_boundary)


def get_inbox_count(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    agent = request.match_info["agent"]
    if agent not in INBOX_AGENTS:
        raise ApiError(404, "not_found", "없는 대화 상대예요.")
    since = _today(deps) - timedelta(days=INBOX_WINDOW_DAYS)
    return dump(InboxCount, {"unseen": AgentsRepo(conn, deps.clock).unseen_count(agent, since)})


def _days(request: web.Request) -> int:
    raw = request.query.get("days")
    if raw is None:
        return NOTES_DEFAULT_DAYS
    try:
        days = int(raw)
    except ValueError:
        days = 0
    if not 1 <= days <= NOTES_MAX_DAYS:
        raise ApiError(400, "invalid_request", "days는 1부터 30까지예요.")
    return days


def get_agent_notes(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    if dashboard_device(request):
        raise ApiError(403, "forbidden", FORBIDDEN_MESSAGE)
    days = _days(request)
    notes = AgentsRepo(conn, deps.clock).notes(None, _today(deps) - timedelta(days=days))
    return dump(AgentNotes, {"notes": [
        {
            "id": n.id, "agent": n.agent, "day": n.day.isoformat(), "text": n.text, "priority": n.priority,
            "shown_at": to_iso(n.shown_at) if n.shown_at else None, "created_at": to_iso(n.created_at),
        }
        for n in notes
    ]})

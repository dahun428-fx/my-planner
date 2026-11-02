"""`GET /panel/suggestions`, `GET /panel/budget`, `GET /owner-statements`, `GET /life-reports[/{id}]` (SP15 스펙 12장).

읽기 전용 연결만 쓰고 두뇌를 부르지 않는다. 대시보드 기기는 모두 `403 forbidden`이다(스펙 12장은 리포트만 적었지만
제안·내가 한 말도 같은 개인 글이다, 계획 결정). 글은 응답 본문에만 있다. 로그에는 아무것도 남기지 않는다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from aiohttp import web

from my_planner.api.models import (
    ApiError,
    LifeReportOut,
    LifeReports,
    OwnerStatements,
    PanelBudget,
    PanelSuggestions,
    dump,
)
from my_planner.api.standing import FORBIDDEN_MESSAGE, dashboard_device
from my_planner.clock import logical_date, to_iso
from my_planner.panel.budget import remaining
from my_planner.panel.report import full_diagnosis_check
from my_planner.store.repos.panel import PanelRepo
from my_planner.store.repos.state import StateRepo
from my_planner.tools.panel import suggestion_view

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

SUGGESTION_STATES = ("proposed", "accepted", "done", "postponed", "dismissed", "expired")
SUGGESTIONS_DEFAULT_DAYS = 28  # `state`가 없을 때 보이는 창(논리적 날짜)
MSG_BAD_STATE = "state가 맞지 않아요."
MSG_NO_REPORT = "없는 리포트예요."


def _personal(request: web.Request) -> None:
    if dashboard_device(request):
        raise ApiError(403, "forbidden", FORBIDDEN_MESSAGE)


def _today(deps: ApiDeps) -> date:
    return logical_date(deps.clock.now(), deps.settings.timezone, deps.settings.day_boundary)


def _day_start(deps: ApiDeps, d: date) -> datetime:
    """논리적 날짜 `d`가 시작하는 시각(현지 경계 시각)."""
    return datetime.combine(d, deps.settings.day_boundary, tzinfo=ZoneInfo(deps.settings.timezone))


def get_panel_suggestions(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    _personal(request)
    state = request.query.get("state")
    if state is not None and state not in SUGGESTION_STATES:
        raise ApiError(400, "invalid_request", MSG_BAD_STATE)
    repo = PanelRepo(conn, deps.clock)
    if state is None:
        rows = repo.suggestions(since=_day_start(deps, _today(deps) - timedelta(days=SUGGESTIONS_DEFAULT_DAYS)))
    else:
        rows = repo.suggestions(state=state)
    return dump(PanelSuggestions, {
        "items": [{**suggestion_view(conn, s), "created_at": to_iso(s.created_at)} for s in rows],
    })


def get_panel_budget(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    _personal(request)
    today = _today(deps)
    state = StateRepo(conn, deps.clock)
    left = remaining(PanelRepo(conn, deps.clock), state, today)
    ok = full_diagnosis_check(state, today, deps.settings.limits.daily_brain_calls) is None  # 디스패처와 같은 도우미
    return dump(PanelBudget, {"remaining": left, "full_diagnosis_ok": ok})


def get_owner_statements(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    _personal(request)
    rows = PanelRepo(conn, deps.clock).active_statements()
    return dump(OwnerStatements, {"items": [
        {"id": s.id, "kind": s.kind, "area": s.area, "text": s.text, "created_at": to_iso(s.created_at)}
        for s in reversed(rows)  # 저장소는 오래된 것부터
    ]})


def get_life_reports(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    _personal(request)
    rows = PanelRepo(conn, deps.clock).reports()
    return dump(LifeReports, {"items": [{"id": rid, "created_at": to_iso(at)} for rid, at in rows]})


def get_life_report(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    _personal(request)
    raw = request.match_info["id"]
    row = PanelRepo(conn, deps.clock).report(int(raw)) if raw.isascii() and raw.isdigit() and len(raw) <= 18 else None
    if row is None:
        raise ApiError(404, "not_found", MSG_NO_REPORT)
    rid, at, text = row
    return dump(LifeReportOut, {"id": rid, "created_at": to_iso(at), "report": json.loads(text)})

"""쓰기 경로 `POST /actions`(SP3-4 스펙 6.4.2), `POST /activity/{id}/undo`(6.4.3) → `Dispatcher.apply_action`
(즉시 갈래, 4.3), 그리고 활동 읽기 `GET /activity`(6.4.4, 읽기 전용 연결).

쓰기 처리기는 본문을 검증해 `ActionRequest(actor="user", channel="app")`로 넘기고, 받은 결과를 그대로 답한다.
쓰기와 중복 방지(`api_idempotency`)는 디스패처가 한 트랜잭션으로 한다. 로그에는 본문, 인자, 토큰이 없다.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aiohttp import web
from pydantic import ValidationError

from my_planner.api.models import (
    ActionApplied,
    ActionNeedsConfirm,
    ActionRejected,
    ActionRequestBody,
    ActivityResponse,
    ApiError,
    ErrorBody,
    UndoRequestBody,
    UndoResponse,
    api_time,
    dump,
    error_response,
)
from my_planner.clock import to_iso
from my_planner.store.repos.activity import ActivityRepo
from my_planner.tools.actions import ActionRequest
from my_planner.tools.activity import undoable_now

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

_RESPONSE_MODELS = {"applied": ActionApplied, "needs_confirm": ActionNeedsConfirm, "rejected": ActionRejected}
BAD_BODY = "요청 형식이 맞지 않아요."
NO_ACTIVITY = "없는 활동이에요."
ACTIVITY_DEFAULT_LIMIT, ACTIVITY_MAX_LIMIT = 50, 200
_INT = re.compile(r"^[0-9]{1,18}$")
_ISO_WITH_OFFSET = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$")


async def read_json_object(request: web.Request) -> dict[str, Any] | None:
    """본문을 JSON 객체로 읽는다. JSON이 아니거나 객체가 아니면 None."""
    try:
        raw = await request.read()
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


async def post_actions(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = ActionRequestBody.model_validate(body)
    except ValidationError:  # 무엇이 틀렸는지(요청 값)는 답에도 로그에도 넣지 않는다
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None, "안전 모드가 아니면 디스패처가 있다"
    res = deps.dispatcher.apply_action(
        ActionRequest(
            req.action, req.args, actor="user", channel="app", client_msg_id=req.client_msg_id,
            confirm_token=req.confirm_token,
        )
    )
    model = _RESPONSE_MODELS.get(res.status, ErrorBody)
    return web.json_response(dump(model, res.body), status=res.http_status)


async def post_undo(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    raw = request.match_info["id"]
    if not _INT.match(raw):  # 경로 틀은 숫자만 받는다. 너무 큰 수도 없는 활동이다
        return error_response(404, "not_found", NO_ACTIVITY)
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = UndoRequestBody.model_validate(body)
    except ValidationError:
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None, "안전 모드가 아니면 디스패처가 있다"
    res = deps.dispatcher.apply_action(
        ActionRequest(
            "undo", {"activity_id": int(raw)}, actor="user", channel="app", client_msg_id=req.client_msg_id,
            endpoint="undo",
        )
    )
    model = UndoResponse if res.status in ("undone", "already_undone") else ErrorBody
    return web.json_response(dump(model, res.body), status=res.http_status)


# --- GET /activity (6.4.4) ---


def _bad(message: str) -> ApiError:
    return ApiError(400, "invalid_request", message)


def _since(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    if not _ISO_WITH_OFFSET.match(raw):
        raise _bad("since는 시간대가 붙은 ISO 8601 시각이어야 해요.")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise _bad("since는 없는 시각이에요.") from None


def get_activity(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    q = request.query
    order = q.get("order", "asc")
    if order not in ("asc", "desc"):
        raise _bad("order는 asc 또는 desc여야 해요.")
    raw_limit = q.get("limit")
    limit = ACTIVITY_DEFAULT_LIMIT
    if raw_limit is not None:
        if not _INT.match(raw_limit) or not 1 <= int(raw_limit) <= ACTIVITY_MAX_LIMIT:
            raise _bad(f"limit은 1~{ACTIVITY_MAX_LIMIT} 사이 정수여야 해요.")
        limit = int(raw_limit)
    since = _since(q.get("since"))
    repo = ActivityRepo(conn, deps.clock)
    cursor = None
    raw_before = q.get("before")
    if raw_before is not None:
        if order != "desc":
            raise _bad("before는 order=desc에서만 쓸 수 있어요.")
        cursor = repo.get(int(raw_before)) if _INT.match(raw_before) else None
        if cursor is None:
            raise _bad("before는 앞 응답의 next_before 값이어야 해요.")
    rows, more = repo.since(since, limit, order=order, before=cursor)  # type: ignore[arg-type]
    now = deps.clock.now()
    items = [
        {
            "id": a.id, "at": to_iso(a.at), "actor": a.actor, "channel": a.channel, "kind": a.kind,
            "summary": a.summary, "risk": a.risk, "undo_id": a.id if undoable_now(a, repo, now) else None,
            "undone_at": to_iso(a.undone_at) if a.undone_at else None,
        }
        for a in rows
    ]
    latest = max((a.at for a in rows), default=since)
    return dump(ActivityResponse, {
        "items": items,
        "next_since": api_time(latest) if latest is not None else None,
        "next_before": str(rows[-1].id) if order == "desc" and more and rows else None,
    })

"""쓰기 경로 `POST /actions` (SP3-4 스펙 6.4.2) → `Dispatcher.apply_action`(즉시 갈래, 4.3).

처리기는 본문을 검증해 `ActionRequest(actor="user", channel="app")`로 넘기고, 받은 결과를 그대로 답한다.
쓰기와 중복 방지(`api_idempotency`)는 디스패처가 한 트랜잭션으로 한다. 로그에는 본문, 인자, 토큰이 없다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from aiohttp import web
from pydantic import ValidationError

from my_planner.api.models import (
    ActionApplied,
    ActionNeedsConfirm,
    ActionRejected,
    ActionRequestBody,
    ErrorBody,
    dump,
    error_response,
)
from my_planner.tools.actions import ActionRequest

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

_RESPONSE_MODELS = {"applied": ActionApplied, "needs_confirm": ActionNeedsConfirm, "rejected": ActionRejected}
BAD_BODY = "요청 형식이 맞지 않아요."


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

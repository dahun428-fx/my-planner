"""자동 복구용 경로: `POST /client-errors`(브라우저 에러 보고), `POST /internal/notify`(복구 결과 알림) (SP6 스펙 3.3, 6장).

- 둘 다 DB에 쓰지 않는다. `/client-errors`는 로그 한 줄(`client_error`)만 남기고, 에러 메시지는 받지 않는다.
- `/internal/notify`는 기존 고정 안내 길(`Dispatcher.send_notice`)로 실제 통로에 보낸다. 두뇌와 먼저 보낸 메시지 수
  (`proactive_messages`)를 건드리지 않는다. 로그에는 통로만 남기고 본문은 남기지 않는다.
- `/client-errors`의 검증 실패는 `422`(스펙 3.3), `/internal/notify`는 다른 본문처럼 `400`이다.
- role = "dev"(릴리스 흐름 스펙 5.2)는 보낼 통로가 없다: `/internal/notify`는 로그(`recovery_notice_logged`)만 남기고
  응답 모양은 그대로(`channel: telegram`, 텔레그램 자리의 로그 전송과 같다)다. 대화 기록에도 남기지 않는다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web
from pydantic import ValidationError

from my_planner.api.actions import BAD_BODY, read_json_object
from my_planner.api.models import (
    ClientErrorBody,
    RecoveryNoticeBody,
    RecoveryNoticeSent,
    dump,
    error_response,
)

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

log = logging.getLogger(__name__)

NOT_SENT = "알림을 보내지 못했어요."


async def post_client_error(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    body = await read_json_object(request)
    if body is None:
        return error_response(422, "invalid_request", BAD_BODY)
    try:
        err = ClientErrorBody.model_validate(body)
    except ValidationError:  # 어떤 값이 틀렸는지 답에도 로그에도 넣지 않는다
        return error_response(422, "invalid_request", BAD_BODY)
    # `name`은 LogRecord 예약 속성이라 extra로 못 쓴다: 에러 이름은 `error_name`으로 남긴다
    log.warning(
        "client_error",
        extra={
            "app": err.app, "version": err.version, "route": err.route, "error_name": err.name, "frames": err.frames,
        },
    )
    return web.Response(status=204)


async def post_internal_notify(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        notice = RecoveryNoticeBody.model_validate(body)
    except ValidationError:
        return error_response(400, "invalid_request", BAD_BODY)
    if deps.settings.runtime.role == "dev":
        log.info("recovery_notice_logged", extra={"role": "dev", "chars": len(notice.text)})
        return web.json_response(dump(RecoveryNoticeSent, {"channel": "telegram"}))
    assert deps.dispatcher is not None
    channel = await deps.dispatcher.send_notice(notice.text)
    if channel is None:
        return error_response(503, "unavailable", NOT_SENT)
    log.info("recovery_notice_sent", extra={"channel": channel})
    return web.json_response(dump(RecoveryNoticeSent, {"channel": channel}))

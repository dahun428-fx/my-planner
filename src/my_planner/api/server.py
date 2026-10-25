"""aiohttp 앱 조립과 수명: `build_app()`, `start_api()`, `stop_api()` (SP3-4 스펙 4.2, 6.1, 14, 15).

미들웨어(바깥 → 안): 접근 로그 → CORS(사전 요청, 오류를 JSON으로) → 본문 상한 → 인증 → 안전 모드.
- 접근 로그는 aiohttp 기본 것을 끄고(`access_log=None`) 요청마다 `method`, 경로 틀, 상태, 소요 시간만 남긴다.
  쿼리 문자열, 헤더, 본문, 토큰, 푸시 구독 주소는 남기지 않는다.
- `GET` 처리기는 요청마다 따로 연 읽기 전용 연결(`mode=ro`)만 받는다. 쓰기는 디스패처 경로뿐이다(ADR 0007).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner.api.actions import get_activity, post_actions, post_undo
from my_planner.api.auth import AuthLimiter, bearer_ok
from my_planner.api.chat import post_chat
from my_planner.api.cors import CorsPolicy, cors_middleware
from my_planner.api.health import ErrorCounter, health_view, safe_mode_view
from my_planner.api.models import ApiError, error_response
from my_planner.api.push import (
    delete_subscription,
    get_checkin_times,
    get_notify,
    get_vapid_public_key,
    post_push_test,
    post_subscription,
    put_checkin_times,
    put_notify,
)
from my_planner.api.read import (
    get_checkin,
    get_checkins,
    get_conditions,
    get_conversation_messages,
    get_conversations,
    get_curve,
    get_drafts,
    get_habit,
    get_habits,
    get_priorities,
    get_schema,
    get_status,
    get_today,
    get_ui_catalog,
    get_week,
)
from my_planner.api.recovery import post_client_error, post_internal_notify
from my_planner.probe import health_probe_fails

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.config import Settings
    from my_planner.harness.dispatcher import Dispatcher
    from my_planner.store.transcripts import TranscriptStore

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
HEALTH_PATH = f"{API_PREFIX}/health"
UNMATCHED_ROUTE = "(unmatched)"

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass
class ApiDeps:
    settings: Settings
    clock: Clock
    token: str
    read_conn: Callable[[], sqlite3.Connection] | None  # 요청마다 새 읽기 전용 연결. 안전 모드면 None
    dispatcher: Dispatcher | None  # 쓰기 경로(즉시 갈래·두뇌 갈래, 티켓 04~)
    errors: ErrorCounter
    polling_state: Callable[[], str]  # running | down | stopped
    started_at: datetime
    transcripts: TranscriptStore | None = None
    safe_mode: bool = False
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep  # `/chat`의 15초 `: ping`(시험이 바꾼다)


DEPS_KEY = web.AppKey("deps", ApiDeps)
LIMITER_KEY = web.AppKey("auth_limiter", AuthLimiter)


def route_template(request: web.Request) -> str:
    """경로 틀(`/api/v1/activity/{id}/undo`). 맞는 경로가 없으면 `(unmatched)`: 실제 경로 값은 남기지 않는다."""
    resource = request.match_info.route.resource
    return resource.canonical if resource is not None else UNMATCHED_ROUTE


@web.middleware
async def access_log(request: web.Request, handler: Handler) -> web.StreamResponse:
    started = time.monotonic()
    status = 500
    try:
        resp = await handler(request)
        status = resp.status
        return resp
    except web.HTTPException as e:
        status = e.status
        raise
    finally:
        log.info(
            "api_request",
            extra={
                "method": request.method,
                "route": route_template(request),
                "status": status,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )


def body_limit_middleware(limit_bytes: int) -> Callable[[web.Request, Handler], Awaitable[web.StreamResponse]]:
    """`Content-Length`가 상한을 넘으면 읽지 않고 `413`. 길이가 없는 본문은 `client_max_size`가 막는다."""

    @web.middleware
    async def body_limit(request: web.Request, handler: Handler) -> web.StreamResponse:
        if request.content_length is not None and request.content_length > limit_bytes:
            return error_response(413, "too_large", "요청 본문이 너무 커요.")
        return await handler(request)

    return body_limit


@web.middleware
async def auth(request: web.Request, handler: Handler) -> web.StreamResponse:
    deps = request.app[DEPS_KEY]
    limiter = request.app[LIMITER_KEY]
    if limiter.blocked():
        return error_response(429, "too_many_auth_failures", "잠시 뒤에 다시 해 주세요.")
    if not bearer_ok(request.headers.get("Authorization"), deps.token):
        if limiter.record_failure():
            log.warning("api_auth_blocked")
        log.info("api_auth_failed", extra={"route": route_template(request)})
        return error_response(401, "unauthorized", "인증이 필요해요.")  # 이유를 더 적지 않는다
    return await handler(request)


@web.middleware
async def safe_mode(request: web.Request, handler: Handler) -> web.StreamResponse:
    if request.app[DEPS_KEY].safe_mode and request.path != HEALTH_PATH:
        return error_response(503, "safe_mode", "데이터베이스 안전 모드예요. 상태 확인만 할 수 있어요.")
    return await handler(request)


def read_handler(view: Callable[[sqlite3.Connection, ApiDeps, web.Request], Any]) -> Handler:
    """`GET` 처리기: 읽기 전용 연결을 새로 열어 `view`에 넘기고, 끝나면 닫는다."""

    async def handler(request: web.Request) -> web.StreamResponse:
        deps = request.app[DEPS_KEY]
        assert deps.read_conn is not None, "안전 모드가 아니면 읽기 연결이 있다"
        conn = deps.read_conn()
        try:
            body = view(conn, deps, request)
        except ApiError as e:
            return error_response(e.status, e.code, e.message)
        finally:
            conn.close()
        return web.json_response(body)

    return handler


async def _health(request: web.Request) -> web.StreamResponse:
    deps = request.app[DEPS_KEY]
    if deps.safe_mode:
        return web.json_response(safe_mode_view(deps))
    if await asyncio.to_thread(health_probe_fails):  # git을 부르므로 루프 밖에서  # 개발용 결함 주입(SP6 스펙 12장 4행, `my_planner.probe`)
        return error_response(500, "internal", "잠시 뒤에 다시 해 주세요.")
    return await _health_read(request)


_health_read = read_handler(lambda conn, deps, _request: health_view(conn, deps))


READ_ROUTES: tuple[tuple[str, Callable[[sqlite3.Connection, ApiDeps, web.Request], Any]], ...] = (
    ("/today", get_today),
    ("/week", get_week),
    ("/conditions", get_conditions),
    ("/priorities", get_priorities),
    ("/drafts", get_drafts),
    ("/curve", get_curve),
    ("/status", get_status),
    ("/checkins", get_checkins),
    ("/checkins/{id}", get_checkin),
    ("/habits", get_habits),
    ("/habits/{id}", get_habit),
    ("/conversations", get_conversations),
    ("/conversations/{id}/messages", get_conversation_messages),
    ("/ui/catalog", get_ui_catalog),
    ("/schema", get_schema),
    ("/activity", get_activity),
    ("/push/vapid-public-key", get_vapid_public_key),
    ("/settings/notify", get_notify),
    ("/settings/checkin-times", get_checkin_times),
)


def write_handler(view: Callable[[web.Request, ApiDeps], Awaitable[web.StreamResponse]]) -> Handler:
    """쓰기 처리기: 쓰기는 디스패처(`ApiDeps.dispatcher`)로만 한다(ADR 0007). 읽기 연결은 열지 않는다."""

    async def handler(request: web.Request) -> web.StreamResponse:
        return await view(request, request.app[DEPS_KEY])

    return handler


WRITE_ROUTES: tuple[tuple[str, Callable[[web.Request, ApiDeps], Awaitable[web.StreamResponse]]], ...] = (
    ("/chat", post_chat),
    ("/actions", post_actions),
    ("/activity/{id}/undo", post_undo),
    ("/push/subscriptions", post_subscription),
    ("/push/test", post_push_test),
    ("/client-errors", post_client_error),
    ("/internal/notify", post_internal_notify),
)


def build_app(deps: ApiDeps) -> web.Application:
    cfg = deps.settings.api
    app = web.Application(
        middlewares=[
            access_log,
            cors_middleware(CorsPolicy(cfg.cors_origins)),
            body_limit_middleware(cfg.max_body_kb * 1024),
            auth,
            safe_mode,
        ],
        client_max_size=cfg.max_body_kb * 1024,
    )
    app[DEPS_KEY] = deps
    app[LIMITER_KEY] = AuthLimiter(deps.clock)
    app.router.add_get(HEALTH_PATH, _health)
    for path, view in READ_ROUTES:
        app.router.add_get(API_PREFIX + path, read_handler(view))
    for path, write in WRITE_ROUTES:
        app.router.add_post(API_PREFIX + path, write_handler(write))
    app.router.add_put(API_PREFIX + "/settings/notify", write_handler(put_notify))
    app.router.add_put(API_PREFIX + "/settings/checkin-times", write_handler(put_checkin_times))
    app.router.add_delete(API_PREFIX + "/push/subscriptions/{id}", write_handler(delete_subscription))
    return app


async def start_api(app: web.Application, host: str, port: int) -> web.AppRunner | None:
    """같은 이벤트 루프에서 연다. 포트를 못 잡으면 `api_bind_error`를 남기고 None(BE는 API 없이 계속 돈다)."""
    runner = web.AppRunner(app, access_log=None, handle_signals=False)
    await runner.setup()
    try:
        await web.TCPSite(runner, host, port).start()
    except OSError as e:
        log.error("api_bind_error", extra={"host": host, "port": port, "error_type": type(e).__name__})
        await runner.cleanup()
        return None
    log.info("api_started", extra={"host": host, "port": port})
    return runner


async def stop_api(runner: web.AppRunner | None) -> None:
    """새 요청을 받지 않고 닫는다. 열린 SSE는 `finish` 없이 끊긴다(스펙 15)."""
    if runner is None:
        return
    await runner.cleanup()
    log.info("api_stopped")

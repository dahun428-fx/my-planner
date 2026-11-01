"""aiohttp 앱 조립과 수명: `build_app()`, `start_api()`, `stop_api()` (SP3-4 스펙 4.2, 6.1, 14, 15).

미들웨어(바깥 → 안): 접근 로그 → CORS(사전 요청, 오류를 JSON으로) → 본문 상한 → 인증 → 안전 모드.
- 몸 기록 `POST /body`(SP8 7.2)는 경로 틀로 기대 토큰을 `BODY_TOKEN`으로 바꾸고(다른 경로는 `API_TOKEN`), 본문 상한
  4KB, CORS 없음이다. `BODY_TOKEN`이 없으면 이 경로를 등록하지 않는다.
- 사진 올리기 `POST /photos`(SP10 5.3)는 `Content-Length` 상한만 5.5MiB다. `client_max_size`(64KB)는 그대로라 다른
  경로는 길이 없는 본문도 64KB에서 413이고, 사진 처리기는 multipart 스트림을 세며 읽는다(`api/photos.py`).
- 접근 로그는 aiohttp 기본 것을 끄고(`access_log=None`) 요청마다 `method`, 경로 틀, 상태, 소요 시간만 남긴다.
  쿼리 문자열, 헤더, 본문, 토큰, 푸시 구독 주소는 남기지 않는다.
- `GET` 처리기는 요청마다 따로 연 읽기 전용 연결(`mode=ro`)만 받는다. 쓰기는 디스패처 경로뿐이다(ADR 0007).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner.api.actions import get_activity, post_actions, post_undo
from my_planner.api.auth import AuthLimiter, bearer_ok
from my_planner.api.body import BODY_MAX_BYTES, BODY_PATH, post_body
from my_planner.api.calendar import (
    CALENDAR_PATH,
    get_calendar_ics,
    get_calendar_settings,
    post_calendar_settings,
)
from my_planner.api.chat import (
    delete_conversation,
    post_chat,
    post_chat_stop,
    post_new_conversation,
)
from my_planner.api.cors import CorsPolicy, cors_middleware
from my_planner.api.devices import (
    DeviceTokens,
    PairCodes,
    delete_device,
    get_devices,
    get_pair_status,
    post_pair,
    post_pair_code,
    touch_device,
)
from my_planner.api.health import ErrorCounter, health_view, safe_mode_view
from my_planner.api.models import ApiError, error_response
from my_planner.api.photos import (
    PHOTO_BODY_MAX,
    PHOTOS_PATH,
    disk_free_bytes,
    get_photo,
    post_photo_read,
    post_photos,
)
from my_planner.api.push import (
    delete_subscription,
    get_checkin_times,
    get_digest_settings,
    get_notify,
    get_vapid_public_key,
    post_push_test,
    post_subscription,
    put_checkin_times,
    put_digest_settings,
    put_notify,
)
from my_planner.api.read import (
    get_checkin,
    get_checkins,
    get_conditions,
    get_conversation_messages,
    get_conversations,
    get_curve,
    get_curve_history,
    get_drafts,
    get_event,
    get_events,
    get_habit,
    get_habits,
    get_memo,
    get_memos,
    get_moments,
    get_priorities,
    get_schema,
    get_status,
    get_today,
    get_ui_catalog,
    get_week,
)
from my_planner.api.recovery import post_client_error, post_internal_notify
from my_planner.api.standing import get_standing, get_standing_measures
from my_planner.api.workout import get_workout
from my_planner.probe import health_probe_fails

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.config import Settings
    from my_planner.harness.dispatcher import Dispatcher
    from my_planner.store.transcripts import TranscriptStore

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
HEALTH_PATH = f"{API_PREFIX}/health"
PAIR_PATH = f"{API_PREFIX}/pair"  # Bearer 없이 연결 코드로 인증한다(기기 연결 스펙 4.4)
API_TOKEN_ONLY = frozenset({f"{API_PREFIX}/internal/notify"})  # 기기 토큰을 받지 않는 경로(4.4)
UNMATCHED_ROUTE = "(unmatched)"
MASKED_QUERY = "?key=***"

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
    body_token: str | None = None  # `POST /body`만 받는 토큰(SP8 7.2). None이면 그 경로를 등록하지 않는다
    devices: DeviceTokens = field(default_factory=DeviceTokens)  # 기기 토큰 사전(기기 연결 스펙 4.4). `build_app`이 채운다
    pair_codes: PairCodes = field(init=False)  # 연결 코드(4.3). 메모리에만
    # 데이터 폴더 드라이브의 남은 바이트(SP10 5.6 4번: `POST /photos` 507, `/health` `disk_low`). 시험이 바꾼다
    disk_free: Callable[[Path], int] = disk_free_bytes

    def __post_init__(self) -> None:
        self.pair_codes = PairCodes(self.clock)


DEPS_KEY = web.AppKey("deps", ApiDeps)
LIMITER_KEY = web.AppKey("auth_limiter", AuthLimiter)
DEVICE_ID_KEY = web.RequestKey("device_id", int)  # 기기 토큰으로 온 요청의 기기(4.4)


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
        extra: dict[str, Any] = {
            "method": request.method,
            "route": route_template(request),
            "status": status,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        if extra["route"] == CALENDAR_PATH and request.query_string:
            extra["query"] = MASKED_QUERY  # 키가 든 쿼리는 통째로 가린다(SP9 5.7)
        log.info("api_request", extra=extra)


def body_limit_middleware(limit_bytes: int) -> Callable[[web.Request, Handler], Awaitable[web.StreamResponse]]:
    """`Content-Length`가 상한을 넘으면 읽지 않고 `413`. 길이가 없는 본문은 `client_max_size`가 막는다.
    `POST /body`는 4KB(SP8 7.2, 길이 없는 본문은 처리기가 읽으며 막는다). `POST /photos`는 5.5MiB(SP10 5.3, 길이
    없는 본문은 처리기가 multipart를 세며 막는다)."""

    @web.middleware
    async def body_limit(request: web.Request, handler: Handler) -> web.StreamResponse:
        route = route_template(request)
        if route == PHOTOS_PATH and request.method == "POST":
            if request.content_length is not None and request.content_length > PHOTO_BODY_MAX:
                return error_response(413, "photo_too_large", "사진이 너무 커요.")
            return await handler(request)
        limit = BODY_MAX_BYTES if route == BODY_PATH else limit_bytes
        if request.content_length is not None and request.content_length > limit:
            return error_response(413, "too_large", "요청 본문이 너무 커요.")
        return await handler(request)

    return body_limit


@web.middleware
async def auth(request: web.Request, handler: Handler) -> web.StreamResponse:
    deps = request.app[DEPS_KEY]
    limiter = request.app[LIMITER_KEY]
    if limiter.blocked():
        blocked = error_response(429, "too_many_auth_failures", "잠시 뒤에 다시 해 주세요.")
        if route_template(request) == CALENDAR_PATH:
            blocked.headers["Cache-Control"] = "no-store"
        return blocked
    if route_template(request) == CALENDAR_PATH:
        return await handler(request)  # 캘린더 구독: Bearer 대신 처리기가 `?key=`를 비교한다(SP9 5.7). 위에서 429는 거른 뒤
    route = route_template(request)
    if route == PAIR_PATH and request.method == "POST":
        return await handler(request)  # 연결 코드가 인증이다(기기 연결 스펙 4.4). 틀린 코드는 처리기가 실패로 센다
    header = request.headers.get("Authorization")
    # 경로 틀로 기대 토큰을 고른다(SP8 7.2): `/body`는 `BODY_TOKEN`만, 그 밖은 `API_TOKEN`만. 다른 쪽 토큰은 맞아도 401.
    # `/body`가 등록되지 않았으면(토큰 없음) 틀이 `(unmatched)`라 `API_TOKEN`을 기대하고, 지나면 라우팅이 404다
    expected = (deps.body_token or "") if route == BODY_PATH else deps.token
    if bearer_ok(header, expected):
        return await handler(request)
    # 기기 토큰(4.4): `/body`, `/internal/notify`, 캘린더(위에서 넘김)는 받지 않는다
    device_id = None
    if route != BODY_PATH and route not in API_TOKEN_ONLY and header and header.startswith("Bearer "):
        device_id = deps.devices.lookup(header[len("Bearer "):])
    if device_id is not None:
        request[DEVICE_ID_KEY] = device_id
        resp = await handler(request)
        touch_device(deps, device_id)
        return resp
    # 안전 모드에는 기기 사전이 비어 있다: `/health`는 Bearer 형식이면 값을 보지 않고 실패로 세지 않는다(4.4)
    if deps.safe_mode and request.path == HEALTH_PATH and header and header.startswith("Bearer ") and header[7:]:
        return await handler(request)
    if limiter.record_failure():
        log.warning("api_auth_blocked")
    log.info("api_auth_failed", extra={"route": route})
    return error_response(401, "unauthorized", "인증이 필요해요.")  # 이유를 더 적지 않는다


@web.middleware
async def safe_mode(request: web.Request, handler: Handler) -> web.StreamResponse:
    if request.app[DEPS_KEY].safe_mode and request.path != HEALTH_PATH:
        unavailable = error_response(503, "safe_mode", "데이터베이스 안전 모드예요. 상태 확인만 할 수 있어요.")
        if route_template(request) == CALENDAR_PATH:
            unavailable.headers["Cache-Control"] = "no-store"
        return unavailable
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
    ("/curve/history", get_curve_history),
    ("/status", get_status),
    ("/standing", get_standing),  # SP13 12장. 대시보드 기기는 403
    ("/standing/measures", get_standing_measures),
    ("/moments", get_moments),
    ("/checkins", get_checkins),
    ("/checkins/{id}", get_checkin),
    ("/habits", get_habits),
    ("/habits/{id}", get_habit),
    ("/workout", get_workout),
    ("/events", get_events),
    ("/events/{id}", get_event),
    ("/memos", get_memos),
    ("/memos/{id}", get_memo),
    ("/conversations", get_conversations),
    ("/conversations/{id}/messages", get_conversation_messages),
    ("/ui/catalog", get_ui_catalog),
    ("/schema", get_schema),
    ("/activity", get_activity),
    ("/push/vapid-public-key", get_vapid_public_key),
    ("/settings/notify", get_notify),
    ("/settings/checkin-times", get_checkin_times),
    ("/settings/digests", get_digest_settings),
    ("/settings/calendar", get_calendar_settings),
    ("/devices", get_devices),  # 기기 연결 스펙 4.5
)


def write_handler(view: Callable[[web.Request, ApiDeps], Awaitable[web.StreamResponse]]) -> Handler:
    """쓰기 처리기: 쓰기는 디스패처(`ApiDeps.dispatcher`)로만 한다(ADR 0007). 읽기 연결은 열지 않는다."""

    async def handler(request: web.Request) -> web.StreamResponse:
        return await view(request, request.app[DEPS_KEY])

    return handler


WRITE_ROUTES: tuple[tuple[str, Callable[[web.Request, ApiDeps], Awaitable[web.StreamResponse]]], ...] = (
    ("/chat", post_chat),
    ("/chat/stop", post_chat_stop),  # 답 멈추기
    ("/conversations/new", post_new_conversation),  # SP9 7.3
    ("/actions", post_actions),
    ("/activity/{id}/undo", post_undo),
    ("/push/subscriptions", post_subscription),
    ("/push/test", post_push_test),
    ("/settings/calendar", post_calendar_settings),
    ("/client-errors", post_client_error),
    ("/internal/notify", post_internal_notify),
    ("/devices/pair", post_pair_code),  # 기기 연결 스펙 4.5
    ("/pair", post_pair),
    ("/photos", post_photos),  # SP10 5.3: multipart 스트림, 본문 상한은 `body_limit`의 경로 틀
    ("/photos/{id}/read", post_photo_read),  # SP10 5.4: 두뇌 큐에서 사진 읽기
)


def body_route_open(deps: ApiDeps) -> bool:
    """`POST /body`를 등록하나. `BODY_TOKEN`이 있고 `API_TOKEN`과 다를 때만(`app._body_token`이 먼저 거르지만 한 번 더)."""
    if not deps.body_token:
        return False
    return not hmac.compare_digest(deps.body_token.encode("utf-8"), deps.token.encode("utf-8"))


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
    app.router.add_get(CALENDAR_PATH, get_calendar_ics)
    for path, view in READ_ROUTES:
        app.router.add_get(API_PREFIX + path, read_handler(view))
    for path, write in WRITE_ROUTES:
        app.router.add_post(API_PREFIX + path, write_handler(write))
    app.router.add_put(API_PREFIX + "/settings/notify", write_handler(put_notify))
    app.router.add_put(API_PREFIX + "/settings/checkin-times", write_handler(put_checkin_times))
    app.router.add_put(API_PREFIX + "/settings/digests", write_handler(put_digest_settings))
    app.router.add_delete(API_PREFIX + "/push/subscriptions/{id}", write_handler(delete_subscription))
    app.router.add_delete(API_PREFIX + "/conversations/{id}", write_handler(delete_conversation))  # SP9 7.7
    app.router.add_get(API_PREFIX + "/devices/pair", write_handler(get_pair_status))  # 메모리만 읽는다
    # 사진 바이트(SP10 5.3): JSON이 아니라 `read_handler` 대신 처리기가 읽기 전용 연결을 열고 닫는다
    app.router.add_get(API_PREFIX + "/photos/{id}", write_handler(get_photo))
    app.router.add_delete(API_PREFIX + "/devices/{id}", write_handler(delete_device))
    if deps.read_conn is not None and not deps.safe_mode:  # 끊지 않은 기기 토큰(4.4)
        conn = deps.read_conn()
        try:
            deps.devices.load(conn)
        finally:
            conn.close()
    if body_route_open(deps):  # 아이폰 단축어(SP8 7.2). 토큰이 없으면 경로도 없다
        app.router.add_post(BODY_PATH, write_handler(post_body))
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

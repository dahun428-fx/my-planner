"""요청·응답 pydantic 모델(JSON 스키마의 정본, SP3-4 스펙 4.2, 6)과 API 경계의 공통 도구.

- 응답의 시각은 UTC ISO 8601(`2026-10-24T09:00:00Z`)이다. 저장소와 도구 결과는 오프셋 붙은 ISO(`+00:00`,
  `+09:00`)를 주므로 `to_api_times`가 경계에서 바꾼다. 날짜(`2026-10-24`)와 기간은 그대로 둔다.
- 오류 모양은 `{"error": {"code", "message"}}` 하나다(6.1).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

# 오프셋(또는 Z)이 붙은 ISO 시각만. 날짜만 있는 값과 오프셋 없는 시각은 건드리지 않는다
_OFFSET_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$")

ErrorCode = Literal[
    "invalid_request", "unauthorized", "not_found", "conflict", "superseded", "undo_expired", "too_large",
    "rejected", "not_undoable", "too_many_auth_failures", "safe_mode", "internal",
]


def api_time(dt: datetime) -> str:
    """UTC `Z` 형식. 마이크로초가 0이면 초까지만 쓴다."""
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def to_api_times(value: Any) -> Any:
    """dict·list 안의 오프셋 붙은 ISO 시각 문자열을 모두 UTC `Z`로 바꾼다(그 밖의 값은 그대로)."""
    if isinstance(value, dict):
        return {k: to_api_times(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_api_times(v) for v in value]
    if isinstance(value, datetime):
        return api_time(value)
    if isinstance(value, str) and _OFFSET_ISO.match(value):
        try:
            return api_time(datetime.fromisoformat(value))
        except ValueError:
            return value
    return value


def error_response(status: int, code: ErrorCode, message: str) -> web.Response:
    """오류 응답. `message`는 사람용 한 줄이고 토큰, 본문, 경로 값을 넣지 않는다."""
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


_HTTP_CODES: dict[int, tuple[ErrorCode, str]] = {
    400: ("invalid_request", "요청 형식이 맞지 않아요."),
    404: ("not_found", "없는 경로예요."),
    405: ("invalid_request", "이 경로에서 쓸 수 없는 메서드예요."),
    413: ("too_large", "요청 본문이 너무 커요."),
}


async def call_json(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]], request: web.Request
) -> web.StreamResponse:
    """처리기를 부르고, aiohttp 예외(없는 경로 등)와 예상 못 한 예외를 6.1 오류 모양으로 바꾼다.

    예상 못 한 예외는 로그에 종류만 남긴다(본문, 경로 값, 토큰 없이).
    """
    try:
        return await handler(request)
    except web.HTTPException as e:
        if e.status < 400:
            raise
        code, message = _HTTP_CODES.get(e.status, ("invalid_request", "요청을 처리할 수 없어요."))
        return error_response(e.status, code, message)
    except Exception as e:  # noqa: BLE001 - 무엇이든 500으로. 예외 메시지는 남기지 않는다
        log.error("api_internal_error", extra={"error_type": type(e).__name__})
        return error_response(500, "internal", "잠시 뒤에 다시 해 주세요.")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(_Model):
    code: ErrorCode
    message: str


class ErrorBody(_Model):
    error: ErrorDetail


class HealthVersion(_Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    app: str
    api: Literal["v1"]
    schema_: int | None = Field(alias="schema")  # BaseModel.schema와 겹쳐 별칭을 쓴다. 안전 모드면 None
    ui_catalog: str


class HealthBrain(_Model):
    auth: Literal["ok", "login", "billing", "unknown"]
    checked_at: str | None
    limited_until: str | None
    calls_today: int
    calls_cap: int


class HealthProactive(_Model):
    sent_today: int
    cap: int


class HealthNotify(_Model):
    primary: Literal["telegram", "app"]
    effective: Literal["telegram", "app"]


class HealthRun(_Model):
    id: int
    loop: Literal["morning_brief", "evening_checkin", "review", "return"]
    cadence: Literal["day", "week", "month", "quarter", "year"]
    scheduled_for: str
    status: str
    skip_reason: str | None
    delivered_via: list[Literal["telegram", "app"]]
    checkin_state: Literal["pending", "answered", "missed"] | None


class HealthErrors(_Model):
    window_hours: int
    since: str
    total: int
    by_event: dict[str, int]


class HealthPush(_Model):
    subscriptions: int
    last_success_at: str | None


class Health(_Model):
    """`GET /health` (6.3.1)."""

    status: Literal["ok", "degraded"]
    version: HealthVersion
    now: str
    started_at: str
    last_tick_at: str | None
    polling: Literal["running", "down", "stopped"]
    brain: HealthBrain
    proactive: HealthProactive
    paused_until: str | None
    plan_open: bool
    notify: HealthNotify
    runs_today: list[HealthRun]
    errors: HealthErrors
    push: HealthPush


class SafeModeHealth(_Model):
    """안전 모드의 `GET /health`: 상태, 판, 지금만."""

    status: Literal["safe_mode"]
    version: HealthVersion
    now: str


MODELS: dict[str, type[BaseModel]] = {
    "Error": ErrorBody,
    "Health": Health,
    "SafeModeHealth": SafeModeHealth,
}


def schema_bundle() -> dict[str, Any]:
    """모델 이름 → JSON 스키마(`GET /schema`, `python -m my_planner schema`는 티켓 02)."""
    return {name: model.model_json_schema(by_alias=True) for name, model in sorted(MODELS.items())}

"""기기 연결 코드와 기기 토큰: `/devices/*`, `POST /pair` (기기 연결 스펙 4장, ADR 0018).

- 연결 코드는 메모리에만 둔다(`PairCodes`, 살아 있는 코드 하나). 재시작하면 사라진다.
- 기기 토큰은 `POST /pair` 응답에만 한 번 나온다. DB(`devices.token_hash`)와 메모리 사전(`DeviceTokens`)에는 sha256만 둔다.
- `devices` 쓰기는 즉시 갈래 내부 동작(`device_pair`, `device_revoke`, `device_touch`)으로만 한다(ADR 0007). 사전은 동작이
  커밋된 뒤 처리기가 고친다.
- 코드와 토큰은 로그, 오류 응답, 동작 인자에 넣지 않는다.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from aiohttp import web
from pydantic import ValidationError

from my_planner.api.actions import BAD_BODY, read_json_object
from my_planner.api.models import (
    DeviceList,
    PairBody,
    PairCreated,
    PairResult,
    PairStatus,
    dump,
    error_response,
)
from my_planner.clock import Clock, logical_date, to_iso
from my_planner.store.repos.devices import DevicesRepo
from my_planner.tools.actions import ActionRequest

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

log = logging.getLogger(__name__)

PAIR_TTL = timedelta(minutes=5)
MAX_CODE_FAILURES = 5  # 한 코드로 5번 틀리면 그 코드는 사라진다(4.3)
STATUS_KEEP = timedelta(minutes=10)  # `used`·`expired`를 돌려주는 시간
BAD_CODE = "코드가 맞지 않거나 만료됐어요."
NO_DEVICE = "없는 기기예요."


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class _Code:
    code: str = field(repr=False)
    expires_at: datetime
    failures: int = 0


class PairCodes:
    """살아 있는 연결 코드 하나와 마지막 코드의 결과(4.3)."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._code: _Code | None = None
        self._result: tuple[Literal["used", "expired"], datetime, dict[str, Any] | None] | None = None

    def create(self) -> tuple[str, datetime]:
        """새 코드. 전 코드는 사라진다."""
        now = self.clock.now()
        code = f"{secrets.randbelow(10**6):06d}"
        self._code = _Code(code, now + PAIR_TTL)
        self._result = None
        return code, self._code.expires_at

    def _expire_if_due(self, now: datetime) -> None:
        if self._code is not None and now >= self._code.expires_at:
            self._result = ("expired", self._code.expires_at, None)
            self._code = None

    def status(self) -> dict[str, Any]:
        now = self.clock.now()
        self._expire_if_due(now)
        if self._code is not None:
            return {"state": "waiting"}
        if self._result is not None and now < self._result[1] + STATUS_KEEP:
            state, _at, device = self._result
            return {"state": state, "device": device} if device is not None else {"state": state}
        return {"state": "none"}

    def check(self, code: str) -> bool:
        """맞으면 True(코드는 아직 남는다: 기기를 넣은 뒤 `mark_used`). 틀리면 실패를 세고 5번이면 코드를 지운다."""
        now = self.clock.now()
        self._expire_if_due(now)
        live = self._code
        if live is None:
            return False
        if hmac.compare_digest(live.code.encode("ascii"), code.encode("ascii")):
            return True
        live.failures += 1
        if live.failures >= MAX_CODE_FAILURES:
            self._result = ("expired", now, None)
            self._code = None
        return False

    def mark_used(self, device: dict[str, Any]) -> None:
        self._result = ("used", self.clock.now(), device)
        self._code = None


class DeviceTokens:
    """끊지 않은 기기의 `token_hash → device_id`와 마지막으로 `last_used_at`을 쓴 날(4.4)."""

    def __init__(self) -> None:
        self._by_hash: dict[str, int] = {}
        self._touched: dict[int, date] = {}

    def load(self, conn: sqlite3.Connection) -> None:
        self._by_hash = {d.token_hash: d.id for d in DevicesRepo(conn).active()}

    def lookup(self, token: str) -> int | None:
        return self._by_hash.get(token_hash(token)) if token else None

    def add(self, hash_: str, device_id: int) -> None:
        self._by_hash[hash_] = device_id

    def remove(self, device_id: int) -> None:
        self._by_hash = {h: i for h, i in self._by_hash.items() if i != device_id}
        self._touched.pop(device_id, None)

    def claim_touch(self, device_id: int, today: date) -> bool:
        """오늘 처음이면 오늘로 적고 True(같은 날 다른 요청은 다시 쓰지 않는다)."""
        if self._touched.get(device_id) == today:
            return False
        self._touched[device_id] = today
        return True


def _request(action: str, args: dict[str, Any]) -> ActionRequest:
    return ActionRequest(action, args, actor="user", channel="app", endpoint="devices")


def _this_device(request: web.Request) -> int | None:
    from my_planner.api.server import DEVICE_ID_KEY

    return request.get(DEVICE_ID_KEY)


# --- 연결 코드 ---


async def post_pair_code(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    code, expires_at = deps.pair_codes.create()
    resp = web.json_response(dump(PairCreated, {"code": code, "expires_at": to_iso(expires_at)}), status=201)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def get_pair_status(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    resp = web.json_response(dump(PairStatus, deps.pair_codes.status()))
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def post_pair(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    """Bearer 없이 코드로 인증한다(`auth`가 이 경로만 넘긴다). 틀린 코드는 `AuthLimiter`에 센다."""
    from my_planner.api.server import LIMITER_KEY

    if request.content_type != "application/json":  # 사전 요청 없는 단순 요청으로 코드를 소진하지 못하게(4.5)
        return error_response(400, "invalid_request", BAD_BODY)
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = PairBody.model_validate(body)
    except ValidationError:
        return error_response(400, "invalid_request", BAD_BODY)
    if not deps.pair_codes.check(req.code):
        request.app[LIMITER_KEY].record_failure()
        return error_response(401, "bad_code", BAD_CODE)
    token = secrets.token_urlsafe(32)
    hashed = token_hash(token)
    assert deps.dispatcher is not None, "안전 모드가 아니면 디스패처가 있다"
    res = deps.dispatcher.apply_action(_request("device_pair", {
        "token_hash": hashed, "label": req.label, "client": req.client,
    }))
    if res.status != "applied":
        return error_response(400, "invalid_request", BAD_BODY)
    device_id = int(res.body["result"]["id"])
    deps.devices.add(hashed, device_id)
    deps.pair_codes.mark_used({"id": device_id, "label": req.label})
    out = {"token": token, "device": {"id": device_id, "label": req.label, "client": req.client}}
    resp = web.json_response(dump(PairResult, out), status=201)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# --- 기기 목록 ---


def get_devices(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    this = _this_device(request)
    return dump(DeviceList, {"devices": [
        {
            "id": d.id, "label": d.label, "client": d.client, "created_at": to_iso(d.created_at),
            "last_used_at": to_iso(d.last_used_at) if d.last_used_at else None, "this_device": d.id == this,
        }
        for d in DevicesRepo(conn).active()
    ]})


async def delete_device(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    raw = request.match_info["id"]
    if not raw.isdigit() or len(raw) > 18:
        return error_response(404, "not_found", NO_DEVICE)
    assert deps.dispatcher is not None
    res = deps.dispatcher.apply_action(_request("device_revoke", {"id": int(raw)}))
    if res.status != "applied":
        return error_response(404, "not_found", NO_DEVICE)
    deps.devices.remove(int(raw))
    return web.Response(status=204)


def touch_device(deps: ApiDeps, device_id: int) -> None:
    """요청이 끝난 뒤 하루 한 번 `last_used_at`(4.4). 실패해도 요청에는 영향이 없다."""
    if deps.dispatcher is None:
        return
    now = deps.clock.now()
    today = logical_date(now, deps.settings.timezone, deps.settings.day_boundary)
    if not deps.devices.claim_touch(device_id, today):
        return
    try:
        res = deps.dispatcher.apply_action(_request("device_touch", {"id": device_id}))
        if res.status != "applied":
            log.warning("device_touch_failed")
    except Exception:  # noqa: BLE001 - 사용 시각 때문에 응답이 틀어지면 안 된다(4.4)
        log.warning("device_touch_failed")

"""몸 기록 `POST /api/v1/body` (SP8 스펙 7.2, 7.3): 아이폰 단축어가 걸음 수와 잠(분)을 보낸다.

- 이 경로는 `BODY_TOKEN`만 받는다(`api/server.auth`가 경로 틀로 기대 토큰을 고른다). `BODY_TOKEN`은 다른 경로에서 `401`.
- 본문 상한 4KB(`body_limit` 미들웨어와 여기서 한 번 더), CORS 없음(`api/cors.py`가 건너뛴다), `client_msg_id` 없음.
- 쓰기는 즉시 갈래의 내부 동작 `record_body_days`(`endpoint="body"`, 계획 결정 1)로만 한다. 활동 기록·경험치는 없다.
- 로그에는 `body_received {days: n}`만 남긴다. 걸음·잠 숫자, 날짜, 토큰은 남기지 않는다.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner.api.models import BodySaved, dump, error_response
from my_planner.clock import local
from my_planner.store.repos.body import BodyDay
from my_planner.tools.actions import ActionRequest

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

log = logging.getLogger(__name__)

BODY_PATH = "/api/v1/body"
BODY_MAX_BYTES = 4096
DAYS_MAX = 7
DAYS_BACK = 13  # 한국 달력의 오늘 − 13일까지(지난 14일)
STEPS_MAX = 100_000
SLEEP_MAX = 1_440
_ITEM_KEYS = frozenset({"date", "steps", "sleep_minutes"})
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# 부록 A "몸 기록 API 오류"
MSG_KEYS = "걸음 수와 잠만 받아요."
MSG_DAYS = "지난 14일 안의 날만 받아요."
MSG_DUP = "하루를 두 번 보냈어요."
MSG_MANY = "한 번에 7일까지 보낼 수 있어요."
MSG_RANGE = "걸음 수는 0~100,000, 잠은 0~1,440분이에요."
MSG_NONE = "걸음 수나 잠 가운데 하나는 있어야 해요."
BAD_BODY = "요청 형식이 맞지 않아요."  # JSON이 아닌 본문(`/actions`와 같은 글)
TOO_LARGE = "요청 본문이 너무 커요."


def _count(v: Any, top: int) -> bool:
    """정수 0..top. `bool`(파이썬에서 `int`)과 소수(`8123.0`)는 받지 않는다(Review Focus 2)."""
    return type(v) is int and 0 <= v <= top


def _date(v: Any, today: date) -> date | None:
    if not isinstance(v, str) or not _ISO_DATE.fullmatch(v):
        return None
    try:
        d = date.fromisoformat(v)
    except ValueError:
        return None
    return d if today - timedelta(days=DAYS_BACK) <= d <= today else None


def parse_body_days(payload: Any, today: date) -> list[BodyDay] | str:
    """7.3 검증. 맞으면 `BodyDay` 목록(보내지 않은 값은 None), 하나라도 어기면 오류 문구(부록 A) 하나.

    `today`는 한국 달력의 오늘(자정 기준, 논리적 날짜가 아니다): 00:00~03:59에 보낸 오늘 날짜도 받는다.
    """
    if not isinstance(payload, dict) or set(payload) != {"days"} or not isinstance(payload["days"], list):
        return MSG_KEYS
    items = payload["days"]
    if not items:
        return MSG_NONE
    if len(items) > DAYS_MAX:
        return MSG_MANY
    out: list[BodyDay] = []
    seen: set[date] = set()
    for item in items:
        if not isinstance(item, dict) or not set(item) <= _ITEM_KEYS:
            return MSG_KEYS
        d = _date(item.get("date"), today)
        if d is None:
            return MSG_DAYS
        if d in seen:
            return MSG_DUP
        seen.add(d)
        if "steps" in item and not _count(item["steps"], STEPS_MAX):
            return MSG_RANGE
        if "sleep_minutes" in item and not _count(item["sleep_minutes"], SLEEP_MAX):
            return MSG_RANGE
        if "steps" not in item and "sleep_minutes" not in item:
            return MSG_NONE
        out.append(BodyDay(d, item.get("steps"), item.get("sleep_minutes")))
    return out


def _arg(d: BodyDay) -> dict[str, Any]:
    """즉시 갈래에 넘기는 하루: 보낸 값만."""
    out: dict[str, Any] = {"date": d.date.isoformat()}
    if d.steps is not None:
        out["steps"] = d.steps
    if d.sleep_minutes is not None:
        out["sleep_minutes"] = d.sleep_minutes
    return out


async def post_body(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    raw = await request.read()  # 64KB(`client_max_size`) 넘는 본문은 aiohttp가 먼저 413으로 막는다
    if len(raw) > BODY_MAX_BYTES:  # 길이 없는(chunked) 본문도 4KB에서 막는다
        return error_response(413, "too_large", TOO_LARGE)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return error_response(400, "invalid_request", BAD_BODY)
    today = local(deps.clock.now(), deps.settings.timezone).date()
    days = parse_body_days(payload, today)
    if isinstance(days, str):
        return error_response(400, "invalid_request", days)  # 무엇이 틀렸는지(값)는 로그에 넣지 않는다
    assert deps.dispatcher is not None, "안전 모드가 아니면 디스패처가 있다"
    res = deps.dispatcher.apply_action(
        ActionRequest(
            "record_body_days", {"days": [_arg(d) for d in days]}, actor="user", channel="app", endpoint="body",
        )
    )
    if res.status != "applied":
        return error_response(res.http_status, "invalid_request", MSG_KEYS)
    saved = int(res.body["result"]["saved"])
    log.info("body_received", extra={"days": saved})
    return web.json_response(dump(BodySaved, {"saved": saved}))

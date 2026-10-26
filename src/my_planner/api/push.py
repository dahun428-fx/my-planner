"""웹 푸시와 알림 설정: `/push/*` (SP3-4 스펙 6.4.8), `/settings/notify` (6.4.9), 체크인 시간
`/settings/checkin-times` (SP9 8장), 일정 정리 알림 `/settings/digests` (SP9b 5장).

- VAPID 값이 없으면 `/push/*`는 모두 `404`이고 실제 통로는 늘 `telegram`이다(15장). `/settings/notify`는 그대로 답한다.
- 쓰기(구독 추가·삭제, 주 통로)는 즉시 갈래 `Dispatcher.apply_action`의 내부 동작(`endpoint="push"`)으로만 한다.
  `POST /push/test`는 보내기를 `asyncio.to_thread`로 하고 결과를 즉시 갈래(`push_test_result`)로 적는다(4.3).
- 구독 `endpoint`와 키는 비밀값처럼 다룬다: 응답, 오류 문구, 로그에 넣지 않는다(14장). 검증이 틀려도 무엇이
  틀렸는지 적지 않는다.
"""

from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING, Any

from aiohttp import web
from pydantic import ValidationError

from my_planner.api.actions import (
    BAD_BODY,
    action_response,
    read_json_object,
    refresh_wake,
)
from my_planner.api.models import (
    ApiError,
    CheckinTimePutBody,
    CheckinTimes,
    CheckinTimesUpdated,
    DigestSettingPutBody,
    DigestSettings,
    DigestSettingsUpdated,
    NotifyPutBody,
    NotifySettings,
    PushSubscribeBody,
    PushSubscribed,
    PushTestResult,
    VapidPublicKey,
    dump,
    error_response,
)
from my_planner.clock import logical_date
from my_planner.harness.delivery import effective_channel
from my_planner.loop.digests import validate_digest_time
from my_planner.store.repos.push import PushRepo
from my_planner.store.repos.state import NOTIFY_PRIMARY_KEY, StateRepo
from my_planner.tools.actions import ActionRequest
from my_planner.tools.checkin_times import (
    MSG_INVALID,
    checkin_items,
    parse_loop,
    validate_checkin_time,
)
from my_planner.tools.digest_settings import ACTION as DIGEST_ACTION
from my_planner.tools.digest_settings import MSG_INVALID as MSG_DIGEST_INVALID

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

NO_ROUTE = "없는 경로예요."
NO_SUBSCRIPTION = "없는 구독이에요."
_INT = re.compile(r"^[0-9]{1,18}$")


def _push_off(deps: ApiDeps) -> web.Response | None:
    """VAPID가 없으면 푸시 경로는 없는 것과 같다(`404`)."""
    return error_response(404, "not_found", NO_ROUTE) if deps.settings.vapid is None else None


def _request(action: str, args: dict[str, Any]) -> ActionRequest:
    return ActionRequest(action, args, actor="user", channel="app", endpoint="push")


def notify_view(conn: sqlite3.Connection, deps: ApiDeps) -> dict[str, Any]:
    """`{"primary", "effective", "push_subscriptions"}`. 읽기 전용 연결 하나만 쓴다."""
    s = deps.settings
    primary = StateRepo(conn, deps.clock).get(NOTIFY_PRIMARY_KEY) or s.notify.default_primary
    count = PushRepo(conn).count_active()
    return dump(NotifySettings, {
        "primary": primary,
        "effective": effective_channel(primary, count, s.vapid is not None),
        "push_subscriptions": count,
    })


# --- 읽기 ---


def get_vapid_public_key(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    if deps.settings.vapid is None:
        raise ApiError(404, "not_found", NO_ROUTE)
    return dump(VapidPublicKey, {"public_key": deps.settings.vapid.public_key})


def get_notify(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    return notify_view(conn, deps)


# --- 쓰기 (즉시 갈래) ---


async def post_subscription(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    from my_planner.api.server import DEVICE_ID_KEY

    if (off := _push_off(deps)) is not None:
        return off
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        sub = PushSubscribeBody.model_validate(body)
    except ValidationError:  # 무엇이 틀렸는지(구독 주소 등)는 답에도 로그에도 넣지 않는다
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None
    res = deps.dispatcher.apply_action(_request("push_subscribe", {
        "endpoint": sub.endpoint, "p256dh": sub.keys.p256dh, "auth": sub.keys.auth, "label": sub.label,
        "device_id": request.get(DEVICE_ID_KEY),  # 기기 토큰으로 왔으면 그 기기(기기 연결 스펙 4.6)
    }))
    if res.status != "applied":
        return error_response(400, "invalid_request", BAD_BODY)
    return web.json_response(dump(PushSubscribed, {"id": res.body["result"]["id"]}), status=201)


async def delete_subscription(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    if (off := _push_off(deps)) is not None:
        return off
    raw = request.match_info["id"]
    if not _INT.match(raw):
        return error_response(404, "not_found", NO_SUBSCRIPTION)
    assert deps.dispatcher is not None
    res = deps.dispatcher.apply_action(_request("push_unsubscribe", {"id": int(raw)}))
    if res.status != "applied":
        return error_response(404, "not_found", NO_SUBSCRIPTION)
    return web.Response(status=204)


async def post_push_test(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    if (off := _push_off(deps)) is not None:
        return off
    assert deps.dispatcher is not None
    ok, failed = await deps.dispatcher.push_test()
    return web.json_response(dump(PushTestResult, {"ok": ok, "failed": failed}))


async def put_notify(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = NotifyPutBody.model_validate(body)
    except ValidationError:
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None and deps.read_conn is not None
    res = deps.dispatcher.apply_action(_request("notify_set", {"primary": req.primary}))
    if res.status != "applied":
        return error_response(400, "invalid_request", BAD_BODY)
    conn = deps.read_conn()
    try:
        return web.json_response(notify_view(conn, deps))
    finally:
        conn.close()


# --- 체크인 시간 (SP9 8장) ---


def checkin_times_view(conn: sqlite3.Connection, deps: ApiDeps) -> dict[str, Any]:
    s = deps.settings
    today = logical_date(deps.clock.now(), s.timezone, s.day_boundary)
    state = StateRepo(conn, deps.clock)
    return {
        "items": checkin_items(s, state.get_schedule_override(), today), "wake_updated": not state.wake_task_stale(),
    }


def get_checkin_times(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    return dump(CheckinTimes, checkin_times_view(conn, deps))


async def put_checkin_times(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    """한 칸을 바로 바꾸고(즉시 갈래 `set_checkin_time`, 되돌릴 수 있음), 깨우기 작업을 다시 등록한다(최대 20초).
    범위 밖이면 `422 checkin_time_invalid`. 깨우기 작업이 안 되면 `wake_updated: false`(바꾼 시각은 그대로 적용)."""
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = CheckinTimePutBody.model_validate(body)
    except ValidationError:
        return error_response(400, "invalid_request", BAD_BODY)
    loop = parse_loop(req.loop)
    if loop is None or validate_checkin_time(loop, req.time) is None:
        return error_response(422, "checkin_time_invalid", MSG_INVALID)
    assert deps.dispatcher is not None and deps.read_conn is not None
    res = deps.dispatcher.apply_action(ActionRequest(
        "set_checkin_time", {"loop": req.loop, "day_type": req.day_type, "time": req.time}, actor="user", channel="app",
    ))
    if res.status != "applied":  # 그대로 넘긴다(검증은 위에서 했다: 여기는 거절·충돌 같은 다른 결과)
        return action_response(res)
    await refresh_wake(deps)
    conn = deps.read_conn()
    try:
        view = checkin_times_view(conn, deps)
    finally:
        conn.close()
    return web.json_response(dump(CheckinTimesUpdated, {
        **view, "applies": res.body["result"]["applies"],
        "activity_id": res.body.get("activity_id"), "undo_id": res.body.get("undo_id"),
    }))


# --- 일정 정리 알림 (SP9b 5장) ---


def digest_settings_view(conn: sqlite3.Connection, deps: ApiDeps) -> dict[str, Any]:
    """`{"morning", "night", "wake_updated"}`. 저장한 값이 깨졌거나 없는 칸은 config 값이다(예외 없음)."""
    state = StateRepo(conn, deps.clock)
    settings = state.get_digest_settings(deps.settings.schedule.digest)
    return {
        **{k: {"on": s.on, "time": f"{s.time:%H:%M}"} for k, s in settings.items()},
        "wake_updated": not state.wake_task_stale(),
    }


def get_digest_settings(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    return dump(DigestSettings, digest_settings_view(conn, deps))


def _unknown_kind_only(e: ValidationError, body: dict[str, Any]) -> bool:
    """본문 모양은 맞고 `kind`만 모르는 글자다: 범위 밖 시각과 같은 `422`로 답한다(5장)."""
    return isinstance(body.get("kind"), str) and all(err["loc"][:1] == ("kind",) for err in e.errors())


async def put_digest_settings(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    """한 종류를 바로 바꾸고(즉시 갈래 `set_digest_settings`, 되돌릴 수 있음), 바뀌었으면 깨우기 작업을 다시 등록한다
    (최대 20초). 범위 밖, 10분 단위 아님, 모르는 종류면 `422 digest_time_invalid`. 지금과 같은 값이면 아무것도 적지
    않고 깨우기 작업도 건드리지 않는다(`applies`, `activity_id`, `undo_id`가 null)."""
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = DigestSettingPutBody.model_validate(body)
    except ValidationError as e:
        if _unknown_kind_only(e, body):
            return error_response(422, "digest_time_invalid", MSG_DIGEST_INVALID)
        return error_response(400, "invalid_request", BAD_BODY)
    if validate_digest_time(req.kind, req.time) is None:
        return error_response(422, "digest_time_invalid", MSG_DIGEST_INVALID)
    assert deps.dispatcher is not None and deps.read_conn is not None
    res = deps.dispatcher.apply_action(_request(DIGEST_ACTION, {"kind": req.kind, "on": req.on, "time": req.time}))
    if res.status != "applied":  # 그대로 넘긴다(검증은 위에서 했다: 여기는 거절·충돌 같은 다른 결과)
        return action_response(res)
    result = res.body["result"]
    changed = not result.get("unchanged")
    if changed:
        await refresh_wake(deps)
    conn = deps.read_conn()
    try:
        view = digest_settings_view(conn, deps)
    finally:
        conn.close()
    return web.json_response(dump(DigestSettingsUpdated, {
        **view, "applies": result["applies"] if changed else None,
        "activity_id": res.body.get("activity_id"), "undo_id": res.body.get("undo_id"),
    }))

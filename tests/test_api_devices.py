"""기기 연결 코드와 기기 토큰 (기기 연결 스펙 4장, ADR 0018)."""

import hashlib
import sqlite3

import jsonschema
import pytest
from aiohttp.test_utils import TestClient, TestServer
from be_env import TEST_TOKEN, BeEnv
from fakes import FakePushSender, make_settings
from test_api_logging import _raw
from test_api_push import _sub_body
from test_dispatcher_messages import kst

from my_planner.api.health import ErrorCounter
from my_planner.api.models import schema_bundle
from my_planner.api.server import LIMITER_KEY, ApiDeps, build_app
from my_planner.clock import FakeClock
from my_planner.logging_setup import setup_logging

START = kst(2026, 10, 26, 14, 0)
EP = "https://push.example.invalid/sub/device-fake-0001"


def _valid(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def _rows(env, sql, *args):
    c = sqlite3.connect(env.db_path)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as e:
        yield e


async def _code(env, token=TEST_TOKEN):
    resp = await env.post("/devices/pair", token=token)
    assert resp.status == 201
    body = await resp.json()
    _valid("PairCreated", body)
    return body["code"]


async def _pair(env, code, *, client="dashboard", label="Windows · 대시보드"):
    return await env.post("/pair", token=None, json={"code": code, "client": client, "label": label})


async def _device(env, **kw):
    resp = await _pair(env, await _code(env), **kw)
    assert resp.status == 201
    body = await resp.json()
    _valid("PairResult", body)
    return body["token"], body["device"]["id"]


def _wrong(code):
    return f"{(int(code) + 1) % 10**6:06d}"


# --- 연결 코드 ---


async def test_pair_code_six_digits_expires_after_5_minutes(env):
    code = await _code(env)
    assert len(code) == 6 and code.isdigit()
    env.clock.advance(minutes=4, seconds=59)
    assert (await env.get("/devices/pair")).status == 200
    assert (await (await env.get("/devices/pair")).json()) == {"state": "waiting"}
    env.clock.advance(seconds=1)
    resp = await _pair(env, code)
    assert resp.status == 401
    assert (await resp.json())["error"]["code"] == "bad_code"
    assert (await (await env.get("/devices/pair")).json()) == {"state": "expired"}


async def test_pair_code_single_use(env):
    code = await _code(env)
    assert (await _pair(env, code)).status == 201
    resp = await _pair(env, code)
    assert resp.status == 401 and (await resp.json())["error"]["code"] == "bad_code"


async def test_new_code_replaces_old(env):
    old = await _code(env)
    new = await _code(env)
    if old != new:
        assert (await _pair(env, old)).status == 401
    assert (await _pair(env, new)).status == 201


async def test_five_wrong_codes_kill_code(env):
    code = await _code(env)
    for _ in range(5):
        assert (await _pair(env, _wrong(code))).status == 401
    assert (await _pair(env, code)).status == 401
    assert (await (await env.get("/devices/pair")).json()) == {"state": "expired"}


async def test_pair_status_waiting_used_expired_none(env):
    assert (await (await env.get("/devices/pair")).json()) == {"state": "none"}
    code = await _code(env)
    assert (await _pair(env, code)).status == 201
    body = await (await env.get("/devices/pair")).json()
    _valid("PairStatus", body)
    assert body["state"] == "used" and body["device"]["label"] == "Windows · 대시보드"
    env.clock.advance(minutes=10)
    assert (await (await env.get("/devices/pair")).json()) == {"state": "none"}


async def test_pair_without_bearer_returns_device_token_once(env):
    code = await _code(env)
    resp = await _pair(env, code, client="app", label="iPhone · 앱")
    assert resp.status == 201
    assert resp.headers["Cache-Control"] == "no-store"
    body = await resp.json()
    token = body["token"]
    assert len(token) == 43
    assert body["device"] == {"id": body["device"]["id"], "label": "iPhone · 앱", "client": "app"}
    rows = _rows(env, "SELECT * FROM devices")
    assert len(rows) == 1
    assert rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    dump = "\n".join(str(tuple(r)) for r in _rows(env, "SELECT * FROM devices"))
    assert token not in dump


async def test_pair_rejects_non_json_content_type(env):
    code = await _code(env)
    resp = await env.post("/pair", token=None, data=f'{{"code":"{code}","client":"app","label":"x"}}',
                          headers={"Content-Type": "text/plain"})
    assert resp.status == 400
    assert (await _pair(env, code)).status == 201  # 코드는 그대로 살아 있다


@pytest.mark.parametrize("label", ["", "a\nb", "tab\there", "x" * 41, "a\x85b", "a\u2028b", "a\u202eb", "a\u2066b"])
async def test_pair_label_rejects_control_chars(env, label):
    code = await _code(env)
    assert (await _pair(env, code, label=label)).status == 400


async def test_pair_body_rejects_bad_fields(env):
    code = await _code(env)
    assert (await env.post("/pair", token=None, json={"code": code, "client": "tv", "label": "x"})).status == 400
    assert (await env.post("/pair", token=None, json={"code": "12345", "client": "app", "label": "x"})).status == 400
    assert (await env.post("/pair", token=None, json={"code": code, "client": "app", "label": "x", "y": 1})).status == 400


# --- 기기 토큰 ---


async def test_device_token_reads_today(env):
    token, _ = await _device(env)
    assert (await env.get("/today", token=token)).status == 200
    assert (await env.get("/health", token=token)).status == 200


async def test_device_token_can_make_codes(env):
    token, _ = await _device(env)
    code = await _code(env, token=token)
    assert (await _pair(env, code)).status == 201


async def test_revoked_device_token_401(env):
    token, did = await _device(env)
    assert (await env.delete(f"/devices/{did}", token=token)).status == 204
    assert (await env.get("/today", token=token)).status == 401
    assert _rows(env, "SELECT revoked_at FROM devices WHERE id = ?", did)[0]["revoked_at"] is not None


async def test_api_token_still_works(env):
    await _device(env)
    assert (await env.get("/today")).status == 200


async def test_device_token_survives_restart(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        token, _ = await _device(env)
        app = build_app(ApiDeps(  # 같은 DB로 새로 띄운 앱(재시작)
            settings=env.deps.settings, clock=env.clock, token=TEST_TOKEN, read_conn=env.deps.read_conn,
            dispatcher=env.deps.dispatcher, errors=env.deps.errors, polling_state=env.deps.polling_state,
            started_at=env.deps.started_at,
        ))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/api/v1/today", headers={"Authorization": f"Bearer {token}"})
            assert resp.status == 200
        finally:
            await client.close()


async def test_device_token_rejected_on_body_calendar_and_internal_notify(tmp_path):
    body = "body-token-" + "q" * 40
    async with BeEnv.start(tmp_path, start=START, body_token=body) as env:
        token, _ = await _device(env)
        assert (await env.post("/body", token=token, json={"days": []})).status == 401
        assert (await env.post("/internal/notify", token=token, json={})).status == 401
        assert (await env.get("/calendar.ics", token=token)).status in (401, 404)
        resp = await env.client.get(f"/api/v1/calendar.ics?key={token}")
        assert resp.status in (401, 404)


async def test_wrong_codes_count_in_auth_limiter(env):
    code = await _code(env)
    for i in range(10):
        resp = await _pair(env, _wrong(code))
        assert resp.status == 401, i
        assert (await resp.json())["error"]["code"] == "bad_code"
    resp = await _pair(env, code)
    assert resp.status == 429
    assert (await resp.json())["error"]["code"] == "too_many_auth_failures"


async def test_revoke_disables_device_push_subscriptions(tmp_path):
    async with BeEnv.start(tmp_path, start=START, push=FakePushSender()) as env:
        token, did = await _device(env, client="app", label="iPhone · 앱")
        assert (await env.post("/push/subscriptions", token=token, json=_sub_body(EP))).status == 201
        assert _rows(env, "SELECT device_id FROM push_subscriptions")[0]["device_id"] == did
        assert (await env.delete(f"/devices/{did}")).status == 204
        assert _rows(env, "SELECT disabled_at FROM push_subscriptions")[0]["disabled_at"] is not None


async def test_resubscribe_moves_device_id(tmp_path):
    async with BeEnv.start(tmp_path, start=START, push=FakePushSender()) as env:
        token, _ = await _device(env, client="app", label="iPhone · 앱")
        assert (await env.post("/push/subscriptions", token=token, json=_sub_body(EP))).status == 201
        assert (await env.post("/push/subscriptions", json=_sub_body(EP))).status == 201  # API 토큰으로 다시
        assert _rows(env, "SELECT device_id FROM push_subscriptions")[0]["device_id"] is None


async def test_delete_unknown_or_revoked_device_404(env):
    _, did = await _device(env)
    assert (await env.delete("/devices/999")).status == 404
    assert (await env.delete("/devices/abc")).status == 404
    assert (await env.delete(f"/devices/{did}")).status == 204
    assert (await env.delete(f"/devices/{did}")).status == 404


async def test_devices_list_marks_this_device_and_hides_api_token(env):
    t1, d1 = await _device(env, label="Windows · 대시보드")
    _t2, d2 = await _device(env, client="app", label="iPhone · 앱")
    body = await (await env.get("/devices", token=t1)).json()
    _valid("DeviceList", body)
    assert [(d["id"], d["this_device"]) for d in body["devices"]] == [(d1, True), (d2, False)]
    body = await (await env.get("/devices")).json()
    assert all(not d["this_device"] for d in body["devices"])
    assert len(body["devices"]) == 2


async def test_last_used_at_written_once_per_day(env):
    token, _ = await _device(env)
    assert _rows(env, "SELECT last_used_at FROM devices")[0]["last_used_at"] is None
    assert (await env.get("/today", token=token)).status == 200
    first = _rows(env, "SELECT last_used_at FROM devices")[0]["last_used_at"]
    assert first is not None
    env.clock.advance(hours=1)
    assert (await env.get("/today", token=token)).status == 200
    assert _rows(env, "SELECT last_used_at FROM devices")[0]["last_used_at"] == first
    env.clock.advance(days=1)
    assert (await env.get("/today", token=token)).status == 200
    assert _rows(env, "SELECT last_used_at FROM devices")[0]["last_used_at"] != first


# --- 안전 모드 ---


def _safe_client(tmp_path):
    clock = FakeClock(START)
    deps = ApiDeps(
        settings=make_settings(tmp_path), clock=clock, token=TEST_TOKEN, read_conn=None, dispatcher=None,
        errors=ErrorCounter(clock), polling_state=lambda: "stopped", started_at=START, safe_mode=True,
    )
    return TestClient(TestServer(build_app(deps)))


async def test_safe_mode_health_any_bearer_not_401_not_counted(tmp_path):
    client = _safe_client(tmp_path)
    await client.start_server()
    try:
        for _ in range(12):
            resp = await client.get("/api/v1/health", headers={"Authorization": "Bearer some-device-token"})
            assert resp.status == 200
        assert not client.app[LIMITER_KEY].blocked()
    finally:
        await client.close()


async def test_safe_mode_health_no_header_401(tmp_path):
    client = _safe_client(tmp_path)
    await client.start_server()
    try:
        assert (await client.get("/api/v1/health")).status == 401
        assert (await client.get("/api/v1/health", headers={"Authorization": "Bearer "})).status == 401
    finally:
        await client.close()


async def test_safe_mode_pair_503(tmp_path):
    client = _safe_client(tmp_path)
    await client.start_server()
    try:
        resp = await client.post("/api/v1/pair", json={"code": "123456", "client": "app", "label": "x"})
        assert resp.status == 503
    finally:
        await client.close()


# --- 로그 ---


async def test_code_and_token_never_logged(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        setup_logging(env.settings.paths.state_dir, 30)
        code = await _code(env)
        await _pair(env, _wrong(code))
        resp = await _pair(env, code)
        token = (await resp.json())["token"]
        assert (await env.get("/today", token=token)).status == 200
        await env.drain()
        raw = _raw(env.settings.paths.state_dir)
        assert code not in raw and _wrong(code) not in raw
        assert token not in raw
        assert hashlib.sha256(token.encode()).hexdigest() not in raw


# --- SP13-06: 기기 사전이 기기 종류도 안다(대시보드 기기 403) ---


async def test_device_tokens_know_client_after_pair_and_restart(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        _t1, dash = await _device(env, client="dashboard", label="Windows · 대시보드")
        _t2, app_id = await _device(env, client="app", label="iPhone · 앱")
        assert env.deps.devices.client(dash) == "dashboard"
        assert env.deps.devices.client(app_id) == "app"
        assert env.deps.devices.client(9999) is None
        restarted = ApiDeps(
            settings=env.deps.settings, clock=env.clock, token=TEST_TOKEN, read_conn=env.deps.read_conn,
            dispatcher=env.deps.dispatcher, errors=env.deps.errors, polling_state=env.deps.polling_state,
            started_at=env.deps.started_at,
        )
        build_app(restarted)  # `load`가 `client`를 함께 담는다
        assert restarted.devices.client(dash) == "dashboard"
        assert restarted.devices.client(app_id) == "app"
        assert (await env.delete(f"/devices/{dash}")).status == 204
        assert env.deps.devices.client(dash) is None


def test_device_tokens_add_takes_client():
    from my_planner.api.devices import DeviceTokens, token_hash

    tokens = DeviceTokens()
    tokens.add(token_hash("꾸민-토큰"), 7, "dashboard")
    assert tokens.lookup("꾸민-토큰") == 7
    assert tokens.client(7) == "dashboard"
    tokens.remove(7)
    assert tokens.lookup("꾸민-토큰") is None and tokens.client(7) is None

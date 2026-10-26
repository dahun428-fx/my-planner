"""몸 기록 `POST /api/v1/body` (SP8 스펙 7장, 1장 조건 8). 아이폰 단축어가 `BODY_TOKEN`으로 걸음과 잠을 보낸다.

`BeEnv` + 가짜 시계. 오늘은 2026-10-25(일) 13:00. 토큰과 숫자는 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import jsonschema
import pytest
from be_env import TEST_TOKEN, BeEnv
from test_dispatcher_messages import kst
from test_status_snapshot import check, habit

from my_planner.api.body import BODY_MAX_BYTES, BODY_PATH, parse_body_days
from my_planner.api.calendar import CALENDAR_PATH
from my_planner.api.models import schema_bundle
from my_planner.api.server import LIMITER_KEY
from my_planner.app import _body_token
from my_planner.store.repos.body import BodyDay, BodyRepo
from my_planner.tools.actions import ActionRequest

SUN_1300 = kst(2026, 10, 25, 13, 0)
TODAY = date(2026, 10, 25)
BODY = "body-token-" + "y" * 40  # 꾸며 낸 값(51자). API 토큰과 다르다
ORIGIN = "https://dash.example"

MSG_KEYS = "걸음 수와 잠만 받아요."
MSG_DAYS = "지난 14일 안의 날만 받아요."
MSG_DUP = "하루를 두 번 보냈어요."
MSG_MANY = "한 번에 7일까지 보낼 수 있어요."
MSG_RANGE = "걸음 수는 0~100,000, 잠은 0~1,440분이에요."
MSG_NONE = "걸음 수나 잠 가운데 하나는 있어야 해요."

EXAMPLE = {"days": [
    {"date": "2026-10-24", "steps": 8123, "sleep_minutes": 412},
    {"date": "2026-10-23", "steps": 5310},
    {"date": "2026-10-25", "sleep_minutes": 395},
]}


def _validate(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300, body_token=BODY) as e:
        yield e


async def send(env, payload, *, token=BODY, **kw):
    data = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    resp = await env.post(BODY_PATH, token=token, data=data, headers={"Content-Type": "application/json"}, **kw)
    return resp.status, await resp.json()


def rows(env):
    return [tuple(r) for r in env.conn.execute(
        "SELECT date, steps, sleep_minutes FROM body_days ORDER BY date"
    ).fetchall()]


def put(env, d, steps=None, sleep=None):
    BodyRepo(env.conn, env.clock).upsert([BodyDay(d, steps, sleep)], env.clock.now())


async def status(env):
    resp = await env.get("/status")
    body = await resp.json()
    assert resp.status == 200, body
    _validate("Status", body)
    return body


def health(body):
    return next(s for s in body["stats"] if s["area"] == "health")


# --- 저장 ---


async def test_saves_three_days_returns_saved_only(env):
    code, body = await send(env, EXAMPLE)
    assert (code, body) == (200, {"saved": 3})
    _validate("BodySaved", body)
    assert rows(env) == [("2026-10-23", 5310, None), ("2026-10-24", 8123, 412), ("2026-10-25", None, 395)]


def _day(n=0, **kw):
    return {"date": (TODAY - timedelta(days=n)).isoformat(), **kw}


@pytest.mark.parametrize(("payload", "message"), [
    pytest.param({"days": [_day(steps=1)], "note": "x"}, MSG_KEYS, id="unknown-top-key"),
    pytest.param({"day": [_day(steps=1)]}, MSG_KEYS, id="no-days"),
    pytest.param({"days": "x"}, MSG_KEYS, id="days-not-list"),
    pytest.param([_day(steps=1)], MSG_KEYS, id="not-object"),
    pytest.param({"days": [_day(steps=1, heart=60)]}, MSG_KEYS, id="unknown-item-key"),
    pytest.param({"days": ["2026-10-25"]}, MSG_KEYS, id="item-not-object"),
    pytest.param({"days": []}, MSG_NONE, id="zero-days"),
    pytest.param({"days": [_day(n, steps=1) for n in range(8)]}, MSG_MANY, id="eight-days"),
    pytest.param({"days": [_day(1, steps=1), _day(1, sleep_minutes=1)]}, MSG_DUP, id="duplicate-date"),
    pytest.param({"days": [{"date": "2026-10-26", "steps": 1}]}, MSG_DAYS, id="future"),
    pytest.param({"days": [_day(14, steps=1)]}, MSG_DAYS, id="older-than-14"),
    pytest.param({"days": [{"date": "2026-10-5", "steps": 1}]}, MSG_DAYS, id="bad-date-format"),
    pytest.param({"days": [{"date": "2026-02-30", "steps": 1}]}, MSG_DAYS, id="impossible-date"),
    pytest.param({"days": [{"steps": 1}]}, MSG_DAYS, id="no-date"),
    pytest.param({"days": [_day(steps=-1)]}, MSG_RANGE, id="steps-negative"),
    pytest.param({"days": [_day(steps=100_001)]}, MSG_RANGE, id="steps-over"),
    pytest.param({"days": [_day(sleep_minutes=1441)]}, MSG_RANGE, id="sleep-over"),
    pytest.param({"days": [_day(steps="8123")]}, MSG_RANGE, id="steps-string"),
    pytest.param({"days": [_day(steps=None)]}, MSG_RANGE, id="steps-null"),
    pytest.param({"days": [_day(steps=5000, sleep_minutes=None)]}, MSG_RANGE, id="sleep-null"),
    pytest.param({"days": [_day()]}, MSG_NONE, id="neither"),
    pytest.param({"days": [_day(1, steps=7000), _day(steps=-5)]}, MSG_RANGE, id="one-bad-writes-nothing"),
])
async def test_validation(env, payload, message):
    code, body = await send(env, payload)
    assert (code, body) == (400, {"error": {"code": "invalid_request", "message": message}})
    assert rows(env) == []


@pytest.mark.parametrize("value", [True, False, 8123.0, 8123.5, 1e3])
async def test_body_rejects_bool_and_float_values(env, value):
    """Review Focus 2: 단축어 합계가 `8123.0`·`true`로 와도 걸음 1이나 8123으로 저장하지 않는다."""
    for key in ("steps", "sleep_minutes"):
        code, body = await send(env, {"days": [_day(**{key: value})]})
        assert (code, body["error"]["message"]) == (400, MSG_RANGE)
    assert rows(env) == []


def test_parse_body_days_edges():
    assert parse_body_days({"days": [_day(13, steps=0), _day(sleep_minutes=1440)]}, TODAY) == [
        BodyDay(TODAY - timedelta(days=13), 0, None), BodyDay(TODAY, None, 1440),
    ]
    assert parse_body_days({"days": [_day(steps=100_000)]}, TODAY) == [BodyDay(TODAY, 100_000, None)]
    assert len(parse_body_days({"days": [_day(n, steps=1) for n in range(7)]}, TODAY)) == 7


async def test_not_json_400(env):
    code, body = await send(env, "{not json")
    assert code == 400 and body["error"]["code"] == "invalid_request"
    assert rows(env) == []


async def test_today_calendar_date_accepted_at_0230(tmp_path):
    """10/26 02:30(한국): 아이폰의 오늘 10/26을 받는다. 보너스 셈에서는 논리적 오늘이 10/25라 `d = −1`로 빠지고,
    04:00 뒤 `d = 0`으로 들어간다."""
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 2, 30), body_token=BODY) as env:
        code, body = await send(env, {"days": [{"date": "2026-10-26", "steps": 8000}]})
        assert (code, body) == (200, {"saved": 1})
        assert rows(env) == [("2026-10-26", 8000, None)]
        h = health(await status(env))
        assert (h["activity"]["body_days"], h["bonus"]) == (0, 0.0)
        env.clock.set(kst(2026, 10, 26, 4, 0))
        h = health(await status(env))
        assert (h["activity"]["body_days"], h["bonus"]) == (1, 0.1)  # S = 0.5


async def test_overwrite_only_sent_values(env):
    assert (await send(env, {"days": [_day(1, steps=7000, sleep_minutes=400)]}))[0] == 200
    assert (await send(env, {"days": [_day(1, sleep_minutes=430)]}))[0] == 200
    assert rows(env) == [("2026-10-24", 7000, 430)]
    assert (await send(env, {"days": [_day(1, steps=9000)]}))[0] == 200
    assert rows(env) == [("2026-10-24", 9000, 430)]


# --- 토큰 (7.2) ---


async def test_api_token_on_body_401(env):
    code, body = await send(env, EXAMPLE, token=TEST_TOKEN)
    assert (code, body["error"]["code"]) == (401, "unauthorized")
    assert (await send(env, EXAMPLE, token=None))[0] == 401
    assert rows(env) == []


# Bearer 검사를 건너뛰는 경로(이름으로 적는다). 이 경로도 `BODY_TOKEN`으로는 열리지 않는지 따로 본다
PUBLIC_ROUTES = {("GET", CALENDAR_PATH)}  # 캘린더 구독: 처리기가 `?key=`를 비교한다(SP9 5.7)


async def test_body_token_401_on_every_other_route(env):
    """실제 라우터의 모든 경로(`/body` 빼고, `{id}`는 숫자로)에 `BODY_TOKEN`을 보내면 401. 새 경로가 생겨도 이 시험이 본다."""
    routes = sorted({
        (r.method, r.resource.canonical) for r in env.client.app.router.routes()
        if r.resource is not None and r.method != "HEAD"  # HEAD는 aiohttp가 GET마다 더한 것(같은 처리기)
    })
    assert ("POST", BODY_PATH) in routes and PUBLIC_ROUTES <= set(routes) and len(routes) > 20
    # `POST /pair`는 Bearer 없이 연결 코드로 인증한다(기기 연결 스펙 4.4): `test_api_devices.py`가 본다
    skip = {("POST", BODY_PATH), ("POST", "/api/v1/pair")}
    for method, path in [*(x for x in routes if x not in skip), ("GET", "/api/v1/nope")]:
        url = path.replace("{id}", "1")
        resp = await env.request(method, url, token=BODY, json={})
        assert resp.status == 401, (method, path)
        assert (await resp.json())["error"]["code"] == "unauthorized", (method, path)
        if (method, path) in PUBLIC_ROUTES:  # 쿼리 자리에 넣어도 안 된다
            resp = await env.request(method, f"{url}?key={BODY}", token=None)
            assert resp.status == 401, (method, path)
        env.client.app[LIMITER_KEY]._failures.clear()  # 실패 세기에 막히지 않게(세기는 다른 시험이 본다)


async def test_actions_record_body_days_rejected_400(env):
    code, body = await env.action("record_body_days", {"days": [_day(steps=7000)]})
    assert (code, body["error"]["code"]) == (400, "invalid_request")
    # 즉시 갈래에서도 `/body` 경로의 요청이 아니면 거절한다(`_callable_from`)
    for endpoint in ("actions", "chat", "push", "undo"):
        res = env.parts.dispatcher.apply_action(ActionRequest(
            "record_body_days", {"days": [_day(steps=7000)]}, actor="user", channel="app", endpoint=endpoint,
        ))
        assert res.http_status == 400
    res = env.parts.dispatcher.apply_action(ActionRequest(
        "record_body_days", {"days": [_day(steps=7000)]}, actor="secretary", channel="scheduler",
    ))
    assert res.http_status == 400
    assert rows(env) == []


@pytest.mark.parametrize(("value", "reason"), [
    pytest.param("", "missing", id="missing"),
    pytest.param("short-body-token", "too_short", id="too_short"),
    pytest.param(TEST_TOKEN, "same_as_api", id="same_as_api"),
])
async def test_route_closed_when_token_missing_short_or_same(tmp_path, caplog, value, reason):
    caplog.set_level(logging.WARNING, logger="my_planner.app")
    async with BeEnv.start(tmp_path, start=SUN_1300, body_token=value) as env:
        assert env.deps.body_token is None
        resp = await env.post(BODY_PATH, token=TEST_TOKEN, json=EXAMPLE)  # 경로가 없다: 인증 뒤 라우팅이 404
        assert resp.status == 404
        resp = await env.post(BODY_PATH, token=value or BODY, json=EXAMPLE)
        assert resp.status == (404 if value == TEST_TOKEN else 401)
        assert (await env.get("/status")).status == 200  # 다른 경로는 그대로
        assert rows(env) == []
    warnings = [r for r in caplog.records if r.getMessage() == "body_token_missing"]
    assert len(warnings) == 1 and warnings[0].reason == reason
    assert all(value not in str(r.__dict__) for r in caplog.records if value)


async def test_build_app_never_opens_body_with_api_token(env):
    """`app._body_token`을 거치지 않은 `ApiDeps`라도 `BODY_TOKEN == API_TOKEN`이면 경로를 등록하지 않는다."""
    import dataclasses

    from my_planner.api.server import build_app

    def paths(deps):
        return {r.resource.canonical for r in build_app(deps).router.routes() if r.resource is not None}

    assert BODY_PATH in paths(env.deps)
    assert BODY_PATH not in paths(dataclasses.replace(env.deps, body_token=TEST_TOKEN))
    assert BODY_PATH not in paths(dataclasses.replace(env.deps, body_token=""))


def test_body_token_rules(make_settings_with):
    assert _body_token(make_settings_with(BODY), TEST_TOKEN) == BODY
    assert _body_token(make_settings_with(None), TEST_TOKEN) is None
    assert _body_token(make_settings_with("x" * 42), TEST_TOKEN) is None
    assert _body_token(make_settings_with("x" * 43), TEST_TOKEN) == "x" * 43


@pytest.fixture
def make_settings_with(tmp_path):
    from fakes import make_settings

    def build(value):
        return make_settings(tmp_path, api_token=TEST_TOKEN, **({"body_token": value} if value is not None else {}))

    return build


# --- 본문 상한, CORS, 실패 세기 ---


async def test_over_4kb_413_other_routes_keep_limit(env):
    big = json.dumps({"days": [_day(steps=1)], "pad": "x" * BODY_MAX_BYTES})
    resp = await env.post(BODY_PATH, token=BODY, data=big, headers={"Content-Type": "application/json"})
    assert resp.status == 413
    assert (await resp.json())["error"]["code"] == "too_large"

    async def chunks():  # 길이 없는 본문도 처리기가 4KB에서 막는다
        for _ in range(5):
            yield b" " * 1024

    resp = await env.post(BODY_PATH, token=BODY, data=chunks(), headers={"Content-Type": "application/json"})
    assert resp.status == 413
    ten_kb = json.dumps({"action": "add_task", "args": {"title": "꾸민 일 " + "가" * 3000}, "client_msg_id": "cm-big"})
    assert len(ten_kb.encode()) > 9 * 1024
    resp = await env.post("/actions", data=ten_kb, headers={"Content-Type": "application/json"})
    assert resp.status != 413
    assert rows(env) == []


async def test_no_cors_headers_and_no_preflight(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300, body_token=BODY,
                           overrides={"api": {"cors_origins": [ORIGIN]}}) as env:
        h = {"Origin": ORIGIN}
        resp = await env.post(BODY_PATH, token=BODY, json=EXAMPLE, headers=h)
        assert resp.status == 200
        assert "Access-Control-Allow-Origin" not in resp.headers
        pre = {**h, "Access-Control-Request-Method": "POST", "Access-Control-Request-Private-Network": "true"}
        for token in (None, BODY):
            resp = await env.request("OPTIONS", BODY_PATH, token=token, headers=pre)
            assert resp.status != 204
            assert not any(k.lower().startswith("access-control-") for k in resp.headers)
        # 다른 경로의 CORS는 그대로다
        resp = await env.request("OPTIONS", "/status", token=None, headers={**pre, "Access-Control-Request-Method": "GET"})
        assert resp.status == 204 and resp.headers["Access-Control-Allow-Origin"] == ORIGIN
        resp = await env.get("/status", headers=h)
        assert resp.headers["Access-Control-Allow-Origin"] == ORIGIN


async def test_auth_failures_shared_limit(env):
    for _ in range(5):
        assert (await send(env, EXAMPLE, token="nope"))[0] == 401
    for _ in range(4):
        assert (await env.get("/status", token=BODY)).status == 401
    assert (await send(env, EXAMPLE, token=TEST_TOKEN))[0] == 401  # 10번째
    assert (await send(env, EXAMPLE))[0] == 429
    assert (await env.get("/status")).status == 429
    env.clock.advance(timedelta(seconds=61))
    assert (await send(env, EXAMPLE))[0] == 200


# --- 보관, 보너스, 상태창 ---


async def test_prune_56_days(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300, body_token=BODY) as env:
        env.parts.runner.checkins = False
        today = date(2026, 10, 26)
        put(env, today - timedelta(days=57), steps=1)
        put(env, today - timedelta(days=56), steps=2)
        put(env, today - timedelta(days=1), steps=3)
        env.clock.set(kst(2026, 10, 26, 4, 1))
        await env.tick()
        assert rows(env) == [("2026-08-31", 2, None), ("2026-10-25", 3, None)]
        res = env.parts.dispatcher.apply_action(
            ActionRequest("prune_records", {}, actor="secretary", channel="scheduler")
        )
        assert res.body["result"]["body_days_pruned"] == 0


async def test_health_bonus_from_body(env):
    """5.4 예 2′: 건강 습관 28일 + 걸음 ≥ 6,000 28일 → S = 14.5 → 상한 2.0. 바탕 4 → 6.0."""
    from curve_sql import area_scores

    area_scores(env.conn, "2026-Q4", health=4)
    hid = habit(env.conn, "health")
    for d in range(28):
        check(env.conn, hid, TODAY - timedelta(days=d))
        put(env, TODAY - timedelta(days=d), steps=6000 + d, sleep=400)
    put(env, TODAY - timedelta(days=28), steps=9000)  # 창 밖
    h = health(await status(env))
    assert {k: h[k] for k in ("score", "bonus", "effective_score", "activity")} == {
        "score": 4, "bonus": 2.0, "effective_score": 6.0,
        "activity": {"tasks": 0, "habit_checks": 28, "body_days": 28},
    }
    others = [s for s in (await status(env))["stats"] if s["area"] != "health"]
    assert all(s["activity"]["body_days"] == 0 for s in others)


async def test_health_bonus_below_thresholds_counts_nothing(env):
    put(env, TODAY, steps=5999, sleep=419)
    h = health(await status(env))
    assert (h["bonus"], h["activity"]["body_days"]) == (0.0, 0)
    put(env, TODAY, sleep=420)
    h = health(await status(env))
    assert (h["bonus"], h["activity"]["body_days"]) == (0.1, 1)


async def test_status_body_summary_and_null(env):
    assert (await status(env))["body"] is None
    put(env, TODAY - timedelta(days=56), steps=9999)  # 56일 밖
    assert (await status(env))["body"] is None
    put(env, TODAY - timedelta(days=30), steps=9999, sleep=999)  # 56일 안, 7일 밖
    assert (await status(env))["body"] == {
        "last_date": "2026-09-25", "days_7": 0, "steps_avg_7": None, "sleep_avg_7": None,
    }
    put(env, TODAY - timedelta(days=1), steps=8000, sleep=400)
    put(env, TODAY - timedelta(days=2), steps=5600)
    put(env, TODAY - timedelta(days=6), sleep=420)
    put(env, TODAY - timedelta(days=7), steps=1, sleep=1)  # 7일 밖
    body = await status(env)
    assert body["body"] == {"last_date": "2026-10-24", "days_7": 3, "steps_avg_7": 6800, "sleep_avg_7": 410}
    # 두뇌 `get_status`도 같은 `body`를 받는다
    from my_planner.domain import RunContext

    brain = env.parts.tools.get_status(RunContext(None, None, channel="app"))
    assert brain["body"] == body["body"]


def test_summary_rounds_half_up(conn):
    from my_planner.clock import FakeClock

    repo = BodyRepo(conn, FakeClock(SUN_1300))
    repo.upsert([BodyDay(TODAY, 6001, 401), BodyDay(TODAY - timedelta(days=1), 6000, 400)], SUN_1300)
    assert repo.summary(TODAY) == {"last_date": "2026-10-25", "days_7": 2, "steps_avg_7": 6001, "sleep_avg_7": 401}
    assert repo.between(TODAY - timedelta(days=1), TODAY - timedelta(days=1)) == [
        BodyDay(TODAY - timedelta(days=1), 6000, 400)
    ]


async def test_no_activity_no_xp_for_body(env):
    xp_before = env.conn.execute("SELECT COUNT(*) FROM status_xp_ledger").fetchone()[0]
    act_before = env.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0]
    assert (await send(env, EXAMPLE))[0] == 200
    assert env.conn.execute("SELECT COUNT(*) FROM status_xp_ledger").fetchone()[0] == xp_before
    assert env.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == act_before
    assert env.conn.execute("SELECT COUNT(*) FROM api_idempotency").fetchone()[0] == 0
    assert env.conn.execute("SELECT COUNT(*) FROM tool_events_log").fetchone()[0] == 0

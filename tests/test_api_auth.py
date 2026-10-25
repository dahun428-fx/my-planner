"""API 인증 (SP3-4 스펙 6.1, 14): Bearer 헤더만, 상수 시간 비교, 1분 실패 10회면 1분 동안 429."""

from datetime import timedelta

import pytest
from be_env import TEST_TOKEN, BeEnv
from test_dispatcher_messages import kst

from my_planner.api.auth import AuthLimiter, bearer_ok
from my_planner.clock import FakeClock

START = kst(2026, 10, 24, 13, 0)


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as e:
        yield e


def test_bearer_ok():
    assert bearer_ok(f"Bearer {TEST_TOKEN}", TEST_TOKEN)
    assert not bearer_ok(None, TEST_TOKEN)
    assert not bearer_ok(TEST_TOKEN, TEST_TOKEN)  # 방식 이름이 없다
    assert not bearer_ok(f"bearer {TEST_TOKEN}", TEST_TOKEN)
    assert not bearer_ok(f"Bearer {TEST_TOKEN}x", TEST_TOKEN)
    assert not bearer_ok("Bearer ", "")  # 빈 토큰은 언제나 거절
    assert not bearer_ok("Bearer 한글", TEST_TOKEN)


async def test_no_token_401(env):
    resp = await env.get("/health", token=None)
    assert resp.status == 401
    assert await resp.json() == {"error": {"code": "unauthorized", "message": "인증이 필요해요."}}


async def test_wrong_token_401_body_has_no_reason(env):
    resp = await env.get("/health", token="WRONG-" + TEST_TOKEN)
    body = await resp.text()
    assert resp.status == 401
    assert "WRONG" not in body and TEST_TOKEN not in body
    assert (await resp.json())["error"]["code"] == "unauthorized"


async def test_right_token_200(env):
    resp = await env.get("/health")
    assert resp.status == 200
    assert resp.content_type == "application/json"


async def test_unknown_path_401_without_token_404_json_with(env):
    assert (await env.get("/nope", token=None)).status == 401  # 경로가 있는지도 알려 주지 않는다
    resp = await env.get("/nope")
    assert resp.status == 404
    assert (await resp.json())["error"]["code"] == "not_found"


async def test_token_in_query_or_cookie_not_accepted(env):
    assert (await env.get(f"/health?token={TEST_TOKEN}", token=None)).status == 401
    assert (await env.get(f"/health?access_token={TEST_TOKEN}", token=None)).status == 401
    resp = await env.get("/health", token=None, headers={"Cookie": f"token={TEST_TOKEN}; api_token={TEST_TOKEN}"})
    assert resp.status == 401


async def test_ten_failures_then_429_for_a_minute(env):
    for _ in range(10):
        assert (await env.get("/health", token="nope")).status == 401
    resp = await env.get("/health")  # 맞는 토큰도 1분 동안 거절
    assert resp.status == 429
    assert (await resp.json())["error"]["code"] == "too_many_auth_failures"
    env.clock.advance(timedelta(seconds=59))
    assert (await env.get("/health")).status == 429
    env.clock.advance(timedelta(seconds=2))
    assert (await env.get("/health")).status == 200


def test_limiter_window_slides():
    clock = FakeClock(START)
    lim = AuthLimiter(clock)
    for _ in range(9):
        lim.record_failure()
    clock.advance(timedelta(seconds=61))  # 앞의 9회는 창 밖으로 나갔다
    assert not lim.record_failure()
    assert not lim.blocked()


async def test_options_preflight_without_token(env):
    resp = await env.request(
        "OPTIONS", "/health", token=None,
        headers={"Origin": "https://dash.example", "Access-Control-Request-Method": "GET"},
    )
    assert resp.status == 204


# --- SP8 7.2: 경로 틀로 기대 토큰을 고른다(`BODY_TOKEN`은 `/body`만) ---

BODY = "body-token-" + "q" * 40  # 꾸며 낸 값(51자)


async def test_body_token_rejected_on_every_other_route(tmp_path):
    """등록된 모든 경로(틀의 `{id}`는 숫자로)에 `BODY_TOKEN`을 보내면 401. `/body`에 `API_TOKEN`도 401."""
    from my_planner.api.body import BODY_PATH
    from my_planner.api.server import LIMITER_KEY

    async with BeEnv.start(tmp_path, start=START, body_token=BODY) as env:
        routes = sorted({
            (r.method, r.resource.canonical) for r in env.client.app.router.routes()
            if r.resource is not None and r.method != "HEAD"
        })
        assert ("POST", BODY_PATH) in routes and len(routes) > 20
        for method, path in routes:
            url = path.replace("{id}", "1")
            resp = await env.request(method, url, token=BODY if path != BODY_PATH else TEST_TOKEN, json={})
            assert resp.status == 401, (method, path)
            env.client.app[LIMITER_KEY]._failures.clear()  # 실패 세기에 막히지 않게(세기는 다른 시험이 본다)
        resp = await env.request("POST", BODY_PATH, token=BODY, json={"days": [{"date": "2026-10-24", "steps": 1}]})
        assert resp.status == 200


# --- SP9 5.7: 캘린더 구독 경로만 Bearer 없이 `?key=`로 열린다 ---

ICS = "/api/v1/calendar.ics"


async def _calendar_key(env) -> str:
    return (await (await env.post("/settings/calendar", json={"rotate": False})).json())["url"].split("key=")[1]


async def test_api_token_not_needed_for_ics(env):
    key = await _calendar_key(env)
    assert (await env.get(f"{ICS}?key={key}", token=None)).status == 200
    # 키 없이 API 토큰만으로는 안 된다(토큰이 키 자리를 대신하지 않는다)
    assert (await env.get(ICS)).status == 401
    assert (await env.get(f"{ICS}?key={TEST_TOKEN}")).status == 401


async def test_wrong_key_401_counts_limiter(env):
    await _calendar_key(env)
    for _ in range(9):
        resp = await env.get(f"{ICS}?key=wrong", token=None)
        assert resp.status == 401
        assert resp.headers["Cache-Control"] == "no-store"
        assert (await resp.json())["error"]["code"] == "unauthorized"
    assert (await env.get(f"{ICS}", token=None)).status == 401  # 키 없음도 센다: 10번째
    # 10번 채웠으니 1분 동안 모든 요청이 429(맞는 API 토큰도)
    assert (await env.get("/health")).status == 429
    assert (await env.get(f"{ICS}?key=wrong", token=None)).status == 429
    env.clock.advance(timedelta(seconds=61))
    assert (await env.get("/health")).status == 200


async def test_no_key_set_yet_401(env):
    assert (await env.get(f"{ICS}?key=", token=None)).status == 401
    assert (await env.get(f"{ICS}?key=anything", token=None)).status == 401


async def test_calendar_key_not_accepted_elsewhere(env):
    key = await _calendar_key(env)
    for path in ("/health", "/today", "/events?start=2026-10-24&end=2026-10-25", "/settings/calendar"):
        assert (await env.get(path, token=key)).status == 401  # Bearer 자리
        sep = "&" if "?" in path else "?"
        assert (await env.get(f"{path}{sep}key={key}", token=None)).status == 401  # 쿼리 자리
    assert (await env.post("/settings/calendar", token=key, json={"rotate": True})).status == 401

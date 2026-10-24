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

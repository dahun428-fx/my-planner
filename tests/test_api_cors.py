"""API CORS (SP3-4 스펙 14, S9): 정확한 허용 목록 + 선택 정규식, 사전 요청, 사설망 접근, 노출 헤더."""

import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.api.cors import CorsPolicy
from my_planner.config import ApiConfig

START = kst(2026, 10, 24, 13, 0)
DASH = "https://my-planner-dash.vercel.app"
REGEX = r"^https://my-planner-dash-[a-z0-9-]+-team\.vercel\.app$"
PREVIEW = "https://my-planner-dash-git-abc123-team.vercel.app"
CORS_HEADERS = (
    "Access-Control-Allow-Origin", "Access-Control-Allow-Methods", "Access-Control-Allow-Headers",
    "Access-Control-Allow-Private-Network", "Access-Control-Expose-Headers", "Access-Control-Allow-Credentials",
)


@pytest.fixture
async def env(tmp_path):
    api = ApiConfig(cors_origins=[DASH], cors_origin_regex=REGEX)
    async with BeEnv.start(tmp_path, start=START, overrides={"api": api}) as e:
        yield e


def _preflight(origin, *, pna=False):
    h = {"Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    if pna:
        h["Access-Control-Request-Private-Network"] = "true"
    return h


async def test_allowed_origin_preflight_headers(env):
    resp = await env.request("OPTIONS", "/health", token=None, headers=_preflight(DASH))
    assert resp.status == 204
    assert resp.headers["Access-Control-Allow-Origin"] == DASH
    assert resp.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT, DELETE"
    assert resp.headers["Access-Control-Allow-Headers"] == "Authorization, Content-Type"
    assert resp.headers["Vary"] == "Origin"
    assert "Access-Control-Allow-Private-Network" not in resp.headers  # PNA 요청에만
    assert "Access-Control-Allow-Credentials" not in resp.headers  # 쿠키는 허용하지 않는다


async def test_private_network_preflight(env):
    resp = await env.request("OPTIONS", "/health", token=None, headers=_preflight(DASH, pna=True))
    assert resp.status == 204
    assert resp.headers["Access-Control-Allow-Private-Network"] == "true"


async def test_regex_origin_allowed(env):
    resp = await env.request("OPTIONS", "/health", token=None, headers=_preflight(PREVIEW))
    assert resp.headers["Access-Control-Allow-Origin"] == PREVIEW
    resp = await env.get("/health", headers={"Origin": PREVIEW})
    assert resp.headers["Access-Control-Allow-Origin"] == PREVIEW


@pytest.mark.parametrize("origin", [
    "https://evil.vercel.app",
    "https://my-planner-dash.vercel.app.evil.com",
    "https://my-planner-dash-git-abc-team.vercel.app.evil.com",  # 정규식은 전체 일치
    "http://my-planner-dash.vercel.app",
    "null",
])
async def test_other_vercel_app_not_allowed(env, origin):
    pre = await env.request("OPTIONS", "/health", token=None, headers=_preflight(origin, pna=True))
    assert pre.status == 204
    got = await env.get("/health", headers={"Origin": origin})
    assert got.status == 200  # 토큰 검사는 그대로, CORS 헤더만 없다
    for resp in (pre, got):
        assert not [h for h in CORS_HEADERS if h in resp.headers]


async def test_expose_header_on_get(env):
    resp = await env.get("/health", headers={"Origin": DASH})
    assert resp.status == 200
    assert resp.headers["Access-Control-Allow-Origin"] == DASH
    assert resp.headers["Access-Control-Expose-Headers"] == "x-conversation-id"
    assert resp.headers["Vary"] == "Origin"


async def test_error_responses_carry_cors_headers(env):
    # 브라우저가 401·404를 읽으려면 오류 응답에도 허용 헤더가 있어야 한다
    for resp in (await env.get("/health", token=None, headers={"Origin": DASH}),
                 await env.get("/nope", headers={"Origin": DASH})):
        assert resp.status in (401, 404)
        assert resp.headers["Access-Control-Allow-Origin"] == DASH


def test_policy_without_regex():
    p = CorsPolicy([DASH], "")
    assert p.allows(DASH) and not p.allows(PREVIEW) and not p.allows(None) and not p.allows("")

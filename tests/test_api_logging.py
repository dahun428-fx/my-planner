"""API 로그 (SP3-4 스펙 14): 접근 로그는 method, 경로 틀, 상태, 소요 시간만. 쿼리, 헤더, 본문, 토큰은 없다."""

import json
import logging

import pytest
from aiohttp import web
from be_env import TEST_TOKEN, BeEnv
from test_dispatcher_messages import kst

from my_planner.api.server import DEPS_KEY, build_app
from my_planner.logging_setup import setup_logging

START = kst(2026, 10, 24, 13, 0)


def _raw(state_dir):
    for h in logging.getLogger().handlers:
        h.flush()
    return (state_dir / "logs" / "my-planner.jsonl").read_text(encoding="utf-8")


def _entries(state_dir, msg):
    return [e for e in map(json.loads, _raw(state_dir).splitlines()) if e.get("msg") == msg]


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as e:
        setup_logging(e.settings.paths.state_dir, 30)
        yield e


async def test_access_log_route_template_only(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        setup_logging(env.settings.paths.state_dir, 30)
        # 경로 틀을 보려고 시험용 경로 하나를 더 단 앱으로 다시 띄운다
        app = build_app(env.deps)

        async def thing(request):
            return web.json_response({"ok": True})

        app.router.add_get("/api/v1/things/{id}/undo", thing)
        from aiohttp.test_utils import TestClient, TestServer

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            h = {"Authorization": f"Bearer {TEST_TOKEN}", "X-Secret-Header": "SECRET-HEADER"}
            assert (await client.get("/api/v1/health?q=SECRET-QUERY", headers=h)).status == 200
            assert (await client.get("/api/v1/things/987654/undo?x=SECRET-QUERY", headers=h)).status == 200
            assert (await client.get("/api/v1/no-such/SECRET-PATH", headers=h)).status == 404
        finally:
            await client.close()
        assert app[DEPS_KEY] is env.deps
        raw = _raw(env.settings.paths.state_dir)
        lines = _entries(env.settings.paths.state_dir, "api_request")

    assert [(e["method"], e["route"], e["status"]) for e in lines] == [
        ("GET", "/api/v1/health", 200),
        ("GET", "/api/v1/things/{id}/undo", 200),
        ("GET", "(unmatched)", 404),
    ]
    assert all(isinstance(e["duration_ms"], int) for e in lines)
    assert set(lines[0]) == {"ts", "level", "logger", "msg", "method", "route", "status", "duration_ms"}
    for secret in ("SECRET-QUERY", "SECRET-HEADER", "SECRET-PATH", "987654", TEST_TOKEN, "Bearer"):
        assert secret not in raw


async def test_failed_auth_log_has_no_token(env):
    wrong = "WRONG-SECRET-TOKEN-" + "z" * 30
    for _ in range(10):
        await env.get("/health", token=wrong)
    await env.get("/health")  # 429 (맞는 토큰도)
    state_dir = env.settings.paths.state_dir
    raw = _raw(state_dir)
    assert wrong not in raw and TEST_TOKEN not in raw and "Bearer" not in raw
    assert len(_entries(state_dir, "api_auth_failed")) == 10
    assert len(_entries(state_dir, "api_auth_blocked")) == 1
    assert [e["status"] for e in _entries(state_dir, "api_request")][-2:] == [401, 429]


async def test_body_over_64kb_413(env):
    body = "가" * (64 * 1024 // 3 + 10)  # UTF-8 3바이트 × … > 64KB
    big = json.dumps({"text": body + "SECRET-BODY"})
    resp = await env.post("/health", data=big, headers={"Content-Type": "application/json"})
    assert resp.status == 413
    assert await resp.json() == {"error": {"code": "too_large", "message": "요청 본문이 너무 커요."}}
    ok = await env.post("/health", data=json.dumps({"text": "작은 본문"}), headers={"Content-Type": "application/json"})
    assert ok.status == 405  # 상한 안이면 그다음 단계(GET만 있는 경로)
    assert "SECRET-BODY" not in _raw(env.settings.paths.state_dir)


async def test_chunked_body_over_limit_413(env):
    # 길이 없는(chunked) 본문은 middleware가 길이를 모른다: 처리기가 읽을 때 client_max_size가 413으로 막는다
    app = build_app(env.deps)

    async def echo(request):
        await request.read()
        return web.json_response({"ok": True})

    app.router.add_post("/api/v1/echo", echo)
    from aiohttp.test_utils import TestClient, TestServer

    async def gen():
        for _ in range(70):
            yield b"x" * 1024

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post("/api/v1/echo", data=gen(), headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        assert resp.status == 413
        assert (await resp.json())["error"]["code"] == "too_large"
    finally:
        await client.close()


async def test_read_endpoints_log_no_titles_bodies_or_ids(tmp_path):
    from datetime import date

    from fakes import FakeTurn

    from my_planner.domain import Area, TaskStatus

    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "비밀 답장 문장")]) as env:
        setup_logging(env.settings.paths.state_dir, 30)
        env.parts.tasks.create("비밀 할 일 제목", [Area.career], TaskStatus.open, date(2026, 10, 24), None, None, "비밀 메모")
        await env.telegram("비밀 사용자 문장")
        cid = (await (await env.get("/conversations")).json())["items"][0]["id"]
        for path in (
            "/today", "/week", "/drafts", "/conditions?from=2026-10-01", "/checkins", f"/conversations/{cid}/messages",
            "/priorities?cadence=week&period=SECRET-PERIOD", "/checkins/SECRET-ID",
        ):
            await env.get(path)
        raw = _raw(env.settings.paths.state_dir)
        routes = {e["route"] for e in _entries(env.settings.paths.state_dir, "api_request")}

    for secret in ("비밀 할 일 제목", "비밀 메모", "비밀 사용자 문장", "비밀 답장 문장", "SECRET-PERIOD", "SECRET-ID", "2026-10-01"):
        assert secret not in raw
    assert "/api/v1/conversations/{id}/messages" in routes and "/api/v1/checkins/{id}" in routes


async def test_chat_logs_have_no_body_args_or_token(tmp_path):
    """`POST /chat`: 시스템 로그에 메시지 본문, 도구 인자, 두뇌 답, 토큰이 없다(1장 완료 조건 3)."""
    from fakes import FakeTurn

    add = ("add_task", {"title": "꾸민제목-SECRET-ARG", "areas": ["health"], "planned_for": "2026-10-25"})
    script = [FakeTurn([add], "꾸민답-SECRET-REPLY")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        setup_logging(env.settings.paths.state_dir, 30)
        _, raw_stream = await env.chat("꾸민문장-SECRET-BODY", client_msg_id="cm-log")
        await env.chat("꾸민문장-SECRET-BODY", client_msg_id="cm-log")  # 재생
        await env.chat("/today")
        raw = _raw(env.settings.paths.state_dir)
        routes = [(e["method"], e["route"], e["status"]) for e in _entries(env.settings.paths.state_dir, "api_request")]

    assert b"SECRET-REPLY" in raw_stream  # 스트림에는 있다
    for secret in ("SECRET-BODY", "SECRET-ARG", "SECRET-REPLY", TEST_TOKEN, "cm-log"):
        assert secret not in raw, secret
    assert routes == [("POST", "/api/v1/chat", 200)] * 3


async def test_full_scenario_logs_have_no_secrets(tmp_path):
    """BE 마무리(SP3-4 티켓 15, 1장 완료 조건 3, 14장): 텔레그램·앱·버튼·`/actions`·되돌리기·푸시·회차·하루 한 번
    작업·`/status`·경험치를 한 번에 돌린 뒤 시스템 로그에 토큰, 메시지 본문, 할 일 제목, 도구 인자 값, 푸시
    `endpoint`가 없다. 내용은 꾸며 낸 것이다."""
    from datetime import timedelta

    from fakes import FakePushSender, FakeTurn
    from test_delivery import tick_at

    sentence = "비밀 문장 7f3a"
    title = "비밀제목-9c1e"
    note = "비밀메모-5b2d"
    reason = "비밀사유-1a8f"
    endpoint = "https://push.example.invalid/sub/SECRET-ENDPOINT-44d1"
    add = ("add_task", {"title": title, "areas": ["health"], "planned_for": "2026-10-24", "note": note})
    grant = ("grant_xp", {"amount": 10, "reason": reason})
    propose = ("propose_tasks", {"tasks": [{"title": f"{title}-초안", "areas": ["career"]}]})
    script = [FakeTurn([add, grant], f"답-{sentence}"), FakeTurn([], "비밀답-앱-3e7c"),
              FakeTurn([propose], "비밀회차본문-6f0a"), FakeTurn([], "비밀회차답-8d2b")]
    push = FakePushSender()
    async with BeEnv.start(tmp_path, start=START, script=script, push=push) as env:
        setup_logging(env.settings.paths.state_dir, 30)
        await env.telegram(sentence)
        await env.chat(f"앱-{sentence}")
        tid = env.parts.tasks.list()[0].id
        _, done = await env.action("complete_task", {"id": tid})
        await env.post(f"/activity/{done['activity_id']}/undo", json={"client_msg_id": "SECRET-CMID-0b9e"})
        await env.action("update_task", {"id": tid, "note": f"{note}-2"})
        await env.subscribe(endpoint, label="비밀기기-2c4f")
        await env.post("/push/test", json={})
        await tick_at(env, kst(2026, 10, 24, 18, 0) + timedelta(seconds=30))  # 저녁 체크인(푸시)
        env.clock.set(kst(2026, 10, 24, 18, 30))
        await env.telegram("비밀회차글-4a9d")
        await env.press("c:2026-10-24:4")
        draft = env.parts.tasks.list(status="draft")[0].id
        await env.press(f"d:c:{draft}")
        await env.telegram("/status")
        await env.chat("/status")
        await tick_at(env, kst(2026, 10, 26, 9, 0) + timedelta(seconds=30))  # 하루 한 번 작업(쉬는 날 X9)
        raw = _raw(env.settings.paths.state_dir)
        ledger = env.conn.execute("SELECT source_kind FROM status_xp_ledger").fetchall()

    assert {r["source_kind"] for r in ledger} >= {"task_done", "secretary", "condition", "checkin_reply", "rest_day"}
    for secret in (TEST_TOKEN, "Bearer", sentence, "7f3a", title, note, reason, endpoint, "SECRET-ENDPOINT",
                   "비밀답-앱", "비밀회차본문", "비밀회차답", "비밀회차글", "비밀기기", "SECRET-CMID", "push.example"):
        assert secret not in raw, secret
    assert "xp_granted_by_secretary" in raw and "rest_days_granted" in raw  # 남는 것은 이름과 수만

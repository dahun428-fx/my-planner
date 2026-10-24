"""`POST /client-errors`, `POST /internal/notify` (SP6 스펙 3.3, 6장). 내용은 꾸며 낸 것이다."""

import logging
import sqlite3

import jsonschema
import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle

MON_0900 = kst(2026, 10, 26, 9, 0)
GOOD = {
    "app": "app", "version": "a792f21", "route": "/today/[id]", "name": "TypeError",
    "frames": ["app-today.js:1:2345"], "at": "2026-10-26T00:00:00Z",
}


def _counts(env):
    c = sqlite3.connect(env.db_path)
    try:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        c.close()


async def test_client_error_logged_without_message(tmp_path, caplog):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        bad = await env.post("/client-errors", json={**GOOD, "message": "할 일 제목"})
        assert bad.status == 422
        assert (await bad.json())["error"]["code"] == "invalid_request"
        with caplog.at_level(logging.WARNING, logger="my_planner"):
            ok = await env.post("/client-errors", json=GOOD)
        assert ok.status == 204
    recs = [r for r in caplog.records if r.msg == "client_error"]
    assert len(recs) == 1
    assert recs[0].route == "/today/[id]" and recs[0].error_name == "TypeError"
    assert recs[0].app == "app" and recs[0].version == "a792f21" and recs[0].frames == GOOD["frames"]
    assert "할 일 제목" not in caplog.text
    assert "할 일 제목" not in repr(recs[0].__dict__)


@pytest.mark.parametrize("field,value", [
    ("route", "/today?x=1"),
    ("frames", [f"a.js:{i}:1" for i in range(11)]),
    ("name", "a b"),
    ("frames", ["x" * 161]),
    ("app", "other"),
    ("version", "v" * 41),
    ("version", "a b"),
    ("frames", ["https://x.example/a.js:1:1"]),
    ("frames", ["/abs/path/a.js:1:1"]),
    ("frames", ["할 일 제목"]),
])
async def test_client_error_rejects_bad_route_and_long_frames(tmp_path, field, value):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        resp = await env.post("/client-errors", json={**GOOD, field: value})
        body = await resp.json()
    assert resp.status == 422 and body["error"]["code"] == "invalid_request"


async def test_client_error_bad_json_is_422(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        resp = await env.post("/client-errors", data=b"not json")
    assert resp.status == 422


async def test_client_error_requires_token(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        assert (await env.post("/client-errors", json=GOOD, token=None)).status == 401


async def test_client_error_writes_nothing(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        before = _counts(env)
        assert (await env.post("/client-errors", json=GOOD)).status == 204
        after = _counts(env)
    assert before == after


async def test_internal_notify_uses_effective_channel(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        before = env.parts.state.usage(MON_0900.date()).proactive_messages
        resp = await env.post("/internal/notify", json={"text": "복구했어요.", "kind": "recovery"})
        body = await resp.json()
        after = env.parts.state.usage(MON_0900.date()).proactive_messages
        sent = [o.text for o in env.sender.sent]
    assert resp.status == 200 and body == {"channel": "telegram"}
    assert sent == ["복구했어요."]
    assert before == after


async def test_internal_notify_logs_without_text(tmp_path, caplog):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        with caplog.at_level(logging.INFO, logger="my_planner"):
            await env.post("/internal/notify", json={"text": "비밀문구", "kind": "recovery"})
    assert any(r.msg == "recovery_notice_sent" and r.channel == "telegram" for r in caplog.records)
    assert "비밀문구" not in caplog.text


async def test_internal_notify_503_when_undeliverable(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        env.sender.fail = True
        resp = await env.post("/internal/notify", json={"text": "x", "kind": "recovery"})
        body = await resp.json()
    assert resp.status == 503 and body["error"]["code"] == "unavailable"


@pytest.mark.parametrize("body", [
    {"text": "", "kind": "recovery"},
    {"text": "x" * 501, "kind": "recovery"},
    {"text": "x", "kind": "other"},
    {"text": "x"},
    {"text": "x", "kind": "recovery", "extra": 1},
])
async def test_internal_notify_validation_400(tmp_path, body):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        resp = await env.post("/internal/notify", json=body)
        assert env.sender.sent == []
        assert resp.status == 400 and (await resp.json())["error"]["code"] == "invalid_request"


async def test_internal_notify_requires_token(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        resp = await env.post("/internal/notify", json={"text": "x", "kind": "recovery"}, token=None)
        assert env.sender.sent == []
    assert resp.status == 401


async def test_internal_notify_writes_no_conversation_rows(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        before = _counts(env)
        await env.post("/internal/notify", json={"text": "x", "kind": "recovery"})
        after = _counts(env)
    for t in ("todos", "conversations", "messages", "runs", "run_deliveries"):
        if t in before:
            assert before[t] == after[t], t


async def test_recovery_routes_in_schema_bundle(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0900) as env:
        body = await (await env.get("/schema")).json()
    assert {"ClientErrorBody", "RecoveryNoticeBody"} <= set(body["models"])
    jsonschema.Draft202012Validator(schema_bundle()["models"]["ClientErrorBody"]).validate(GOOD)


async def test_internal_notify_dev_role_only_logs(tmp_path, caplog):
    # 릴리스 흐름 5.2: 개발용 BE는 보낼 통로가 없다. 로그만 남기고 응답 모양은 그대로다
    async with BeEnv.start(tmp_path, start=MON_0900, overrides={"runtime": {"role": "dev"}}) as env:
        before = _counts(env)
        with caplog.at_level(logging.INFO, logger="my_planner"):
            resp = await env.post("/internal/notify", json={"text": "비밀문구", "kind": "recovery"})
        body = await resp.json()
        assert env.sender.sent == []
        assert _counts(env) == before
    assert resp.status == 200 and body == {"channel": "telegram"}
    assert any(r.msg == "recovery_notice_logged" and r.role == "dev" for r in caplog.records)
    assert not any(r.msg == "recovery_notice_sent" for r in caplog.records)
    assert "비밀문구" not in caplog.text

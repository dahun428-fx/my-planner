"""API 수용 시험 (가짜 두뇌 + 가짜 시계, `BeEnv`)."""

from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst


async def test_health_after_morning_brief(tmp_path):
    # 토요일(주말 아침 10:00) 10:00:30
    async with BeEnv.start(
        tmp_path, start=kst(2026, 10, 24, 10, 0) + timedelta(seconds=30), script=[FakeTurn([], "좋은 아침이에요")]
    ) as env:
        await env.tick()
        resp = await env.get("/health")
        assert resp.status == 200
        body = await resp.json()

    run = body["runs_today"][0]
    assert run["loop"] == "morning_brief"
    assert run["status"] == "done"
    assert run["delivered_via"] == ["telegram"]
    assert run["checkin_state"] == "pending"
    assert run["scheduled_for"] == "2026-10-24T01:00:00Z"
    assert body["proactive"]["sent_today"] == 1
    assert body["brain"]["calls_today"] == 1
    assert body["brain"]["auth"] == "ok"
    assert body["notify"] == {"primary": "app", "effective": "telegram"}
    assert body["status"] == "ok"

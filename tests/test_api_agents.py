"""`GET /agents/{agent}/inbox/count`, `GET /agents/notes` (SP14-07)."""

from datetime import date, timedelta

import jsonschema
from be_env import TEST_TOKEN, BeEnv
from test_api_devices import _device
from test_api_read import get_json
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.store.db import transaction
from my_planner.store.repos.agents import AgentsRepo

START = kst(2026, 11, 1, 14, 0)
TODAY = date(2026, 11, 1)
FORBIDDEN = {"error": {"code": "forbidden", "message": "이 화면에서는 볼 수 없어요."}}


def _valid(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def _event(env, repo, ref, day, to):
    with transaction(env.conn):
        return repo.add_event("task_done", ref, "career", "app", day, to=to, now=env.clock.now())


async def test_inbox_count_per_agent(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        repo = AgentsRepo(env.conn, env.clock)
        _event(env, repo, "task:1", TODAY, ("mate", "manager"))
        env.clock.advance(timedelta(seconds=61))
        _event(env, repo, "task:2", TODAY - timedelta(days=8), ("mate",))
        env.clock.advance(timedelta(seconds=61))
        _event(env, repo, "task:3", TODAY - timedelta(days=7), ("manager",))
        mate = await get_json(env, "/agents/mate/inbox/count")
        manager = await get_json(env, "/agents/manager/inbox/count")
        for bad in ("secretary", "bogus"):
            resp = await env.get(f"/agents/{bad}/inbox/count")
            assert resp.status == 404
            assert await resp.json() == {"error": {"code": "not_found", "message": "없는 대화 상대예요."}}
        assert env.brain.calls == []
        assert env.parts.state.usage(TODAY).brain_calls == 0
    assert mate == {"unseen": 1}
    assert manager == {"unseen": 2}
    _valid("InboxCount", mate)


def _note(env, repo, day, text="관찰", priority=2):
    with transaction(env.conn):
        return repo.add_note("mate", day, text, priority, [], env.clock.now())


async def test_notes_days_param(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        repo = AgentsRepo(env.conn, env.clock)
        _note(env, repo, TODAY - timedelta(days=1), "하나")
        _note(env, repo, TODAY - timedelta(days=8), "둘")
        default = await get_json(env, "/agents/notes")
        wide = await get_json(env, "/agents/notes?days=30")
        for bad in ("0", "31", "abc", ""):
            resp = await env.get(f"/agents/notes?days={bad}")
            assert resp.status == 400, bad
            assert await resp.json() == {"error": {"code": "invalid_request", "message": "days는 1부터 30까지예요."}}
    assert [n["text"] for n in default["notes"]] == ["하나"]
    assert [n["text"] for n in wide["notes"]] == ["하나", "둘"]
    _valid("AgentNotes", wide)
    n = default["notes"][0]
    assert set(n) == {"id", "agent", "day", "text", "priority", "shown_at", "created_at"}
    assert n["day"] == "2026-10-31" and n["shown_at"] is None and n["created_at"].endswith("Z")


async def test_notes_dashboard_forbidden(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        dash, _ = await _device(env, client="dashboard", label="Windows · 대시보드")
        app, _ = await _device(env, client="app", label="iPhone · 앱")
        resp = await env.get("/agents/notes", token=dash)
        assert resp.status == 403
        assert await resp.json() == FORBIDDEN
        assert (await env.get("/agents/notes", token=app)).status == 200
        assert (await env.get("/agents/notes", token=TEST_TOKEN)).status == 200
        assert (await env.get("/agents/mate/inbox/count", token=dash)).status == 200


async def test_notes_include_handoff_priority_3(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        repo = AgentsRepo(env.conn, env.clock)
        _note(env, repo, TODAY, "넘기기", priority=3)
        body = await get_json(env, "/agents/notes")
    assert [(n["text"], n["priority"]) for n in body["notes"]] == [("넘기기", 3)]

"""`GET /panel/suggestions`, `GET /panel/budget`, `GET /owner-statements` (SP15-09). 글은 꾸며 낸 것이다."""

from __future__ import annotations

from datetime import date, timedelta

import jsonschema
from be_env import BeEnv
from test_api_devices import _device
from test_api_read import get_json
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.domain import RunContext
from my_planner.store.db import transaction

WED = kst(2026, 11, 4, 12, 0)  # 논리적 오늘 2026-11-04, 2026-W45
FORBIDDEN = {"error": {"code": "forbidden", "message": "이 화면에서는 볼 수 없어요."}}
EV = [{"type": "record", "ref": "task:1", "note": "가짜 근거"}, {"type": "external", "ref": "bench:income",
                                                                "note": "가짜 기준"}]
PATHS = ("/panel/suggestions", "/panel/budget", "/owner-statements")


def _valid(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def _suggest(env, title: str, *, days_ago: int = 0, state: str | None = None, week: str = "2026-W45") -> int:
    panel = env.parts.panel
    now = env.clock.now()
    with transaction(env.conn):
        sid = panel.add_suggestion(
            conversation_id=None, kind="task", title=title, area="career", size_min=30, per_week=None,
            due_hint=date(2026, 11, 10), experts=["career", "finance"], evidence=EV, week=week,
            now=now - timedelta(days=days_ago),
        )
        if state is not None:
            panel.set_state(sid, state, now=now)
    return sid


async def test_suggestions_state_filter(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        env.parts.tools.add_task(
            RunContext(None, None, actor="user", channel="app"), title="가짜 할 일", areas=["career"], planned_for="2026-11-04",
        )
        old = _suggest(env, "가짜 오래됨", days_ago=29, week="2026-W40")
        a = _suggest(env, "가짜 하나", days_ago=2)
        b = _suggest(env, "가짜 둘", days_ago=1, state="dismissed")
        default = await get_json(env, "/panel/suggestions")
        proposed = await get_json(env, "/panel/suggestions?state=proposed")
        dismissed = await get_json(env, "/panel/suggestions?state=dismissed")
        bad = []
        for q in ("bogus", ""):
            resp = await env.get(f"/panel/suggestions?state={q}")
            bad.append((resp.status, await resp.json()))
    assert [i["id"] for i in default["items"]] == [b, a]
    assert [i["id"] for i in proposed["items"]] == [a, old]
    assert [i["id"] for i in dismissed["items"]] == [b]
    assert bad == [(400, {"error": {"code": "invalid_request", "message": "state가 맞지 않아요."}})] * 2
    item = proposed["items"][0]
    assert item == {
        "id": a, "kind": "task", "title": "가짜 하나", "area": "career", "size_min": 30, "per_week": None,
        "due_hint": "2026-11-10", "experts": ["career", "finance"],
        "evidence": [{**EV[0], "href": "/todos/"}, {**EV[1], "href": None}], "state": "proposed", "week": "2026-W45",
        "created_at": item["created_at"],
    }
    assert item["created_at"].endswith("Z")
    _valid("PanelSuggestions", default)


async def test_budget_remaining_only(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        empty = await get_json(env, "/panel/budget")
        _suggest(env, "가짜 하나")
        one = await get_json(env, "/panel/budget")
    assert empty == {"remaining": 2, "full_diagnosis_ok": True}
    assert set(one) == {"remaining", "full_diagnosis_ok"} and one["remaining"] == 1
    _valid("PanelBudget", one)


async def test_owner_statements_active(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        panel = env.parts.panel
        seeded = [s.id for s in panel.active_statements()]
        with transaction(env.conn):
            first = panel.add_statement("fact", "career", "가짜 사실", now=env.clock.now())
            env.clock.advance(timedelta(minutes=1))
            gone = panel.add_statement("preference", None, "가짜 취향", now=env.clock.now())
            env.clock.advance(timedelta(minutes=1))
            last = panel.add_statement("preference", "health", "가짜 둘", now=env.clock.now())
            panel.retire(gone, env.clock.now())
        body = await get_json(env, "/owner-statements")
    ids = [i["id"] for i in body["items"]]
    assert ids[:2] == [last, first] and gone not in ids and set(ids[2:]) == set(seeded)
    assert body["items"][0] == {
        "id": last, "kind": "preference", "area": "health", "text": "가짜 둘", "created_at": body["items"][0]["created_at"],
    }
    _valid("OwnerStatements", body)


async def test_panel_routes_dashboard_forbidden(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        dash, _ = await _device(env, client="dashboard", label="Windows · 대시보드")
        app, _ = await _device(env, client="app", label="iPhone · 앱")
        out = []
        for path in PATHS:
            d = await env.get(path, token=dash)
            a = await env.get(path, token=app)
            out.append((path, d.status, await d.json(), a.status))
    assert out == [(p, 403, FORBIDDEN, 200) for p in PATHS]


async def test_panel_reads_no_brain(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        for path in PATHS:
            await get_json(env, path)
        calls = list(env.brain.calls)
    assert calls == []

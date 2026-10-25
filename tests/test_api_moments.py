"""이룬 순간 API: `GET /status`의 `moments`, `GET /moments`, `/actions`의 숨기기·다시 보이기·지우기 (SP8 스펙 6.4, 6.5).

`BeEnv` + 가짜 시계. 오늘은 2026-10-25(일) 13:00. 순간의 글은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import jsonschema
from be_env import BeEnv
from test_dispatcher_messages import kst
from test_moments_job import done_task, started, tick_at

from my_planner.api.models import schema_bundle
from my_planner.store.db import transaction
from my_planner.store.repos.moments import Moment
from my_planner.store.views import moment_dict

SUN_1300 = kst(2026, 10, 25, 13, 0)
D = {n: date(2026, 10, n) for n in range(10, 27)}
TEXT = "꾸며 낸 순간: 화분에 물을 줬어요"
CONFIRM = "이 순간을 지울까요? 되돌릴 수 없어요."
REPO = Path(__file__).resolve().parents[1]


def _validate(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def seed(env, d, *texts, area="health", sources=("chat",)):
    """그날의 순간(slot 1..n). 하루 끝 작업과 같은 저장 함수(`save_day`)."""
    items = [(t, area, list(sources)) for t in texts]
    return [m.id for m in env.parts.moments.save_day(d, items, env.clock.now())]


def hide(env, moment_id, at=None):
    with transaction(env.conn):
        env.parts.moments.hide(moment_id, at or env.clock.now())


def row(env, moment_id):
    r = env.conn.execute("SELECT * FROM status_moments WHERE id = ?", (moment_id,)).fetchone()
    return dict(r) if r else None


async def get_json(env, path):
    resp = await env.get(path)
    return resp.status, await resp.json()


async def status(env):
    code, body = await get_json(env, "/status")
    assert code == 200, body
    _validate("Status", body)
    return body


async def applied(env, action, args, **kw):
    code, body = await env.action(action, args, **kw)
    assert (code, body["status"]) == (200, "applied"), body
    return body


# --- GET /status ---


async def test_status_moments_14_days_not_hidden_max_20_order(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        seed(env, D[11], "꾸며 낸 순간: 14일 밖")  # 10/25 기준 15일 전
        old = seed(env, D[12], "꾸며 낸 순간: 14일 안 첫날")
        for n in range(17, 25):  # 8일 × 3 = 24개
            seed(env, D[n], f"꾸며 낸 순간 {n}-1", f"꾸며 낸 순간 {n}-2", f"꾸며 낸 순간 {n}-3")
        (hidden,) = seed(env, D[13], "꾸며 낸 순간: 숨김")
        hide(env, hidden)
        body = await status(env)

    items = body["moments"]
    assert len(items) == 20
    assert [m["date"] for m in items[:4]] == ["2026-10-24"] * 3 + ["2026-10-23"]
    assert [m["text"] for m in items[:3]] == ["꾸며 낸 순간 24-1", "꾸며 낸 순간 24-2", "꾸며 낸 순간 24-3"]
    assert all(m["hidden"] is False for m in items)
    assert old[0] not in {m["id"] for m in items}  # 최대 20개: 오래된 것이 빠진다
    assert items[0] == {
        "id": items[0]["id"], "date": "2026-10-24", "text": "꾸며 낸 순간 24-1", "area": "health",
        "sources": ["chat"], "hidden": False,
    }


async def test_status_moments_hidden_count(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        none = await status(env)
        a, b = seed(env, D[24], "꾸며 낸 순간 하나", "꾸며 낸 순간 둘")
        (c,) = seed(env, D[11], "꾸며 낸 순간: 14일 밖")
        for i in (a, c):
            hide(env, i)
        body = await status(env)

    assert (none["moments"], none["moments_hidden"]) == ([], 0)
    assert [m["id"] for m in body["moments"]] == [b]
    assert body["moments_hidden"] == 1  # 14일 밖의 숨긴 순간은 세지 않는다


# --- GET /moments ---


async def test_get_moments_range_from_to(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        seed(env, D[10], "꾸며 낸 순간 10")
        (first,) = seed(env, D[11], "꾸며 낸 순간 11")
        (last,) = seed(env, D[24], "꾸며 낸 순간 24")
        seed(env, D[25], "꾸며 낸 순간 25")
        code, body = await get_json(env, "/moments?before=2026-10-25&days=14")
        code2, default = await get_json(env, "/moments")
        code3, short = await get_json(env, "/moments?before=2026-10-12&days=1")

    assert code == code2 == code3 == 200
    _validate("MomentsList", body)
    assert (body["from"], body["to"]) == ("2026-10-11", "2026-10-24")
    assert [m["id"] for m in body["items"]] == [last, first]
    assert (default["from"], default["to"]) == ("2026-10-12", "2026-10-25")  # `before`가 없으면 `to` = 오늘
    assert [m["text"] for m in default["items"]] == ["꾸며 낸 순간 25", "꾸며 낸 순간 24"]
    assert (short["from"], short["to"]) == ("2026-10-11", "2026-10-11")
    assert [m["id"] for m in short["items"]] == [first]


async def test_get_moments_include_hidden_marks_hidden(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        a, b = seed(env, D[24], "꾸며 낸 순간 하나", "꾸며 낸 순간 둘")
        hide(env, a)
        _, shown = await get_json(env, "/moments?before=2026-10-25")
        _, every = await get_json(env, "/moments?before=2026-10-25&include_hidden=true")
        _, off = await get_json(env, "/moments?include_hidden=false")

    assert [m["id"] for m in shown["items"]] == [b]
    assert [(m["id"], m["hidden"]) for m in every["items"]] == [(a, True), (b, False)]
    assert [m["id"] for m in off["items"]] == [b]


async def test_get_moments_bad_query_400(tmp_path):
    bad = (
        "before=2026-13-01", "before=2026-10-1", "before=20261025", "before=2026-10-25%0A", "days=0", "days=61",
        "days=abc", "days=-1", "include_hidden=yes", "include_hidden=True",
    )
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        seed(env, D[24], TEXT)
        got = [await get_json(env, f"/moments?{q}") for q in bad]
        ok = await get_json(env, "/moments?days=60")

    for q, (code, body) in zip(bad, got, strict=True):
        assert code == 400, q
        assert body["error"]["code"] == "invalid_request", q
        assert TEXT not in str(body)
    # 문구는 플랜 문구 표(H4)와 같다(최종 리뷰 N1)
    messages = {q: body["error"]["message"] for q, (_, body) in zip(bad, got, strict=True)}
    assert messages["before=2026-10-1"] == "before는 YYYY-MM-DD 형식이어야 해요."
    assert messages["before=2026-13-01"] == "before는 없는 날짜예요."
    assert messages["days=61"] == "days는 1~60 사이 정수여야 해요."
    assert messages["include_hidden=yes"] == "include_hidden은 true 또는 false여야 해요."
    assert ok[0] == 200 and (ok[1]["from"], ok[1]["to"]) == ("2026-08-27", "2026-10-25")


def test_sources_are_kinds_only():
    m = Moment(id=1, date=D[24], slot=1, text=TEXT, area=None, sources=["task:12", "task:15", "chat"], hidden_at=None)
    assert moment_dict(m)["sources"] == ["task", "chat"]
    m2 = Moment(id=2, date=D[24], slot=2, text=TEXT, area=None,
                sources=["habit:3", "condition", "task:9", "habit:4"], hidden_at=None)
    assert moment_dict(m2)["sources"] == ["habit", "condition", "task"]


# --- /actions: 숨기기, 다시 보이기, 지우기 (6.4) ---


async def test_hide_then_undo_visible_again(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        (mid,) = seed(env, D[24], TEXT)
        body = await applied(env, "hide_moment", {"id": mid})
        hidden = await status(env)
        act = env.activity()[-1]
        resp = await env.post(f"/activity/{body['undo_id']}/undo", json={"client_msg_id": "undo-1"})
        undone = await resp.json()
        after = await status(env)
        r = row(env, mid)

    assert body["undo_id"] == body["activity_id"]
    assert body["confirmation"] == "이룬 순간 숨김 (10/24)"
    assert TEXT not in str(body)
    assert (hidden["moments"], hidden["moments_hidden"]) == ([], 1)
    assert (act["kind"], act["target"], act["summary"]) == ("moment_hidden", f"moment:{mid}", "이룬 순간 숨김 (10/24)")
    assert resp.status == 200 and undone["status"] == "undone"
    assert [m["id"] for m in after["moments"]] == [mid] and after["moments_hidden"] == 0
    assert r["hidden_at"] is None


async def test_unhide_then_undo_hidden_again(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        (mid,) = seed(env, D[24], TEXT)
        hide(env, mid, kst(2026, 10, 25, 9, 0))
        before = row(env, mid)["hidden_at"]
        env.clock.advance(minutes=5)
        body = await applied(env, "unhide_moment", {"id": mid})
        shown = row(env, mid)["hidden_at"]
        act = env.activity()[-1]
        resp = await env.post(f"/activity/{body['undo_id']}/undo", json={"client_msg_id": "undo-1"})
        again = row(env, mid)["hidden_at"]

    assert body["confirmation"] == "이룬 순간 다시 보임 (10/24)"
    assert shown is None
    assert (act["kind"], act["target"]) == ("moment_unhidden", f"moment:{mid}")
    assert resp.status == 200
    assert again == before  # 이전 `hidden_at` 그대로


async def test_hide_twice_already(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        (mid,) = seed(env, D[24], TEXT)
        await applied(env, "hide_moment", {"id": mid})
        first = row(env, mid)["hidden_at"]
        n = len(env.activity())
        env.clock.advance(minutes=5)
        body = await applied(env, "hide_moment", {"id": mid})
        unhide = await applied(env, "unhide_moment", {"id": mid})
        twice = await applied(env, "unhide_moment", {"id": mid})
        end, acts = row(env, mid), len(env.activity())

    assert body["result"] == {"already": True} and body["activity_id"] is None
    assert first is not None and end["hidden_at"] is None
    assert acts == n + 1  # 두 번째 숨기기·다시 보이기는 활동이 없다. 첫 다시 보이기 하나만
    assert unhide["result"].get("already") is None
    assert twice["result"] == {"already": True}


async def test_delete_needs_confirm_then_row_gone_not_undoable(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        (mid,) = seed(env, D[24], TEXT)
        code, ask = await env.action("delete_moment", {"id": mid})
        still = row(env, mid)
        body = await applied(env, "delete_moment", {"id": mid}, confirm_token=ask["confirm_token"])
        gone = row(env, mid)
        act = env.activity()[-1]
        resp = await env.post(f"/activity/{body['activity_id']}/undo", json={"client_msg_id": "undo-1"})
        undo = await resp.json()

    assert (code, ask["status"], ask["summary"]) == (200, "needs_confirm", CONFIRM)
    assert still is not None
    assert gone is None
    assert "undo_id" not in body
    assert body["confirmation"] == "이룬 순간 지움 (10/24)"
    assert (act["kind"], act["target"], act["risk"]) == ("moment_deleted", f"moment:{mid}", "confirm")
    assert TEXT not in act["summary"]
    assert (resp.status, undo["error"]["code"]) == (422, "not_undoable")


async def test_deleted_moment_actions_404(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1300) as env:
        (mid,) = seed(env, D[24], TEXT)
        with transaction(env.conn):
            env.parts.moments.delete(mid)
        got = [await env.action(a, {"id": mid}) for a in ("hide_moment", "unhide_moment", "delete_moment")]
        missing = await env.action("hide_moment", {"id": 9999})

    for code, body in [*got, missing]:
        assert code == 404, body
        assert body["error"] == {"code": "not_found", "message": "없는 순간이에요."}


async def test_deleted_day_not_reorganized(tmp_path):
    """지운 날은 다시 정리하지 않는다: 날 행은 `done` 그대로, 다음 날 tick에도 두뇌를 부르지 않는다(6.4)."""
    async with started(tmp_path, since="2026-10-23") as env:
        done_task(env, "꾸민 할 일", kst(2026, 10, 24, 15, 0))
        (mid,) = seed(env, D[24], TEXT, sources=("chat",))
        with transaction(env.conn):
            env.parts.moments.mark(D[25], "empty", env.clock.now())  # 10/25는 이미 본 날
        _, ask = await env.action("delete_moment", {"id": mid})
        await applied(env, "delete_moment", {"id": mid}, confirm_token=ask["confirm_token"])
        await tick_at(env)
        await env.drain()
        day = env.parts.moments.day(D[24])
        calls = list(env.brain.calls)
        await tick_at(env, kst(2026, 10, 27, 4, 1))
        await env.drain()
        later = env.parts.moments.day(D[24])

    assert (day.state, day.saved) == ("done", 1)
    assert [c for c in calls if c["run_ctx"].kind == "moments"] == []
    assert later.state == "done"
    assert [c for c in env.brain.calls if c["run_ctx"].kind == "moments"] == []


def test_dashboard_reads_only():
    """대시보드는 `GET /status`의 `moments`만 읽는다: 쓰기(`POST`)나 `/actions`, `/moments`를 부르지 않는다(6.5)."""
    src = REPO / "web" / "dashboard" / "src"
    files = [p for p in src.rglob("*.ts*") if ".test." not in p.name and not p.name.endswith(".gen.ts")]
    assert any(p.name == "api.ts" for p in files)
    text = "\n".join(p.read_text(encoding="utf-8") for p in files)
    for needle in ('"/actions"', "'/actions'", "/actions`", '"/moments', "hide_moment", "delete_moment"):
        assert needle not in text, needle
    assert not re.search(r"""method:\s*["'](POST|PUT|PATCH|DELETE)["']""", text)

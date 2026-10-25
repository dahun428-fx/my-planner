"""초안 할 일: propose_tasks, confirm_tasks (스펙 5.5, 5.7). MCP 핸들러 경계."""

from datetime import timedelta

import pytest
from test_tools_tasks import ToolEnv

from my_planner.domain import TaskStatus


@pytest.fixture
def env(tmp_path, conn):
    return ToolEnv(tmp_path, conn)


def _proposal(title, **kw):
    return {"title": title, "areas": ["career"], **kw}


def test_propose_tasks_creates_drafts(env):
    ctx = env.ctx(conv=5)
    out = env.tools.propose_tasks(
        ctx, tasks=[_proposal("보고서 목차 쓰기", planned_for="2026-10-24"), _proposal("운동", areas=["health"])]
    )

    assert "error" not in out
    ids = [t["id"] for t in out["proposed"]]
    assert len(ids) == 2
    assert [env.repo.get(i).status for i in ids] == [TaskStatus.draft, TaskStatus.draft]
    assert env.repo.get(ids[0]).planned_for.isoformat() == "2026-10-24"
    # 이벤트 하나, data에 ids
    assert [(e.kind, e.data["ids"]) for e in ctx.events] == [("tasks_proposed", ids)]
    assert ctx.tool_names == ["propose_tasks"]
    # 할 일마다 tool_events_log 한 줄: "전부 추가" 버튼이 이것으로 그 대화의 초안을 찾는다
    rows = env.conn.execute(
        "SELECT task_id, conversation_id, kind FROM tool_events_log ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [(ids[0], 5, "tasks_proposed"), (ids[1], 5, "tasks_proposed")]
    kinds = [r["kind"] for r in env.conn.execute("SELECT kind FROM task_events WHERE task_id = ?", (ids[0],))]
    assert kinds == ["proposed"]

    # 하나라도 잘못되면 아무것도 만들지 않는다
    bad = env.tools.propose_tasks(env.ctx(), tasks=[_proposal("괜찮은 것"), _proposal("영역이 틀림", areas=["x"])])
    assert "error" in bad
    for empty in ([], None, "운동"):
        assert "error" in env.tools.propose_tasks(env.ctx(), tasks=empty)
    assert env.conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2


def test_confirm_tasks_only_drafts(env):
    from my_planner.tools.confirmations import render_confirmations

    drafts = [t["id"] for t in env.tools.propose_tasks(env.ctx(), tasks=[_proposal("가"), _proposal("나")])["proposed"]]
    opened = env.tools.add_task(env.ctx(), title="이미 열린 일", areas=["career"])["id"]
    dropped = env.tools.propose_tasks(env.ctx(), tasks=[_proposal("뺀 초안")])["proposed"][0]["id"]
    env.tools.drop_task(env.ctx(), id=dropped)

    ctx = env.ctx(conv=3)
    out = env.tools.confirm_tasks(ctx, ids=[drafts[0], opened, dropped, 999, drafts[1]])

    assert [t["id"] for t in out["confirmed"]] == [drafts[0], drafts[1]]
    assert all(t["status"] == "open" for t in out["confirmed"])
    assert out["skipped_ids"] == [opened, dropped, 999]
    assert env.repo.get(dropped).status is TaskStatus.dropped
    assert [e.kind for e in ctx.events] == ["tasks_confirmed", "tasks_confirmed"]
    assert render_confirmations(ctx.events, env.tools.today()) == "✓ 확정: 가\n✓ 확정: 나"
    kinds = [r["kind"] for r in env.conn.execute("SELECT kind FROM task_events WHERE task_id = ?", (drafts[0],))]
    assert kinds == ["proposed", "confirmed"]
    rows = env.conn.execute("SELECT task_id, conversation_id FROM tool_events_log WHERE kind = 'tasks_confirmed'")
    assert [tuple(r) for r in rows] == [(drafts[0], 3), (drafts[1], 3)]

    # 다시 확정해도 바뀌는 것이 없다
    again = env.ctx()
    assert env.tools.confirm_tasks(again, ids=[drafts[0]]) == {"confirmed": [], "skipped_ids": [drafts[0]]}
    assert again.events == []
    for bad in (None, 3, ["1"], [True]):
        assert "error" in env.tools.confirm_tasks(env.ctx(), ids=bad)
    # 제안 자체에는 확인 문구가 없다(버튼이 대신한다)
    proposed = env.ctx()
    env.tools.propose_tasks(proposed, tasks=[_proposal("다")])
    assert render_confirmations(proposed.events, env.tools.today()) == ""


def test_drafts_cannot_be_priorities(env):
    d = env.tools.propose_tasks(env.ctx(), tasks=[_proposal("제안된 일")])["proposed"][0]["id"]

    out = env.tools.set_priorities(env.ctx(), cadence="day", period="2026-10-24", task_ids=[d])
    assert "error" in out
    assert env.repo.priorities("day", "2026-10-24") == []

    env.tools.confirm_tasks(env.ctx(), ids=[d])  # 확정하면 올릴 수 있다
    out = env.tools.set_priorities(env.ctx(), cadence="day", period="2026-10-24", task_ids=[d])
    assert [t["id"] for t in out["priorities"]] == [d]


def test_list_tasks_default_hides_drafts(env):
    env.tools.add_task(env.ctx(), title="열린 일", areas=["career"])
    env.tools.propose_tasks(env.ctx(), tasks=[_proposal("초안 일")])

    assert [t["title"] for t in env.tools.list_tasks(env.ctx())["tasks"]] == ["열린 일"]
    assert [t["title"] for t in env.tools.list_tasks(env.ctx(), status="draft")["tasks"]] == ["초안 일"]


def test_reopen_never_opens_dropped_draft(env):
    d = env.tools.propose_tasks(env.ctx(), tasks=[_proposal("뺀 초안")])["proposed"][0]["id"]
    env.tools.drop_task(env.ctx(), id=d)
    expired = env.tools.propose_tasks(env.ctx(), tasks=[_proposal("만료된 초안")])["proposed"][0]["id"]
    env.repo.expire_drafts(env.clock.now() + timedelta(seconds=1))

    for i in (d, expired):
        assert "error" in env.tools.reopen_task(env.ctx(), id=i)
        assert env.repo.get(i).status is TaskStatus.dropped
    # 아직 초안인 것도 reopen으로 열 수 없다(확정은 confirm_tasks로만)
    live = env.tools.propose_tasks(env.ctx(), tasks=[_proposal("초안")])["proposed"][0]["id"]
    assert "error" in env.tools.reopen_task(env.ctx(), id=live)
    # 확정했다가 내려놓은 것은 전에 열려 있었으니 되돌릴 수 있다
    c = env.tools.propose_tasks(env.ctx(), tasks=[_proposal("확정 뒤 뺀 일")])["proposed"][0]["id"]
    env.tools.confirm_tasks(env.ctx(), ids=[c])
    env.tools.drop_task(env.ctx(), id=c)
    assert env.tools.reopen_task(env.ctx(), id=c)["status"] == "open"


async def test_propose_and_confirm_reachable_through_mcp_handler(env):
    import json

    from my_planner.tools.mcp_adapter import TOOL_NAMES, build_planner_tools

    assert {"propose_tasks", "confirm_tasks"} <= set(TOOL_NAMES)
    ctx = env.ctx(conv=9)
    handlers = {t.name: t for t in build_planner_tools(env.tools, ctx)}
    assert "tasks" in handlers["propose_tasks"].input_schema["properties"]
    assert handlers["confirm_tasks"].input_schema["required"] == ["ids"]

    res = await handlers["propose_tasks"].handler({"tasks": [_proposal("산책", areas=["health"])]})
    assert res["is_error"] is False
    tid = json.loads(res["content"][0]["text"])["proposed"][0]["id"]
    res = await handlers["confirm_tasks"].handler({"ids": [tid]})
    assert json.loads(res["content"][0]["text"])["confirmed"][0]["status"] == "open"
    assert [e.kind for e in ctx.events] == ["tasks_proposed", "tasks_confirmed"]


async def test_brain_todos_always_get_a_date(env):
    # 비서가 날짜를 빼고 넣은 할 일은 오늘로 들어간다(날짜 없는 할 일은 앱 목록 어디에도 안 보였다)
    import json

    from my_planner.tools.mcp_adapter import build_planner_tools

    handlers = {t.name: t for t in build_planner_tools(env.tools, env.ctx(conv=9))}
    today = env.tools.today().isoformat()
    res = await handlers["add_task"].handler({"title": "치과 예약", "areas": ["health"]})
    added = json.loads(res["content"][0]["text"])
    res = await handlers["add_task"].handler({"title": "책", "areas": ["learning"], "planned_for": "2026-11-02"})
    dated = json.loads(res["content"][0]["text"])
    res = await handlers["propose_tasks"].handler({"tasks": [_proposal("산책"), _proposal("정리", planned_for="2026-11-03")]})
    proposed = json.loads(res["content"][0]["text"])["proposed"]

    assert env.repo.get(added["id"]).planned_for.isoformat() == today
    assert env.repo.get(dated["id"]).planned_for.isoformat() == "2026-11-02"
    assert [env.repo.get(p["id"]).planned_for.isoformat() for p in proposed] == [today, "2026-11-03"]

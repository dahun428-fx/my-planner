import json
from datetime import time

import pytest
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import RunContext
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools
from my_planner.tools.mcp_adapter import TOOL_NAMES, build_planner_server, build_planner_tools

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)


class ToolEnv:
    def __init__(self, tmp_path, conn, now=None):
        self.clock = FakeClock(now or kst(2026, 10, 24, 10, 0))
        self.repo = TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY)
        self.transcripts = TranscriptStore(tmp_path / "data", TZ, BOUNDARY)
        self.export_path = tmp_path / "data" / "exports" / "tasks.md"
        self.tools = Tools(
            tasks=self.repo,
            transcripts=self.transcripts,
            export_path=self.export_path,
            clock=self.clock,
            tz=TZ,
            boundary=BOUNDARY,
        )
        self.conn = conn

    def ctx(self, conv=1):
        return RunContext(conversation_id=conv, run_id=None, events=[])


@pytest.fixture
def env(tmp_path, conn):
    return ToolEnv(tmp_path, conn)


def test_add_task_creates_open_task_and_exports(env):
    ctx = env.ctx()
    out = env.tools.add_task(ctx, title="치과", areas=["health"], scheduled_at="2026-10-25T14:00")

    assert isinstance(out["id"], int) and "error" not in out
    assert out["status"] == "open"
    assert "치과" in env.export_path.read_text(encoding="utf-8")
    row = env.conn.execute("SELECT * FROM tool_events_log").fetchone()
    assert (row["task_id"], row["conversation_id"], row["kind"]) == (out["id"], 1, "task_added")
    assert [e.kind for e in ctx.events] == ["task_added"]
    assert ctx.tool_names == ["add_task"]


def test_add_task_bad_area_returns_error_dict(env):
    out = env.tools.add_task(env.ctx(), title="운동", areas=["sports"])
    assert "error" in out and "영역" in out["error"]
    assert env.conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_add_task_requires_area(env):
    for areas in (None, []):
        assert "error" in env.tools.add_task(env.ctx(), title="운동", areas=areas)


def test_title_length_limits(env):
    assert "error" in env.tools.add_task(env.ctx(), title="", areas=["health"])
    assert "error" in env.tools.add_task(env.ctx(), title="가" * 201, areas=["health"])
    assert "error" not in env.tools.add_task(env.ctx(), title="가" * 200, areas=["health"])


def test_complete_then_reopen_clears_completed_at(env):
    t = env.tools.add_task(env.ctx(), title="보고서", areas=["career"])
    assert "error" not in env.tools.complete_task(env.ctx(), id=t["id"])
    done = env.tools.list_tasks(env.ctx(), status="done")["tasks"]
    assert [d["id"] for d in done] == [t["id"]] and done[0]["completed_at"]

    assert "error" not in env.tools.reopen_task(env.ctx(), id=t["id"])
    assert env.tools.list_tasks(env.ctx(), status="done")["tasks"] == []
    assert env.tools.list_tasks(env.ctx(), status="open")["tasks"][0]["completed_at"] is None


def test_move_task_to_no_date(env):
    t = env.tools.add_task(env.ctx(), title="운동", areas=["health"], planned_for="2026-10-25")
    assert t["planned_for"] == "2026-10-25"
    out = env.tools.move_task(env.ctx(), id=t["id"], planned_for=None)
    assert out["planned_for"] is None and "error" not in out


def test_list_tasks_limit_capped_at_50(env):
    for i in range(55):
        env.tools.add_task(env.ctx(), title=f"일{i}", areas=["career"])
    assert len(env.tools.list_tasks(env.ctx(), limit=500)["tasks"]) == 50


def test_list_excludes_soft_deleted(env):
    t = env.tools.add_task(env.ctx(), title="지울 일", areas=["career"])
    env.conn.execute("UPDATE tasks SET deleted_at = '2026-10-24T00:00:00+00:00'")
    assert env.tools.list_tasks(env.ctx())["tasks"] == []
    assert "error" in env.tools.complete_task(env.ctx(), id=t["id"])


def test_parent_must_exist(env):
    assert "error" in env.tools.add_task(env.ctx(), title="첫 걸음", areas=["career"], parent_id=99)
    p = env.tools.add_task(env.ctx(), title="큰 일", areas=["career"])
    c = env.tools.add_task(env.ctx(), title="첫 걸음", areas=["career"], parent_id=p["id"])
    assert c["parent_id"] == p["id"]


def test_read_transcript_more_than_7_days_returns_error(env):
    assert "error" in env.tools.read_transcript(env.ctx(), **{"from": "2026-10-01", "to": "2026-10-08"})
    ok = env.tools.read_transcript(env.ctx(), **{"from": "2026-10-01", "to": "2026-10-07"})
    assert "error" not in ok


async def test_two_servers_keep_separate_contexts(env):
    ctx_a, ctx_b = env.ctx(conv=1), env.ctx(conv=2)
    handlers_a = {t.name: t.handler for t in build_planner_tools(env.tools, ctx_a)}
    handlers_b = {t.name: t.handler for t in build_planner_tools(env.tools, ctx_b)}
    assert list(handlers_a) == TOOL_NAMES

    res = await handlers_a["add_task"]({"title": "A의 일", "areas": ["career"]})
    await handlers_b["add_task"]({"title": "B의 일", "areas": ["career"]})
    assert json.loads(res["content"][0]["text"])["title"] == "A의 일" and not res["is_error"]
    assert [e.data["title"] for e in ctx_a.events] == ["A의 일"]
    assert [e.data["title"] for e in ctx_b.events] == ["B의 일"]
    convs = [r["conversation_id"] for r in env.conn.execute("SELECT * FROM tool_events_log ORDER BY id")]
    assert convs == [1, 2]

    bad = await handlers_a["add_task"]({"title": "", "areas": ["career"]})
    assert bad["is_error"] is True
    assert build_planner_server(env.tools, ctx_a)["name"] == "planner"

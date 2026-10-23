import json
from datetime import time

import pytest
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import Area, RunContext, TaskStatus
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools
from my_planner.tools.mcp_adapter import (
    TOOL_NAMES,
    build_planner_server,
    build_planner_tools,
)

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


def _log(env):
    return [
        (r["kind"], r["task_id"], r["conversation_id"])
        for r in env.conn.execute("SELECT * FROM tool_events_log ORDER BY id")
    ]


def _event_kinds(env, task_id):
    return [
        r["kind"]
        for r in env.conn.execute("SELECT kind FROM task_events WHERE task_id = ? ORDER BY id", (task_id,))
    ]


def test_add_task_rolls_back_when_event_log_write_fails(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("log down")

    monkeypatch.setattr(env.repo, "log_tool_event", boom)
    with pytest.raises(RuntimeError):
        env.tools.add_task(env.ctx(), title="치과", areas=["health"])
    assert env.conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert env.conn.execute("SELECT count(*) FROM task_areas").fetchone()[0] == 0
    assert env.conn.execute("SELECT count(*) FROM task_events").fetchone()[0] == 0


def test_complete_rolls_back_when_event_log_write_fails(env, monkeypatch):
    t = env.tools.add_task(env.ctx(), title="치과", areas=["health"])
    monkeypatch.setattr(env.repo, "log_tool_event", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        env.tools.complete_task(env.ctx(), id=t["id"])
    assert env.repo.get(t["id"]).status.value == "open"


def test_every_mutating_tool_writes_tool_events_log(env):
    t = env.tools.add_task(env.ctx(conv=7), title="일", areas=["career"])["id"]
    env.tools.update_task(env.ctx(conv=7), id=t, note="메모")
    env.tools.move_task(env.ctx(conv=7), id=t, planned_for="2026-10-26")
    env.tools.complete_task(env.ctx(conv=7), id=t)
    env.tools.reopen_task(env.ctx(conv=7), id=t)
    env.tools.drop_task(env.ctx(conv=7), id=t)
    assert _log(env) == [
        ("task_added", t, 7),
        ("task_updated", t, 7),
        ("task_moved", t, 7),
        ("task_completed", t, 7),
        ("task_reopened", t, 7),
        ("task_dropped", t, 7),
    ]


def test_reopen_dropped_task_records_reopened_event(env):
    t = env.tools.add_task(env.ctx(), title="일", areas=["career"])["id"]
    env.tools.drop_task(env.ctx(), id=t)
    out = env.tools.reopen_task(env.ctx(), id=t)
    assert out["status"] == "open" and "error" not in out
    assert _event_kinds(env, t) == ["created", "dropped", "reopened"]


def test_tasks_md_reflects_complete_and_move_and_skips_drafts(env):
    a = env.tools.add_task(env.ctx(), title="완료할일", areas=["career"], planned_for="2026-10-24")["id"]
    b = env.tools.add_task(env.ctx(), title="옮길일", areas=["career"], planned_for="2026-10-24")["id"]
    env.repo.create("초안일", ["career"], status="draft", planned_for=None)

    def section(name):
        text = env.export_path.read_text(encoding="utf-8")
        return text.split(f"## {name}")[1].split("\n## ")[0]

    env.tools.complete_task(env.ctx(), id=a)
    assert "완료할일" not in section("오늘") and "[x] #" in section("이번 주 완료")
    assert "완료할일" in section("이번 주 완료")
    env.tools.move_task(env.ctx(), id=b, planned_for="2026-10-25")
    assert "옮길일" not in section("오늘") and "옮길일" in section("이번 주")
    assert "초안일" not in env.export_path.read_text(encoding="utf-8")


def test_add_task_early_morning_schedule_belongs_to_previous_logical_day(env):
    out = env.tools.add_task(env.ctx(), title="새벽", areas=["health"], scheduled_at="2026-10-25T01:30")
    assert out["planned_for"] == "2026-10-24"


def test_move_task_keeps_local_time_of_scheduled_task(env):
    t = env.tools.add_task(env.ctx(), title="치과", areas=["health"], scheduled_at="2026-10-25T14:00")
    out = env.tools.move_task(env.ctx(), id=t["id"], planned_for="2026-10-28")
    assert out["planned_for"] == "2026-10-28"
    assert out["scheduled_at"] == "2026-10-28T14:00+09:00"
    assert _event_kinds(env, t["id"])[-1] == "moved"


def test_move_task_to_no_date_clears_schedule(env):
    t = env.tools.add_task(env.ctx(), title="치과", areas=["health"], scheduled_at="2026-10-25T14:00")
    out = env.tools.move_task(env.ctx(), id=t["id"], planned_for=None)
    assert out["planned_for"] is None and out["scheduled_at"] is None


def test_update_scheduled_at_rederives_planned_for(env):
    t = env.tools.add_task(env.ctx(), title="치과", areas=["health"], planned_for="2026-10-25", scheduled_at="2026-10-25T14:00")
    out = env.tools.update_task(env.ctx(), id=t["id"], scheduled_at="2026-10-27T09:00")
    assert out["planned_for"] == "2026-10-27"
    out = env.tools.update_task(env.ctx(), id=t["id"], scheduled_at="2026-10-29T02:00")
    assert out["planned_for"] == "2026-10-28"


def test_move_early_morning_schedule_keeps_logical_date(env):
    t = env.tools.add_task(env.ctx(), title="새벽 운동", areas=["health"], scheduled_at="2026-10-25T01:30")
    assert t["planned_for"] == "2026-10-24"
    out = env.tools.move_task(env.ctx(), id=t["id"], planned_for="2026-10-27")
    assert out["planned_for"] == "2026-10-27"
    assert out["scheduled_at"] == "2026-10-28T01:30+09:00"  # 논리적 날짜 10/27의 새벽 1시 30분


def _three(env):
    return [env.tools.add_task(env.ctx(), title=n, areas=["career"])["id"] for n in ("A", "B", "C")]


def _prio(env, cadence="week", period="2026-W43"):
    return [t.title for t in env.repo.priorities(cadence, period)]


def test_set_priorities_replaces_whole_period(env):
    a, b, c = _three(env)
    ctx = env.ctx()
    out = env.tools.set_priorities(ctx, cadence="week", period="2026-W43", task_ids=[a, b, c])
    assert "error" not in out and [t["id"] for t in out["priorities"]] == [a, b, c]
    assert _prio(env) == ["A", "B", "C"]
    assert ctx.tool_names == ["set_priorities"]
    assert [e.kind for e in ctx.events] == ["priorities_set"]
    assert env.conn.execute("SELECT kind FROM tool_events_log ORDER BY id").fetchall()[-1]["kind"] == "priorities_set"

    env.tools.set_priorities(env.ctx(), cadence="week", period="2026-W43", task_ids=[c, a])
    assert _prio(env) == ["C", "A"]
    env.tools.set_priorities(env.ctx(), cadence="day", period="2026-10-24", task_ids=[b])
    assert _prio(env) == ["C", "A"] and _prio(env, "day", "2026-10-24") == ["B"]
    env.tools.set_priorities(env.ctx(), cadence="week", period="2026-W43", task_ids=[])
    assert _prio(env) == []


def test_set_priorities_four_returns_error(env):
    a, b, c = _three(env)
    d = env.tools.add_task(env.ctx(), title="D", areas=["career"])["id"]
    env.tools.set_priorities(env.ctx(), cadence="week", period="2026-W43", task_ids=[a])
    ctx = env.ctx()
    out = env.tools.set_priorities(ctx, cadence="week", period="2026-W43", task_ids=[a, b, c, d])
    assert "error" in out and "3" in out["error"]
    assert _prio(env) == ["A"]  # 기존 우선순위는 그대로
    assert ctx.events == []


def test_set_priorities_rejects_draft_and_done(env):
    a, b, _ = _three(env)
    draft = env.repo.create("초안", [Area.career], TaskStatus.draft, None, None, None, "").id
    env.tools.complete_task(env.ctx(), id=b)
    env.tools.set_priorities(env.ctx(), cadence="week", period="2026-W43", task_ids=[a])
    for bad in (draft, b, 999):
        ctx = env.ctx()
        out = env.tools.set_priorities(ctx, cadence="week", period="2026-W43", task_ids=[a, bad])
        assert "error" in out
        assert ctx.events == []
    assert _prio(env) == ["A"]


def test_priority_unique_task_per_period(env):
    a, b, _ = _three(env)
    ctx = env.ctx()
    out = env.tools.set_priorities(ctx, cadence="week", period="2026-W43", task_ids=[a, b, a])
    assert "error" in out and ctx.events == []
    assert _prio(env) == []
    # 같은 할 일이 다른 기간(오늘과 이번 주)에 오르는 것은 괜찮다
    env.tools.set_priorities(env.ctx(), cadence="week", period="2026-W43", task_ids=[a])
    out = env.tools.set_priorities(env.ctx(), cadence="day", period="2026-10-24", task_ids=[a])
    assert "error" not in out


def test_drop_removes_from_priorities(env):
    a, b, c = _three(env)
    env.tools.set_priorities(env.ctx(), cadence="week", period="2026-W43", task_ids=[a, b, c])
    env.tools.set_priorities(env.ctx(), cadence="day", period="2026-10-24", task_ids=[b])
    env.tools.drop_task(env.ctx(), id=b)
    assert _prio(env) == ["A", "C"] and _prio(env, "day", "2026-10-24") == []
    ranks = [r["rank"] for r in env.conn.execute("SELECT rank FROM priorities WHERE cadence='week'")]
    assert sorted(ranks) == [1, 3]  # 순위 번호는 다시 매기지 않는다(스펙: 행만 지운다)


def test_set_priorities_rejects_bad_cadence_or_period(env):
    a, _, _ = _three(env)
    for cadence, period in (
        ("decade", "2026"),
        ("week", "2026-10-24"),
        ("day", "내일"),
        ("month", "2026-13"),
        ("quarter", "2026-Q5"),
        ("week", "2026-W54"),
        ("week", None),
    ):
        out = env.tools.set_priorities(env.ctx(), cadence=cadence, period=period, task_ids=[a])
        assert "error" in out, (cadence, period)
    for cadence, period in (("day", "2026-10-24"), ("week", "2026-W43"), ("month", "2026-10"),
                            ("quarter", "2026-Q4"), ("year", "2026")):
        assert "error" not in env.tools.set_priorities(env.ctx(), cadence=cadence, period=period, task_ids=[a])


async def test_set_priorities_reachable_through_mcp_handler(env):
    a, b, _ = _three(env)
    ctx = env.ctx()
    handlers = {t.name: t.handler for t in build_planner_tools(env.tools, ctx)}
    assert "set_priorities" in TOOL_NAMES
    res = await handlers["set_priorities"](
        {"cadence": "week", "period": "2026-W43", "task_ids": [a, b]}
    )
    assert res["is_error"] is False
    assert _prio(env) == ["A", "B"]

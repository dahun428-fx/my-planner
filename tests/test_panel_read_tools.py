"""SP15-07: 라이프 매니저·전문가 읽기 도구와 도구 목록(T2, 스펙 6.1).

도구를 직접 부른다. 글과 값은 꾸며 낸 것이다.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.clock import to_iso
from my_planner.domain import RunContext
from my_planner.store.db import transaction
from my_planner.tools.mcp_adapter import (
    _SPECS,
    APP_ONLY_TOOLS,
    DAYEND_TOOLS,
    EXPERT_TOOLS,
    MANAGER_HIDDEN_TOOLS,
    MANAGER_READ_TOOLS,
    MATE_TOOLS,
    PANEL_WRITE_TOOLS,
    REPORT_TOOLS,
    TOOL_NAMES,
    build_planner_tools,
    tool_names_for,
)

MON = kst(2026, 11, 2, 13, 0)  # 월요일 낮, 논리적 오늘 2026-11-02

EXPERT_TABLE = {
    "career": ["read_tasks_career", "read_measures_career", "search_memos", "read_memo", "list_statements",
               "read_benchmark"],
    "finance": ["read_measures_finance", "read_tasks_finance", "list_statements", "read_benchmark"],
    "health": ["get_measures", "read_body_days", "list_workouts", "read_conditions", "read_benchmark"],
    "image": ["read_measures_looks", "list_chat_photos", "read_benchmark"],
    "relationship": ["read_schedule_shape", "read_measures_relationships", "list_statements",
                     "read_tasks_relationships", "read_benchmark"],
    "psych": ["read_conditions", "read_moments", "get_curve", "read_reviews", "read_panel_results", "read_benchmark"],
}
MATE_WRITES = {"save_body_note", "drop_body_note", "set_workout_plan", "log_workout", "update_workout_log",
               "delete_workout_log", "record_condition"}
SECRETARY_READS = {"list_tasks", "list_habits", "get_curve", "get_status", "read_transcript"}
_APP_WRITE_PREFIXES = ("create_", "update_", "delete_", "pin_", "unpin_")


def _user() -> RunContext:
    return RunContext(conversation_id=None, run_id=None, actor="user", channel="app")


def _manager(conversation_id: int | None = None, chip: str | None = None) -> RunContext:
    return RunContext(conversation_id, None, channel="app", agent="manager", chip=chip, in_brain=True)


def _ok(out: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in out, out
    return out


# --- 도구 목록 (T2) ---


async def test_manager_tool_list(tmp_path):
    names = tool_names_for(RunContext(None, None, channel="app", agent="manager"))
    head = [*MANAGER_READ_TOOLS, *PANEL_WRITE_TOOLS]
    assert names[: len(head)] == head
    tail = names[len(head):]
    expert_only: list[str] = []
    for tools in EXPERT_TABLE.values():
        expert_only += [n for n in tools if n not in head and n not in expert_only]
    assert tail == expert_only == MANAGER_HIDDEN_TOOLS
    assert len(names) == len(set(names))
    for banned in ("save_life_report", "write_note", "hand_off", "add_task", "create_event", "log_workout",
                   "set_workout_plan", "create_memo", "complete_task"):
        assert banned not in names, banned
    full = tool_names_for(RunContext(None, None, channel="app", agent="manager", chip="manager_full"))
    assert full[: len(head) + 1] == [*head, "save_life_report"]
    assert full[len(head) + 1:] == tail
    for name in full:
        assert name in _SPECS, name
    async with BeEnv.start(tmp_path, start=MON) as env:
        built = [x.name for x in build_planner_tools(env.parts.tools, _manager(chip="manager_full"))]
    assert built == full


def test_expert_tools_read_only():
    writes = (
        (set(TOOL_NAMES) - SECRETARY_READS)
        | {n for n in APP_ONLY_TOOLS if n.startswith(_APP_WRITE_PREFIXES)}
        | {"reorder_cards", "set_checkin_time", "propose_measures"}
        | MATE_WRITES
        | set(PANEL_WRITE_TOOLS) | set(REPORT_TOOLS) | set(DAYEND_TOOLS)
    )
    assert EXPERT_TOOLS == EXPERT_TABLE
    assert list(EXPERT_TOOLS) == ["career", "finance", "health", "image", "relationship", "psych"]
    for expert, names in EXPERT_TOOLS.items():
        assert not set(names) & writes, expert
        for name in names:
            assert name in _SPECS, name
    assert MATE_WRITES <= set(MATE_TOOLS)


async def test_panel_write_skeleton_not_ready(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        for name in (*PANEL_WRITE_TOOLS[:3], *REPORT_TOOLS):
            assert getattr(t, name)(_manager(1)) == {"error": "아직 없어요."}, name


# --- 측정값 범위 ---


async def test_measure_scopes(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        _ok(t.save_measures(_user(), source_kind="manual", rows=[
            {"metric": "salary_krw", "value": 12_340_000, "measured_on": "2026-10-20"},
            {"metric": "net_worth_krw", "value": 5678, "measured_on": "2026-10-20"},
            {"metric": "body_fat_pct", "value": 21.5, "measured_on": "2026-10-20"},
            {"metric": "face_rating", "value": 55, "measured_on": "2026-10-20"},
            {"metric": "support_people", "value": 3, "measured_on": "2026-10-20"},
            {"metric": "company_tier", "value": 7, "measured_on": "2026-10-20"},
            {"metric": "profile_sex", "value": "m", "measured_on": "2026-10-20"},
        ]))
        ids = {r["metric"]: r["id"] for r in env.conn.execute("SELECT id, metric FROM standing_measures")}
        ctx = _manager(1)
        got = {
            name: _ok(getattr(t, name)(ctx))["measures"]
            for name in ("read_measures_career", "read_measures_finance", "read_measures_looks",
                         "read_measures_relationships", "read_measures_all", "get_measures")
        }
    metrics = {name: {m["metric"] for m in rows} for name, rows in got.items()}
    assert metrics["read_measures_career"] == {"salary_krw", "company_tier"}
    assert metrics["read_measures_finance"] == {"net_worth_krw", "salary_krw"}
    assert metrics["read_measures_looks"] == {"body_fat_pct", "face_rating"}
    assert metrics["read_measures_relationships"] == {"support_people"}
    assert metrics["read_measures_all"] == set(ids) - {"profile_sex"}
    assert metrics["get_measures"] == {"body_fat_pct", "face_rating"}
    for rows in got.values():
        for m in rows:
            assert m["ref"] == f"measure:{ids[m['metric']]}"
            assert set(m) == {"metric", "label", "value", "unit", "measured_on", "reliability", "ref"}


# --- 일정 모양 ---


async def test_schedule_shape_has_no_titles(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        ev = _ok(t.create_event(_user(), title="비밀일정XYZ", date="2026-11-05", time="19:30", duration_min=90,
                                note="비밀메모XYZ", area="relationships"))
        _ok(t.create_event(_user(), title="먼 일정", date="2026-12-20", time="10:00"))
        out = _ok(t.read_schedule_shape(_manager(1)))
        assert "error" in t.read_schedule_shape(_manager(1), days=29)
        assert "error" in t.read_schedule_shape(_manager(1), days=0)
    text = json.dumps(out, ensure_ascii=False)
    assert "비밀일정XYZ" not in text and "비밀메모XYZ" not in text
    assert out == {"items": [{
        "ref": f"event:{ev['id']}", "date": "2026-11-05", "start": "19:30", "minutes": 90, "all_day": False,
        "area": "relationships",
    }]}


# --- 영역별 할 일 ---


async def test_tasks_by_area_and_window(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        u = _user()
        open_id = _ok(t.add_task(u, title="가짜 커리어 열림", areas=["career"], planned_for="2026-11-03"))["id"]
        old_id = _ok(t.add_task(u, title="가짜 커리어 오래 전", areas=["career"], planned_for="2026-09-01"))["id"]
        recent_id = _ok(t.add_task(u, title="가짜 커리어 최근", areas=["career"], planned_for="2026-10-23"))["id"]
        _ok(t.add_task(u, title="가짜 건강", areas=["health"], planned_for="2026-11-03"))
        dropped_id = _ok(t.add_task(u, title="가짜 커리어 버림", areas=["career"], planned_for="2026-11-01"))["id"]
        env.parts.tasks.set_status(dropped_id, "dropped")
        for tid, days in ((old_id, 60), (recent_id, 10)):
            _ok(t.complete_task(u, id=tid))
            env.conn.execute("UPDATE tasks SET completed_at = ? WHERE id = ?",
                             (to_iso(MON - timedelta(days=days)), tid))
        env.conn.commit()
        out = _ok(t.read_tasks_career(_manager(1)))
        assert _ok(t.read_tasks_finance(_manager(1))) == {"items": []}
        assert _ok(t.read_tasks_relationships(_manager(1))) == {"items": []}
    assert out == {"items": [
        {"ref": f"task:{open_id}", "title": "가짜 커리어 열림", "status": "open", "planned_for": "2026-11-03",
         "completed_on": None},
        {"ref": f"task:{dropped_id}", "title": "가짜 커리어 버림", "status": "dropped", "planned_for": "2026-11-01",
         "completed_on": "2026-11-02"},
        {"ref": f"task:{recent_id}", "title": "가짜 커리어 최근", "status": "done", "planned_for": "2026-10-23",
         "completed_on": "2026-10-23"},
    ]}


# --- 기준표 ---


async def test_read_benchmark(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        out = _ok(t.read_benchmark(_manager(1), key="income"))
        bad = t.read_benchmark(_manager(1), key="nope")
        meta = t.read_benchmark(_manager(1), key="version")
        keys = _ok(t.read_benchmark(_manager(1)))
    assert out["ref"] == "bench:income"
    assert out["source"] and out["year"] == 2026 and out["estimate"] is True
    assert "national" in out["table"] and "source" not in out["table"]
    assert bad["error"].startswith("기준표에 없는 키예요. 키: height, looks, ")
    assert meta == bad
    assert keys["keys"][:2] == ["height", "looks"] and "version" not in keys["keys"]


# --- 내가 한 말 ---


async def test_list_statements_refs(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        panel = env.parts.panel
        assert panel is not None
        now = env.clock.now()
        with transaction(env.conn):
            keep = panel.add_statement("fact", "career", "가짜 사실 하나", now=now)
            gone = panel.add_statement("preference", None, "가짜 지운 말", now=now)
            panel.retire(gone, now)
        out = _ok(env.parts.tools.list_statements(_manager(1)))
    refs = [i["ref"] for i in out["items"]]
    assert refs == ["decision:career_first", f"statement:{keep}"]
    assert out["items"][1] == {"ref": f"statement:{keep}", "kind": "fact", "area": "career", "text": "가짜 사실 하나"}
    assert f"statement:{gone}" not in refs


# --- 사진 ---


def _conv(env, agent: str) -> int:
    return int(env.conn.execute(
        "INSERT INTO conversations (kind, channel, logical_date, opened_at, last_message_at, agent) "
        "VALUES ('chat', 'app', '2026-11-02', 'a', 'a', ?)", (agent,),
    ).lastrowid)


async def test_chat_photos_only_this_conversation(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        assert t.photos is not None
        man, sec = _conv(env, "manager"), _conv(env, "secretary")
        pids = []
        for i, conv in enumerate((man, sec)):
            p = t.photos.insert(env.conn, sha256=f"{i:064x}", path=f"p{i}.jpg", thumb_path=f"t{i}.jpg", bytes=10,
                                width=10, height=10, origin="chat", now=env.clock.now())
            t.photos.link_message(env.conn, 100 + i, conv, [p.id])
            pids.append(p.id)
        t.photos.set_read_text(env.conn, pids[0], "가짜 읽은 글")
        env.conn.commit()
        out = _ok(t.list_chat_photos(_manager(man)))
        none = _ok(t.list_chat_photos(_manager(None)))
    assert out == {"items": [{"photo_id": pids[0], "date": "2026-11-02", "read_text": "가짜 읽은 글"}]}
    assert none == {"items": []}


# --- 그 밖의 읽기 ---


async def test_other_reads_shape(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        t = env.parts.tools
        ctx = _manager(1)
        _ok(t.record_condition(_user(), score=4, note="가짜 메모글"))
        cond = _ok(t.read_conditions(ctx))
        assert "error" in t.read_conditions(ctx, days=57)
        assert "error" in t.read_body_days(ctx, days=0)
        assert "error" in t.read_moments(ctx, days=181)
        assert "error" in t.read_panel_results(ctx, weeks=13)
        assert _ok(t.read_body_days(ctx)) == {"items": []}
        assert _ok(t.read_moments(ctx)) == {"items": []}
        assert _ok(t.read_reviews(ctx)) == {"items": []}
        assert _ok(t.read_panel_results(ctx)) == {"items": []}
        panel = env.parts.panel
        assert panel is not None
        with transaction(env.conn):
            env.conn.execute(
                "INSERT INTO curve_area_scores (period, area, score, note, recorded_at) VALUES "
                "('2026-Q3', 'career', 6, '가짜 회고', 'a')"
            )
            kw: dict[str, Any] = {"conversation_id": None, "kind": "task", "area": "career", "size_min": 30,
                                  "per_week": None, "due_hint": None, "experts": ["career"],
                                  "evidence": [{"type": "record", "ref": "task:1", "note": "가짜"}],
                                  "now": env.clock.now()}
            now_id = panel.add_suggestion(title="가짜 이번 주", week="2026-W45", **kw)
            panel.add_suggestion(title="가짜 오래 전", week="2026-W30", **kw)
        reviews = _ok(t.read_reviews(ctx))
        results = _ok(t.read_panel_results(ctx))
    assert cond == {"items": [{"date": "2026-11-02", "score": 4}]}
    assert reviews == {"items": [
        {"ref": "review:2026-Q3:career", "period": "2026-Q3", "area": "career", "score": 6, "note": "가짜 회고"},
    ]}
    assert results == {"items": [{"ref": f"suggestion:{now_id}", "title": "가짜 이번 주", "area": "career",
                                  "state": "proposed", "dismiss_reason": None, "week": "2026-W45"}]}

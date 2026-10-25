"""이룬 순간 도구 `save_moments` (SP8 스펙 6.3 M1~M5, 6.6). 도구를 직접 부른다. 내용은 꾸며 낸 것이다."""

from __future__ import annotations

import json
from datetime import date, time

import pytest
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import RunContext
from my_planner.store.repos.activity import ActivityRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.moments import MomentsRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools
from my_planner.tools.mcp_adapter import (
    _SPECS,
    APP_ONLY_TOOLS,
    TOOL_NAMES,
    build_planner_tools,
    tool_names_for,
)

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
TICK = kst(2026, 10, 26, 4, 1)
DAY = date(2026, 10, 24)
REFS = frozenset({"task:12", "habit:3", "condition", "chat"})

NOT_HERE = "쓸 수 없는 도구예요."
OTHER_DATE = "이 날짜만 정리할 수 있어요."
TOO_MANY = "이룬 순간은 하루 3개까지예요."
BAD_SOURCES = "근거로 쓸 수 없는 항목이 있어요."
GOOD = "포트폴리오 사례 하나를 끝까지 다듬었어요"


class MomentsEnv:
    def __init__(self, tmp_path, conn):
        self.clock = FakeClock(TICK)
        self.conn = conn
        self.activity = ActivityRepo(conn, self.clock)
        self.status = StatusRepo(conn, self.clock)
        self.moments = MomentsRepo(conn, self.clock)
        self.tools = Tools(
            tasks=TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY),
            transcripts=TranscriptStore(tmp_path / "data", TZ, BOUNDARY),
            export_path=tmp_path / "data" / "exports" / "tasks.md", clock=self.clock, tz=TZ, boundary=BOUNDARY,
            activity=self.activity, status=self.status, habits=HabitsRepo(conn, self.clock), moments=self.moments,
        )

    def ctx(self, day=DAY, refs=REFS):
        return RunContext(None, None, kind="moments", activity_channel="scheduler", moments_date=day, moments_refs=refs)

    def save(self, items, *, ctx=None, day="2026-10-24"):
        return self.tools.save_moments(ctx or self.ctx(), date=day, moments=items)

    def rows(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM status_moments ORDER BY date, slot")]

    def acts(self):
        return [self.activity.get(r[0]) for r in self.conn.execute("SELECT id FROM activity ORDER BY id")]

    def day_row(self, d="2026-10-24"):
        r = self.conn.execute("SELECT * FROM status_moment_days WHERE date = ?", (d,)).fetchone()
        return dict(r) if r else None


@pytest.fixture
def env(tmp_path, conn):
    return MomentsEnv(tmp_path, conn)


def _m(text=GOOD, area="career", sources=("task:12",)):
    return {"text": text, "area": area, "sources": list(sources)}


# --- 도구 목록 (6.3 인터페이스) ---


def test_tool_names_moments_kind_only_save_moments(env):
    ctx = env.ctx()
    assert tool_names_for(ctx) == ["save_moments"]
    assert [t.name for t in build_planner_tools(env.tools, ctx)] == ["save_moments"]
    for channel in ("telegram", "app"):  # 통로와 상관없이
        ctx = RunContext(None, None, kind="moments", channel=channel)
        assert [t.name for t in build_planner_tools(env.tools, ctx)] == ["save_moments"]
    schema = _SPECS["save_moments"][1]
    assert schema["required"] == ["date", "moments"] and schema["additionalProperties"] is False
    items = schema["properties"]["moments"]
    assert items["maxItems"] == 3
    item = items["items"]
    assert item["properties"]["text"]["maxLength"] == 60
    assert None in item["properties"]["area"]["enum"]
    assert (item["properties"]["sources"]["minItems"], item["properties"]["sources"]["maxItems"]) == (1, 5)


def test_chat_and_run_tool_lists_have_no_save_moments(env):
    assert "save_moments" not in TOOL_NAMES and "save_moments" not in APP_ONLY_TOOLS
    for kind in ("chat", "run"):
        for channel, n in (("telegram", 28), ("app", 36)):
            ctx = RunContext(None, None, kind=kind, channel=channel)
            names = tool_names_for(ctx)
            assert len(names) == n and "save_moments" not in names
            assert [t.name for t in build_planner_tools(env.tools, ctx)] == names


def test_save_moments_rejected_outside_moments_kind(env):
    for ctx in (
        RunContext(conversation_id=7, run_id=None, inbound_id=1001),
        RunContext(conversation_id=7, run_id=3, kind="run", activity_channel="scheduler"),
        RunContext(None, None, channel="app", moments_date=DAY, moments_refs=REFS),  # 날짜가 있어도 kind가 아니면
    ):
        assert env.save([_m()], ctx=ctx) == {"error": NOT_HERE}
    assert env.rows() == [] and env.day_row() is None and env.acts() == []


# --- M1, M2 ---


def test_m1_other_date_error(env):
    assert env.save([_m()], day="2026-10-23") == {"error": OTHER_DATE}
    assert env.save([_m()], day="2026-10-24T00:00") == {"error": OTHER_DATE}
    assert env.save([_m()], day=None) == {"error": OTHER_DATE}
    ctx = RunContext(None, None, kind="moments", moments_refs=REFS)  # 작업 날짜가 없으면 아무 날도 안 된다
    assert env.save([_m()], ctx=ctx) == {"error": OTHER_DATE}
    assert env.rows() == [] and env.day_row() is None


def test_m2_more_than_3_error_saves_nothing(env):
    assert env.save([_m(), _m("둘째"), _m("셋째"), _m("넷째")]) == {"error": TOO_MANY}
    shape = {"error": "moments는 0~3개의 배열로 보내 주세요."}
    assert env.save("하나") == shape and env.save(None) == shape  # 배열이 아니거나 없으면
    assert env.rows() == [] and env.day_row() is None and env.acts() == []


def test_m2_source_not_in_input_error(env):
    for sources in ((), ("task:99",), ("task:12", "memo:1"), ("task:12",) * 6, (12,)):
        assert env.save([_m(), _m("둘째", sources=sources)]) == {"error": BAD_SOURCES}, sources
    bad_area = env.save([_m(area="money")])
    assert "error" in bad_area and "career" in bad_area["error"]
    assert env.rows() == [] and env.day_row() is None


def test_moment_text_strip_codepoints_and_newline(env):
    """Review Focus 3: 앞뒤 공백은 빼고 코드포인트로 센다(SQLite `length()`와 같다)."""
    for bad in ("가" * 61, "   ", "", "첫 줄\n둘째 줄", "탭\t글", "글\x07", "줄\u2028바꿈", "방향\u202e글", None, 5):
        out = env.save([_m(text=bad)])
        assert "error" in out, bad
        assert out["error"] not in (OTHER_DATE, TOO_MANY, BAD_SOURCES, NOT_HERE)
    assert env.rows() == []
    sixty = "가" * 60
    assert env.save([_m(text=f"  {sixty}\n "), _m(text=" 산책을 즐겼어요 ", area=None, sources=["chat"])]) == {
        "saved": 2, "rejected": 0,
    }
    rows = env.rows()
    assert [r["text"] for r in rows] == [sixty, "산책을 즐겼어요"]
    assert conn_length(env, rows[0]["id"]) == 60


def conn_length(env, moment_id):
    return env.conn.execute("SELECT length(text) FROM status_moments WHERE id = ?", (moment_id,)).fetchone()[0]


# --- M3 금지어 ---


def test_m3_banned_item_dropped_others_saved(env):
    out = env.save([_m("지난번 실패한 발표를 다시 했어요"), _m("물을 챙겨 마셨어요", "health", ["habit:3"])])
    assert out == {"saved": 1, "rejected": 1}
    rows = env.rows()
    assert [(r["slot"], r["text"], r["area"]) for r in rows] == [(1, "물을 챙겨 마셨어요", "health")]
    assert json.loads(rows[0]["sources_json"]) == ["habit:3"]
    assert env.day_row()["state"] == "done" and env.day_row()["saved"] == 1


def test_m3_does_not_drop_good_phrases(env):
    out = env.save([_m("지출이 줄었어요", "finance", ["condition"])])
    assert out == {"saved": 1, "rejected": 0}
    assert env.rows()[0]["text"] == "지출이 줄었어요"


# --- M4, M5 ---


def test_m4_second_call_already(env):
    assert env.save([_m()]) == {"saved": 1, "rejected": 0}
    assert env.save([_m("다른 글"), _m("또 다른 글")]) == {"already": True}
    assert [r["text"] for r in env.rows()] == [GOOD]
    assert env.day_row()["saved"] == 1
    assert len(env.acts()) == 1


def test_zero_moments_marks_done(env):
    assert env.save([]) == {"saved": 0, "rejected": 0}
    assert env.rows() == [] and (env.day_row()["state"], env.day_row()["saved"]) == ("done", 0)


def test_m5_one_transaction(env, monkeypatch):
    def boom(**kw):
        raise RuntimeError("활동 쓰기 실패")

    monkeypatch.setattr(env.activity, "add", boom)
    with pytest.raises(RuntimeError):
        env.save([_m(), _m("둘째", sources=["chat"])])
    assert env.rows() == [] and env.day_row() is None
    assert env.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 0


def test_moments_activity_summary_has_date_only(env):
    ctx = env.ctx()
    assert env.save([_m("꾸며 낸 순간 글"), _m("꾸며 낸 둘째 글", sources=["chat"])], ctx=ctx) == {
        "saved": 2, "rejected": 0,
    }
    (a,) = env.acts()
    assert (a.kind, a.target, a.summary) == ("moments_saved", "moments:2026-10-24", "이룬 순간 2개 정리 (10/24)")
    assert (a.actor, a.channel, a.undo) == ("secretary", "scheduler", None)
    row = dict(env.conn.execute("SELECT * FROM activity").fetchone())
    assert "꾸며 낸" not in json.dumps(row, ensure_ascii=False)
    assert ctx.undo_ids == []
    (e,) = ctx.events
    assert (e.kind, e.task_id, e.data) == ("moments_saved", None, {"date": "2026-10-24", "saved": 2, "rejected": 0})
    assert ctx.tool_names == ["save_moments"]


def test_no_xp_from_moments(env):
    before = env.status.total()
    kinds = [r[0] for r in env.conn.execute("SELECT source_kind FROM status_xp_ledger")]
    env.save([_m(), _m("둘째", sources=["chat"])])
    assert env.status.total() == before
    assert [r[0] for r in env.conn.execute("SELECT source_kind FROM status_xp_ledger")] == kinds
    assert env.ctx().xp.gained == 0


def test_no_moments_repo_rejects(env):
    env.tools.moments = None
    assert env.save([_m()]) == {"error": NOT_HERE}

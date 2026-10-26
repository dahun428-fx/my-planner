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
    tool_description,
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
        for channel, n in (("telegram", 28), ("app", 49)):  # SP6 G-BE2 화면 도구 넷, SP9-03 메모 도구 3개, SP9-05 일정 도구 4개·`ui_events`, SP9-09 `find_conversations`(앱에만)
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


# --- `get_status`의 이룬 순간: 통로마다 (SP8 6.7, 10.3, 1장 조건 7) ---

SECRET_A = "꾸며 낸 순간: 산책을 30분 했어요"
SECRET_B = "꾸며 낸 순간: 친구에게 먼저 연락했어요"
SECRET_OLD = "꾸며 낸 순간: 8일 전 일"
SECRET_HIDDEN = "꾸며 낸 순간: 숨긴 것"


def _status_tools(env):
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.curve import CurveRepo

    env.tools.curve = CurveRepo(env.conn, env.clock)
    env.tools.conditions = ConditionsRepo(env.conn, env.clock)
    m = env.moments
    now = env.clock.now()
    a, b = m.save_day(date(2026, 10, 24), [(SECRET_A, "health", ["chat"]), (SECRET_B, None, ["task:12"])], now)
    m.save_day(date(2026, 10, 22), [("꾸며 낸 순간: 22일", "career", ["habit:3"])], now)
    m.save_day(date(2026, 10, 19), [(SECRET_OLD, None, ["chat"])], now)  # 10/26 기준 7일 밖(14일 안)
    (h,) = m.save_day(date(2026, 10, 23), [(SECRET_HIDDEN, None, ["chat"])], now)
    m.hide(h.id, now)
    return a, b


def test_get_status_telegram_has_dates_and_counts_only(env):
    _status_tools(env)
    out = env.tools.get_status(RunContext(None, None, channel="telegram"))
    text = json.dumps(out, ensure_ascii=False)

    assert out["moments"] == [{"date": "2026-10-24", "count": 2}, {"date": "2026-10-22", "count": 1}]
    for secret in (SECRET_A, SECRET_B, SECRET_OLD, SECRET_HIDDEN, "꾸며 낸"):
        assert secret not in text
    run = env.tools.get_status(RunContext(None, None, kind="run", activity_channel="scheduler"))
    assert "꾸며 낸" not in json.dumps(run, ensure_ascii=False)  # 회차 차례도 `ctx.channel`(telegram) 그대로


def test_get_status_app_has_text_last_7_days(env):
    a, b = _status_tools(env)
    out = env.tools.get_status(RunContext(None, None, channel="app"))

    assert [(m["id"], m["text"]) for m in out["moments"]] == [
        (a.id, SECRET_A), (b.id, SECRET_B), (out["moments"][2]["id"], "꾸며 낸 순간: 22일"),
    ]
    assert out["moments"][0] == {
        "id": a.id, "date": "2026-10-24", "text": SECRET_A, "area": "health", "sources": ["chat"], "hidden": False,
    }
    text = json.dumps(out, ensure_ascii=False)
    assert SECRET_OLD not in text and SECRET_HIDDEN not in text


def test_get_status_body_numbers_app_only(env):
    """SP8 10.3, 11장(S2 판정): 걸음·잠 7일 평균은 앱 통로만 받는다. 텔레그램 대화와 회차 차례는 `body`가 null이고
    건강 영역의 `body_days`(날 수)만 남는다. 숫자는 꾸며 낸 것이다."""
    from my_planner.store.repos.body import BodyDay, BodyRepo

    _status_tools(env)
    env.tools.body = BodyRepo(env.conn, env.clock)
    env.tools.body.upsert(
        [BodyDay(date(2026, 10, d), 7321, 437) for d in (23, 24, 25)], env.clock.now(),
    )

    app = env.tools.get_status(RunContext(None, None, channel="app"))
    assert app["body"]["steps_avg_7"] == 7321 and app["body"]["sleep_avg_7"] == 437
    for ctx in (
        RunContext(None, None, channel="telegram"),
        RunContext(None, None, kind="run", activity_channel="scheduler"),
    ):
        out = env.tools.get_status(ctx)
        assert out["body"] is None
        health = next(s for s in out["stats"] if s["area"] == "health")
        assert health["activity"]["body_days"] == 3
        text = json.dumps(out, ensure_ascii=False)
        assert "7321" not in text and "437" not in text


def test_read_transcript_telegram_omits_app_secretary_lines(env):
    """SP8 1장 조건 7, 11장: 앱 대화의 비서 줄은 이룬 순간의 글을 옮겨 말했을 수 있다. 텔레그램 통로(회차 차례 포함)의
    `read_transcript`에는 그 줄이 없다. 앱 사용자 줄과 텔레그램 줄은 그대로다. 앱 통로는 그 대화의 줄을 모두 받는다."""
    tr = env.tools.transcripts
    tr.append(kst(2026, 10, 24, 9, 0), "사용자", 1, None, "꾸민 텔레그램 질문")
    tr.append(kst(2026, 10, 24, 9, 1), "비서", 1, None, "꾸민 텔레그램 답")
    tr.append(kst(2026, 10, 24, 20, 0), "사용자", 2, None, "꾸민 앱 질문", channel="app", message_id="m-1")
    tr.append(kst(2026, 10, 24, 20, 1), "비서", 2, None, f"어제 순간: {SECRET_A}", ["get_status"],
              channel="app", message_id="m-2")
    tr.append(kst(2026, 10, 24, 21, 0), "사용자", 1, None, "꾸민 텔레그램 둘째 질문")
    args = {"from": "2026-10-24", "to": "2026-10-24"}
    tele = env.tools.read_transcript(RunContext(None, None, channel="telegram"), **args)["text"]
    run = env.tools.read_transcript(RunContext(None, None, kind="run", activity_channel="scheduler"), **args)["text"]
    app = env.tools.read_transcript(RunContext(2, None, channel="app"), **args)["text"]  # SP9-09: 이 대화(2)의 줄만

    for text in (tele, run):
        assert SECRET_A not in text and "get_status" not in text
        for kept in ("꾸민 텔레그램 질문", "꾸민 텔레그램 답", "꾸민 앱 질문", "꾸민 텔레그램 둘째 질문"):
            assert kept in text, kept
    assert SECRET_A in app and "꾸민 앱 질문" in app


def test_app_read_transcript_only_current_conversation(env):
    """SP9 7.5, ADR 0014: 앱 통로의 `read_transcript`는 이 대화(`ctx.conversation_id`)의 줄만 준다. 다른 대화의
    원문(앱이든 텔레그램이든)은 나가지 않는다. 대화가 없으면 빈 글. 텔레그램 통로는 그대로다."""
    tr = env.tools.transcripts
    tr.append(kst(2026, 10, 24, 9, 0), "사용자", 1, None, "A 대화 고유문자열-ALPHA", channel="app", message_id="a-1")
    tr.append(kst(2026, 10, 24, 9, 1), "비서", 1, None, "A 답 ALPHA-REPLY", channel="app", message_id="a-2")
    tr.append(kst(2026, 10, 24, 9, 30), "사용자", 3, None, "텔레그램 줄 TELE-ONLY")
    tr.append(kst(2026, 10, 24, 10, 0), "사용자", 2, None, "B 대화 질문 BRAVO", channel="app", message_id="b-1")
    tr.append(kst(2026, 10, 24, 10, 1), "비서", 2, None, "B 답 BRAVO-REPLY", channel="app", message_id="b-2")
    args = {"from": "2026-10-24", "to": "2026-10-24"}
    b = env.tools.read_transcript(RunContext(2, None, channel="app"), **args)["text"]
    none = env.tools.read_transcript(RunContext(None, None, channel="app"), **args)["text"]
    tele = env.tools.read_transcript(RunContext(3, None, channel="telegram"), **args)["text"]

    assert "BRAVO" in b and "BRAVO-REPLY" in b
    for other in ("ALPHA", "TELE-ONLY"):
        assert other not in b and other not in none
    assert "BRAVO" not in none
    for kept in ("ALPHA", "TELE-ONLY", "BRAVO"):  # 텔레그램 통로는 SP8 그대로(앱 사용자 줄 포함)
        assert kept in tele
    assert "ALPHA-REPLY" not in tele and "BRAVO-REPLY" not in tele
    assert "이 대화" in tool_description("read_transcript", RunContext(2, None, channel="app"))
    assert "이 대화" not in tool_description("read_transcript", RunContext(3, None, channel="telegram"))

"""습관 도구 (SP7 스펙 5.3, 5.4 규칙 H1~H7, 부록 A). 도구를 직접 부른다. 내용은 꾸며 낸 것이다."""

from __future__ import annotations

import json
import logging
from datetime import date, time

import pytest
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import RunContext
from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.confirmations import (
    confirmation_line,
    habit_line,
    render_confirmations,
)
from my_planner.tools.core import Tools
from my_planner.tools.mcp_adapter import TOOL_NAMES, build_planner_tools, tool_names_for

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
SAT_1300 = kst(2026, 10, 24, 13, 0)  # 논리적 오늘 = 10/24(토)
RUN_ID = 340

CAP = "습관은 한 번에 10개까지 챙길 수 있어요. 하나를 쉬어 가거나 그만두면 더할 수 있어요."
DUP = "이미 있는 습관이에요."
FUTURE = "아직 오지 않은 날은 체크할 수 없어요."
RANGE = "오늘 포함 7일 안의 날만 체크할 수 있어요."
PAUSED = "쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요."
TARGET = "주 몇 번인지 1~6으로 알려 주세요. 매일이면 매일 습관으로 만들어요."
RUN_TURN = "사용자가 말한 습관만 체크할 수 있어요."
NOT_FOUND = "없는 습관이에요."


class HabitEnv:
    def __init__(self, tmp_path, conn, now=SAT_1300):
        self.clock = FakeClock(now)
        self.conn = conn
        self.tasks = TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY)
        self.habits = HabitsRepo(conn, self.clock)
        self.activity = ActivityRepo(conn, self.clock)
        self.confirms = ConfirmsRepo(conn, self.clock)
        self.status = StatusRepo(conn, self.clock)
        self.export_dir = tmp_path / "data" / "exports"
        self.tools = Tools(
            tasks=self.tasks, transcripts=TranscriptStore(tmp_path / "data", TZ, BOUNDARY),
            export_path=self.export_dir / "tasks.md", clock=self.clock, tz=TZ, boundary=BOUNDARY,
            activity=self.activity, confirms=self.confirms, reply_until=lambda run_id: kst(2026, 10, 24, 23, 0),
            status=self.status, habits=self.habits,
        )

    def user(self, channel="telegram", inbound_id=1001):
        """사용자 메시지에 답하는 차례(A3)."""
        return RunContext(conversation_id=7, run_id=None, inbound_id=inbound_id, channel=channel)

    def button(self, channel="app"):
        """버튼·`/actions`(사용자)."""
        return RunContext(conversation_id=None, run_id=None, actor="user", channel=channel)

    def run(self, channel="telegram"):
        """회차 차례(A1)."""
        return RunContext(conversation_id=7, run_id=RUN_ID, activity_channel="scheduler", channel=channel)

    def add(self, title="물 마시기", area="health", kind="daily", target=None, ctx=None):
        out = self.tools.add_habit(ctx or self.user(), title=title, area=area, kind=kind, target_per_week=target)
        assert "error" not in out, out
        return out["id"]

    def rows(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM habits ORDER BY id")]

    def checks(self):
        return [tuple(r) for r in self.conn.execute("SELECT habit_id, date FROM habit_checks ORDER BY 1, 2")]

    def tool_log(self):
        return self.conn.execute("SELECT * FROM tool_events_log ORDER BY id").fetchall()

    def acts(self):
        return self.conn.execute("SELECT * FROM activity ORDER BY id").fetchall()


@pytest.fixture
def env(tmp_path, conn):
    return HabitEnv(tmp_path, conn)


# --- 추가, 규칙 H1~H3, 상한 ---


def test_add_habit_daily_and_weekly(env):
    ctx = env.user()
    a = env.tools.add_habit(ctx, title="물 마시기", area="health", kind="daily")
    b = env.tools.add_habit(ctx, title="운동", area="health", kind="weekly", target_per_week=3)

    assert a == {"id": a["id"], "title": "물 마시기", "area": "health", "kind": "daily", "target_per_week": None,
                 "status": "active", "checked": False, "week_count": 0}
    assert (b["kind"], b["target_per_week"]) == ("weekly", 3)
    assert [r["sort_order"] for r in env.rows()] == [1, 2]
    assert ctx.tool_names == ["add_habit", "add_habit"]
    assert [e.kind for e in ctx.events] == ["habit_added", "habit_added"]
    assert ctx.events[1].task_id is None
    assert ctx.events[1].data == {"habit_id": b["id"], "title": "운동", "label": "주 3회", "date": None}
    acts = env.acts()
    assert [(r["kind"], r["target"], r["summary"]) for r in acts] == [
        ("habit_added", f"habit:{a['id']}", "✓ 습관 추가: 물 마시기 (매일)"),
        ("habit_added", f"habit:{b['id']}", "✓ 습관 추가: 운동 (주 3회)"),
    ]
    assert json.loads(acts[0]["undo_json"]) == {"habit_id": a["id"]}


@pytest.mark.parametrize("bad", [
    {"kind": "daily", "target_per_week": 3},
    {"kind": "weekly"},
    {"kind": "weekly", "target_per_week": None},
    {"kind": "weekly", "target_per_week": 0},
    {"kind": "weekly", "target_per_week": 7},
    {"kind": "weekly", "target_per_week": "3"},
    {"kind": "weekly", "target_per_week": True},
])
def test_kind_target_mismatch_rejected(env, bad):
    out = env.tools.add_habit(env.user(), title="운동", area="health", **bad)
    assert out == {"error": TARGET}
    assert env.rows() == []


def test_add_habit_input_errors(env):
    ctx = env.user()
    assert "error" in env.tools.add_habit(ctx, title="  ", area="health", kind="daily")
    assert "error" in env.tools.add_habit(ctx, title="가" * 41, area="health", kind="daily")
    assert "영역" in env.tools.add_habit(ctx, title="운동", area="sports", kind="daily")["error"]
    assert "error" in env.tools.add_habit(ctx, title="운동", area="health", kind="monthly")
    assert env.rows() == []


def test_title_strip_and_duplicate(env):
    """Review Focus 3: 앞뒤 공백은 빼고 저장, 같은 제목 거절(추가·이름 바꾸기·그만둔 습관 다시 시작)."""
    ctx = env.user()
    a = env.add(" 운동 ")
    assert env.habits.get(a).title == "운동"
    assert env.tools.add_habit(ctx, title="운동", area="health", kind="daily") == {"error": DUP}
    assert env.tools.add_habit(ctx, title="  운동", area="learning", kind="weekly", target_per_week=2) == {
        "error": DUP}
    # 대소문자는 그대로 비교한다(다른 제목)
    env.add("Run")
    assert "error" not in env.tools.add_habit(ctx, title="run", area="health", kind="daily")
    # 이모지가 든 40자 제목은 받는다
    emoji = "🏃" + "가" * 39
    assert len(emoji) == 40
    e = env.add(emoji)
    assert env.habits.get(e).title == emoji
    # 쉬는 습관도 같은 제목이다
    assert env.tools.set_habit_status(ctx, id=a, status="paused")["status"] == "paused"
    assert env.tools.add_habit(ctx, title="운동", area="health", kind="daily") == {"error": DUP}
    # 이름 바꾸기
    b = env.add("물 마시기")
    assert env.tools.update_habit(ctx, id=b, title=" 운동 ") == {"error": DUP}
    assert env.tools.update_habit(ctx, id=b, title=" 물 마시기 ")["title"] == "물 마시기"  # 자기 이름은 된다
    # 그만두면 같은 제목을 새로 만들 수 있고, 그때 그만둔 습관의 다시 시작은 거절한다
    assert env.tools.set_habit_status(ctx, id=a, status="archived")["status"] == "archived"
    c = env.add("운동")
    assert env.tools.set_habit_status(ctx, id=a, status="active") == {"error": DUP}
    assert env.habits.get(a).status == "archived"
    # 새 습관을 그만두면 이전 것을 다시 시작할 수 있다
    env.tools.set_habit_status(ctx, id=c, status="archived")
    assert env.tools.set_habit_status(ctx, id=a, status="active")["status"] == "active"


def test_active_cap_10(env):
    ctx = env.user()
    ids = [env.add(f"습관{i}") for i in range(10)]
    assert env.tools.add_habit(ctx, title="열한째", area="health", kind="daily") == {"error": CAP}
    # 쉬는 습관은 세지 않는다. 쉬어 가면 하나 더할 수 있고, 그때 다시 시작은 거절한다
    env.tools.set_habit_status(ctx, id=ids[0], status="paused")
    new = env.add("열한째")
    assert env.tools.set_habit_status(ctx, id=ids[0], status="active") == {"error": CAP}
    env.tools.set_habit_status(ctx, id=new, status="archived")
    assert env.tools.set_habit_status(ctx, id=ids[0], status="active")["status"] == "active"
    assert env.habits.count_active() == 10


# --- 체크·취소 (5.3) ---


def test_check_date_range_today_minus_6_ok_minus_7_rejected_future_rejected(env):
    h = env.add()
    ctx = env.user()
    ok = env.tools.check_habit(ctx, id=h, date="2026-10-18")  # 오늘(10/24) 포함 7일의 첫날
    assert ok["date"] == "2026-10-18" and ok["already"] is False
    assert env.tools.check_habit(ctx, id=h, date="2026-10-17") == {"error": RANGE}
    assert env.tools.check_habit(ctx, id=h, date="2026-10-25") == {"error": FUTURE}
    assert env.tools.uncheck_habit(ctx, id=h, date="2026-10-17") == {"error": RANGE}
    assert env.tools.uncheck_habit(ctx, id=h, date="2026-10-25") == {"error": FUTURE}
    for bad in ("20261020", "2026-W43-5", "10/20", 20261020):
        assert env.tools.check_habit(ctx, id=h, date=bad) == {"error": "date는 YYYY-MM-DD 형식으로 알려 주세요."}
    assert env.checks() == [(h, "2026-10-18")]
    # 추가한 날 이전 날짜도 7일 안이면 받는다
    assert env.tools.check_habit(ctx, id=h)["date"] == "2026-10-24"
    out = env.tools.uncheck_habit(ctx, id=h, date="2026-10-18")
    assert (out["date"], out["already"], out["habit"]["checked"]) == ("2026-10-18", False, False)
    assert env.checks() == [(h, "2026-10-24")]


def test_check_at_0130_counts_previous_logical_day(tmp_path, conn):
    """Review Focus 1: 10/25 01:30의 체크는 10/24, 10/26(월) 02:00의 체크는 10/25(일), 전 주(W43)."""
    env = HabitEnv(tmp_path, conn, now=kst(2026, 10, 25, 1, 30))
    h = env.add("운동", kind="weekly", target=3)
    first = env.tools.check_habit(env.user(), id=h)
    env.clock.set(kst(2026, 10, 26, 2, 0))
    second = env.tools.check_habit(env.user(), id=h)

    assert first["date"] == "2026-10-24" and second["date"] == "2026-10-25"
    assert env.checks() == [(h, "2026-10-24"), (h, "2026-10-25")]
    assert second["habit"]["week_count"] == 2  # 둘 다 2026-W43
    listed = env.tools.list_habits(env.user())
    assert (listed["date"], listed["week"]) == ("2026-10-25", "2026-W43")
    assert listed["items"][0]["checked"] is True and listed["items"][0]["week_count"] == 2


def test_check_paused_rejected(env):
    a, b = env.add("물 마시기"), env.add("운동")
    env.tools.check_habit(env.user(), id=b)
    env.tools.set_habit_status(env.user(), id=a, status="paused")
    env.tools.set_habit_status(env.user(), id=b, status="archived")
    assert env.tools.check_habit(env.user(), id=a) == {"error": PAUSED}
    assert env.tools.check_habit(env.user(), id=b) == {"error": PAUSED}
    assert env.tools.uncheck_habit(env.user(), id=b) == {"error": PAUSED}
    assert env.checks() == [(b, "2026-10-24")]


def test_check_twice_already_true(env):
    h = env.add()
    ctx = env.user()
    first = env.tools.check_habit(ctx, id=h)
    acts = len(env.acts())
    second = env.tools.check_habit(ctx, id=h)
    assert first["already"] is False and second["already"] is True
    assert second["habit"]["checked"] is True and second["habit"]["week_count"] == 1
    assert len(env.acts()) == acts  # 바꾸지 않았으니 활동도 없다
    assert [e.kind for e in ctx.events] == ["habit_checked"]
    env.tools.uncheck_habit(ctx, id=h)
    again = env.tools.uncheck_habit(ctx, id=h)
    assert again["already"] is True and again["habit"]["checked"] is False
    assert [e.kind for e in ctx.events] == ["habit_checked", "habit_unchecked"]


def test_deleted_habit_not_found(env):
    h = env.add()
    env.habits.soft_delete(h, env.clock.now())
    ctx = env.user()
    for call in (
        lambda: env.tools.check_habit(ctx, id=h),
        lambda: env.tools.uncheck_habit(ctx, id=h),
        lambda: env.tools.update_habit(ctx, id=h, title="새 이름"),
        lambda: env.tools.set_habit_status(ctx, id=h, status="paused"),
        lambda: env.tools.check_habit(ctx, id=999),
        lambda: env.tools.check_habit(ctx, id="1"),
        lambda: env.tools.check_habit(ctx, id=True),
    ):
        assert call() == {"error": NOT_FOUND}
    assert env.tools.list_habits(ctx, status="all")["items"] == []
    # 지운 습관의 제목은 다시 쓸 수 있다
    assert "error" not in env.tools.add_habit(ctx, title="물 마시기", area="health", kind="daily")


def test_list_habits_status_and_date(env):
    a, b = env.add("물 마시기"), env.add("운동", kind="weekly", target=2)
    env.tools.check_habit(env.user(), id=a, date="2026-10-20")
    env.tools.set_habit_status(env.user(), id=b, status="paused")
    ctx = env.user()
    assert [x["id"] for x in env.tools.list_habits(ctx)["items"]] == [a]
    assert [x["id"] for x in env.tools.list_habits(ctx, status="paused")["items"]] == [b]
    assert [x["id"] for x in env.tools.list_habits(ctx, status="all")["items"]] == [a, b]
    day = env.tools.list_habits(ctx, date="2026-10-20")
    assert (day["date"], day["week"], day["items"][0]["checked"]) == ("2026-10-20", "2026-W43", True)
    assert env.tools.list_habits(ctx, status="done") == {"error": "status는 active, paused, archived, all 중 하나예요."}
    assert env.tools.list_habits(ctx, date="어제") == {"error": "date는 YYYY-MM-DD 형식으로 알려 주세요."}
    assert ctx.events == []


# --- 회차 차례 (규칙 H6, H7) ---


def test_run_turn_check_add_rejected(env):
    h = env.add()
    env.tools.check_habit(env.user(), id=h, date="2026-10-23")
    before = (env.rows(), env.checks(), len(env.acts()))
    for channel in ("telegram", "app"):
        ctx = env.run(channel)
        assert env.tools.check_habit(ctx, id=h) == {"error": RUN_TURN}
        assert env.tools.uncheck_habit(ctx, id=h, date="2026-10-23") == {"error": RUN_TURN}
        assert env.tools.add_habit(ctx, title="스트레칭", area="health", kind="daily") == {"error": RUN_TURN}
        assert ctx.events == []
    assert (env.rows(), env.checks(), len(env.acts())) == before
    # 읽기는 된다
    assert env.tools.list_habits(env.run())["items"][0]["id"] == h


def test_run_turn_archive_and_update_need_confirm_pause_applies(env):
    a = env.add("운동", kind="weekly", target=3)
    b = env.add("물 마시기")
    rows = env.rows()
    ctx = env.run()

    archive = env.tools.set_habit_status(ctx, id=a, status="archived")
    weekly = env.tools.update_habit(ctx, id=a, target_per_week=2)
    daily = env.tools.update_habit(ctx, id=a, kind="daily")
    rename = env.tools.update_habit(ctx, id=b, title="물 두 잔")
    rename_ro = env.tools.update_habit(ctx, id=b, title="산책")
    assert env.rows() == rows  # 아무것도 바꾸지 않았다

    assert archive == {"status": "needs_confirm", "confirm_token": archive["confirm_token"],
                       "summary": "운동 습관을 그만둘까요? 기록은 남아요."}
    assert weekly["summary"] == "운동 습관을 주 2회로 바꿀까요?"
    assert daily["summary"] == "운동 습관을 매일로 바꿀까요?"
    assert rename["summary"] == "물 마시기 습관 이름을 물 두 잔으로 바꿀까요?"
    assert rename_ro["summary"] == "물 마시기 습관 이름을 산책으로 바꿀까요?"
    tokens = env.conn.execute("SELECT * FROM pending_confirms ORDER BY created_at, rowid").fetchall()
    assert [(t["action"], json.loads(t["args_json"])) for t in tokens] == [
        ("set_habit_status", {"id": a, "status": "archived"}),
        ("update_habit", {"id": a, "target_per_week": 2}),
        ("update_habit", {"id": a, "kind": "daily"}),
        ("update_habit", {"id": b, "title": "물 두 잔"}),
        ("update_habit", {"id": b, "title": "산책"}),
    ]
    assert [e.data["button"] for e in ctx.events] == [
        "그만두기: 운동", "습관 고치기: 운동", "습관 고치기: 운동", "습관 고치기: 물 마시기", "습관 고치기: 물 마시기"]
    # 잘못된 입력은 토큰 없이 오류
    assert env.tools.update_habit(ctx, id=a, kind="daily", target_per_week=2) == {"error": TARGET}
    assert env.tools.update_habit(ctx, id=b, title="운동") == {"error": DUP}
    # 쉬어 가기는 바로 적용한다
    paused = env.tools.set_habit_status(ctx, id=a, status="paused")
    assert paused["status"] == "paused" and env.habits.get(a).status == "paused"
    (act,) = [r for r in env.acts() if r["kind"] == "habit_status_set"]
    assert (act["actor"], act["channel"], act["summary"]) == ("secretary", "scheduler", "✓ 습관 쉬어 가기: 운동")


def test_user_turn_applies_directly(env):
    a = env.add("운동", kind="weekly", target=3)
    for ctx in (env.user(), env.user("app"), env.button(), env.button("telegram")):
        assert env.tools.update_habit(ctx, id=a, target_per_week=2)["target_per_week"] == 2
        assert env.tools.set_habit_status(ctx, id=a, status="archived")["status"] == "archived"
        assert env.tools.set_habit_status(ctx, id=a, status="active")["status"] == "active"
        assert env.tools.check_habit(ctx, id=a)["habit"]["checked"] is True
        assert env.tools.uncheck_habit(ctx, id=a)["habit"]["checked"] is False
    assert env.conn.execute("SELECT COUNT(*) FROM pending_confirms").fetchone()[0] == 0


# --- 확인 문구 (규칙 H4, 부록 A), 호출 기록 (규칙 H5) ---


def test_confirmation_lines(env):
    today = date(2026, 10, 24)
    assert [
        habit_line("habit_added", "물 마시기", label="매일", today=today),
        habit_line("habit_added", "운동", label="주 3회", today=today),
        habit_line("habit_checked", "물 마시기", day=today, today=today),
        habit_line("habit_checked", "물 마시기", day=date(2026, 10, 22), today=today),
        habit_line("habit_unchecked", "물 마시기", day=date(2026, 10, 22), today=today),
        habit_line("habit_status_set", "운동", label="paused", today=today),
        habit_line("habit_status_set", "운동", label="active", today=today),
        habit_line("habit_status_set", "운동", label="archived", today=today),
        habit_line("habit_updated", "운동", label="주 2회", today=today),
    ] == [
        "✓ 습관 추가: 물 마시기 (매일)",
        "✓ 습관 추가: 운동 (주 3회)",
        "✓ 습관: 물 마시기",
        "✓ 습관: 물 마시기 (10/22)",
        "↩ 습관 체크 취소: 물 마시기",
        "✓ 습관 쉬어 가기: 운동",
        "✓ 습관 다시 시작: 운동",
        "✓ 습관 그만두기: 운동",
        "✓ 습관 고침: 운동 (주 2회)",
    ]
    # 도구가 낸 이벤트로 하네스가 같은 문구를 만든다(활동 `summary`도 같다)
    ctx = env.user()
    w = env.tools.add_habit(ctx, title="물 마시기", area="health", kind="daily")["id"]
    r = env.tools.add_habit(ctx, title="운동", area="health", kind="weekly", target_per_week=3)["id"]
    env.tools.check_habit(ctx, id=w)
    env.tools.check_habit(ctx, id=w, date="2026-10-22")
    env.tools.uncheck_habit(ctx, id=w, date="2026-10-22")
    env.tools.set_habit_status(ctx, id=r, status="paused")
    env.tools.set_habit_status(ctx, id=r, status="active")
    env.tools.update_habit(ctx, id=r, target_per_week=2)
    env.tools.set_habit_status(ctx, id=r, status="archived")
    lines = render_confirmations(ctx.events, today).split("\n")
    assert lines == [
        "✓ 습관 추가: 물 마시기 (매일)",
        "✓ 습관 추가: 운동 (주 3회)",
        "✓ 습관: 물 마시기",
        "✓ 습관: 물 마시기 (10/22)",
        "↩ 습관 체크 취소: 물 마시기",
        "✓ 습관 쉬어 가기: 운동",
        "✓ 습관 다시 시작: 운동",
        "✓ 습관 고침: 운동 (주 2회)",
        "✓ 습관 그만두기: 운동",
    ]
    assert [r["summary"] for r in env.acts()] == lines
    assert confirmation_line(ctx.events[3], today) == "✓ 습관: 물 마시기 (10/22)"
    banned = ("연속", "스트릭", "달성률", "밀렸다", "놓쳤다", "실패", "끊겼", "며칠째", "남음")
    assert not [w for w in banned for line in lines if w in line]


def test_check_does_not_write_tool_events_log(env):
    h = env.add()
    n = len(env.tool_log())
    env.tools.check_habit(env.user(), id=h)
    env.tools.uncheck_habit(env.user(), id=h)
    env.tools.check_habit(env.user(), id=h, date="2026-10-23")
    assert len(env.tool_log()) == n
    assert [r["kind"] for r in env.acts()][-3:] == ["habit_checked", "habit_unchecked", "habit_checked"]


def test_add_writes_tool_events_log_with_inbound_id(env):
    ctx = env.user(inbound_id=5551)
    h = env.tools.add_habit(ctx, title="물 마시기", area="health", kind="daily")["id"]
    env.tools.update_habit(ctx, id=h, title="물 두 잔")
    env.tools.set_habit_status(ctx, id=h, status="paused")
    rows = env.tool_log()
    assert [(r["kind"], r["inbound_id"], r["conversation_id"], r["task_id"]) for r in rows] == [
        ("habit_added", 5551, 7, None), ("habit_updated", 5551, 7, None), ("habit_status_set", 5551, 7, None)]
    assert [json.loads(r["data_json"]) for r in rows] == [
        {"habit_id": h, "title": "물 마시기", "label": "매일", "date": None},
        {"habit_id": h, "title": "물 두 잔", "label": "매일", "date": None},
        {"habit_id": h, "title": "물 두 잔", "label": "paused", "date": None},
    ]
    (a, u, s) = env.acts()
    assert json.loads(u["undo_json"]) == {"habit_id": h, "before": {"title": "물 마시기"}}
    assert json.loads(s["undo_json"]) == {"habit_id": h, "status": "active"}
    assert all(r["inbound_id"] == 5551 for r in (a, u, s))


# --- 내보내기 (5.8), 도구 수 (규칙 H8), 로그 (8장) ---


def test_export_habits_md(env):
    path = env.export_dir / "habits.md"
    w = env.add("물 마시기")
    r = env.add("운동", kind="weekly", target=3)
    s = env.add("스트레칭", area="quality_of_life")
    q = env.add("일기", area="learning")
    for d in ("2026-10-18", "2026-10-22", "2026-10-24"):
        env.tools.check_habit(env.user(), id=w, date=d)
    env.tools.check_habit(env.user(), id=r, date="2026-10-20")
    env.tools.set_habit_status(env.user(), id=s, status="paused")
    env.tools.set_habit_status(env.user(), id=q, status="archived")
    # 지난 4주 = 오늘이 든 주의 3주 전 월요일(9/28, `GET /habits/{id}?weeks=4`의 `from`)부터 오늘까지
    env.conn.execute("INSERT INTO habit_checks VALUES (?, '2026-09-27', '2026-09-27T00:00:00.000000+00:00')", (w,))
    env.conn.execute("INSERT INTO habit_checks VALUES (?, '2026-09-28', '2026-09-28T00:00:00.000000+00:00')", (r,))
    env.conn.commit()
    env.tools.update_habit(env.user(), id=r, title="운동하기")  # 다시 만든다
    text = path.read_text(encoding="utf-8")
    expected = [
        "# 습관",
        "",
        "_이 파일은 자동으로 다시 만들어져요. 직접 고치지 마세요._",
        "",
        "## 챙기는 습관",
        "",
        "- 물 마시기 · 매일 · 건강 · 지난 4주 3번",
        "- 운동하기 · 주 3회 · 건강 · 지난 4주 2번",
        "",
        "## 쉬는 습관",
        "",
        "- 스트레칭 · 매일 · 삶의 질 · 지난 4주 0번",
        "",
        "## 그만둔 습관",
        "",
        "- 일기 · 매일 · 배움 · 지난 4주 0번",
        "",
    ]
    assert text == "\n".join(expected)
    # 되돌리기와 할 일 변경도 같은 `_export`로 다시 만든다(지운 습관은 빠진다)
    env.habits.soft_delete(q, env.clock.now())
    env.tools._export()
    assert "일기" not in path.read_text(encoding="utf-8")
    assert "## 그만둔 습관\n\n(없음)" in path.read_text(encoding="utf-8")


def test_export_habits_skipped_without_repo(tmp_path, conn):
    env = HabitEnv(tmp_path, conn)
    env.tools.habits = None
    env.tools._export()
    assert not (env.export_dir / "habits.md").exists()
    assert env.tools.check_habit(env.user(), id=1) == {"error": "습관을 다룰 수 없어요."}


async def test_telegram_tool_count_28(env):
    habit_tools = ["add_habit", "update_habit", "set_habit_status", "check_habit", "uncheck_habit", "list_habits"]
    assert TOOL_NAMES[22:] == habit_tools
    assert len(tool_names_for("telegram")) == 28 == len(set(tool_names_for("telegram")))
    assert len(tool_names_for("app")) == 35  # 화면 도구 `ui_habit_check`(SP7-06) +1
    ctx = env.user()
    handlers = {t.name: t for t in build_planner_tools(env.tools, ctx)}
    assert list(handlers) == TOOL_NAMES
    for name in habit_tools:
        assert handlers[name].input_schema["additionalProperties"] is False
    out = await handlers["add_habit"].handler(
        {"title": "물 마시기", "area": "health", "kind": "daily"})
    h = json.loads(out["content"][0]["text"])
    assert out["is_error"] is False and h["title"] == "물 마시기"
    out = await handlers["check_habit"].handler({"id": h["id"]})
    assert json.loads(out["content"][0]["text"])["habit"]["checked"] is True
    out = await handlers["check_habit"].handler({"id": h["id"], "date": "2026-10-01"})
    assert out["is_error"] is True and json.loads(out["content"][0]["text"]) == {"error": RANGE}
    out = await handlers["list_habits"].handler({"status": "all"})
    assert [x["id"] for x in json.loads(out["content"][0]["text"])["items"]] == [h["id"]]
    assert ctx.tool_names == ["add_habit", "check_habit", "check_habit", "list_habits"]


def test_logs_have_no_habit_titles(env, caplog):
    caplog.set_level(logging.DEBUG)
    title, renamed = "꾸민습관제목", "꾸민새이름"
    ctx = env.user()
    h = env.tools.add_habit(ctx, title=title, area="health", kind="weekly", target_per_week=3)["id"]
    env.tools.check_habit(ctx, id=h)
    env.tools.check_habit(ctx, id=h)
    env.tools.uncheck_habit(ctx, id=h)
    env.tools.update_habit(ctx, id=h, title=renamed)
    env.tools.set_habit_status(ctx, id=h, status="paused")
    env.tools.set_habit_status(env.run(), id=h, status="active")
    env.tools.update_habit(env.run(), id=h, title=title)  # 회차 차례: 확인 토큰
    env.tools.set_habit_status(env.run(), id=h, status="archived")
    env.tools.list_habits(ctx, status="all")
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert {r.getMessage() for r in caplog.records} >= {
        "habit_added", "habit_checked", "habit_unchecked", "habit_updated", "habit_status_set", "confirm_requested"}
    assert title not in text and renamed not in text
    recs = [r for r in caplog.records if r.getMessage() == "habit_checked"]
    assert [(r.habit_id, r.date, r.already) for r in recs] == [(h, "2026-10-24", False), (h, "2026-10-24", True)]
    # 상태창 "최근 경험치" 줄(원장 `label`)에도 제목이 없다
    assert [r["label"] for r in env.conn.execute("SELECT label FROM status_xp_ledger")] == ["습관 체크"]


# --- 리뷰 뒤 고친 것 ---


def test_update_habit_without_change_is_already(env):
    h = env.add("운동", kind="weekly", target=2)
    log_n, act_n = len(env.tool_log()), len(env.acts())
    for ctx in (env.user(), env.run()):
        out = env.tools.update_habit(ctx, id=h, target_per_week=2, title=" 운동 ", area="health")
        assert out["already"] is True and out["target_per_week"] == 2
        assert ctx.events == [] and ctx.undo_ids == []
    assert (len(env.tool_log()), len(env.acts())) == (log_n, act_n)
    assert env.conn.execute("SELECT COUNT(*) FROM pending_confirms").fetchone()[0] == 0


def test_run_turn_update_summary_without_cadence_change(env):
    a = env.add("운동", kind="weekly", target=3)
    ctx = env.run()
    assert env.tools.update_habit(ctx, id=a, area="learning")["summary"] == "운동 습관을 고칠까요?"
    assert env.tools.update_habit(ctx, id=a, title="달리기", area="learning")["summary"] == "달리기 습관을 고칠까요?"
    assert env.tools.update_habit(ctx, id=a, title="달리기")["summary"] == "운동 습관 이름을 달리기로 바꿀까요?"
    assert env.tools.update_habit(ctx, id=a, area="learning", target_per_week=3)["summary"] == "운동 습관을 고칠까요?"
    assert env.tools.update_habit(ctx, id=a, area="learning", target_per_week=2)["summary"] == (
        "운동 습관을 주 2회로 바꿀까요?")
    assert env.habits.get(a).area.value == "health"


def test_export_area_labels_match_status():
    from my_planner.status.xp import AREA_LABELS
    from my_planner.store.exports import _AREA_LABELS

    assert _AREA_LABELS == AREA_LABELS

"""스케줄 도구 (SP9 스펙 5.1, 5.2, 5.5, 10장, 티켓 SP9-05). 가짜 시계, 내용은 꾸며 낸 것이다.

시험 날짜 2026-10-26(월)~2026-11-01(일).
"""

from __future__ import annotations

import json
import logging
from datetime import time, timedelta

import pytest
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import RunContext
from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo
from my_planner.store.repos.events import EVENTS_MAX, EventsRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools
from my_planner.tools.mcp_adapter import APP_ONLY_TOOLS, TOOL_NAMES, tool_names_for

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
NOW = kst(2026, 10, 26, 9, 0)  # 월요일
RUN_ID = 340
EVENT_TOOLS = ["list_events", "create_event", "update_event", "delete_event"]


class Env:
    def __init__(self, tmp_path, conn):
        self.clock = FakeClock(NOW)
        self.conn = conn
        self.tasks = TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY)
        self.events = EventsRepo(conn, self.clock, TZ)
        self.confirms = ConfirmsRepo(conn, self.clock)
        self.tools = Tools(
            tasks=self.tasks, transcripts=TranscriptStore(tmp_path / "data", TZ, BOUNDARY),
            export_path=tmp_path / "data" / "exports" / "tasks.md", clock=self.clock, tz=TZ, boundary=BOUNDARY,
            activity=ActivityRepo(conn, self.clock), confirms=self.confirms, events=self.events,
            reply_until=lambda run_id: NOW + timedelta(hours=3),
        )

    def chat(self):
        """앱 대화에서 사용자 메시지에 답하는 두뇌 차례."""
        return RunContext(conversation_id=7, run_id=None, inbound_id=1001, channel="app")

    def run(self):
        """회차 차례(아침 브리핑)."""
        return RunContext(conversation_id=7, run_id=RUN_ID, activity_channel="scheduler", channel="app")

    def user(self):
        """앱이 `POST /actions`로 부른 것(사용자가 누른 것)."""
        return RunContext(conversation_id=None, run_id=None, actor="user", channel="app")

    def make(self, **kw):
        args = {"title": "치과", "date": "2026-10-28", "time": "14:00", **kw}
        out = self.tools.create_event(self.chat(), **args)
        assert "error" not in out, out
        return out

    def tokens(self):
        return self.conn.execute("SELECT action, args_json, summary, origin FROM pending_confirms ORDER BY rowid").fetchall()

    def snapshot(self):
        return [tuple(r) for r in self.conn.execute("SELECT * FROM events ORDER BY id")], [
            tuple(r) for r in self.conn.execute("SELECT * FROM event_skips ORDER BY 1, 2")]


@pytest.fixture
def env(tmp_path, conn):
    return Env(tmp_path, conn)


# --- 만들기 ---


def test_create_event_default_remind_10_and_all_day_0(env):
    out = env.make()
    assert out["remind_min"] == 10 and out["origin"] == "chat" and "note" not in out
    day = env.make(title="카드 결제일", date="2026-10-30", time=None, all_day=True)
    assert day["remind_min"] == 0 and day["time"] is None
    silent = env.make(title="조용한 일정", remind_min=None)
    assert silent["remind_min"] is None
    weekly = env.make(title="팀 회의", repeat="weekly")  # 요일을 빼면 첫 날(수)
    assert weekly["weekdays"] == ["wed"]
    assert env.tools.create_event(env.user(), title="직접", date="2026-10-28", time="09:00")["origin"] == "user"
    kinds = [r["kind"] for r in env.conn.execute("SELECT kind FROM activity ORDER BY id")]
    assert kinds == ["event_created"] * 5


def test_weekly_start_not_in_weekdays_422(env):
    out = env.tools.create_event(env.chat(), title="운동", date="2026-10-27", time="07:00", repeat="weekly",
                                 weekdays=["mon", "wed"])
    assert out["code"] == "start_not_in_weekdays"
    assert out["error"] == "첫 날(date)의 요일이 반복 요일(weekdays)에 들어 있어야 해요."
    assert env.events.count_live() == 0


def test_all_day_rejects_10_30_60(env):
    for m in (10, 30, 60):
        out = env.tools.create_event(env.chat(), title="휴가", date="2026-10-30", all_day=True, remind_min=m)
        assert out["code"] == "remind_invalid", m
    for m in (0, 1440, None):
        assert "error" not in env.tools.create_event(env.chat(), title="휴가", date="2026-10-30", all_day=True,
                                                     remind_min=m)
    assert env.tools.create_event(env.chat(), title="치과", date="2026-10-30", time="14:00",
                                  remind_min=15)["code"] == "remind_invalid"
    e = env.make()
    assert env.tools.update_event(env.user(), id=e["id"], all_day=True, remind_min=30)["code"] == "remind_invalid"
    changed = env.tools.update_event(env.user(), id=e["id"], all_day=True)  # 10분 전 → 정시(09:00)
    assert changed["remind_min"] == 0 and changed["time"] is None


def test_cap_300(env):
    at = NOW.isoformat()
    env.conn.executemany(
        "INSERT INTO events (title, all_day, start_date, start_time, repeat, origin, created_at, updated_at) "
        "VALUES (?, 0, '2026-10-28', '10:00', 'none', 'user', ?, ?)",
        [(f"일정 {i}", at, at) for i in range(EVENTS_MAX)],
    )
    env.conn.commit()
    out = env.tools.create_event(env.chat(), title="하나 더", date="2026-10-28", time="11:00")
    assert out == {"error": "일정은 300개까지 둘 수 있어요. 지난 일정을 지우면 새로 만들 수 있어요.",
                   "code": "too_many_events"}


def test_create_task_rejects_scheduled_at(env):
    out = env.tools.add_task(env.chat(), title="치과", areas=["health"], scheduled_at="2026-10-28T14:00")
    assert out == {"error": "시간이 정해진 일은 스케줄로 만들어요. create_event를 써 주세요."}
    assert env.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


# --- 확인(5.5) ---


def test_update_time_needs_confirm_title_direct(env):
    e = env.make(repeat="daily", remind_min=30)
    before = env.snapshot()
    ctx = env.chat()
    out = env.tools.update_event(ctx, id=e["id"], time="15:00")
    assert out["status"] == "needs_confirm"
    assert out["summary"] == "일정을 바꿔요: 치과 → 매일 15:00"
    assert env.snapshot() == before
    (tok,) = env.tokens()
    assert (tok["action"], json.loads(tok["args_json"]), tok["origin"]) == (
        "update_event", {"id": e["id"], "time": "15:00"}, "actions")
    assert [ev.kind for ev in ctx.events] == ["confirm_requested"] and ctx.events[0].data["card"] is True

    out = env.tools.update_event(env.chat(), id=e["id"], remind_min=None)  # 알림도 때에 든다
    assert out["status"] == "needs_confirm" and out["summary"] == "일정을 바꿔요: 치과 → 매일 14:00 · 알림 없음"

    ctx = env.chat()
    out = env.tools.update_event(ctx, id=e["id"], title="치과 검진", note="꾸민 메모", area="health")
    assert out["title"] == "치과 검진" and out["area"] == "health" and "note" not in out
    assert [ev.kind for ev in ctx.events] == ["event_updated"] and ctx.undo_ids
    assert env.events.get(e["id"]).note == "꾸민 메모"
    assert env.tools.update_event(env.chat(), id=e["id"], title="치과 검진")["already"] is True

    applied = env.tools.update_event(env.user(), id=e["id"], time="15:00")  # 사용자가 누른 것은 바로
    assert applied["time"] == "15:00"


def test_delete_always_confirm(env):
    once = env.make()
    daily = env.make(title="물 마시기", repeat="daily", time="10:00")
    before = env.snapshot()
    for args, summary in (
        ({"id": once["id"], "scope": "all"}, "일정을 지워요: 치과"),
        ({"id": daily["id"], "scope": "one", "date": "2026-10-29"}, "이번만 건너뛰어요: 물 마시기 (10/29)"),
        ({"id": daily["id"], "scope": "following", "date": "2026-10-29"}, "이후 반복을 끝내요: 물 마시기 (10/29부터)"),
        ({"id": daily["id"], "scope": "all"}, "일정을 지워요: 물 마시기"),
    ):
        out = env.tools.delete_event(env.chat(), **args)
        assert out["status"] == "needs_confirm", args
        assert out["summary"] == summary
    assert env.snapshot() == before and len(env.tokens()) == 4

    user = env.user()
    assert env.tools.delete_event(user, id=daily["id"], scope="one", date="2026-10-29") == {
        "id": daily["id"], "scope": "one", "date": "2026-10-29"}
    assert env.tools.delete_event(user, id=daily["id"], scope="one", date="2026-10-29")["already"] is True
    assert env.tools.delete_event(user, id=daily["id"], scope="following", date="2026-10-26")["scope"] == "all"
    assert env.events.get(daily["id"]) is None
    assert env.tools.delete_event(user, id=once["id"], scope="one", date="2026-10-28")["scope"] == "all"
    kinds = [r["kind"] for r in env.conn.execute("SELECT kind FROM activity WHERE kind LIKE 'event_%' ORDER BY id")]
    assert kinds[-3:] == ["event_skipped", "event_deleted", "event_deleted"]


def test_run_turn_create_needs_ui_confirm(env):
    ctx = env.run()
    out = env.tools.create_event(ctx, title="치과", date="2026-10-28", time="14:00")
    assert out["status"] == "needs_confirm"
    assert out["summary"] == "일정을 만들어요: 치과 (10/28 14:00)"
    assert env.events.count_live() == 0
    (tok,) = env.tokens()
    assert tok["action"] == "create_event" and tok["origin"] == "run_turn"
    assert json.loads(tok["args_json"])["remind_min"] == 10
    assert [ev.kind for ev in ctx.events] == ["confirm_requested"] and "card" not in ctx.events[0].data
    # 회차 차례의 고치기도 회차 토큰(체크인 상세 `ui_confirm`)
    e = env.make()
    assert env.tools.update_event(env.run(), id=e["id"], date="2026-10-29")["status"] == "needs_confirm"
    assert env.tokens()[-1]["origin"] == "run_turn"


def test_app_tools_plus_4_telegram_unchanged():
    app = tool_names_for(RunContext(None, None, channel="app"))
    telegram = tool_names_for(RunContext(None, None, channel="telegram"))
    assert len(app) == 43 and len(telegram) == 28
    assert APP_ONLY_TOOLS[-4:] == EVENT_TOOLS
    assert not set(EVENT_TOOLS) & set(TOOL_NAMES) and not set(EVENT_TOOLS) & set(telegram)
    assert "dismiss_missed_reminder" not in app and "ui_events" not in app


# --- 기록·로그 ---


def test_logs_have_no_titles_or_notes(env, caplog):
    caplog.set_level(logging.DEBUG)
    e = env.make(title="비밀 제목", note="비밀 메모", repeat="daily")
    env.tools.update_event(env.user(), id=e["id"], note="다른 비밀 메모", time="15:00")
    env.tools.list_events(env.chat(), start="2026-10-26", end="2026-11-01")
    env.tools.delete_event(env.user(), id=e["id"], scope="one", date="2026-10-29")
    env.tools.delete_event(env.chat(), id=e["id"], scope="all")
    text = "\n".join(f"{r.getMessage()} {vars(r)}" for r in caplog.records)
    assert "비밀" not in text
    logged = " ".join(r[0] for r in env.conn.execute("SELECT data_json FROM tool_events_log"))
    assert "비밀 메모" not in logged  # 호출 기록에는 제목만(확인 문구에 쓴다), 메모는 없다


async def test_reprocessing_same_inbound_leaves_one_event(tmp_path, conn, state):
    """두뇌 호출 도중 멈춘 뒤 다시 처리: 호출 기록이 있어 두뇌를 다시 부르지 않고 일정은 하나."""
    import asyncio

    from test_dispatcher_messages import Env as DEnv
    from test_inbound_recovery import START, _kill, _receive

    from my_planner.harness.dispatcher import FALLBACK_REPLY
    from my_planner.loop.runner import resubmit_inbound

    make = ("create_event", {"title": "치과", "date": "2026-10-28", "time": "14:00"})
    first = DEnv(tmp_path, conn, state, script=[FakeTurn([make], "", hang=True)], start=START, with_tools=True)
    first.dispatcher.start()
    await _receive(first, state, 51, "수요일 2시 치과 넣어 줘")
    while not first.brain.calls:
        await asyncio.sleep(0)
    await _kill(first)

    second = DEnv(tmp_path, conn, state, script=[], start=START + timedelta(minutes=5), with_tools=True)
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()

    assert second.brain.calls == []
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert [o.text for o in second.sender.sent] == [f"{FALLBACK_REPLY}\n\n✓ 일정 추가: 치과 (10/28 14:00)"]


def test_event_copy_has_no_banned_words():
    """10장 금지어 검사: 이 티켓이 쓴 일정 문구 전부(확인 문구, 오류, 기간 이름)."""
    from my_planner.tools import events as et
    from my_planner.tools.confirmations import _EVENT_LINES, REMIND_LABELS
    from my_planner.tools.ui import banned_words

    copy = [*_EVENT_LINES.values(), *REMIND_LABELS.values(), *(v for k, v in vars(et).items() if k.startswith("MSG_"))]
    assert len(copy) >= 5 + 30
    words = banned_words()
    assert [(c, w) for c in copy for w in words if w in c] == []


def test_preamble_today_events_from_events(env):
    """`## 오늘 일정`은 스케줄의 오늘(논리적 날짜) 그날 일정, 최대 8줄. 시각 있는 옛 할 일은 넣지 않는다."""
    from my_planner.harness.context import build_preamble

    env.tasks.create("꾸민 옛 시각 할 일", ["health"], planned_for=NOW.date(), scheduled_at=kst(2026, 10, 26, 16, 0))
    env.make(title="꾸민 치과", date="2026-10-26", time="14:00")
    env.make(title="꾸민 카드 결제일", date="2026-10-26", time=None, all_day=True)
    env.make(title="꾸민 새벽 일정", date="2026-10-27", time="01:00")  # 논리적 날짜 10/26
    env.make(title="꾸민 내일 일정", date="2026-10-27", time="09:00")

    def block(**kw):
        text = build_preamble(now=env.clock.now(), tz=TZ, boundary=BOUNDARY, tasks=env.tasks, **kw)
        return text[text.index("## 오늘 일정"):].split("\n\n")[0] if "## 오늘 일정" in text else None

    assert block(events=env.events) == (
        "## 오늘 일정\n- 하루 종일 꾸민 카드 결제일 (#e2)\n- 14:00 꾸민 치과 (#e1)\n- 01:00 꾸민 새벽 일정 (#e3)"
    )
    assert block() is None  # 스케줄이 없으면 섹션도 없다
    for i in range(10):
        env.make(title=f"꾸민 회의 {i}", date="2026-10-26", time=f"{10 + i}:30")
    assert block(events=env.events).count("\n- ") == 8

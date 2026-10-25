"""회차 차례의 확인 (SP3-4 스펙 10.1 A1~A7, 티켓 10).

회차를 실행하는 두뇌 호출(회차 차례)에서 비서가 꺼낸 큰 변경은 확인 토큰만 만든다. 앱은 체크인 상세 `cards`의
`ui_confirm`으로, 텔레그램은 회차 메시지 아래 `k:` 버튼으로 확인한다. 사용자 메시지에 답하는 차례는 SP1 그대로다.
가짜 두뇌 + 가짜 시계. 내용은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.bot.telegram_io import (
    CONFIRM_KEEP_LABEL,
    confirm_keyboard,
    message_keyboard,
)
from my_planner.clock import FakeClock
from my_planner.domain import RunContext, TaskStatus
from my_planner.harness.dispatcher import Outbound
from my_planner.harness.stream import harness_cards
from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.actions import STALE_TOKEN
from my_planner.tools.core import Tools

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
NOW = kst(2026, 10, 26, 9, 0)  # 월요일 아침 브리핑
REPLY_UNTIL = kst(2026, 10, 26, 12, 0)  # 아침 브리핑 답장 창 끝
RUN_ID = 340


class Env:
    def __init__(self, tmp_path, conn):
        self.clock = FakeClock(NOW)
        self.conn = conn
        self.tasks = TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY)
        self.confirms = ConfirmsRepo(conn, self.clock)
        self.activity = ActivityRepo(conn, self.clock)
        self.asked: list[int] = []

        def reply_until(run_id: int):
            self.asked.append(run_id)
            return REPLY_UNTIL

        self.tools = Tools(
            tasks=self.tasks, transcripts=TranscriptStore(tmp_path / "data", TZ, BOUNDARY),
            export_path=tmp_path / "data" / "exports" / "tasks.md", clock=self.clock, tz=TZ, boundary=BOUNDARY,
            activity=self.activity, confirms=self.confirms, reply_until=reply_until,
        )

    def run_ctx(self, channel="telegram"):
        return RunContext(conversation_id=7, run_id=RUN_ID, activity_channel="scheduler", channel=channel)

    def user_ctx(self, channel="telegram"):
        return RunContext(conversation_id=7, run_id=None, inbound_id=1001, channel=channel)

    def add(self, title, **kw):
        return self.tools.add_task(self.user_ctx(), title=title, areas=["health"], **kw)["id"]

    def snapshot(self):
        tasks = [tuple(r) for r in self.conn.execute(
            "SELECT id, title, status, planned_for, scheduled_at, deleted_at FROM tasks ORDER BY id")]
        prios = [tuple(r) for r in self.conn.execute("SELECT * FROM priorities ORDER BY 1, 2, 3")]
        return tasks, prios

    def tokens(self):
        return self.conn.execute("SELECT * FROM pending_confirms ORDER BY created_at, rowid").fetchall()


@pytest.fixture
def env(tmp_path, conn):
    return Env(tmp_path, conn)


# --- A1: 회차 차례 판정 ---


async def test_run_turn_detection_both_channels(tmp_path):
    # 단위: run_id가 있고 inbound_id가 없을 때만. 통로와 상관없다
    for channel in ("telegram", "app"):
        assert RunContext(conversation_id=1, run_id=5, channel=channel).run_turn is True
        assert RunContext(conversation_id=1, run_id=5, inbound_id=9, channel=channel).run_turn is False
        assert RunContext(conversation_id=1, run_id=None, inbound_id=9, channel=channel).run_turn is False
    assert RunContext(conversation_id=None, run_id=None).run_turn is False  # 버튼·`/actions`

    # 끝에서 끝까지: 회차 호출 → 회차 대화에 텔레그램으로 답 → 앱 체크인 화면에서 답
    script = [FakeTurn([], "꾸민 아침", session_id="s-run"), FakeTurn([], "꾸민 텔레그램 답", session_id="s-run"),
              FakeTurn([], "꾸민 앱 답", session_id="s-fork")]
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30), script=script) as be:
        await be.tick()
        run_id = be.conn.execute("SELECT id FROM runs WHERE loop = 'morning_brief'").fetchone()["id"]
        be.clock.set(kst(2026, 10, 26, 9, 30))
        await be.telegram("꾸민 답")
        await be.chat("꾸민 앱 답", checkin_id=run_id)
        calls = [c["run_ctx"] for c in be.brain.calls]

    assert [c.run_turn for c in calls] == [True, False, False]
    assert [c.channel for c in calls[1:]] == ["telegram", "app"]


# --- A2: 회차 차례에서는 토큰만 ---


def _cases(env):
    """(동작, 인자, 확인 문구 일부). 시각 있는 할 일 하나(SP9 전에 만든 것: 도구로는 더 만들 수 없다), 날짜만 있는 할 일 하나."""
    timed = env.tasks.create("꾸민 진료", ["health"], planned_for=kst(2026, 10, 27, 14, 0).date(),
                             scheduled_at=kst(2026, 10, 27, 14, 0)).id
    plain = env.add("꾸민 산책", planned_for="2026-10-26")
    return timed, plain


CASES = [
    ("drop_task", lambda t, p: {"id": p}, "내려놓아요: 꾸민 산책"),
    ("set_priorities", lambda t, p: {"cadence": "day", "period": "2026-10-26", "task_ids": [p]}, "오늘 우선순위"),
    ("set_priorities", lambda t, p: {"cadence": "week", "period": "2026-W44", "task_ids": [p, t]}, "이번 주 우선순위"),
    ("set_priorities", lambda t, p: {"cadence": "month", "period": "2026-10", "task_ids": [p]}, "이번 달 우선순위"),
    ("set_priorities", lambda t, p: {"cadence": "quarter", "period": "2026-Q4", "task_ids": [t]}, "이번 분기 우선순위"),
    ("set_priorities", lambda t, p: {"cadence": "year", "period": "2026", "task_ids": [p]}, "올해 우선순위"),
    # SP9 5.4: 할 일의 시각 확인(`update_task`의 `scheduled_at`, 시각 있는 할 일의 `move_task`)은 없어졌다.
    # 일정의 시각 확인은 `update_event`다(tests/test_event_tools.py)
]


@pytest.mark.parametrize(("action", "make_args", "summary_part"), CASES)
@pytest.mark.parametrize("channel", ["telegram", "app"])
def test_run_turn_tools_need_confirm(env, action, make_args, summary_part, channel):
    timed, plain = _cases(env)
    args = make_args(timed, plain)
    before = env.snapshot()
    ctx = env.run_ctx(channel)

    out = getattr(env.tools, action)(ctx, **args)

    assert out["status"] == "needs_confirm" and "error" not in out
    assert out["confirm_token"].startswith("ct_")
    assert summary_part in out["summary"]
    assert env.snapshot() == before  # 아무것도 바꾸지 않는다
    (row,) = env.tokens()
    assert (row["token"], row["action"], row["origin"], row["run_id"], row["conversation_id"]) == (
        out["confirm_token"], action, "run_turn", RUN_ID, 7
    )
    assert row["summary"] == out["summary"] and row["resolved_at"] is None
    assert env.confirms.get(row["token"]).expires_at == REPLY_UNTIL  # 그 회차 답장 창 끝
    assert env.asked == [RUN_ID]
    assert [(e.kind, e.data["confirm_token"]) for e in ctx.events] == [("confirm_requested", out["confirm_token"])]
    acts = env.conn.execute("SELECT * FROM activity WHERE run_id = ?", (RUN_ID,)).fetchall()
    assert [(a["kind"], a["actor"], a["channel"], a["target"], a["undo_json"]) for a in acts] == [
        ("confirm_requested", "secretary", "scheduler", None, None)
    ]
    kinds = [r["kind"] for r in env.conn.execute("SELECT kind FROM tool_events_log WHERE run_id = ?", (RUN_ID,))]
    assert kinds == ["confirm_requested"]


def test_run_turn_token_args_apply_as_is(env):
    """토큰의 `args`는 `/actions`에 그대로 다시 보낼 수 있는 모양이다."""
    timed, plain = _cases(env)
    out = env.tools.set_priorities(env.run_ctx(), cadence="week", period="2026-W44", task_ids=[plain, timed])
    p = env.confirms.get(out["confirm_token"])
    assert p.args == {"cadence": "week", "period": "2026-W44", "task_ids": [plain, timed]}


def test_run_turn_invalid_input_is_still_an_error(env):
    _, plain = _cases(env)
    ctx = env.run_ctx()
    assert "error" in env.tools.drop_task(ctx, id=999)
    assert "error" in env.tools.set_priorities(ctx, cadence="day", period="2026-10-26", task_ids=[999])
    assert "error" in env.tools.update_task(ctx, id=plain, scheduled_at="2026-10-28T09:30")  # SP9: 시각은 일정으로
    assert env.tokens() == [] and ctx.events == []


def test_move_task_without_schedule_applies_in_run_turn(env):
    _, plain = _cases(env)
    ctx = env.run_ctx()

    out = env.tools.move_task(ctx, id=plain, planned_for="2026-10-28")
    upd = env.tools.update_task(ctx, id=plain, title="꾸민 저녁 산책")  # 시각을 바꾸지 않는 update_task도 바로

    assert out["planned_for"] == "2026-10-28"
    assert upd["title"] == "꾸민 저녁 산책"
    assert env.tasks.get(plain).planned_for.isoformat() == "2026-10-28"
    assert env.tokens() == []
    assert [e.kind for e in ctx.events] == ["task_moved", "task_updated"]


def test_drop_draft_applies_in_run_turn(env):
    """초안(비서 자신의 제안)을 빼는 것은 회차 차례에서도 바로 한다(리뷰 결정 1)."""
    ctx = env.run_ctx()
    (draft,) = env.tools.propose_tasks(ctx, tasks=[{"title": "꾸민 초안", "areas": ["health"]}])["proposed"]

    out = env.tools.drop_task(ctx, id=draft["id"])

    assert out["status"] == "dropped" and env.tasks.get(draft["id"]).status is TaskStatus.dropped
    assert env.tokens() == []
    assert [e.kind for e in ctx.events] == ["tasks_proposed", "task_dropped"]


def test_no_change_applies_in_run_turn(env):
    """바뀌는 것이 없는 호출은 토큰 없이 SP1처럼 적용한다: 지금과 같은 우선순위 목록(리뷰 결정 2, 지적 5). 시각 있는
    할 일의 옮기기·`update_task`는 SP9부터 확인이 없다."""
    timed, plain = _cases(env)
    env.tools.set_priorities(env.user_ctx(), cadence="week", period="2026-W44", task_ids=[plain, timed])
    ctx = env.run_ctx()

    same_list = env.tools.set_priorities(ctx, cadence="week", period="2026-W44", task_ids=[plain, timed])
    empty = env.tools.set_priorities(ctx, cadence="year", period="2026", task_ids=[])  # 비어 있는 목록을 그대로
    same_day = env.tools.move_task(ctx, id=timed, planned_for="2026-10-27")
    same_time = env.tools.update_task(ctx, id=timed, note="꾸민 메모")

    assert [x.get("status") for x in (same_list, empty)] == [None, None]
    assert [t["id"] for t in same_list["priorities"]] == [plain, timed]
    assert same_day["planned_for"] == "2026-10-27" and same_day["scheduled_at"].startswith("2026-10-27T14:00")
    assert same_time["note"] == "꾸민 메모"
    assert env.tokens() == []
    assert [e.kind for e in ctx.events] == ["priorities_set", "priorities_set", "task_moved", "task_updated"]


def test_add_task_applies_in_run_turn(env):
    ctx = env.run_ctx()
    out = env.tools.add_task(ctx, title="꾸민 물 마시기", areas=["health"], planned_for="2026-10-26")
    assert out["status"] == "open" and env.tasks.get(out["id"]) is not None
    assert env.tokens() == []
    assert [e.kind for e in ctx.events] == ["task_added"]


def test_move_confirm_moved_to_update_event(env):
    """SP9 5.4: 시각 있는 할 일의 날짜 옮기기 확인은 없어졌고(할 일 쪽은 지움) 일정의 `update_event` 확인으로 옮겼다."""
    from my_planner.tools import confirmations

    timed, _ = _cases(env)
    ctx = env.run_ctx()
    out = env.tools.move_task(ctx, id=timed, planned_for="2026-10-29")
    assert out["planned_for"] == "2026-10-29" and out["scheduled_at"].startswith("2026-10-29T14:00")
    assert env.tokens() == [] and [e.kind for e in ctx.events] == ["task_moved"]
    for gone in ("confirm_schedule_summary", "confirm_move_summary", "confirm_button_schedule", "confirm_button_move"):
        assert not hasattr(confirmations, gone)
    assert confirmations.confirm_event_update_summary("치과", "10/27 15:00", {}, {}) == "일정을 바꿔요: 치과 → 10/27 15:00"


# --- A3: 사용자 차례는 SP1 그대로 ---


@pytest.mark.parametrize(("action", "make_args", "summary_part"), CASES)
@pytest.mark.parametrize("channel", ["telegram", "app"])
def test_sp1_user_turn_behavior_unchanged(env, action, make_args, summary_part, channel):
    """사용자 메시지에 답하는 차례(회차 대화의 답 포함)는 확인 저장소가 있어도 바로 적용한다.

    SP1 시험(`tests/test_tools_tasks.py`, `tests/test_dispatcher_tools.py`)은 전체 시험에서 그대로 통과한다."""
    timed, plain = _cases(env)
    ctx = env.user_ctx(channel)
    before = env.snapshot()

    out = getattr(env.tools, action)(ctx, **make_args(timed, plain))

    assert "error" not in out and out.get("status") != "needs_confirm"
    assert env.tokens() == []
    assert "confirm_requested" not in [e.kind for e in ctx.events]
    assert env.snapshot() != before


# --- A5: 확인 카드와 텔레그램 버튼 ---


def _seed_run_ids(conn, next_id):
    """다음 회차 id가 `next_id`가 되게 오래전에 건너뛴 회차 하나를 둔다(꾸며 낸 행)."""
    conn.execute(
        "INSERT INTO runs (id, loop, scheduled_for, status, skip_reason, created_at) "
        "VALUES (?, 'evening_checkin', '2026-09-01T08:30:00.000000+00:00', 'skipped', 'late', "
        "'2026-09-01T08:30:00.000000+00:00')",
        (next_id - 1,),
    )
    conn.commit()


async def _morning_with_proposals(env):
    """앱으로 할 일 셋을 넣고, 아침 브리핑(가짜 두뇌)이 초안 하나, 우선순위, 내려놓기를 꺼낸다."""
    ids = []
    for title in ("꾸민 독서", "꾸민 정리", "꾸민 화분"):
        _, body = await env.action("add_task", {"title": title, "areas": ["learning"], "planned_for": "2026-10-26"})
        ids.append(body["result"]["id"])
    env.brain.script.append(FakeTurn([
        ("propose_tasks", {"tasks": [{"title": "꾸민 스트레칭", "areas": ["health"]}]}),
        ("set_priorities", {"cadence": "day", "period": "2026-10-26", "task_ids": [ids[0], ids[1]]}),
        ("drop_task", {"id": ids[2]}),
    ], "오늘은 독서와 정리를 먼저 해 보면 어떨까요? 화분은 내려놓을지 골라 주세요."))
    await env.tick()
    return ids


async def _cards(env, run_id):
    resp = await env.get(f"/checkins/{run_id}")
    assert resp.status == 200, await resp.text()
    return (await resp.json())["cards"]


async def test_confirm_card_and_telegram_buttons(tmp_path):
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30)) as be:
        _seed_run_ids(be.conn, RUN_ID)
        ids = await _morning_with_proposals(be)
        run = be.conn.execute("SELECT * FROM runs WHERE loop = 'morning_brief'").fetchone()
        sent = be.sender.sent[-1]
        cards = await _cards(be, run["id"])
        prio_before = be.conn.execute("SELECT COUNT(*) FROM priorities").fetchone()[0]
        dropped_before = be.parts.tasks.get(ids[2]).status
        # 앱에서 첫 토큰을 확인한다(카드의 값을 그대로)
        first = next(c for c in cards if c["component"] == "ui_confirm")
        status, body = await be.action(first["props"]["action"], first["props"]["args"],
                                       confirm_token=first["props"]["confirm_token"])
        after = await _cards(be, run["id"])

    assert run["id"] == RUN_ID
    # 그대로(회차 차례에서는 바꾸지 않는다)
    assert prio_before == 0 and dropped_before is TaskStatus.open
    # 텔레그램: 초안 줄 → 확인 줄 둘 → 컨디션 줄
    assert [s for _, s in sent.confirms] == ["우선순위: 오늘", "내려놓기: 꾸민 화분"]
    # 확인 문구 전부는 메시지 글에 있다(버튼은 짧다)
    assert "확인을 기다려요: 오늘 우선순위를 바꿔요: 1. 꾸민 독서 2. 꾸민 정리" in sent.text
    assert "확인을 기다려요: 할 일을 내려놓아요: 꾸민 화분" in sent.text
    rows = message_keyboard(sent, {}).inline_keyboard
    datas = [[b.callback_data for b in row] for row in rows]
    assert datas[0][0].startswith("d:c:") and datas[1] == ["d:all:" + datas[1][0].split(":")[2]]
    assert [d[0][:4] for d in datas[2:4]] == ["k:a:", "k:a:"]
    assert [d[1][:4] for d in datas[2:4]] == ["k:x:", "k:x:"]
    assert all(d[1][4:] == d[0][4:] for d in datas[2:4])
    assert [r[0].text for r in rows[2:4]] == ["✓ 우선순위: 오늘", "✓ 내려놓기: 꾸민 화분"]
    assert {r[1].text for r in rows[2:4]} == {"✗ 그대로 두기"}
    assert all(len(b.callback_data.encode()) <= 64 for row in rows for b in row)
    if sent.ask_condition_for is not None:
        assert datas[4][0].startswith("c:")
    # 앱: 같은 순서의 카드. 확인 카드는 회차 340의 1, 2
    comps = [c["component"] for c in cards]
    assert comps[:3] == ["ui_todo_draft", "ui_confirm", "ui_confirm"]
    assert [c["toolCallId"] for c in cards if c["component"] == "ui_confirm"] == ["h_confirm_340_1", "h_confirm_340_2"]
    assert first["props"] == {
        "summary": "오늘 우선순위를 바꿔요: 1. 꾸민 독서 2. 꾸민 정리", "confirm_token": datas[2][0][4:],
        "action": "set_priorities", "args": {"cadence": "day", "period": "2026-10-26", "task_ids": ids[:2]},
    }
    # 첫 토큰을 확인한 뒤에도 둘째는 h_confirm_340_2
    assert status == 200 and body["status"] == "applied"
    assert [c["toolCallId"] for c in after if c["component"] == "ui_confirm"] == ["h_confirm_340_2"]


def test_confirm_keyboard_shape():
    rows = confirm_keyboard([("ct_" + "a" * 22, "옮기기: 꾸민 확인 문구가 열여섯 글자보다 길어요"),
                             ("ct_" + "b" * 22, "내려놓기: 꾸민 아침 산책 준비")])
    assert [b.text for b in rows[0]] == ["✓ 옮기기: 꾸민 확인 문구가…", CONFIRM_KEEP_LABEL]
    assert rows[1][0].text == "✓ 내려놓기: 꾸민 아침 산책…"  # 줄임표 앞 공백은 지운다
    assert [b.callback_data for b in rows[0]] == ["k:a:ct_" + "a" * 22, "k:x:ct_" + "a" * 22]
    assert all(len(b.callback_data.encode()) <= 64 for row in rows for b in row)
    assert confirm_keyboard([]) == []


def test_chat_stream_has_no_confirm_card():
    """`ui_confirm`은 체크인 상세 `cards`로만 간다. `/chat` 스트림의 하네스 조각에는 없다(6.4.1)."""
    out = Outbound(text="꾸민 답", confirms=[("ct_x", "꾸민 확인")], ask_condition_for=None)
    assert harness_cards(out) == []


async def test_confirm_applies_with_activity_and_decline_changes_nothing(tmp_path):
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30)) as be:
        ids = await _morning_with_proposals(be)
        (mid,) = [m for m in be.sender.message_ids if m is not None]
        (prio_token, prio_summary), (drop_token, _) = be.sender.sent[-1].confirms
        be.clock.set(kst(2026, 10, 26, 9, 10))
        applied = await be.press(f"k:a:{prio_token}", message_id=mid)
        before_decline = (be.parts.tasks.get(ids[2]).status, be.conn.execute("SELECT COUNT(*) FROM priorities").fetchone()[0])
        declined = await be.press(f"k:x:{drop_token}", message_id=mid)
        prios = [tuple(r) for r in be.conn.execute("SELECT cadence, period, rank, task_id FROM priorities ORDER BY rank")]
        dropped = be.parts.tasks.get(ids[2]).status
        acts = [(a["kind"], a["actor"], a["channel"], a["risk"]) for a in be.activity()]
        tokens = {r["token"]: r["resolution"] for r in be.conn.execute("SELECT * FROM pending_confirms")}
        answers = [t for _, t in be.bot.answers]
        run = be.conn.execute("SELECT * FROM runs WHERE loop = 'morning_brief'").fetchone()

    assert (applied, declined) == ("confirmed", "declined")
    assert prios == [("day", "2026-10-26", 1, ids[0]), ("day", "2026-10-26", 2, ids[1])]
    assert dropped is TaskStatus.open and before_decline == (TaskStatus.open, 2)  # 그대로 두기는 아무것도 바꾸지 않는다
    assert tokens == {prio_token: "applied", drop_token: "declined"}
    assert acts[-2:] == [("priorities_set", "user", "telegram", "confirm"), ("confirm_declined", "user", "telegram", "low")]
    assert ("confirm_requested", "secretary", "scheduler", "low") in acts
    assert answers == ["✓ 우선순위(오늘): 1. 꾸민 독서 2. 꾸민 정리", "✗ 그대로 뒀어요 (할 일을 내려놓아요: 꾸민 화분)"]
    assert prio_summary == "우선순위: 오늘"
    assert (run["answered_via"]) == "telegram"  # 회차에 붙은 버튼이라 그 회차의 답이다


async def test_double_press_expired_or_stale_not_applied(tmp_path):
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30)) as be:
        ids = await _morning_with_proposals(be)
        (prio_token, _), (drop_token, _) = be.sender.sent[-1].confirms
        be.clock.set(kst(2026, 10, 26, 9, 10))
        # 두 번 누름
        first = await be.press(f"k:a:{prio_token}")
        second = await be.press(f"k:a:{prio_token}")
        # stale: 토큰 뒤에 앱에서 그 할 일을 완료했다
        be.clock.set(kst(2026, 10, 26, 9, 20))
        await be.action("complete_task", {"id": ids[2]})
        stale = await be.press(f"k:a:{drop_token}")
        stale_status = be.parts.tasks.get(ids[2]).status
        resolutions = {r["token"]: r["resolution"] for r in be.conn.execute("SELECT * FROM pending_confirms")}
        answers = [t for _, t in be.bot.answers]
        # 모르는 토큰
        unknown = await be.press("k:a:ct_" + "z" * 22)
        status, body = await be.action("set_priorities", {"cadence": "day", "period": "2026-10-26", "task_ids": ids[:2]},
                                       confirm_token=prio_token)

    assert (first, second, stale, unknown) == ("confirmed", "stale", "stale", "stale")
    assert answers[1:] == [STALE_TOKEN, STALE_TOKEN]
    assert be.bot.answers[-1][1] == STALE_TOKEN
    assert stale_status is TaskStatus.done  # 내려놓지 않았다
    assert resolutions == {prio_token: "applied", drop_token: "stale"}
    assert status == 409 and body["error"]["message"] == STALE_TOKEN


async def test_expired_token_not_applied(tmp_path):
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30)) as be:
        ids = await _morning_with_proposals(be)
        run_id = be.conn.execute("SELECT id FROM runs WHERE loop = 'morning_brief'").fetchone()["id"]
        (prio_token, _), _ = be.sender.sent[-1].confirms
        be.clock.set(REPLY_UNTIL + timedelta(minutes=1))  # 답장 창이 끝났다
        cards = await _cards(be, run_id)
        expired = await be.press(f"k:a:{prio_token}")
        prios = be.conn.execute("SELECT COUNT(*) FROM priorities").fetchone()[0]
        resolution = be.conn.execute("SELECT resolution FROM pending_confirms WHERE token = ?", (prio_token,)).fetchone()[0]

    assert ids and expired == "stale" and prios == 0 and resolution == "expired"
    assert be.bot.answers[-1][1] == STALE_TOKEN
    assert [c for c in cards if c["component"] == "ui_confirm"] == []


async def test_token_survives_restart(tmp_path):
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30)) as be:
        ids = await _morning_with_proposals(be)
        run_id = be.conn.execute("SELECT id FROM runs WHERE loop = 'morning_brief'").fetchone()["id"]
        (prio_token, _), (drop_token, _) = be.sender.sent[-1].confirms
    # 다시 시작한다(같은 DB). 토큰은 DB에 있다
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 10, 0)) as be2:
        cards = await _cards(be2, run_id)
        pressed = await be2.press(f"k:a:{drop_token}")
        status = be2.parts.tasks.get(ids[2]).status
        left = await _cards(be2, run_id)

    assert [c["props"]["confirm_token"] for c in cards if c["component"] == "ui_confirm"] == [prio_token, drop_token]
    assert pressed == "confirmed" and status is TaskStatus.dropped
    assert [c["toolCallId"] for c in left if c["component"] == "ui_confirm"] == [f"h_confirm_{run_id}_1"]


async def test_app_confirm_answers_run_and_clears_telegram_buttons(tmp_path):
    """앱에서 먼저 확인하면 회차의 답이고, 텔레그램 회차 메시지의 버튼(`k:` 포함)을 거둔다(티켓 07 규칙)."""
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30)) as be:
        await _morning_with_proposals(be)
        run_id = be.conn.execute("SELECT id FROM runs WHERE loop = 'morning_brief'").fetchone()["id"]
        (mid,) = [m for m in be.sender.message_ids if m is not None]
        (card, _) = [c for c in await _cards(be, run_id) if c["component"] == "ui_confirm"]
        status, _ = await be.action("decline_confirm", {"confirm_token": card["props"]["confirm_token"]})
        await be.drain()
        detail = await (await be.get(f"/checkins/{run_id}")).json()

    assert status == 200
    assert (detail["state"], detail["answered_via"]) == ("answered", "app")
    assert be.sender.cleared == [mid]


async def test_stale_target_hides_card_but_keeps_token_open(tmp_path):
    """토큰 뒤에 대상이 바뀌면 카드에서 빠진다. 토큰은 닫지 않는다(누를 때 `stale`로 닫힌다). 번호는 그대로다."""
    async with BeEnv.start(tmp_path, start=NOW + timedelta(seconds=30)) as be:
        ids = await _morning_with_proposals(be)
        run_id = be.conn.execute("SELECT id FROM runs WHERE loop = 'morning_brief'").fetchone()["id"]
        (prio_token, _), (drop_token, _) = be.sender.sent[-1].confirms
        be.clock.set(kst(2026, 10, 26, 9, 20))
        await be.action("complete_task", {"id": ids[0]})  # 우선순위 토큰의 대상
        cards = await _cards(be, run_id)
        row = be.conn.execute("SELECT resolved_at FROM pending_confirms WHERE token = ?", (prio_token,)).fetchone()

    assert [(c["toolCallId"], c["props"]["confirm_token"]) for c in cards if c["component"] == "ui_confirm"] == [
        (f"h_confirm_{run_id}_2", drop_token)
    ]
    assert row["resolved_at"] is None


async def test_merged_run_token_expires_at_latest_reply_window(tmp_path):
    """합친 회차(`merged_run_ids`)는 두뇌 호출 전에 적힌다. 그래서 토큰 만료는 묶음의 가장 늦은 답장 창 끝이다."""
    from my_planner.domain import Cadence, LoopKey
    from my_planner.harness.checkins import reply_until

    start = kst(2026, 10, 25, 21, 0) + timedelta(seconds=30)  # 일요일 밤
    async with BeEnv.start(tmp_path, start=start) as be:
        _, added = await be.action("add_task", {"title": "꾸민 빨래", "areas": ["quality_of_life"]})
        runs = be.parts.runs
        evening = runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 25, 21, 0))
        review = runs.ensure(LoopKey.review, kst(2026, 10, 25, 21, 0), Cadence.week)
        for r in (evening, review):
            runs.mark_queued(r.id)
        be.brain.script.append(FakeTurn([("drop_task", {"id": added["result"]["id"]})], "꾸민 회고"))
        be.parts.dispatcher.submit_run(runs.get(evening.id), [runs.get(review.id)])
        await be.drain()
        (row,) = be.conn.execute("SELECT * FROM pending_confirms").fetchall()
        own = reply_until(runs.get(review.id), runs=runs, settings=be.settings)
        alone = kst(2026, 10, 26, 4, 0)  # 저녁 체크인만의 답장 창 끝
        merged_ids = runs.get(evening.id).merged_run_ids
        expires = be.parts.confirms.get(row["token"]).expires_at

    assert merged_ids == [review.id]
    assert row["run_id"] == evening.id
    assert expires == own and expires > alone  # 회고의 24시간 창

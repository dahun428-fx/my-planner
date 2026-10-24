"""텔레그램 회고 단계: 사다리 1·2단계, 기록 문구, 영역 점수 묻기 (SP3-4 스펙 11.1, 부록 A, 계획 빈 곳 12·14).

내용은 모두 꾸며 낸 것이다.
"""

from datetime import date, timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.bot.telegram_io import ladder_keyboard, message_keyboard
from my_planner.harness.dispatcher import Outbound
from my_planner.harness.review_steps import LADDER_STEP1, LADDER_STEP2

SUN_1129 = kst(2026, 11, 29, 18, 0)
REVIEW = "꾸민 월말 회고 본문"


def _rows(rows):
    return [[(b.text, b.callback_data) for b in row] for row in rows]


def _datas(out):
    markup = message_keyboard(out, {})
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


async def _review(env):
    """11/29(일) 18:00 회고+저녁 체크인 한 메시지. (회차 id, 버튼이 붙은 메시지 id)."""
    await env.tick()
    run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
    return run_id, env.sender.message_ids[0]


def _start(tmp_path, script=(), at=SUN_1129 + timedelta(seconds=30)):
    return BeEnv.start(tmp_path, start=at, script=[FakeTurn([], REVIEW), *script])


# --- 슬라이스 2: 1단계의 자리 ---


def test_one_keyboard_kind_per_message():
    now = _rows(ladder_keyboard("2026-11", "n"))
    assert now == [
        [(str(n), f"l:2026-11:n:{n}") for n in range(6)],
        [(str(n), f"l:2026-11:n:{n}") for n in range(6, 11)],
    ]
    future = _rows(ladder_keyboard("2026-11", "f"))
    assert future[:2] == [
        [(str(n), f"l:2026-11:f:{n}") for n in range(6)],
        [(str(n), f"l:2026-11:f:{n}") for n in range(6, 11)],
    ]
    assert future[2] == [("건너뛰기", "l:2026-11:f:skip")]
    assert all(len(d.encode()) <= 64 for row in now + future for _, d in row)

    # 사다리 줄과 컨디션 줄은 한 메시지에 같이 오지 않는다(초안 줄은 함께 둘 수 있다)
    both = Outbound(text="꾸민 답", draft_task_ids=[3], ask_condition_for=date(2026, 11, 29), ladder=("2026-11", "n"))
    datas = _datas(both)
    assert datas[:2] == ["d:c:3", "d:x:3"]
    assert not [d for d in datas if d.startswith("c:")]
    assert [d for d in datas if d.startswith("l:")] == [f"l:2026-11:n:{n}" for n in range(11)]


async def test_review_message_has_condition_row_not_ladder(tmp_path):
    async with _start(tmp_path) as env:
        await _review(env)
        (out,) = env.sender.sent

    assert out.text == REVIEW
    assert out.ask_condition_for == date(2026, 11, 29)
    assert out.ladder is None
    assert _datas(out) == [f"c:2026-11-29:{n}" for n in range(1, 6)]
    assert "## 하네스가 붙이는 질문" not in env.brain.prompts[0]


async def test_condition_press_on_review_sends_ladder_step1_message(tmp_path):
    async with _start(tmp_path) as env:
        run_id, mid = await _review(env)
        assert await env.press("c:2026-11-29:4", message_id=mid) == "recorded"
        toast = env.bot.answers[-1][1]
        step = env.sender.sent[-1]
        # 다시 눌러도(점수를 바꿔도) 1단계는 회차마다 한 번: SP1처럼 토스트
        await env.press("c:2026-11-29:3", message_id=mid)
        again = env.bot.answers[-1][1]
        sent = len(env.sender.sent)
        detail = await (await env.get(f"/checkins/{run_id}")).json()
        prompted = env.parts.state.get("ladder_prompted_run_id")

    assert toast is None  # 토스트 대신 새 메시지
    assert step.text == f"컨디션 4 기록했어요.\n\n{LADDER_STEP1}"
    assert step.ladder == ("2026-11", "n") and step.ask_condition_for is None
    assert again == "컨디션 3 기록했어요." and sent == 2
    assert detail["state"] == "answered"
    assert prompted == str(run_id)


async def test_condition_press_outside_review_is_toast(tmp_path):
    # 월말이 아닌 회고(11/22)의 컨디션 누름은 SP1 그대로 토스트
    async with _start(tmp_path, at=kst(2026, 11, 22, 18, 0) + timedelta(seconds=30)) as env:
        await env.tick()
        await env.press("c:2026-11-22:4", message_id=env.sender.message_ids[0])
        assert env.bot.answers[-1][1] == "컨디션 4 기록했어요."
        assert len(env.sender.sent) == 1


async def test_first_text_reply_gets_step1_when_no_condition_button(tmp_path):
    async with _start(tmp_path, script=[FakeTurn([], "꾸민 답 하나"), FakeTurn([], "꾸민 답 둘")]) as env:
        _, mid = await _review(env)
        env.clock.advance(minutes=5)
        await env.telegram("꾸민 사용자 글")
        reply = env.sender.sent[-1]
        note = env.brain.prompts[-1]
        await env.telegram("꾸민 두 번째 글")
        second = env.sender.sent[-1]
        await env.press("c:2026-11-29:4", message_id=mid)
        toast = env.bot.answers[-1][1]

    assert reply.text == f"꾸민 답 하나\n\n{LADDER_STEP1}"
    assert reply.ladder == ("2026-11", "n")
    assert "## 하네스가 붙이는 질문" in note and LADDER_STEP1 in note
    assert second.text == "꾸민 답 둘" and second.ladder is None
    assert toast == "컨디션 4 기록했어요."  # 이미 물었다: 토스트


async def test_condition_already_recorded_step1_on_review_message(tmp_path):
    async with _start(tmp_path) as env:
        _, added = await env.action("record_condition", {"score": 4, "date": "2026-11-29"})
        assert added["status"] == "applied"
        run_id, _ = await _review(env)
        (out,) = env.sender.sent
        prompt = env.brain.prompts[0]
        saved = env.conn.execute("SELECT outbound_text FROM runs WHERE id = ?", (run_id,)).fetchone()[0]

    assert out.ask_condition_for is None
    assert out.ladder == ("2026-11", "n")
    assert out.text == f"{REVIEW}\n\n{LADDER_STEP1}" == saved
    assert _datas(out) == [f"l:2026-11:n:{n}" for n in range(11)]
    assert "## 하네스가 붙이는 질문" in prompt


async def test_step2_after_now_press(tmp_path):
    async with _start(tmp_path) as env:
        _, mid = await _review(env)
        await env.press("c:2026-11-29:4", message_id=mid)
        assert await env.press("l:2026-11:n:6") == "recorded"
        toast = env.bot.answers[-1][1]
        step2 = env.sender.sent[-1]

    assert toast is None
    assert step2.text == LADDER_STEP2 and step2.ladder == ("2026-11", "f")


# --- 슬라이스 3: 2단계와 기록 문구 ---


async def _to_step1(env):
    run_id, mid = await _review(env)
    await env.press("c:2026-11-29:4", message_id=mid)
    return run_id


async def test_now_then_future_then_recorded_copy(tmp_path):
    async with _start(tmp_path) as env:
        await _to_step1(env)
        await env.press("l:2026-11:n:6")
        assert await env.press("l:2026-11:f:8") == "recorded"
        done = env.sender.sent[-1]
        toast = env.bot.answers[-1][1]
        ladder = env.parts.curve.ladder("2026-11")
        lines = env.parts.transcripts.read_range(date(2026, 11, 29), date(2026, 11, 29))
        proactive = env.parts.state.usage(date(2026, 11, 29)).proactive_messages

    assert done.text == "기록했어요: 지금 6, 5년 뒤 8" and done.ladder is None
    assert toast is None
    assert (ladder.now, ladder.future) == (6, 8)
    assert "[버튼] 사다리 지금 6" in lines and "[버튼] 사다리 5년 뒤 8" in lines
    assert "기록했어요: 지금 6, 5년 뒤 8" in lines
    assert proactive == 1  # 단계 메시지는 하루 3회에 세지 않는다(회고 메시지 하나만)


async def test_skip_future_copy(tmp_path):
    async with _start(tmp_path) as env:
        await _to_step1(env)
        await env.press("l:2026-11:n:6")
        assert await env.press("l:2026-11:f:skip") == "skipped"
        done = env.sender.sent[-1]
        ladder = env.parts.curve.ladder("2026-11")

    assert done.text == "기록했어요: 지금 6"
    assert (ladder.now, ladder.future) == (6, None)


def test_ladder_callback_shapes():
    from my_planner.bot.callbacks import _parse_ladder

    assert _parse_ladder("l:2026-11:n:10") == ("2026-11", "n", 10)
    assert _parse_ladder("l:2026-11:f:skip") == ("2026-11", "f", None)
    for bad in ("l:2026-11:n:skip", "l:2026-13:n:1", "l:2026-11:n:11", "l:2026-11:x:1", "l:202611:n:1", None):
        assert _parse_ladder(bad) is None


# --- 슬라이스 4: 이미 기록한 달, 분기 영역 점수, 답장 창 뒤, 건너뛴 회고 ---

SUN_1227 = kst(2026, 12, 27, 18, 0)
AREA_ASK_Q3 = (
    "이번 분기 영역 점수도 여쭤볼게요. 1~10으로 답해 주세요. 지난 분기: 커리어 7 · 경제 5. "
    "예: 커리어 7 경제 5 건강 6 관계 8 배움 7 삶의 질 6"
)


async def test_ladder_already_recorded_this_month_not_asked(tmp_path):
    # 사용자가 먼저 "이번 달 사다리 7"이라고 해 두었다(빈 곳 14): 그 달 `now`가 있으면 1단계를 묻지 않는다
    script = [FakeTurn([], "꾸민 답")]
    async with _start(tmp_path, script=script) as env:
        _, body = await env.action("record_ladder_score", {"period": "2026-11", "now": 7})
        assert body["status"] == "applied"
        run_id, mid = await _review(env)
        review_msg = env.sender.sent[0]
        await env.press("c:2026-11-29:4", message_id=mid)
        toast = env.bot.answers[-1][1]
        env.clock.advance(minutes=5)
        await env.telegram("꾸민 사용자 글")
        reply = env.sender.sent[-1]
        detail = await (await env.get(f"/checkins/{run_id}")).json()

    assert review_msg.ladder is None and review_msg.ask_condition_for == date(2026, 11, 29)
    assert toast == "컨디션 4 기록했어요."
    assert len(env.sender.sent) == 2 and reply.text == "꾸민 답" and reply.ladder is None
    assert [c["component"] for c in detail["cards"]] == []  # 컨디션도 사다리도 기록됐다


async def test_quarter_area_prompt_with_previous_scores(tmp_path):
    from curve_sql import area_scores

    async with _start(tmp_path, at=SUN_1227 + timedelta(seconds=30)) as env:
        area_scores(env.conn, "2026-Q3", career=7, finance=5)
        env.conn.commit()
        _, mid = await _review(env)
        await env.press("c:2026-12-27:4", message_id=mid)
        step1 = env.sender.sent[-1]
        await env.press("l:2026-12:n:6")
        await env.press("l:2026-12:f:8")
        done = env.sender.sent[-1]

    assert step1.ladder == ("2026-12", "n")
    assert done.text == f"기록했어요: 지금 6, 5년 뒤 8\n\n{AREA_ASK_Q3}"
    assert done.ladder is None


async def test_quarter_without_ladder_step_asks_areas_after_condition(tmp_path):
    from curve_sql import ladder

    # 그 달 사다리는 이미 있다: 컨디션 다음 첫 단계는 영역 점수 묻기(지난 분기 점수가 없으면 그 문장을 뺀다)
    async with _start(tmp_path, at=SUN_1227 + timedelta(seconds=30)) as env:
        ladder(env.conn, "2026-12", now=5)
        env.conn.commit()
        _, mid = await _review(env)
        await env.press("c:2026-12-27:4", message_id=mid)
        step = env.sender.sent[-1]

    assert step.text == (
        "컨디션 4 기록했어요.\n\n이번 분기 영역 점수도 여쭤볼게요. 1~10으로 답해 주세요. "
        "예: 커리어 7 경제 5 건강 6 관계 8 배움 7 삶의 질 6"
    )
    assert step.ladder is None


async def test_late_button_after_window_records_without_next_step(tmp_path):
    async with _start(tmp_path) as env:
        await _to_step1(env)
        sent = len(env.sender.sent)
        # 답장 창(회고 24시간)은 11/30 18:00에 끝났다. 버튼은 그대로 기록만 한다
        env.clock.set(kst(2026, 12, 1, 10, 0))
        assert await env.press("l:2026-11:n:6") == "recorded"
        late_now = env.bot.answers[-1][1]
        assert await env.press("l:2026-11:f:8") == "recorded"
        late_future = env.bot.answers[-1][1]
        ladder = env.parts.curve.ladder("2026-11")

    assert len(env.sender.sent) == sent  # 다음 단계는 보내지 않는다
    assert late_now == "기록했어요: 지금 6"
    assert late_future == "기록했어요: 지금 6, 5년 뒤 8"
    assert (ladder.now, ladder.future) == (6, 8)


async def test_late_skipped_review_next_review_does_not_ask_twice(tmp_path):
    from my_planner.domain import Cadence, LoopKey, SkipReason

    # 11/29 월말 회고가 늦어 skipped(late): 11월 사다리는 빈 채로 둔다. 12/6 회고는 11월을 다시 묻지 않는다
    async with _start(tmp_path, at=kst(2026, 12, 6, 18, 0) + timedelta(seconds=30)) as env:
        runs = env.parts.runs
        late = (runs.ensure(LoopKey.evening_checkin, SUN_1129), runs.ensure(LoopKey.review, SUN_1129, Cadence.week))
        for r in late:
            runs.mark_skipped(r.id, SkipReason.late)
        await env.tick()
        out = env.sender.sent[-1]
        await env.press("c:2026-12-06:4", message_id=env.sender.message_ids[-1])
        toast = env.bot.answers[-1][1]
        prompt = env.brain.prompts[0]
        november = env.parts.curve.ladder("2026-11")

    assert out.ladder is None and toast == "컨디션 4 기록했어요."
    assert len(env.sender.sent) == 1
    assert "## 월말 회고" not in prompt
    assert november is None


# --- 슬라이스 5: 새벽 경계, 답한 회차, 앱 카드 ---


async def test_ladder_button_at_0130_records_button_month(tmp_path):
    # Review Focus 5: 01:30에 누른 사다리 버튼은 버튼에 든 달에 기록한다(오늘이 든 달이 아니라)
    async with _start(tmp_path) as env:
        await _to_step1(env)
        env.clock.set(kst(2026, 11, 30, 1, 30))  # 논리적 날짜 11/29, 답장 창 안
        await env.press("l:2026-11:n:6")
        in_window = env.sender.sent[-1]
        env.clock.set(kst(2026, 12, 2, 1, 30))  # 논리적 날짜 12/1(12월), 답장 창 뒤
        await env.press("l:2026-11:f:8")
        nov, dec = env.parts.curve.ladder("2026-11"), env.parts.curve.ladder("2026-12")

    assert in_window.text == LADDER_STEP2
    assert (nov.now, nov.future) == (6, 8)
    assert dec is None


async def test_ladder_press_marks_review_answered(tmp_path):
    async with _start(tmp_path) as env:
        run_id, _ = await _review(env)
        await env.press("l:2026-11:n:6")  # 1단계 메시지(회차 메시지가 아니다)의 버튼
        tg = await (await env.get(f"/checkins/{run_id}")).json()
    assert (tg["state"], tg["answered_via"]) == ("answered", "telegram")

    async with _start(tmp_path / "app") as env:
        run_id, _ = await _review(env)
        status, body = await env.action("record_ladder_score", {"period": "2026-11", "now": 6})
        app = await (await env.get(f"/checkins/{run_id}")).json()
    assert status == 200 and body["status"] == "applied"
    assert (app["state"], app["answered_via"]) == ("answered", "app")

    # 다른 달의 사다리는 이 회고의 답이 아니다
    async with _start(tmp_path / "other") as env:
        run_id, _ = await _review(env)
        await env.action("record_ladder_score", {"period": "2026-10", "now": 6})
        other = await (await env.get(f"/checkins/{run_id}")).json()
    assert other["state"] == "pending"


async def test_app_checkin_cards_ladder_and_area(tmp_path):
    from curve_sql import area_scores

    from my_planner.tools.ui import validate_props

    async with _start(tmp_path, at=SUN_1227 + timedelta(seconds=30)) as env:
        area_scores(env.conn, "2026-Q3", career=7)
        env.conn.commit()
        run_id, _ = await _review(env)

        async def cards():
            return {c["component"]: c for c in (await (await env.get(f"/checkins/{run_id}")).json())["cards"]}

        first = await cards()
        env.clock.advance(minutes=1)
        await env.action("record_ladder_score", {"period": "2026-12", "now": 6})
        after_now = await cards()
        await env.action("record_ladder_score", {"period": "2026-12", "future": 8})
        after_future = await cards()
        await env.action("record_area_scores", {"period": "2026-Q4", "scores": {"career": 8}})
        after_areas = await cards()

    assert list(first) == ["ui_condition_picker", "ui_ladder_picker", "ui_area_scores"]
    ladder, areas = first["ui_ladder_picker"], first["ui_area_scores"]
    assert ladder["toolCallId"] == f"h_ladder_{run_id}"
    assert ladder["props"] == {"period": "2026-12", "field": "now"}
    assert areas["toolCallId"] == f"h_areas_{run_id}"
    assert areas["props"] == {"period": "2026-Q4", "previous": {"career": 7}}
    assert validate_props("ui_ladder_picker", ladder["props"]) is None
    assert validate_props("ui_area_scores", areas["props"]) is None
    assert after_now["ui_ladder_picker"]["props"] == {"period": "2026-12", "field": "future"}
    assert "ui_ladder_picker" not in after_future and "ui_area_scores" in after_future
    assert "ui_area_scores" not in after_areas


async def test_app_checkin_cards_none_outside_month_end(tmp_path):
    async with _start(tmp_path, at=kst(2026, 11, 22, 18, 0) + timedelta(seconds=30)) as env:
        run_id, _ = await _review(env)
        detail = await (await env.get(f"/checkins/{run_id}")).json()
    assert [c["component"] for c in detail["cards"]] == ["ui_condition_picker"]


async def test_resend_on_start_keeps_ladder_on_review_message(tmp_path):
    # 회고 메시지에 바로 붙인 사다리(c)가 보내지지 않았다: 시작 때 다시 보낼 때도 컨디션 줄 대신 사다리 줄
    async with _start(tmp_path) as env:
        await env.action("record_condition", {"score": 4, "date": "2026-11-29"})
        env.sender.fail = True
        await env.tick()
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
        assert env.conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "failed"
        env.conn.execute("UPDATE runs SET resent = 0 WHERE id = ?", (run_id,))
        env.conn.commit()
        env.sender.fail = False
        env.parts.dispatcher.submit_resend(env.parts.runs.get(run_id))
        await env.drain()
        (out,) = env.sender.sent

    assert out.text == f"{REVIEW}\n\n{LADDER_STEP1}"
    assert out.ladder == ("2026-11", "n") and out.ask_condition_for is None

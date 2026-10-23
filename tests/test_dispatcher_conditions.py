"""디스패처: 저녁 체크인, 자정 넘긴 답장, 아침 브리핑의 어제 컨디션 (스펙 5.3, 5.4)."""

from datetime import date

import pytest
from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.domain import ConversationKind, LoopKey, RunStatus, SkipReason
from my_planner.harness import prompts

MON = date(2026, 10, 26)
MON_1730 = kst(2026, 10, 26, 17, 30)
TUE_0900 = kst(2026, 10, 27, 9, 0)
CHECKIN = "오늘 하루 어땠어요? 컨디션을 눌러 주세요."


def _env(tmp_path, conn, state, script, start):
    return Env(tmp_path, conn, state, script=script, start=start, with_tools=True, with_conditions=True)


def _queued(env, loop, at):
    run = env.runs.ensure(loop, at)
    env.runs.mark_queued(run.id)
    return env.runs.get(run.id)


async def test_evening_run_sets_ask_condition_for_logical_date(tmp_path, conn, state):
    # 월 17:30 체크인을 화 01:00에 보내도(한계 04:00 안) 버튼 날짜는 그 회차의 논리적 날짜(월)다
    env = _env(tmp_path, conn, state, [FakeTurn([], CHECKIN)], start=kst(2026, 10, 27, 1, 0))
    run = _queued(env, LoopKey.evening_checkin, MON_1730)
    await env.process_run(run)

    assert [(o.text, o.ask_condition_for) for o in env.sender.sent] == [(CHECKIN, MON)]
    assert env.runs.get(run.id).status is RunStatus.done
    assert prompts.load("evening_checkin.md") in env.brain.prompts[0]


async def test_resend_after_failed_send_keeps_condition_buttons(tmp_path, conn, state):
    from test_dispatcher_runs import TimedSender, _wait_for

    env = _env(tmp_path, conn, state, [FakeTurn([], CHECKIN)], start=MON_1730)
    env.sender = env.dispatcher.sender = TimedSender(env.clock, fail_times=3)
    run = _queued(env, LoopKey.evening_checkin, MON_1730)
    env.dispatcher.start()
    env.dispatcher.submit_run(run, [])
    await _wait_for(lambda: env.runs.get(run.id).resent == 1)
    await env.dispatcher.stop(timeout=5)

    assert [(o.text, o.ask_condition_for) for o in env.sender.sent] == [(CHECKIN, MON)]


async def _sent_checkin(tmp_path, conn, state, script):
    env = _env(tmp_path, conn, state, [FakeTurn([], CHECKIN, session_id="eve-s"), *script], start=MON_1730)
    run = _queued(env, LoopKey.evening_checkin, MON_1730)
    await env.process_run(run)
    return env, env.runs.get(run.id).conversation_id


async def test_reply_to_evening_checkin_after_midnight_continues(tmp_path, conn, state):
    env, run_conv = await _sent_checkin(
        tmp_path, conn, state,
        [FakeTurn([], "푹 쉬세요.", session_id="eve-s"), FakeTurn([], "네, 내일 봬요.", session_id="eve-s")],
    )

    env.clock.set(kst(2026, 10, 27, 1, 30))  # 자정 넘어 화 01:30, 논리적 날짜는 아직 월
    await env.process(env.inbound("오늘은 좀 지쳤어요", update_id=1))
    env.clock.set(kst(2026, 10, 27, 3, 59))  # 마지막 말 뒤 2시간이 넘었어도 답장 창(04:00) 안
    await env.process(env.inbound("이제 잘게요", update_id=2))

    assert env.brain.session_ids[1:] == ["eve-s", "eve-s"]
    assert [c["run_ctx"].conversation_id for c in env.brain.calls[1:]] == [run_conv, run_conv]
    mon = env.day_file("2026-10-26").read_text(encoding="utf-8")
    assert f"### 01:30 사용자 [{run_conv}]" in mon and "오늘은 좀 지쳤어요" in mon
    assert not env.day_file("2026-10-27").exists()


async def test_reply_after_0400_opens_new_chat(tmp_path, conn, state):
    env, run_conv = await _sent_checkin(tmp_path, conn, state, [FakeTurn([], "좋은 아침이에요.", session_id="chat-s")])

    env.clock.set(kst(2026, 10, 27, 4, 1))  # 답장 창(화 04:00) 밖, 논리적 날짜도 화
    await env.process(env.inbound("일찍 깼어요", update_id=1))

    assert env.brain.session_ids[1] is None
    conv = env.convs.get(env.brain.calls[1]["run_ctx"].conversation_id)
    assert conv.id != run_conv and conv.kind is ConversationKind.chat
    assert prompts.load("chat.md") in env.brain.prompts[1]
    tue = env.day_file("2026-10-27").read_text(encoding="utf-8")
    assert f"### 04:01 사용자 [{conv.id}]" in tue and "일찍 깼어요" in tue


@pytest.mark.parametrize("reason", [SkipReason.late, SkipReason.merged_into_return])
async def test_morning_asks_yesterday_condition_when_evening_not_done(tmp_path, conn, state, reason):
    env = _env(tmp_path, conn, state, [FakeTurn([], "좋은 아침이에요.")], start=TUE_0900)
    eve = env.runs.ensure(LoopKey.evening_checkin, MON_1730)
    env.runs.mark_skipped(eve.id, reason)
    run = _queued(env, LoopKey.morning_brief, TUE_0900)
    await env.process_run(run)

    assert [o.ask_condition_for for o in env.sender.sent] == [MON]


async def test_morning_no_ask_when_condition_exists(tmp_path, conn, state):
    # 어제 체크인이 늦어 건너뛰었어도, 어제 컨디션이 이미 있으면(예: 글로 말해 기록함) 묻지 않는다
    env = _env(tmp_path, conn, state, [FakeTurn([], "좋은 아침이에요.")], start=TUE_0900)
    eve = env.runs.ensure(LoopKey.evening_checkin, MON_1730)
    env.runs.mark_skipped(eve.id, SkipReason.late)
    env.conditions.upsert(MON, 3, None)
    run = _queued(env, LoopKey.morning_brief, TUE_0900)
    await env.process_run(run)

    assert [o.ask_condition_for for o in env.sender.sent] == [None]


async def test_morning_no_ask_when_evening_done(tmp_path, conn, state):
    # 어제 체크인이 나갔으면(done) 버튼을 누르지 않았어도 아침에 다시 묻지 않는다
    env = _env(tmp_path, conn, state, [FakeTurn([], "좋은 아침이에요.")], start=TUE_0900)
    eve = env.runs.ensure(LoopKey.evening_checkin, MON_1730)
    env.runs.mark_done(eve.id)
    run = _queued(env, LoopKey.morning_brief, TUE_0900)
    await env.process_run(run)

    assert [o.ask_condition_for for o in env.sender.sent] == [None]


async def test_preamble_yesterday_condition(tmp_path, conn, state):
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], "좋은 아침이에요."), FakeTurn([], "안녕하세요.")],
        start=TUE_0900,
    )
    env.conditions.upsert(MON, 2, "머리가 아팠어요")
    run = _queued(env, LoopKey.morning_brief, TUE_0900)
    await env.process_run(run)
    assert "## 어제 컨디션\n2/5 (메모: 머리가 아팠어요)" in env.brain.prompts[0]

    # 기록이 없으면 "기록 없음"
    env.clock.set(kst(2026, 10, 28, 13, 0))  # 수요일, 어제(화) 기록 없음
    await env.process(env.inbound("안녕", update_id=1))
    assert "## 어제 컨디션\n기록 없음" in env.brain.prompts[1]


async def test_run_prompt_says_condition_buttons_attached(tmp_path, conn, state):
    # 두뇌가 버튼이 붙는다는 것을 알고 쓰도록, 버튼을 붙이는 회차에만 알린다
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], "좋은 아침이에요."), FakeTurn([], "좋은 아침이에요.")],
        start=TUE_0900,
    )
    run = _queued(env, LoopKey.morning_brief, TUE_0900)  # 어제 체크인 회차가 없다: done이 아니다
    await env.process_run(run)
    assert "## 컨디션 버튼\n이 메시지 아래에 10/26(월) 컨디션 버튼(1~5)이 붙습니다." in env.brain.prompts[0]

    env.conditions.upsert(date(2026, 10, 27), 4, None)
    wed = _queued(env, LoopKey.morning_brief, kst(2026, 10, 28, 9, 0))
    env.clock.set(kst(2026, 10, 28, 9, 0))
    await env.process_run(wed)
    assert "## 컨디션 버튼" not in env.brain.prompts[1]


async def test_reply_after_condition_button_tells_brain_the_score(tmp_path, conn, state):
    # 버튼은 두뇌를 거치지 않는다. 이어지는 답에서 두뇌가 점수를 알아야 "2 이하면 줄이자"를 할 수 있다
    from my_planner.domain import RunContext

    env, _ = await _sent_checkin(
        tmp_path, conn, state,
        [FakeTurn([], "내일은 하나만 해요.", session_id="eve-s"), FakeTurn([], "네.", session_id="eve-s")],
    )
    env.clock.set(kst(2026, 10, 26, 18, 0))
    await env.process(env.inbound("별일 없었어요", update_id=1))
    assert "## 기록된 컨디션" not in env.brain.prompts[1]

    env.tools.record_condition(RunContext(None, None), score=2, date="2026-10-26")  # 버튼 누름
    env.clock.set(kst(2026, 10, 27, 0, 30))
    await env.process(env.inbound("오늘 좀 힘들었어요", update_id=2))
    prompt = env.brain.prompts[2]
    assert "## 기록된 컨디션\n- 오늘(10/26): 2/5" in prompt
    assert prompt.index("## 기록된 컨디션") < prompt.index("## 메시지")


def test_condition_prompts_cover_buttons_and_lightening_without_banned_words():
    eve = prompts.load("evening_checkin.md")
    for must in ("버튼(1~5)", "한 줄 메모", "record_condition", "오늘 한 일", "내일로 옮길", "move_task", "2 이하"):
        assert must in eve, must
    assert "2 이하" in prompts.load("morning_brief.md") and "컨디션 버튼" in prompts.load("morning_brief.md")
    assert "2 이하" in prompts.load("chat.md") and "record_condition" in prompts.load("chat.md")
    for name in ("evening_checkin.md", "morning_brief.md", "chat.md"):
        for word in ("놓쳤어요", "밀렸어요", "늦었지만", "실패"):
            assert word not in prompts.load(name), (name, word)


async def test_reply_after_yesterday_button_tells_brain_the_score(tmp_path, conn, state):
    # 아침 브리핑에 붙은 어제 버튼을 누른 뒤 같은 아침 대화로 답하면 두뇌가 어제 점수를 안다
    from my_planner.domain import RunContext

    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], "좋은 아침이에요.", session_id="am-s"), FakeTurn([], "오늘은 가볍게 해요.", session_id="am-s")],
        start=TUE_0900,
    )
    run = _queued(env, LoopKey.morning_brief, TUE_0900)
    await env.process_run(run)
    env.tools.record_condition(RunContext(None, None), score=1, date="2026-10-26")  # 어제 버튼
    env.clock.set(kst(2026, 10, 27, 9, 30))
    await env.process(env.inbound("어제 너무 힘들었어요", update_id=1))

    assert env.brain.session_ids[1] == "am-s"
    assert "## 기록된 컨디션\n- 어제(10/26): 1/5" in env.brain.prompts[1]


async def test_evening_run_sent_at_limit_0400_still_asks_its_own_date(tmp_path, conn, state):
    # 한계 시각 정확히 화 04:00에 보내면 지금의 논리적 날짜는 화지만, 버튼 날짜는 그 회차의 날짜(월)다
    env = _env(tmp_path, conn, state, [FakeTurn([], CHECKIN)], start=kst(2026, 10, 27, 4, 0))
    run = _queued(env, LoopKey.evening_checkin, MON_1730)
    await env.process_run(run)

    assert [o.ask_condition_for for o in env.sender.sent] == [MON]
    assert "이 메시지 아래에 10/26(월) 컨디션 버튼" in env.brain.prompts[0]


async def test_morning_asks_when_only_an_older_evening_is_done(tmp_path, conn, state):
    # 일요일 체크인은 done이어도 월요일 체크인이 늦어 건너뛰었으면 화 아침은 월요일을 묻는다
    env = _env(tmp_path, conn, state, [FakeTurn([], "좋은 아침이에요.")], start=TUE_0900)
    sun = env.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
    env.runs.mark_done(sun.id)
    mon = env.runs.ensure(LoopKey.evening_checkin, MON_1730)
    env.runs.mark_skipped(mon.id, SkipReason.late)
    run = _queued(env, LoopKey.morning_brief, TUE_0900)
    await env.process_run(run)

    assert [o.ask_condition_for for o in env.sender.sent] == [MON]


async def test_evening_merged_into_review_still_gets_buttons(tmp_path, conn, state):
    # 일 18:00 회고와 저녁 체크인을 합쳐 회고가 primary여도 저녁 체크인 날짜의 버튼을 붙인다
    from my_planner.domain import Cadence

    sun_1800 = kst(2026, 10, 25, 18, 0)
    env = _env(tmp_path, conn, state, [FakeTurn([], "한 주 돌아보기와 체크인")], start=sun_1800)
    review = env.runs.ensure(LoopKey.review, sun_1800, Cadence.week)
    eve = env.runs.ensure(LoopKey.evening_checkin, sun_1800)
    for r in (review, eve):
        env.runs.mark_queued(r.id)
    await env.process_run(env.runs.get(review.id), [env.runs.get(eve.id)])

    assert [o.ask_condition_for for o in env.sender.sent] == [date(2026, 10, 25)]


async def test_return_run_uses_return_prompt_without_condition_buttons(tmp_path, conn, state):
    # 화 08:00 복귀 인사(어제 체크인 없음): return.md로 쓰고, 컨디션 버튼은 붙이지 않는다. 먼저 보낸 메시지로 센다
    hello = "다시 이어서 해 볼까요? 오늘은 보고서 목차부터 정해 봐요."
    tue_0800 = kst(2026, 10, 27, 8, 0)
    env = _env(tmp_path, conn, state, [FakeTurn([], hello)], start=tue_0800)
    run = _queued(env, LoopKey.return_, tue_0800)
    await env.process_run(run)

    assert [(o.text, o.ask_condition_for) for o in env.sender.sent] == [(hello, None)]
    assert prompts.load("return.md") in env.brain.prompts[0]
    assert "## 컨디션 버튼" not in env.brain.prompts[0]
    assert env.runs.get(run.id).status is RunStatus.done
    assert state.usage(date(2026, 10, 27)).proactive_messages == 1

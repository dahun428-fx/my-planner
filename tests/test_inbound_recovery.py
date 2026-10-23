"""받은 메시지는 답하기 전에 저장하고, 강제 종료 뒤 시작할 때 다시 처리한다 (최종 리뷰 Important 1)."""

import asyncio
from datetime import timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst
from test_telegram_io import OWNER, _RecordingBot, _update

from my_planner.bot.telegram_io import handle_update
from my_planner.loop.runner import resubmit_inbound

START = kst(2026, 10, 23, 15, 0)


async def _receive(env, state, update_id, text):
    return await handle_update(
        _update(update_id=update_id, text=text),
        bot=_RecordingBot(), owner_id=OWNER, state=state, dispatcher=env.dispatcher,
        transcripts=env.transcripts, clock=env.clock,
    )


async def _kill(env):
    """강제 종료: 진행 중인 두뇌 호출을 기다리지 않고 작업자를 끊는다(아무것도 더 쓰지 않는다)."""
    await env.dispatcher.stop(timeout=0.01)


async def test_kill_between_submit_and_send_then_restart_replies_exactly_once(tmp_path, conn, state):
    first = Env(tmp_path, conn, state, script=[FakeTurn([], "", hang=True)], start=START)
    first.dispatcher.start()
    assert await _receive(first, state, 41, "내일 치과 14시 추가해 줘") == "accept"
    while not first.brain.calls:  # 두뇌 호출 중에
        await asyncio.sleep(0)
    await _kill(first)
    assert first.sender.sent == [] and not state.is_seen_update(41)

    # 다시 시작: 복구 뒤 남은 메시지를 다시 넣는다
    second = Env(tmp_path, conn, state, script=[FakeTurn([], "내일 14시에 치과 넣어 둘게요.")], start=START)
    second.clock.advance(timedelta(minutes=10))
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()

    assert [o.text for o in second.sender.sent] == ["내일 14시에 치과 넣어 둘게요."]
    assert "내일 치과 14시 추가해 줘" in second.brain.prompts[0]
    assert state.is_seen_update(41) and state.pending_inbound() == []

    # 그다음 시작에는 다시 넣을 것이 없다: 답은 정확히 한 번
    third = Env(tmp_path, conn, state, script=[], start=START + timedelta(minutes=20))
    assert resubmit_inbound(state, third.dispatcher) == 0


async def test_resubmitted_old_message_gets_stale_and_redacted_notices(tmp_path, conn, state):
    # 노트북이 꺼진 채 7시간: 보낸 시각 기준으로 "몇 시간 전" 알림, 저장해 둔 가린 글이라 가렸다는 알림도 붙인다
    first = Env(tmp_path, conn, state, script=[], start=START)
    assert await _receive(first, state, 42, "비번은 hunter2야 그리고 운동 내일로 옮겨") == "accept"
    # 작업자를 시작하기 전에 꺼졌다(큐에서 기다리던 메시지)

    second = Env(tmp_path, conn, state, script=[FakeTurn([], "내일로 옮겨 둘게요.")], start=START)
    second.clock.set(kst(2026, 10, 23, 22, 0))
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()

    prompt = second.brain.prompts[0]
    assert "hunter2" not in prompt and "비번은 [가림]야 그리고 운동 내일로 옮겨" in prompt
    assert "- 인증·식별 정보를 가렸어요." in prompt
    assert "시간 전에 보낸 메시지예요." in prompt
    assert [o.text for o in second.sender.sent] == ["내일로 옮겨 둘게요."]
    assert state.pending_inbound() == []


async def test_reply_that_never_sent_is_resubmitted_on_next_start(tmp_path, conn, state):
    from fakes import FakeSender

    first = Env(tmp_path, conn, state, script=[FakeTurn([], "첫 답")], start=START, sender=FakeSender(fail=True))
    first.dispatcher.start()
    await _receive(first, state, 43, "오늘 할 일 알려 줘")
    await first.dispatcher.stop(timeout=5)
    assert [p.update_id for p in state.pending_inbound()] == [43]  # 전송 3회가 다 안 됐다: 남겨 둔다

    second = Env(tmp_path, conn, state, script=[FakeTurn([], "다시 정리한 답")], start=START + timedelta(minutes=5))
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()
    assert [o.text for o in second.sender.sent] == ["다시 정리한 답"]
    assert state.pending_inbound() == [] and state.is_seen_update(43)

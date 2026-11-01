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


def _day(env):
    return env.day_file("2026-10-23").read_text(encoding="utf-8")


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
    assert _day(second).count("사용자 [") == 1  # 다시 처리해도 사용자 줄은 한 번

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


async def test_final_send_failure_then_restart_resends_saved_reply_without_brain(tmp_path, conn, state):
    from fakes import FakeSender

    first = Env(tmp_path, conn, state, script=[FakeTurn([], "첫 답")], start=START, sender=FakeSender(fail=True))
    first.dispatcher.start()
    await _receive(first, state, 43, "오늘 할 일 알려 줘")
    await first.dispatcher.stop(timeout=5)
    assert [p.update_id for p in state.pending_inbound()] == [43]  # 전송 3회가 다 안 됐다: 남겨 둔다

    second = Env(tmp_path, conn, state, script=[], start=START + timedelta(minutes=5))
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()

    assert second.brain.calls == []  # 두뇌는 다시 부르지 않는다
    assert [o.text for o in second.sender.sent] == ["첫 답"]  # 저장해 둔 답을 보낸다
    assert state.pending_inbound() == [] and state.is_seen_update(43)
    day = _day(second)
    assert day.count("사용자 [") == 1 and day.count("비서 [") == 1


async def test_kill_after_tools_ran_then_restart_sends_confirmation_without_brain(tmp_path, conn, state):
    from my_planner.domain import TaskStatus
    from my_planner.harness.dispatcher import FALLBACK_REPLY

    add = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-24"})
    first = Env(tmp_path, conn, state, script=[FakeTurn([add], "", hang=True)], start=START, with_tools=True)
    first.dispatcher.start()
    await _receive(first, state, 44, "내일 치과 추가해 줘")
    while not first.brain.calls:
        await asyncio.sleep(0)
    await _kill(first)
    assert first.sender.sent == []

    second = Env(tmp_path, conn, state, script=[], start=START + timedelta(minutes=5), with_tools=True)
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()

    assert second.brain.calls == []  # 도구가 이미 썼다: 두뇌를 다시 부르지 않는다(스펙 5.4-3)
    assert len(second.tools.tasks.list(status=TaskStatus.open)) == 1  # 할 일은 하나
    assert [o.text for o in second.sender.sent] == [f"{FALLBACK_REPLY}\n\n✓ 추가: 치과 → 내일"]
    assert state.pending_inbound() == [] and state.is_seen_update(44)
    assert _day(second).count("사용자 [") == 1


async def test_kill_after_proposal_then_restart_keeps_draft_buttons(tmp_path, conn, state):
    from test_dispatcher_drafts import propose

    from my_planner.domain import TaskStatus

    first = Env(
        tmp_path, conn, state, script=[FakeTurn([propose("목차 쓰기")], "", hang=True)], start=START, with_tools=True
    )
    first.dispatcher.start()
    await _receive(first, state, 45, "보고서 어떻게 시작하지")
    while not first.brain.calls:
        await asyncio.sleep(0)
    await _kill(first)

    second = Env(tmp_path, conn, state, script=[], start=START + timedelta(minutes=5), with_tools=True)
    resubmit_inbound(state, second.dispatcher)
    await second.process()

    [draft] = second.tools.tasks.list(status=TaskStatus.draft)
    assert second.brain.calls == []
    assert second.sender.sent[0].draft_task_ids == [draft.id]


def test_pending_row_dropped_after_3_attempts(tmp_path, conn, state):
    import json
    import logging
    from datetime import UTC, datetime

    from my_planner.logging_setup import setup_logging

    log_path = setup_logging(tmp_path / "state", 30)
    now = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    state.add_pending_inbound(46, "늘 실패하는 글", now, now)

    class _Collect:
        def __init__(self):
            self.got = []

        def submit_message(self, m):
            self.got.append(m)  # 처리하지 못하고 다시 꺼졌다

    for _ in range(3):
        assert resubmit_inbound(state, _Collect()) == 1
    last = _Collect()
    assert resubmit_inbound(state, last) == 0 and last.got == []
    assert state.pending_inbound() == []
    for h in logging.getLogger().handlers:
        h.flush()
    dropped = [e for e in map(json.loads, log_path.read_text(encoding="utf-8").splitlines())
               if e.get("msg") == "inbound_dropped"]
    assert len(dropped) == 1 and dropped[0]["update_id"] == 46 and dropped[0]["reason"] == "max_attempts"
    assert "늘 실패하는 글" not in log_path.read_text(encoding="utf-8")


async def test_fresh_message_reusing_old_update_id_calls_brain(tmp_path, conn, state):
    # 텔레그램은 한동안 업데이트가 없으면 update_id를 새로 고른다. 예전 메시지의 도구 기록(inbound_id)과 번호가
    # 같아도 새 메시지는 두뇌를 그대로 부른다(최종 재리뷰 Minor 2)
    env = Env(tmp_path, conn, state, script=[FakeTurn([], "새 답")], start=START, with_tools=True)
    env.tools.tasks.log_tool_event(None, 99, 1, "task_added", inbound_id=47, data={"title": "예전 일"})
    env.dispatcher.start()
    await _receive(env, state, 47, "새로 묻는 말")
    await env.dispatcher.stop(timeout=5)

    assert len(env.brain.calls) == 1
    assert [o.text for o in env.sender.sent] == ["새 답"]


async def test_recovered_inbound_keeps_agent(tmp_path):
    """Review Focus 2 (SP12 5.1): 받을 때 정한 상대(`inbound_pending.agent`)로 다시 넣는다. 받은 메이트 대화가 그 사이
    닫혔어도 새 메이트 대화로 처리하고, 열린 비서 대화는 그대로 둔다."""
    from be_env import BeEnv
    from test_mate_prompts import app_message

    start = kst(2026, 10, 31, 19, 0)
    async with BeEnv.start(tmp_path, start=start, script=[FakeTurn([], "가볍게 걸어요")]) as env:
        p = env.parts
        sec = p.dispatcher.route_app_message(env.clock.now(), conversation_id=None, checkin_id=None)
        msg = app_message(env, "오늘 뭐 할까?", "cm-mate-restart", agent="mate")  # 받아 저장한 뒤 BE가 멈췄다
        assert p.state.pending_inbound()[0].agent == "mate"
        p.convs.close(msg.conversation_id)  # 다시 시작하기 전에 받은 대화가 닫혔다
        assert resubmit_inbound(p.state, p.dispatcher) == 1
        await env.drain()
        (call,) = env.brain.calls
        conv = p.convs.get(call["run_ctx"].conversation_id)
        sec_now = p.convs.get(sec.id)
        lines = p.transcripts.messages(conv.id)

    assert call["run_ctx"].agent == "mate"
    assert conv.agent == "mate" and conv.id != msg.conversation_id and conv.id != sec.id
    assert sec_now.closed_at is None
    assert [m.speaker for m in lines] == ["사용자", "운동메이트"]

"""계획 모드 (스펙 5.3 대화 규칙, 5.7): 디스패처 경계."""

from datetime import timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.domain import ConversationKind, LoopKey


async def test_plan_takes_precedence_and_expires_after_2h(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "잡담"), FakeTurn([], "계획 하나"), FakeTurn([], "계획 둘"), FakeTurn([], "새 잡담", session_id="s9")],
        start=kst(2026, 10, 26, 10, 0),
    )
    # 아침 브리핑 대화가 답장 창(12:00) 안에 있고, 30분 이내의 chat 대화도 있다
    run = env.runs.ensure(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    env.runs.mark_done(run.id)
    run_conv = env.dispatcher.router.for_run(run)
    await env.process(env.inbound("안녕", update_id=1))
    chat_id = env.brain.calls[0]["run_ctx"].conversation_id

    plan = env.dispatcher.router.start_plan()
    assert plan.kind is ConversationKind.plan
    env.clock.advance(timedelta(minutes=5))
    await env.process(env.inbound("이번 주 계획", update_id=2))
    # 정확히 2시간 뒤까지는 계획 대화를 잇는다
    env.clock.advance(timedelta(hours=2))
    await env.process(env.inbound("하나 더", update_id=3))
    ids = [c["run_ctx"].conversation_id for c in env.brain.calls]
    assert ids[1] == ids[2] == plan.id
    assert plan.id not in (chat_id, run_conv.id)
    assert env.brain.session_ids[2] == "s1"

    # 마지막 메시지 뒤 2시간이 지나면 저절로 닫히고, 30분 규칙을 쓰지 않는다
    env.clock.advance(timedelta(hours=2, minutes=1))
    assert env.dispatcher.router.plan_open() is False
    await env.process(env.inbound("다른 이야기", update_id=4))
    new_id = env.brain.calls[3]["run_ctx"].conversation_id
    assert new_id not in (plan.id, chat_id, run_conv.id)
    assert env.convs.get(new_id).kind is ConversationKind.chat
    assert env.convs.get(plan.id).closed_at is not None


async def test_plan_uses_plan_prompt(tmp_path, conn, state):
    from my_planner.harness import prompts

    propose = ("propose_tasks", {"tasks": [{"title": "목차 쓰기", "areas": ["career"]}]})
    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "무엇을 하고 싶으세요?"), FakeTurn([propose], "이렇게 시작해 볼까요?")],
        start=kst(2026, 10, 26, 16, 50),
        with_tools=True,
    )
    plan = env.dispatcher.router.start_plan()
    await env.process(env.inbound("계획 모드 시작", update_id=1))
    env.clock.advance(timedelta(minutes=3))
    await env.process(env.inbound("보고서", update_id=2))

    first, second = env.brain.prompts
    assert prompts.load("plan.md") in first
    assert prompts.load("chat.md") not in first
    assert "## 메시지\n계획 모드 시작" in first
    assert prompts.load("plan.md") not in second  # 이어지는 세션은 메시지만
    # 계획 대화의 제안도 초안 버튼으로 확정받는다
    out = env.sender.sent[1]
    assert out.draft_conversation_id == plan.id and len(out.draft_task_ids) == 1
    # 글로 모드를 바꾸지 않고 명령을 안내한다
    assert "/done" in prompts.load("plan.md") and "여기까지" in prompts.load("plan.md")
    assert "/plan" in prompts.load("chat.md") and "같이 계획 세우자" in prompts.load("chat.md")


async def test_queued_run_waits_while_plan_open(tmp_path, conn, state):
    # 큐에 든 뒤 /plan이 열리면 회차는 건너뛰지 않고 pending으로 돌아가 다음 tick이 다시 판정한다.
    # 넘겨 받은 회고는 표시(carry_review_run_id)를 되돌려 혼자 실행되지 않게 한다
    from my_planner.domain import Cadence, RunStatus
    from my_planner.loop.runner import CARRY_REVIEW_KEY

    env = Env(tmp_path, conn, state, script=[], start=kst(2026, 10, 26, 17, 31))
    evening = env.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
    review = env.runs.ensure(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    for r in (evening, review):
        env.runs.mark_queued(r.id)
    env.dispatcher.router.start_plan()

    env.dispatcher.start()
    env.dispatcher.submit_run(env.runs.get(evening.id), [env.runs.get(review.id)], carried_ids=[review.id])
    await env.dispatcher.stop(timeout=5)

    assert env.brain.calls == [] and env.sender.sent == []
    assert env.runs.get(evening.id).status is RunStatus.pending
    assert env.runs.get(review.id).status is RunStatus.pending
    assert env.runs.get(evening.id).merged_run_ids == []
    assert state.get(CARRY_REVIEW_KEY) == str(review.id)

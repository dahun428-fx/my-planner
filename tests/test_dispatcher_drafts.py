"""디스패처: 제안한 초안을 버튼용으로 Outbound에 싣는다 (스펙 5.7)."""

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst
from test_dispatcher_runs import MON_0900, RecordingSender, _queued_morning

from my_planner.domain import RunContext, TaskStatus


def propose(*titles):
    return ("propose_tasks", {"tasks": [{"title": t, "areas": ["career"]} for t in titles]})


async def test_chat_proposals_go_to_outbound_draft_ids(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state, start=kst(2026, 10, 24, 10, 0), with_tools=True,
        script=[FakeTurn([propose("목차 쓰기", "자료 모으기")], "이렇게 해 보면 어떨까요?")],
    )
    await env.process(env.inbound("보고서 어떻게 시작하지"))

    out = env.sender.sent[0]
    assert out.text == "이렇게 해 보면 어떨까요?"  # 제안에는 확인 문구가 없다
    drafts = env.tools.tasks.list(status=TaskStatus.draft)
    assert out.draft_task_ids == [t.id for t in drafts] and len(drafts) == 2
    conv_id = env.brain.calls[0]["run_ctx"].conversation_id
    assert out.draft_conversation_id == conv_id


async def test_run_proposals_go_to_outbound_draft_ids(tmp_path, conn, state):
    from datetime import timedelta

    env = Env(
        tmp_path, conn, state, start=MON_0900 + timedelta(seconds=30), with_tools=True,
        sender=RecordingSender(), script=[FakeTurn([propose("산책 20분")], "좋은 아침이에요.")],
    )
    run = _queued_morning(env)
    await env.process_run(run)

    out = env.sender.sent[0]
    draft = env.tools.tasks.list(status=TaskStatus.draft)[0]
    assert out.text == "좋은 아침이에요."
    assert out.draft_task_ids == [draft.id]
    assert out.draft_conversation_id == env.runs.get(run.id).conversation_id


async def test_confirm_by_words_shows_confirmation_and_no_buttons(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state, start=kst(2026, 10, 24, 10, 0), with_tools=True,
        script=[FakeTurn([("confirm_tasks", {"ids": [1]})], "넣어 둘게요.")],
    )
    env.tools.propose_tasks(RunContext(None, None), tasks=[{"title": "목차 쓰기", "areas": ["career"]}])
    await env.process(env.inbound("좋아 다 넣어"))

    out = env.sender.sent[0]
    assert out.text == "넣어 둘게요.\n\n✓ 확정: 목차 쓰기"
    assert out.draft_task_ids == [] and out.draft_conversation_id is None


async def test_resend_after_failed_send_keeps_draft_buttons(tmp_path, conn, state):
    from datetime import timedelta

    from test_dispatcher_runs import _wait_for

    env = Env(
        tmp_path, conn, state, start=MON_0900 + timedelta(seconds=30), with_tools=True,
        sender=RecordingSender(fail_times=3), script=[FakeTurn([propose("산책 20분")], "좋은 아침이에요.")],
    )
    run = _queued_morning(env)
    env.dispatcher.start()
    env.dispatcher.submit_run(run, [])
    await _wait_for(lambda: env.runs.get(run.id).resent == 1 and env.sender.sent)
    await env.dispatcher.stop(timeout=5)

    out = env.sender.sent[0]
    assert out.draft_task_ids == [env.tools.tasks.list(status=TaskStatus.draft)[0].id]
    assert out.draft_conversation_id == env.runs.get(run.id).conversation_id


async def test_morning_brief_preamble_hides_drafts(tmp_path, conn, state):
    from datetime import timedelta

    env = Env(
        tmp_path, conn, state, start=MON_0900 + timedelta(seconds=30), with_tools=True,
        sender=RecordingSender(), script=[FakeTurn([], "좋은 아침이에요.")],
    )
    env.tools.add_task(RunContext(None, None), title="열린 일", areas=["career"], planned_for="2026-10-26")
    env.tools.propose_tasks(
        RunContext(3, None),
        tasks=[{"title": "제안한 초안", "areas": ["career"], "scheduled_at": "2026-10-26T15:00"}],
    )
    await env.process_run(_queued_morning(env))

    assert "열린 일" in env.brain.prompts[0]
    assert "제안한 초안" not in env.brain.prompts[0]


async def test_ids_confirmed_in_same_turn_get_no_buttons(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state, start=kst(2026, 10, 24, 10, 0), with_tools=True,
        script=[FakeTurn([propose("목차 쓰기", "자료 모으기"), ("confirm_tasks", {"ids": [1]})], "하나는 넣었어요.")],
    )
    await env.process(env.inbound("목차는 바로 넣어 줘"))

    out = env.sender.sent[0]
    assert out.draft_task_ids == [2]
    assert out.text.endswith("✓ 확정: 목차 쓰기")

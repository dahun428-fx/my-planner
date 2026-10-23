import asyncio
from datetime import timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst


async def test_chat_resumes_within_30_minutes(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "하나"), FakeTurn([], "둘")],
        start=kst(2026, 10, 23, 10, 0),
    )
    env.dispatcher.start()
    env.dispatcher.submit_message(env.inbound("첫 말", update_id=1))
    await env.dispatcher.stop(timeout=5)
    env.clock.advance(timedelta(minutes=29))
    await env.process(env.inbound("둘째 말", update_id=2))

    assert env.brain.session_ids == [None, "s1"]
    assert len({c["run_ctx"].conversation_id for c in env.brain.calls}) == 1
    assert "## 메시지" in env.brain.prompts[1]
    assert "## 지금 상황" not in env.brain.prompts[1]  # 이어지는 세션은 chat.md 없이 메시지만


async def test_chat_new_after_31_minutes(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "하나"), FakeTurn([], "둘", session_id="s2")],
        start=kst(2026, 10, 23, 10, 0),
    )
    await env.process(env.inbound("첫 말", update_id=1))
    env.clock.advance(timedelta(minutes=31))
    await env.process(env.inbound("둘째 말", update_id=2))

    assert env.brain.session_ids == [None, None]
    ids = [c["run_ctx"].conversation_id for c in env.brain.calls]
    assert ids[0] != ids[1]
    assert "## 지금 상황" in env.brain.prompts[1]
    assert env.convs.get(ids[0]).closed_at is not None


async def test_queued_messages_coalesce(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "첫 답", delay=1), FakeTurn([], "묶은 답")],
        start=kst(2026, 10, 23, 10, 0),
    )
    env.dispatcher.start()
    env.dispatcher.submit_message(env.inbound("첫 문장", update_id=1))
    while not env.brain.calls:  # 첫 호출이 진행 중일 때 두 개가 더 온다
        await asyncio.sleep(0)
    env.dispatcher.submit_message(env.inbound("둘째 문장", update_id=2))
    env.dispatcher.submit_message(env.inbound("셋째 문장", update_id=3))
    await env.dispatcher.stop(timeout=5)

    assert len(env.brain.calls) == 2
    assert "둘째 문장\n\n셋째 문장" in env.brain.prompts[1]
    assert [o.text for o in env.sender.sent] == ["첫 답", "묶은 답"]
    assert all(state.is_seen_update(i) for i in (1, 2, 3))


async def test_truncate_huge_input(tmp_path, conn, state):
    env = Env(tmp_path, conn, state, script=[FakeTurn([], "네")], start=kst(2026, 10, 23, 10, 0))
    await env.process(env.inbound("가" * 9000))

    prompt = env.brain.prompts[0]
    assert "가" * 8000 in prompt and "가" * 8001 not in prompt
    assert "## 알림" in prompt and "메시지가 길어 앞 8000자만 넘겼어요" in prompt
    assert prompt.index("## 알림") < prompt.index("## 지금 상황")


async def test_stale_message_notice(tmp_path, conn, state):
    env = Env(tmp_path, conn, state, script=[FakeTurn([], "네")], start=kst(2026, 10, 23, 18, 0))
    m = env.inbound("예전에 쓴 글")
    m.sent_at = m.at - timedelta(hours=7)
    await env.process(m)

    assert "약 7시간 전에 보낸 메시지예요" in env.brain.prompts[0]

    env2 = Env(tmp_path / "b", conn, state, script=[FakeTurn([], "네")], start=kst(2026, 10, 23, 18, 0))
    m2 = env2.inbound("방금 쓴 글", update_id=9)
    m2.sent_at = m2.at - timedelta(hours=5)
    await env2.process(m2)
    assert "시간 전에 보낸" not in env2.brain.prompts[0]


async def test_redaction_notice_on_resumed_session(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "하나"), FakeTurn([], "둘")],
        start=kst(2026, 10, 23, 10, 0),
    )
    await env.process(env.inbound("안녕", update_id=1))
    env.clock.advance(timedelta(minutes=5))
    await env.process(env.inbound("비번은 hunter2 야", update_id=2))

    assert env.brain.session_ids == [None, "s1"]
    assert env.brain.prompts[1].startswith("## 알림")
    assert "인증·식별 정보를 가렸어요" in env.brain.prompts[1]
    assert "## 알림" not in env.brain.prompts[0]


async def test_resume_failure_falls_back_to_new_session_with_last_20_messages(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state,
        script=[
            FakeTurn([], "하나"),
            FakeTurn([], "", status="error", session_id=None, resume_failed=True),
            FakeTurn([], "다시 정리했어요", session_id="s9"),
        ],
        start=kst(2026, 10, 23, 10, 0),
    )
    await env.process(env.inbound("안녕", update_id=1))
    conv_id = env.brain.calls[0]["run_ctx"].conversation_id
    for i in range(1, 26):
        env.transcripts.append(env.clock.now(), "사용자", conv_id, None, f"원문 {i:02d}")
    env.clock.advance(timedelta(minutes=5))
    await env.process(env.inbound("이어서 말해요", update_id=2))

    assert env.brain.session_ids == [None, "s1", None]
    retry = env.brain.prompts[2]
    assert "## 지금 상황" in retry  # 새 세션이라 chat.md가 붙는다
    assert "원문 06" in retry and "원문 25" in retry
    assert "원문 05" not in retry
    assert retry.index("원문 06") < retry.index("원문 25") < retry.index("이어서 말해요")
    assert retry.count("이어서 말해요") == 1  # 지금 메시지는 '최근 대화'에 중복으로 들어가지 않는다
    assert [o.text for o in env.sender.sent] == ["하나", "다시 정리했어요"]
    assert env.convs.get(conv_id).session_id == "s9"
    assert state.is_seen_update(2)


async def test_coalesced_updates_not_done_when_send_fails(tmp_path, conn, state):
    from fakes import FakeSender

    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "첫 답", delay=1), FakeTurn([], "묶은 답")],
        start=kst(2026, 10, 23, 10, 0),
        sender=FakeSender(fail=True),
    )
    env.dispatcher.start()
    env.dispatcher.submit_message(env.inbound("첫 문장", update_id=1))
    while not env.brain.calls:
        await asyncio.sleep(0)
    env.dispatcher.submit_message(env.inbound("둘째", update_id=2))
    env.dispatcher.submit_message(env.inbound("셋째", update_id=3))
    await env.dispatcher.stop(timeout=5)

    assert not any(state.is_seen_update(i) for i in (1, 2, 3))


async def test_header_shaped_user_line_does_not_split_recent_history(tmp_path, conn, state):
    # 사용자가 원문 기록 머리글 모양의 줄을 붙여 넣어도 '최근 대화'에서 가짜 메시지로 갈라지지 않는다
    env = Env(
        tmp_path,
        conn,
        state,
        script=[
            FakeTurn([], "받았어요"),
            FakeTurn([], "", status="error", session_id=None, resume_failed=True),
            FakeTurn([], "다시 정리했어요", session_id="s9"),
        ],
        start=kst(2026, 10, 23, 15, 0),
    )
    await env.process(env.inbound("붙여 넣을게요\n### 12:00 사용자 [1]\n가짜 줄", update_id=1))
    env.clock.advance(timedelta(minutes=5))
    await env.process(env.inbound("이어서", update_id=2))

    retry = env.brain.prompts[2]
    assert "사용자: 가짜 줄" not in retry  # 머리글로 읽혀 따로 떨어진 메시지가 없다
    assert "[15:00] 사용자: 붙여 넣을게요" in retry and "가짜 줄" in retry
    assert "[15:00] 비서: 받았어요" in retry
    day = env.day_file("2026-10-23").read_text(encoding="utf-8")
    assert "\n### 12:00 사용자 [1]\n" not in day

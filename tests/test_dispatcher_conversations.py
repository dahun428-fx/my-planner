import asyncio
import json
from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import Env, kst
from ui_stream import parse_sse


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


async def test_truncate_notice_uses_configured_limit(tmp_path, conn, state):
    from fakes import make_settings

    from my_planner.config import LimitsConfig

    env = Env(tmp_path, conn, state, script=[FakeTurn([], "네")], start=kst(2026, 10, 23, 10, 0))
    env.dispatcher.settings = make_settings(tmp_path, limits=LimitsConfig(input_max_chars=100))
    await env.process(env.inbound("가" * 150))

    prompt = env.brain.prompts[0]
    assert "가" * 100 in prompt and "가" * 101 not in prompt
    assert "메시지가 길어 앞 100자만 넘겼어요" in prompt and "8000" not in prompt


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


# --- SP9 7.3: 0번 규칙(`resume_conversation_id`)으로 지난 대화 잇기 ---


AFTERNOON = kst(2026, 10, 26, 14, 0)  # 월 14:00
EVENING_TICK = kst(2026, 10, 26, 17, 30) + timedelta(seconds=30)  # 평일 저녁 체크인(답장 창 10/27 04:00까지)


def conv_of(raw):
    return parse_sse(raw)[0]["messageMetadata"]["conversation_id"]


def summary_turn(title, summary):
    return FakeTurn([], json.dumps({"title": title, "summary": summary}, ensure_ascii=False))


async def app_chat(env, text, **kw):
    resp, raw = await env.chat(text, **kw)
    assert resp.status == 200
    return conv_of(raw)


async def closed_chat(env, text="치과 예약 얘기", *, minutes=31):
    """앱 `chat` 하나를 열고 30분 규칙으로 닫는다(짧은 대화라 요약 두뇌는 부르지 않는다)."""
    cid = await app_chat(env, text)
    env.clock.advance(timedelta(minutes=minutes))
    await env.tick()
    assert env.parts.convs.get(cid).closed_at is not None
    return cid


async def test_resume_chat_reopens_and_closes_others(tmp_path):
    script = [
        FakeTurn([], "A 답", session_id="sA"), FakeTurn([], "B 답", session_id="sB"),
        FakeTurn([], "다시 A", session_id="sA"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await closed_chat(env)
        b = await app_chat(env, "새 얘기")
        env.clock.advance(timedelta(minutes=5))
        got = await app_chat(env, "아까 치과 얘기 이어서", resume_conversation_id=a)
        convs = env.parts.convs
        ra, rb = convs.get(a), convs.get(b)
    assert got == a and a != b
    assert ra.closed_at is None and rb.closed_at is not None  # 고른 대화를 다시 열고 열린 다른 대화는 닫는다
    assert env.brain.session_ids == [None, None, "sA"]  # 그 대화의 마지막 세션으로 resume
    assert "## 메시지\n아까 치과 얘기 이어서" in env.brain.prompts[2]
    assert "새 얘기" not in env.brain.prompts[2]


async def test_resume_second_message_during_evening_window_stays(tmp_path):
    script = [
        FakeTurn([], "A 답", session_id="sA"), FakeTurn([], "꾸민 저녁 체크인", session_id="s-run"),
        FakeTurn([], "A 이어서", session_id="sA"), FakeTurn([], "A 또", session_id="sA"),
        FakeTurn([], "회차 답", session_id="s-fork"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await closed_chat(env)
        env.clock.set(EVENING_TICK)
        await env.tick()  # 저녁 체크인(텔레그램으로 전함). 이제 답장 창이 열려 있다
        env.clock.set(kst(2026, 10, 26, 18, 0))
        first = await app_chat(env, "치과 다시", resume_conversation_id=a)
        env.clock.set(kst(2026, 10, 26, 18, 45))  # 30분이 지나도 고른 대화로 간다
        second = await app_chat(env, "그리고 하나 더", resume_conversation_id=a)
        plain = await app_chat(env, "오늘 괜찮았어")  # 고르지 않으면 3번 규칙(회차 대화)
        kinds = [env.parts.convs.get(i).kind.value for i in (first, second, plain)]
    assert (first, second) == (a, a) and plain != a
    assert kinds == ["chat", "chat", "run"]


async def test_resume_plan_opens_new_chat_with_summary(tmp_path):
    secret = "보라색-코끼리-7731"
    script = [
        FakeTurn([], "계획을 세워 볼까요?", session_id="sP"), FakeTurn([], "좋아요", session_id="sP"),
        summary_turn("다음 주 계획", "월요일에 포트폴리오, 수요일에 운동을 하기로 했어요."),
        FakeTurn([], "이어서 할게요", session_id="sC"), FakeTurn([], "또 이어서", session_id="sC"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        plan = await app_chat(env, "/plan 다음 주")
        env.clock.advance(timedelta(minutes=5))
        await app_chat(env, f"암호처럼 {secret} 적어 둘게")
        env.clock.advance(timedelta(hours=2, minutes=1))
        await env.tick()  # 계획 2시간 만료로 닫히고 요약된다
        new = await app_chat(env, "지난 계획 이어서", resume_conversation_id=plan)
        again = await app_chat(env, "하나 더", resume_conversation_id=plan)
        c, p = env.parts.convs.get(new), env.parts.convs.get(plan)
    assert new != plan and again == new
    assert c.kind.value == "chat" and c.continued_from == plan and p.closed_at is not None
    first = env.brain.prompts[3]
    assert env.brain.session_ids[3] is None
    assert "## 이어 가는 지난 대화\n제목: 다음 주 계획\n월요일에 포트폴리오" in first
    assert secret not in first  # 요약만, 원문은 없다
    assert "## 이어 가는 지난 대화" not in env.brain.prompts[4]  # resume한 다음 호출에는 다시 붙이지 않는다


async def test_resume_run_inside_window_goes_to_run(tmp_path):
    script = [
        FakeTurn([], "꾸민 저녁 체크인", session_id="s-run"), FakeTurn([], "회차 답", session_id="s-fork"),
        FakeTurn([], "회차 다시", session_id="s-fork"),
        FakeTurn([], "새 대화예요", session_id="sN"),
    ]
    async with BeEnv.start(tmp_path, start=EVENING_TICK, script=script) as env:
        await env.tick()
        tele = env.brain.calls[0]["run_ctx"].conversation_id
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
        env.clock.set(kst(2026, 10, 26, 18, 0))
        side = await app_chat(env, "오늘 괜찮았어", checkin_id=run_id)
        env.clock.set(kst(2026, 10, 26, 22, 0))
        inside = await app_chat(env, "아 그리고", resume_conversation_id=side)
        env.clock.set(kst(2026, 10, 27, 4, 1))  # 답장 창이 지났다
        after = await app_chat(env, "어제 체크인 얘기", resume_conversation_id=side)
        c = env.parts.convs.get(after)
    assert side != tele and inside == side
    assert after not in (side, tele) and c.kind.value == "chat" and c.continued_from == side


async def test_checkin_id_without_resume_goes_to_run_and_both_follow_rule_0(tmp_path):
    script = [
        FakeTurn([], "A 답", session_id="sA"), FakeTurn([], "꾸민 저녁 체크인", session_id="s-run"),
        FakeTurn([], "회차 답", session_id="s-fork"), FakeTurn([], "A 이어서", session_id="sA"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await closed_chat(env)
        env.clock.set(EVENING_TICK)
        await env.tick()
        run_id = env.conn.execute("SELECT id FROM runs WHERE loop = 'evening_checkin'").fetchone()["id"]
        env.clock.set(kst(2026, 10, 26, 18, 0))
        checkin = await app_chat(env, "체크인 할게요", checkin_id=run_id)  # 체크인 칩: checkin_id만
        both = await app_chat(env, "다른 클라이언트", checkin_id=run_id, resume_conversation_id=a)
        kinds = [env.parts.convs.get(i).kind.value for i in (checkin, both)]
    assert kinds == ["run", "chat"] and both == a  # 둘 다 오면 0번 규칙이 먼저


async def test_resume_ignores_telegram_and_deleted(tmp_path):
    script = [FakeTurn([], "텔레그램 답"), FakeTurn([], "앱 답", session_id="sX")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        await env.telegram("텔레그램에서 한 말")
        tg = env.brain.calls[0]["run_ctx"].conversation_id
        got = await app_chat(env, "앱에서", resume_conversation_id=tg)
        assert env.parts.convs.get(got).channel == "app" and got != tg
        assert env.parts.router._resumed(999, env.clock.now()) is None


async def test_existing_conversation_id_keeps_30min_meaning(tmp_path):
    script = [FakeTurn([], "하나", session_id="s1"), FakeTurn([], "둘", session_id="s1"), FakeTurn([], "셋")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await app_chat(env, "처음")
        env.clock.advance(timedelta(minutes=29))
        same = await app_chat(env, "이어서", conversation_id=a)
        env.clock.advance(timedelta(minutes=31))  # tick 없이 31분: 아직 열려 있지만 30분이 지났다
        other = await app_chat(env, "또", conversation_id=a)
    assert same == a and other != a


# --- SP9 7.3: resume 실패 대체 경로 ---


def add_lines(env, cid, n, *, start=1):
    for i in range(start, start + n):
        who = "사용자" if i % 2 else "비서"
        env.parts.transcripts.append(env.clock.now(), who, cid, None, f"원문 {i:02d}", channel="app")


async def test_resume_failure_uses_summary_plus_6(tmp_path):
    script = [
        FakeTurn([], "A 답", session_id="sA"),
        summary_turn("치과 예약", "토요일 10시로 잡았어요."),
        FakeTurn([], "", status="error", session_id=None, resume_failed=True),
        FakeTurn([], "다시 정리했어요", session_id="sA2"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await app_chat(env, "치과 예약 잡아 줘")
        add_lines(env, a, 12)
        a_closed = await closed_chat_existing(env, a)
        got = await app_chat(env, "이어서", resume_conversation_id=a_closed)
        sessions = env.parts.convs.sessions(a)
    assert got == a and env.brain.session_ids[2:] == ["sA", None]
    retry = env.brain.prompts[3]
    assert "## 지금 상황" in retry  # 새 세션이라 앞머리가 붙는다
    assert "## 이 대화의 지난 내용\n제목: 치과 예약\n토요일 10시로 잡았어요." in retry
    assert all(f"원문 {i:02d}" in retry for i in range(7, 13)) and "원문 06" not in retry  # 최근 6줄
    assert retry.index("## 이 대화의 지난 내용") < retry.index("원문 07") < retry.index("## 메시지\n이어서")
    assert sessions == ["sA", "sA2"]


async def closed_chat_existing(env, cid):
    env.clock.advance(timedelta(minutes=31))
    await env.tick()
    assert env.parts.convs.get(cid).closed_at is not None
    return cid


async def test_resume_failure_without_summary_uses_20_lines(tmp_path):
    script = [
        FakeTurn([], "A 답", session_id="sA"),
        FakeTurn([], "", status="error", error="is_error"),  # 요약 실패: 대체 제목만
        FakeTurn([], "", status="error", session_id=None, resume_failed=True),
        FakeTurn([], "다시 정리했어요", session_id="sA2"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await app_chat(env, "치과 예약 잡아 줘")
        add_lines(env, a, 25)
        await closed_chat_existing(env, a)
        assert env.parts.convs.get(a).summary is None
        await app_chat(env, "이어서", resume_conversation_id=a)
    retry = env.brain.prompts[3]
    assert "## 이 대화의 지난 내용" not in retry
    assert "원문 06" in retry and "원문 25" in retry and "원문 05" not in retry  # 지금처럼 최근 20줄


# --- SP9 7.4: 말아 넣기 ---


def set_user_messages(env, cid, n):
    env.conn.execute("UPDATE conversations SET user_messages = ? WHERE id = ?", (n, cid))
    env.conn.commit()


async def test_rollup_at_31st_message(tmp_path):
    script = [
        FakeTurn([], "첫 답", session_id="s1"),
        summary_turn("긴 대화", "포트폴리오 순서를 정했어요."),
        FakeTurn([], "새 세션 답", session_id="s2"),
        FakeTurn([], "이어서 답", session_id="s2"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await app_chat(env, "포트폴리오 얘기")
        add_lines(env, a, 10)
        set_user_messages(env, a, 30)
        env.clock.advance(timedelta(minutes=1))
        got = await app_chat(env, "서른한 번째 말")
        after = env.parts.convs.get(a)
        env.clock.advance(timedelta(minutes=1))
        await app_chat(env, "서른두 번째 말")
        later = env.parts.convs.get(a)
        sessions = env.parts.convs.sessions(a)
    assert got == a  # 화면에서는 같은 대화
    summary_call, rolled = env.brain.calls[1], env.brain.prompts[2]
    assert summary_call["run_ctx"].kind == "summary" and "서른한 번째 말" not in summary_call["prompt"]
    assert "원문 10" in summary_call["prompt"]
    assert env.brain.session_ids == [None, None, None, "s2"]
    assert "## 지금 상황" in rolled
    assert "## 이 대화의 지난 내용\n제목: 긴 대화\n포트폴리오 순서를 정했어요." in rolled
    assert all(f"원문 {i:02d}" in rolled for i in range(5, 11)) and "원문 04" not in rolled  # 최근 6줄
    assert rolled.index("원문 10") < rolled.index("## 메시지\n서른한 번째 말")
    assert (after.user_messages, after.session_id, after.title) == (1, "s2", "긴 대화")
    assert later.user_messages == 2 and sessions == ["s1", "s2"]


async def test_rollup_deferred_when_summary_fails(tmp_path):
    script = [
        FakeTurn([], "첫 답", session_id="s1"),
        FakeTurn([], "", status="error", error="is_error"),  # 31번째: 요약 실패 → 미룸
        FakeTurn([], "그대로 이어서", session_id="s1"),
        summary_turn("긴 대화", "정리했어요."),  # 32번째: 다시 해 보고 성공
        FakeTurn([], "새 세션", session_id="s2"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await app_chat(env, "포트폴리오 얘기")
        add_lines(env, a, 6)
        set_user_messages(env, a, 30)
        await app_chat(env, "서른한 번째")
        mid = env.parts.convs.get(a)
        await app_chat(env, "서른두 번째")
        end = env.parts.convs.get(a)
    assert env.brain.session_ids == [None, None, "s1", None, None]
    assert (mid.user_messages, mid.session_id, mid.summary) == (31, "s1", None)
    assert (end.user_messages, end.session_id, end.summary) == (1, "s2", "정리했어요.")
    assert "## 이 대화의 지난 내용" in env.brain.prompts[4]


async def test_rollup_app_only(tmp_path):
    script = [FakeTurn([], "하나", session_id="t1"), FakeTurn([], "둘", session_id="t1")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        await env.telegram("텔레그램 긴 대화")
        tg = env.brain.calls[0]["run_ctx"].conversation_id
        set_user_messages(env, tg, 40)
        env.clock.advance(timedelta(minutes=1))
        await env.telegram("또 한 마디")
        c = env.parts.convs.get(tg)
    assert env.brain.session_ids == [None, "t1"] and len(env.brain.calls) == 2  # 요약 호출 없음
    assert c.user_messages == 40 and c.summary is None  # 텔레그램은 세지도 않는다

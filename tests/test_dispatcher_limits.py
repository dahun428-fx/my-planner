"""멈춤, 하루 두뇌 호출 상한, 로그인·결제, 사용 한도, 오류 백오프 (스펙 5.3, 5.4, 7). 티켓 10."""

from datetime import date, timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.clock import to_iso

MON_1030 = kst(2026, 10, 26, 10, 30)
MON = date(2026, 10, 26)


def _env(tmp_path, conn, state, script, *, start=MON_1030):
    return Env(tmp_path, conn, state, script=script, start=start, with_tools=True)


async def test_paused_still_answers_messages(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], "네, 쉬는 동안에도 여기 있어요.")])
    state.set("pause_until", to_iso(kst(2026, 10, 29, 10, 30)))
    await env.process(env.inbound("쉬는 중인데 하나만 물어볼게"))

    assert [o.text for o in env.sender.sent] == ["네, 쉬는 동안에도 여기 있어요."]
    assert len(env.brain.calls) == 1
    # 새 세션 앞머리에 멈춤 상태를 한국 시간으로 알린다
    assert "## 멈춤\n10월 29일 10:30까지" in env.brain.prompts[0]
    assert state.is_seen_update(1)


def _use_brain_calls(state, n, d=MON):
    for _ in range(n):
        state.incr_usage(d, "brain_calls")


async def test_daily_cap_reply_without_brain_call(tmp_path, conn, state):
    from test_telegram_io import OWNER, _RecordingBot, _update

    from my_planner.bot.telegram_io import handle_update
    from my_planner.harness.dispatcher import DAILY_CAP_REPLY

    env = _env(tmp_path, conn, state, [])
    _use_brain_calls(state, 60)  # 오늘 60회를 이미 썼다: 61번째 메시지
    await env.process(env.inbound("하나 더 물어볼게", update_id=61))

    assert [o.text for o in env.sender.sent] == [DAILY_CAP_REPLY]
    assert DAILY_CAP_REPLY == "오늘은 여기까지 생각을 아껴 둘게요. 명령(/today)은 계속 쓸 수 있어요."
    assert env.brain.calls == []
    assert state.usage(MON).brain_calls == 60
    assert state.usage(MON).proactive_messages == 0  # 고정 안내는 먼저 보낸 메시지에 세지 않는다
    assert state.is_seen_update(61)
    day = env.day_file("2026-10-26").read_text(encoding="utf-8")
    assert "하나 더 물어볼게" in day and f"비서 [-]\n\n{DAILY_CAP_REPLY}" in day

    # /today는 두뇌 없이 그대로 동작한다
    bot = _RecordingBot()
    verdict = await handle_update(
        _update(update_id=62, text="/today"), bot=bot, owner_id=OWNER, state=state,
        dispatcher=env.dispatcher, transcripts=env.transcripts, clock=env.clock, tools=env.tools,
    )
    assert verdict == "command" and bot.sent[-1][1].startswith("오늘 (10/26 월)")
    assert env.brain.calls == []


def _auth(error="login"):
    return FakeTurn([], "", status="auth_error", error=error, session_id=None)


LOGIN_COPY = "Claude 로그인이 풀렸어요. PC에서 Claude Code에 다시 로그인해 주세요."
BILLING_COPY = "Claude 계정이나 결제 상태를 확인해야 해요. PC에서 Claude 계정을 살펴봐 주세요."


async def test_auth_error_notice_once_per_day(tmp_path, conn, state):
    # 사용자 메시지에는 매번 답한다(침묵 없음). 하루 한 번 제한은 회차가 보내는 안내에만 걸린다
    from my_planner.domain import LoopKey

    env = _env(tmp_path, conn, state, [_auth(), _auth(), _auth(), _auth(), _auth(), _auth()])
    await env.process(env.inbound("안녕", update_id=1))
    env.clock.advance(timedelta(minutes=10))
    await env.process(env.inbound("계속 안 되네", update_id=2))
    assert [o.text for o in env.sender.sent] == [LOGIN_COPY, LOGIN_COPY]
    assert state.get("last_auth_notice_date") is None  # 답장은 하루 한 번 몫을 쓰지 않는다
    assert state.is_seen_update(1) and state.is_seen_update(2)
    day = env.day_file("2026-10-26").read_text(encoding="utf-8")
    assert f"비서 [-]\n\n{LOGIN_COPY}" in day

    await env.process_run(_queued(env))  # 회차의 안내: 그날 첫 번째라 보낸다
    assert [o.text for o in env.sender.sent] == [LOGIN_COPY] * 3
    assert state.get("last_auth_notice_date") == "2026-10-26"
    env.clock.set(kst(2026, 10, 26, 17, 31))
    await env.process_run(_queued(env, LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30)))
    assert len(env.sender.sent) == 3  # 같은 날 회차 안내는 다시 보내지 않는다
    await env.process(env.inbound("아직?", update_id=3))
    assert len(env.sender.sent) == 4  # 메시지에는 그래도 답한다
    assert state.usage(MON).proactive_messages == 0

    env.clock.set(kst(2026, 10, 27, 9, 30))  # 다음 논리적 날짜: 회차 안내를 다시 보낸다
    await env.process_run(_queued(env, LoopKey.morning_brief, kst(2026, 10, 27, 9, 0)))
    assert [o.text for o in env.sender.sent] == [LOGIN_COPY] * 5
    assert state.get("last_auth_notice_date") == "2026-10-27"


async def test_billing_error_uses_billing_copy(tmp_path, conn, state):
    from my_planner.domain import LoopKey

    env = _env(tmp_path, conn, state, [_auth("billing"), _auth("billing"), _auth("billing"), _auth("login")])
    for i in (1, 2):
        await env.process(env.inbound(f"메시지 {i}", update_id=i))
    assert [o.text for o in env.sender.sent] == [BILLING_COPY, BILLING_COPY]
    await env.process_run(_queued(env))
    env.clock.set(kst(2026, 10, 26, 17, 31))
    await env.process_run(_queued(env, LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30)))
    # 회차 안내는 결제든 로그인이든 하루 한 번
    assert [o.text for o in env.sender.sent] == [BILLING_COPY] * 3
    assert state.usage(MON).proactive_messages == 0


def _limited(retry_at):
    return FakeTurn([], "", status="rate_limited", retry_at=retry_at, session_id=None)


def _rate_copy(when):
    return f"지금은 Claude 사용 한도에 닿았어요. {when}쯤 다시 이야기할 수 있어요. 명령(/today)은 계속 쓸 수 있어요."


async def test_rate_limited_notice_once_per_window(tmp_path, conn, state):
    from my_planner.clock import from_iso
    from my_planner.domain import LoopKey

    reset = kst(2026, 10, 26, 21, 30)
    env = _env(
        tmp_path, conn, state,
        [_limited(reset), _limited(reset), _limited(reset), FakeTurn([], "다시 이야기해요.")],
    )
    await env.process(env.inbound("안녕", update_id=1))
    assert [o.text for o in env.sender.sent] == [_rate_copy("21:30")]
    assert from_iso(state.get("limited_until")) == reset
    assert state.get("last_rate_limit_notice_until") is None  # 답장은 구간 한 번 몫을 쓰지 않는다

    # 같은 구간 안의 메시지: 두뇌를 부르지 않고, 기록된 재개 시각으로 매번 답한다
    env.clock.set(kst(2026, 10, 26, 15, 0))
    await env.process(env.inbound("아직이야?", update_id=2))
    assert len(env.brain.calls) == 1
    assert [o.text for o in env.sender.sent] == [_rate_copy("21:30")] * 2
    assert state.is_seen_update(1) and state.is_seen_update(2)

    # 회차의 안내는 구간마다 한 번
    env.clock.set(kst(2026, 10, 26, 17, 31))
    await env.process_run(_queued(env, LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30)))
    assert len(env.sender.sent) == 3
    assert from_iso(state.get("last_rate_limit_notice_until")) == reset
    await env.process_run(_queued(env, LoopKey.review, kst(2026, 10, 25, 18, 0)))
    assert len(env.sender.sent) == 3
    assert state.usage(MON).proactive_messages == 0

    # 풀린 뒤에는 다시 두뇌로 간다
    env.clock.set(kst(2026, 10, 26, 21, 31))
    await env.process(env.inbound("이제 될까", update_id=3))
    assert len(env.brain.calls) == 4
    assert env.sender.sent[-1].text == "다시 이야기해요."


async def test_rate_limited_resume_text_formats(tmp_path, conn, state):
    from my_planner.clock import from_iso

    cases = [
        (kst(2026, 10, 26, 21, 30), "21:30", kst(2026, 10, 26, 21, 30)),  # 오늘(논리적 날짜)
        (kst(2026, 10, 30, 9, 0), "10월 30일 09:00", kst(2026, 10, 30, 9, 0)),  # 다른 날
        (kst(2026, 10, 26, 10, 0), "11:30", kst(2026, 10, 26, 11, 30)),  # 이미 지났다: 지금 + 1시간
        (None, "11:30", kst(2026, 10, 26, 11, 30)),  # 재개 시각이 없다: 지금 + 1시간
    ]
    for i, (retry_at, text, until) in enumerate(cases, start=1):
        state.set("limited_until", None)
        state.set("last_rate_limit_notice_until", None)  # 경우마다 새 구간으로 본다
        env = _env(tmp_path, conn, state, [_limited(retry_at)])
        await env.process(env.inbound("안녕", update_id=i))
        assert env.sender.sent[-1].text == _rate_copy(text), retry_at
        assert from_iso(state.get("limited_until")) == until


def _error():
    return FakeTurn([], "", status="error", session_id=None)


def _record_sleeps(env):
    from my_planner.harness.dispatcher import TYPING_INTERVAL_S

    slept = []
    inner = env.dispatcher._sleep

    async def sleep(seconds):
        if seconds != TYPING_INTERVAL_S:  # 입력 중 표시 간격은 빼고 센다
            slept.append(seconds)
        await inner(seconds)

    env.dispatcher._sleep = sleep
    return slept


async def test_error_retries_3_times_with_backoff_then_fixed_text(tmp_path, conn, state):
    from my_planner.harness.dispatcher import FALLBACK_REPLY

    env = _env(tmp_path, conn, state, [_error(), _error(), _error(), _error()])
    slept = _record_sleeps(env)
    await env.process(env.inbound("안녕"))

    assert len(env.brain.calls) == 4  # 처음 1회 + 다시 3회
    assert slept == [2, 4, 8]
    assert state.usage(MON).brain_calls == 4  # 다시 부른 것도 하루 두뇌 호출에 센다
    assert [o.text for o in env.sender.sent] == [FALLBACK_REPLY]
    assert FALLBACK_REPLY == "지금 잠깐 생각이 안 돼요. 조금 뒤에 다시 말씀해 주세요."
    assert state.is_seen_update(1)


async def test_error_then_ok_on_retry_replies_normally(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [_error(), FakeTurn([], "이제 됐어요.")])
    slept = _record_sleeps(env)
    await env.process(env.inbound("안녕"))
    assert len(env.brain.calls) == 2 and slept == [2]
    assert [o.text for o in env.sender.sent] == ["이제 됐어요."]
    assert state.usage(MON).brain_calls == 2


async def test_resume_failure_fallback_comes_before_backoff(tmp_path, conn, state):
    # resume 실패면 먼저 새 세션으로 한 번(백오프 없이), 그 새 세션 호출의 오류에만 2, 4, 8초 백오프
    env = _env(
        tmp_path, conn, state,
        [
            FakeTurn([], "하나"),
            FakeTurn([], "", status="error", session_id=None, resume_failed=True),
            _error(), _error(), FakeTurn([], "다시 정리했어요", session_id="s9"),
        ],
    )
    await env.process(env.inbound("안녕", update_id=1))
    slept = _record_sleeps(env)
    env.clock.advance(timedelta(minutes=5))
    await env.process(env.inbound("이어서 말해요", update_id=2))

    assert env.brain.session_ids == ["s1" if i == 1 else None for i in range(5)]
    assert slept == [2, 4]
    first_fresh = env.brain.prompts[2]
    assert "## 지금" in first_fresh and all(p == first_fresh for p in env.brain.prompts[3:])
    assert env.sender.sent[-1].text == "다시 정리했어요"
    assert state.usage(MON).brain_calls == 5
    assert env.convs.get(env.brain.calls[0]["run_ctx"].conversation_id).session_id == "s9"


def _queued(env, loop=None, at=None):
    from my_planner.domain import LoopKey

    run = env.runs.ensure(loop or LoopKey.morning_brief, at or kst(2026, 10, 26, 9, 0))
    env.runs.mark_queued(run.id)
    return env.runs.get(run.id)


async def test_run_error_no_backoff_max_two_calls(tmp_path, conn, state):
    from my_planner.domain import RunStatus

    env = _env(tmp_path, conn, state, [_error(), _error()])
    slept = _record_sleeps(env)
    run = _queued(env)
    await env.process_run(run)

    assert len(env.brain.calls) == 2  # 회차당 두뇌 호출 최대 2회, 백오프 없이
    assert slept == []
    assert state.usage(MON).brain_calls == 2
    assert env.runs.get(run.id).status is RunStatus.failed
    assert env.sender.sent == []  # 사용자에게 알리지 않는다


async def test_run_auth_error_marked_skipped_not_rerun(tmp_path, conn, state):
    from my_planner.clock import from_iso
    from my_planner.domain import LoopKey, RunStatus

    env = _env(tmp_path, conn, state, [_auth(), _limited(kst(2026, 10, 26, 21, 30))])
    morning = _queued(env)
    review = _queued(env, LoopKey.review, kst(2026, 10, 25, 18, 0))
    await env.process_run(morning, [review])

    assert len(env.brain.calls) == 1  # 다시 실행하지 않는다
    for r in (morning, review):
        after = env.runs.get(r.id)
        assert after.status is RunStatus.skipped and after.skip_reason == "auth"
    assert [o.text for o in env.sender.sent] == [LOGIN_COPY]

    # 사용 한도도 같다: skipped(rate_limit), 재실행 없음, 구간 기록과 안내
    evening = _queued(env, LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
    env.clock.set(kst(2026, 10, 26, 17, 31))
    await env.process_run(evening)
    assert len(env.brain.calls) == 2
    after = env.runs.get(evening.id)
    assert after.status is RunStatus.skipped and after.skip_reason == "rate_limit"
    assert from_iso(state.get("limited_until")) == kst(2026, 10, 26, 21, 30)
    assert env.sender.sent[-1].text == _rate_copy("21:30")
    assert state.usage(MON).proactive_messages == 0  # 고정 안내는 하루 3회에 세지 않는다
    assert state.usage(MON).brain_calls == 2


async def test_backoff_stops_at_daily_cap(tmp_path, conn, state):
    # 다시 부르기 전마다 상한을 본다. 60회에 닿으면 멈추고 하루 상한 문구로 답한다
    from my_planner.harness.dispatcher import DAILY_CAP_REPLY

    env = _env(tmp_path, conn, state, [_error(), _error(), _error(), _error()])
    _use_brain_calls(state, 58)
    slept = _record_sleeps(env)
    await env.process(env.inbound("안녕"))

    assert len(env.brain.calls) == 2 and slept == [2]
    assert state.usage(MON).brain_calls == 60
    assert [o.text for o in env.sender.sent] == [DAILY_CAP_REPLY]
    assert state.is_seen_update(1)

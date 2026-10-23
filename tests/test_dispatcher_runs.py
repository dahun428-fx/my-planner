"""디스패처의 회차 실행: 두 단계(저장 → 전송), 전송 재시도, 재실행, 답장 창, 직렬 처리 (스펙 5.3, 5.4)."""

from datetime import date, timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.domain import ConversationKind, LoopKey, RunStatus
from my_planner.harness import prompts

MON_0900 = kst(2026, 10, 26, 9, 0)
MON = date(2026, 10, 26)


class RecordingSender:
    """보낼 때마다 그 순간 DB의 outbound_text를 함께 적는다. `fail_times`번까지는 전송이 안 된다."""

    def __init__(self, fail_times=0):
        self.runs = None
        self.run_id = None
        self.attempts = 0
        self.fail_times = fail_times
        self.sent = []
        self.saved_at_send = []
        self.typing_count = 0

    async def send(self, out):
        self.attempts += 1
        if self.runs is not None and self.run_id is not None:
            self.saved_at_send.append(self.runs.get(self.run_id).outbound_text)
        if self.attempts <= self.fail_times:
            raise ConnectionError("fake send failure")
        self.sent.append(out)

    async def typing(self):
        self.typing_count += 1


def _env(tmp_path, conn, state, script, *, start=MON_0900 + timedelta(seconds=30), sender=None):
    env = Env(tmp_path, conn, state, script=script, start=start, sender=sender, with_tools=True)
    return env


def _queued_morning(env, at=MON_0900):
    run = env.runs.ensure(LoopKey.morning_brief, at)
    env.runs.mark_queued(run.id)
    if isinstance(env.sender, RecordingSender):
        env.sender.runs, env.sender.run_id = env.runs, run.id
    return env.runs.get(run.id)


BRIEF = "좋은 아침이에요. 오늘은 보고서 초안 하나만 해 봐요. 첫 걸음: 목차 세 줄 쓰기(15분)."


async def test_morning_run_two_phase(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)], sender=RecordingSender())
    run = _queued_morning(env)
    await env.process_run(run)

    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert env.sender.saved_at_send == [BRIEF]  # 보내기 전에 이미 저장돼 있었다
    done = env.runs.get(run.id)
    assert done.status is RunStatus.done and done.outbound_text == BRIEF and done.attempt == 1
    assert state.usage(MON).proactive_messages == 1

    prompt = env.brain.prompts[0]
    assert prompts.load("morning_brief.md") in prompt
    assert "## 지금" in prompt  # 새 세션의 앞머리
    assert env.brain.session_ids == [None]
    conv = env.convs.get(done.conversation_id)
    assert conv.kind is ConversationKind.run and conv.run_id == run.id and conv.session_id == "s1"
    day = env.day_file("2026-10-26").read_text(encoding="utf-8")
    assert f"비서 [{conv.id}] (morning_brief)" in day and BRIEF in day


async def _wait_for(cond, steps=10_000):
    import asyncio

    for _ in range(steps):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("조건이 끝내 참이 되지 않았다")


class TimedSender(RecordingSender):
    def __init__(self, clock, fail_times):
        super().__init__(fail_times)
        self.clock = clock
        self.times = []

    async def send(self, out):
        self.times.append(self.clock.now())
        await super().send(out)


async def test_send_retries_3_then_failed_then_resend_once(tmp_path, conn, state):
    # 바로 3회가 모두 안 되면 failed, 5분 뒤 전송만 한 번 더(이번에는 된다)
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])
    env.sender = env.dispatcher.sender = TimedSender(env.clock, fail_times=3)
    run = _queued_morning(env)
    env.dispatcher.start()
    env.dispatcher.submit_run(run, [])
    await _wait_for(lambda: env.sender.attempts == 3)
    await _wait_for(lambda: env.runs.get(run.id).status is RunStatus.failed)
    assert env.sender.sent == []
    await _wait_for(lambda: env.runs.get(run.id).resent == 1)
    await env.dispatcher.stop(timeout=5)

    assert env.sender.attempts == 4
    gaps = [(b - a).total_seconds() for a, b in zip(env.sender.times, env.sender.times[1:], strict=False)]
    assert gaps[0] >= 1 and gaps[1] >= 2 and gaps[2] >= 300
    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert len(env.brain.calls) == 1  # 두뇌는 다시 부르지 않는다
    after = env.runs.get(run.id)
    assert after.status is RunStatus.done and after.resent == 1
    assert state.usage(MON).proactive_messages == 1


async def test_resend_also_fails_stays_failed(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])
    env.sender = env.dispatcher.sender = TimedSender(env.clock, fail_times=99)
    run = _queued_morning(env)
    env.dispatcher.start()
    env.dispatcher.submit_run(run, [])
    await _wait_for(lambda: env.runs.get(run.id).resent == 1)
    await env.dispatcher.stop(timeout=5)

    assert env.sender.attempts == 4  # 바로 3회 + 5분 뒤 1회, 그 뒤로는 없다
    after = env.runs.get(run.id)
    assert after.status is RunStatus.failed and after.outbound_text == BRIEF
    assert len(env.brain.calls) == 1
    assert state.usage(MON).proactive_messages == 0


def _brain_error():
    return FakeTurn([], "", status="error", session_id=None)


async def test_brain_failure_without_tool_events_reruns_once(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [_brain_error(), FakeTurn([], BRIEF)])
    run = _queued_morning(env)
    await env.process_run(run)

    assert len(env.brain.calls) == 2
    assert env.brain.session_ids == [None, None]
    assert [o.text for o in env.sender.sent] == [BRIEF]
    after = env.runs.get(run.id)
    assert after.status is RunStatus.done and after.attempt == 2


async def test_brain_failure_with_tool_events_not_rerun(tmp_path, conn, state):
    add = ("add_task", {"title": "보고서", "areas": ["career"]})
    env = _env(tmp_path, conn, state, [FakeTurn([add], "", status="error", session_id=None), FakeTurn([], BRIEF)])
    run = _queued_morning(env)
    await env.process_run(run)

    assert len(env.brain.calls) == 1  # 도구가 이미 데이터를 바꿨으니 다시 실행하지 않는다
    assert env.sender.sent == []
    after = env.runs.get(run.id)
    assert after.status is RunStatus.failed and after.outbound_text is None


async def test_run_failure_sends_nothing_to_user(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [_brain_error(), _brain_error()])
    run = _queued_morning(env)
    await env.process_run(run)

    assert len(env.brain.calls) == 2  # 회차당 두뇌 호출은 최대 2회
    assert env.sender.sent == []
    after = env.runs.get(run.id)
    assert after.status is RunStatus.failed and after.outbound_text is None
    assert state.usage(MON).proactive_messages == 0
    assert not env.day_file("2026-10-26").exists()  # 원문 기록에도 비서 말이 없다


async def test_reply_within_morning_window_continues_run_conversation(tmp_path, conn, state):
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], BRIEF, session_id="run-s"), FakeTurn([], "좋아요.", session_id="run-s"),
         FakeTurn([], "새 대화", session_id="chat-s")],
    )
    run = _queued_morning(env)
    await env.process_run(run)
    run_conv = env.runs.get(run.id).conversation_id

    env.clock.set(kst(2026, 10, 26, 11, 30))  # 브리핑 뒤 2시간 반, 답장 창(12:00) 안
    await env.process(env.inbound("네, 목차부터 할게요", update_id=1))
    assert env.brain.session_ids[1] == "run-s"
    assert env.brain.calls[1]["run_ctx"].conversation_id == run_conv

    env.clock.set(kst(2026, 10, 26, 12, 1))  # 답장 창 밖, 마지막 말 뒤 31분
    await env.process(env.inbound("점심 뭐 먹지", update_id=2))
    assert env.brain.session_ids[2] is None
    other = env.convs.get(env.brain.calls[2]["run_ctx"].conversation_id)
    assert other.id != run_conv and other.kind is ConversationKind.chat


async def test_reply_window_beats_30_minutes(tmp_path, conn, state):
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], "안녕하세요.", session_id="chat-s"), FakeTurn([], BRIEF, session_id="run-s"),
         FakeTurn([], "네, 그렇게 해요.", session_id="run-s")],
        start=kst(2026, 10, 26, 8, 50),
    )
    await env.process(env.inbound("좋은 아침", update_id=1))  # 08:50 chat 대화
    chat_conv = env.brain.calls[0]["run_ctx"].conversation_id

    env.clock.set(MON_0900 + timedelta(seconds=30))
    run = _queued_morning(env)
    await env.process_run(run)

    env.clock.set(kst(2026, 10, 26, 9, 5))  # chat 대화의 마지막 말 뒤 15분이지만 회차 답장 창이 먼저다
    await env.process(env.inbound("보고서부터 할게요", update_id=2))
    assert env.brain.session_ids[2] == "run-s"
    assert env.brain.calls[2]["run_ctx"].conversation_id == env.runs.get(run.id).conversation_id != chat_conv


async def test_reply_to_run_has_no_loop_prompt(tmp_path, conn, state):
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], BRIEF, session_id="run-s"),
         FakeTurn([], "네.", session_id="run-s"),
         FakeTurn([], "", status="error", session_id=None, resume_failed=True),
         FakeTurn([], "다시 이어서 볼게요.", session_id="run-s2")],
    )
    run = _queued_morning(env)
    await env.process_run(run)

    env.clock.set(kst(2026, 10, 26, 9, 10))
    await env.process(env.inbound("목차부터 할게요", update_id=1))
    resumed = env.brain.prompts[1]
    assert resumed.startswith("## 메시지") and "목차부터 할게요" in resumed
    assert "## 지금 상황" not in resumed  # 루프 지시문도 chat.md도 없다

    # resume이 실패하면 preamble과 그 대화의 최근 원문만 넘긴다
    env.clock.set(kst(2026, 10, 26, 10, 0))
    await env.process(env.inbound("다음은 뭐 하죠", update_id=2))
    retry = env.brain.prompts[3]
    assert env.brain.session_ids[2:] == ["run-s", None]
    assert "## 지금 상황" not in retry
    assert prompts.load("morning_brief.md") not in retry and prompts.load("chat.md") not in retry
    assert "## 지금\n" in retry and "## 최근 대화" in retry
    assert BRIEF in retry and "목차부터 할게요" in retry
    assert retry.index("## 최근 대화") < retry.index("## 메시지")
    assert env.convs.get(env.runs.get(run.id).conversation_id).session_id == "run-s2"


async def test_run_and_message_serialized(tmp_path, conn, state):
    import asyncio

    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], "브리핑 A", delay=1), FakeTurn([], "메시지 답"), FakeTurn([], "브리핑 B")],
    )
    run_a = _queued_morning(env)
    run_b = _queued_morning(env, at=kst(2026, 10, 26, 9, 1))  # 한계 안의 다른 회차
    env.dispatcher.start()
    env.dispatcher.submit_run(run_a, [])
    while not env.brain.calls:  # A가 두뇌를 부르는 중에
        await asyncio.sleep(0)
    env.dispatcher.submit_run(run_b, [])  # 회차 B가 먼저 대기열에 들어가고
    env.dispatcher.submit_message(env.inbound("잠깐 질문이요", update_id=1))  # 메시지가 뒤에 온다
    await env.dispatcher.stop(timeout=5)

    assert [o.text for o in env.sender.sent] == ["브리핑 A", "메시지 답", "브리핑 B"]
    assert "잠깐 질문이요" in env.brain.prompts[1]
    assert env.brain.calls[0]["run_ctx"].run_id == run_a.id and env.brain.calls[2]["run_ctx"].run_id == run_b.id


def test_morning_prompt_file_covers_brief_without_banned_words():
    text = prompts.load("morning_brief.md")
    for must in ("우선순위 1~3개", "첫 걸음", "일정", "15~30분"):
        assert must in text
    for word in ("놓쳤어요", "밀렸어요", "늦었지만", "실패"):
        assert word not in text


async def test_undelivered_run_conversation_not_continued(tmp_path, conn, state):
    # 회차가 보내지지 않았으면(두뇌 단계 failed) 사용자의 말은 그 대화가 아니라 새 chat으로 간다
    env = _env(tmp_path, conn, state, [_brain_error(), _brain_error(), FakeTurn([], "안녕하세요.")])
    run = _queued_morning(env)
    await env.process_run(run)

    env.clock.set(kst(2026, 10, 26, 9, 30))
    await env.process(env.inbound("안녕", update_id=1))
    conv = env.convs.get(env.brain.calls[2]["run_ctx"].conversation_id)
    assert conv.kind is ConversationKind.chat
    assert prompts.load("chat.md") in env.brain.prompts[2]


async def test_brain_failure_past_limit_not_rerun(tmp_path, conn, state):
    # 11:59에 시작한 두뇌 호출이 2분 걸려 오류로 끝나면, 한계(12:00)가 지났으니 다시 실행하지 않는다
    slow_error = FakeTurn([], "", status="error", session_id=None, delay=120)
    env = _env(tmp_path, conn, state, [slow_error, FakeTurn([], BRIEF)], start=kst(2026, 10, 26, 11, 59))
    run = _queued_morning(env)
    await env.process_run(run)

    assert len(env.brain.calls) == 1
    assert env.runs.get(run.id).status is RunStatus.failed
    assert env.sender.sent == []


async def test_run_done_even_if_transcript_write_fails(tmp_path, conn, state):
    # 전송이 끝났으면 원문 기록이 안 돼도 회차는 done, 먼저 보낸 메시지 수도 +1
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])

    def broken_append(*a, **kw):
        raise OSError("disk full")

    env.transcripts.append = broken_append
    run = _queued_morning(env)
    await env.process_run(run)

    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert env.runs.get(run.id).status is RunStatus.done
    assert state.usage(MON).proactive_messages == 1


async def test_brain_phase_exception_marks_failed(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])

    def broken_for_run(run):
        raise RuntimeError("boom")

    env.dispatcher.router.for_run = broken_for_run
    run = _queued_morning(env)
    await env.process_run(run)

    after = env.runs.get(run.id)
    assert after.status is RunStatus.failed
    assert env.sender.sent == []


def _resend_tasks():
    import asyncio

    return [t for t in asyncio.all_tasks() if t.get_name().startswith("resend-") and not t.done()]


def _hold_long_sleeps(env):
    """5분 타이머의 sleep은 끝나지 않게 한다. 취소되지 않은 타이머가 남아 보이도록."""
    import asyncio

    fast = env.dispatcher._sleep

    async def sleep(seconds):
        if seconds >= 300:
            await asyncio.Event().wait()
        await fast(seconds)

    env.dispatcher._sleep = sleep


async def test_resend_timer_cancelled_on_stop(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])
    env.sender = env.dispatcher.sender = RecordingSender(fail_times=3)
    _hold_long_sleeps(env)
    run = _queued_morning(env)
    env.dispatcher.start()
    env.dispatcher.submit_run(run, [])
    await _wait_for(lambda: env.runs.get(run.id).status is RunStatus.failed)
    assert len(_resend_tasks()) == 1  # 실패 직후 타이머가 기다리고 있다
    await env.dispatcher.stop(timeout=5)

    assert env.sender.attempts == 3
    assert env.runs.get(run.id).resent == 0
    assert _resend_tasks() == []


async def test_no_resend_timer_left_when_send_fails_during_stop(tmp_path, conn, state):

    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])
    env.sender = env.dispatcher.sender = RecordingSender(fail_times=3)
    _hold_long_sleeps(env)
    run = _queued_morning(env)
    env.dispatcher.start()
    env.dispatcher.submit_run(run, [])
    await env.dispatcher.stop(timeout=5)  # 큐를 비우는 동안 전송이 끝내 안 된다

    assert env.runs.get(run.id).status is RunStatus.failed
    assert _resend_tasks() == []


async def test_resend_skipped_after_reply_window(tmp_path, conn, state):
    # 11:58에 전송이 끝내 안 되면 5분 뒤는 12:03, 답장 창(12:00) 밖이라 보내지 않고 재전송만 기록한다
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)], start=kst(2026, 10, 26, 11, 58))
    env.sender = env.dispatcher.sender = TimedSender(env.clock, fail_times=3)
    run = _queued_morning(env)
    env.dispatcher.start()
    env.dispatcher.submit_run(run, [])
    await _wait_for(lambda: env.runs.get(run.id).resent == 1)
    await env.dispatcher.stop(timeout=5)

    assert env.sender.attempts == 3
    after = env.runs.get(run.id)
    assert after.status is RunStatus.failed and after.resent == 1
    assert state.usage(MON).proactive_messages == 0


async def test_reply_at_exactly_12_00_continues_run_conversation(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF, session_id="run-s"), FakeTurn([], "네.", session_id="run-s")])
    run = _queued_morning(env)
    await env.process_run(run)

    env.clock.set(kst(2026, 10, 26, 12, 0))
    await env.process(env.inbound("지금 답해요", update_id=1))
    assert env.brain.session_ids[1] == "run-s"


async def test_reply_to_run_without_session_gets_recent_history(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF, session_id=None), FakeTurn([], "네.", session_id="s2")])
    run = _queued_morning(env)
    await env.process_run(run)

    env.clock.set(kst(2026, 10, 26, 9, 10))
    await env.process(env.inbound("목차부터 할게요", update_id=1))
    prompt = env.brain.prompts[1]
    assert env.brain.session_ids[1] is None
    assert "## 최근 대화" in prompt and BRIEF in prompt
    assert prompt.count("목차부터 할게요") == 1
    assert prompts.load("chat.md") not in prompt
    assert prompt.index("## 최근 대화") < prompt.index("## 메시지")


async def test_run_past_limit_when_dequeued_is_skipped_late(tmp_path, conn, state):
    from my_planner.domain import SkipReason

    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)], start=kst(2026, 10, 26, 12, 1))
    run = _queued_morning(env)  # 대기하는 동안 한계(12:00)가 지났다
    await env.process_run(run)

    after = env.runs.get(run.id)
    assert after.status is RunStatus.skipped and after.skip_reason is SkipReason.late
    assert env.brain.calls == [] and env.sender.sent == []


async def test_reply_window_routed_by_sent_time(tmp_path, conn, state):
    # 저녁 체크인 답을 03:00에 보냈고(노트북은 잠듦) 09:30에 처리한다: 보낸 시각으로 저녁 대화에 잇는다(스펙 갭 7 결정)
    from my_planner.harness.dispatcher import Inbound

    evening_at = kst(2026, 10, 26, 17, 30)
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], "오늘 하루 어땠어요?", session_id="eve-s"), FakeTurn([], "푹 쉬세요.", session_id="eve-s")],
        start=evening_at + timedelta(seconds=30),
    )
    run = env.runs.ensure(LoopKey.evening_checkin, evening_at)
    env.runs.mark_queued(run.id)
    await env.process_run(env.runs.get(run.id))
    eve_conv = env.runs.get(run.id).conversation_id

    env.clock.set(kst(2026, 10, 27, 9, 30))  # 답장 창(다음 날 04:00) 밖에서 처리한다
    sent = kst(2026, 10, 27, 3, 0)  # 보낸 시각은 답장 창 안
    await env.process(Inbound(text="괜찮았어요", at=env.clock.now(), sent_at=sent, update_ids=[1]))

    assert env.brain.session_ids[1] == "eve-s"
    assert env.brain.calls[1]["run_ctx"].conversation_id == eve_conv


def _short_brain_timeout(env):
    """두뇌 호출 상한을 0.05초로 줄인다. 그동안 '입력 중' 루프가 가짜 시계를 한계 밖으로 돌리지 않게 한다."""
    from fakes import fake_sleep, make_settings

    from my_planner.config import LimitsConfig

    env.dispatcher.settings = make_settings(env.settings.paths.root, limits=LimitsConfig(brain_timeout_s=0.05))
    env.dispatcher._sleep = fake_sleep(env.clock, real=0.005)


async def test_hung_run_brain_call_times_out_and_reruns_once(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], "", hang=True), FakeTurn([], BRIEF)])
    _short_brain_timeout(env)
    run = _queued_morning(env)
    await env.process_run(run)

    assert len(env.brain.calls) == 2
    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert env.runs.get(run.id).status is RunStatus.done


async def test_hung_run_after_tool_write_fails_without_rerun(tmp_path, conn, state):
    add = ("add_task", {"title": "보고서", "areas": ["career"]})
    env = _env(tmp_path, conn, state, [FakeTurn([add], "", hang=True), FakeTurn([], BRIEF)])
    _short_brain_timeout(env)
    run = _queued_morning(env)
    await env.process_run(run)

    assert len(env.brain.calls) == 1
    assert env.sender.sent == []
    assert env.runs.get(run.id).status is RunStatus.failed
    assert conn.execute("SELECT error FROM runs WHERE id = ?", (run.id,)).fetchone()[0] == "error"


async def test_reply_sent_before_catchup_run_joins_the_earlier_run(tmp_path, conn, state):
    # 깨어난 09:30: 따라잡기 아침 브리핑을 09:29에 먼저 보냈고, 03:00에 보낸 저녁 체크인 답은 그 뒤에 받아 왔다.
    # 보낸 시각 이전에 열려 보낸 가장 최근 회차 대화(저녁)에 잇는다(최종 재리뷰 Important 1)
    from my_planner.harness.dispatcher import Inbound

    evening_at = kst(2026, 10, 26, 17, 30)
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], "오늘 하루 어땠어요?", session_id="eve-s"), FakeTurn([], BRIEF, session_id="morning-s"),
         FakeTurn([], "푹 쉬세요.", session_id="eve-s")],
        start=evening_at + timedelta(seconds=30),
    )
    eve = env.runs.ensure(LoopKey.evening_checkin, evening_at)
    env.runs.mark_queued(eve.id)
    await env.process_run(env.runs.get(eve.id))
    eve_conv = env.runs.get(eve.id).conversation_id

    env.clock.set(kst(2026, 10, 27, 9, 29))
    morning = _queued_morning(env, at=kst(2026, 10, 27, 9, 0))
    await env.process_run(morning)
    assert env.runs.get(morning.id).status is RunStatus.done

    env.clock.set(kst(2026, 10, 27, 9, 30))
    await env.process(Inbound(text="괜찮았어요", at=env.clock.now(), sent_at=kst(2026, 10, 27, 3, 0), update_ids=[1]))

    assert env.brain.session_ids[2] == "eve-s"
    assert env.brain.calls[2]["run_ctx"].conversation_id == eve_conv


async def test_reply_sent_while_run_was_still_being_written_is_not_joined_to_it(tmp_path, conn, state):
    # 회차 대화는 두뇌를 부르기 전에 열린다. 그 뒤, 보내기 전에 쓴 메시지는 그 회차에 대한 답이 아니다
    from my_planner.harness.dispatcher import Inbound

    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], BRIEF, session_id="run-s", delay=60), FakeTurn([], "네", session_id="c")],
    )
    run = _queued_morning(env)
    await env.process_run(run)
    opened = env.convs.get(env.runs.get(run.id).conversation_id).opened_at
    env.clock.advance(timedelta(minutes=1))
    sent = opened + timedelta(seconds=30)  # 대화는 열렸지만 회차를 보내기 전(두뇌가 쓰는 중)에 보낸 글
    await env.process(Inbound(text="안녕", at=env.clock.now(), sent_at=sent, update_ids=[2]))
    assert env.brain.session_ids[1] is None

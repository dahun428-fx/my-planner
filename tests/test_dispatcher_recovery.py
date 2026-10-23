"""시작 시 복구: 남은 회차는 interrupted, 재실행 규칙, failed 회차 재전송 (스펙 5.1 4단계, 5.4-3)."""

from datetime import date, timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.clock import to_iso
from my_planner.domain import Cadence, ConversationKind, LoopKey, RunStatus
from my_planner.loop.runner import recover_on_start

MON_0900 = kst(2026, 10, 26, 9, 0)
MON = date(2026, 10, 26)
BRIEF = "좋은 아침이에요. 오늘은 보고서 초안 하나만 해 봐요."


def _env(tmp_path, conn, state, script=(), *, start=MON_0900 + timedelta(minutes=10)):
    return Env(tmp_path, conn, state, script=list(script), start=start, with_tools=True, with_conditions=True)


def _recover(env):
    recover_on_start(env.runs, env.dispatcher, env.clock, env.settings)


async def test_startup_marks_queued_and_running_as_interrupted(tmp_path, conn, state):
    env = _env(tmp_path, conn, state)
    queued = env.runs.ensure(LoopKey.morning_brief, MON_0900)
    env.runs.mark_queued(queued.id)
    running = env.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
    env.runs.mark_running(running.id)
    pending = env.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
    done = env.runs.ensure(LoopKey.morning_brief, kst(2026, 10, 25, 10, 0))
    env.runs.mark_done(done.id)

    _recover(env)  # 디스패처를 아직 시작하지 않았다: 상태만 본다

    assert env.runs.get(queued.id).status is RunStatus.interrupted
    assert env.runs.get(running.id).status is RunStatus.interrupted
    assert env.runs.get(pending.id).status is RunStatus.pending
    assert env.runs.get(done.id).status is RunStatus.done


async def test_interrupted_without_tool_events_reruns_within_limit(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])
    # 같은 tick에 합쳐 큐에 넣었던 복귀 인사(running 중 멈춤)와 아침 브리핑(queued)
    ret = env.runs.ensure(LoopKey.return_, MON_0900 - timedelta(minutes=5))
    env.runs.mark_running(ret.id)
    morning = env.runs.ensure(LoopKey.morning_brief, MON_0900)
    env.runs.mark_queued(morning.id)
    # 한계(다음 날 04:00)가 지난 어제 저녁 체크인
    late = env.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 25, 18, 0))
    env.runs.mark_running(late.id)
    # 이미 두 번 실행한 회차(회차당 두뇌 호출 최대 2회). 한계(+3일) 안이다
    tired = env.runs.ensure(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    env.runs.mark_running(tired.id)
    env.runs.mark_running(tired.id)

    _recover(env)
    env.dispatcher.start()
    await env.dispatcher.stop(timeout=5)

    assert len(env.brain.calls) == 1  # 한 번만, 둘을 합쳐서 다시 실행했다
    assert [o.text for o in env.sender.sent] == [BRIEF]
    after_ret, after_morning = env.runs.get(ret.id), env.runs.get(morning.id)
    assert after_ret.status is RunStatus.done and after_ret.attempt == 2
    assert after_ret.merged_run_ids == [morning.id]
    assert after_morning.status is RunStatus.done
    assert env.runs.get(late.id).status is RunStatus.interrupted
    assert env.runs.get(tired.id).status is RunStatus.interrupted
    assert state.usage(MON).proactive_messages == 1


class _CrashAfterTool:
    """`add_task`를 부른 뒤 끝나지 않는 두뇌. 이 사이에 프로세스가 죽은 것처럼 작업을 취소한다."""

    def __init__(self, tools):
        self.tools = tools
        self.called = False

    async def run(self, prompt, *, session_id, run_ctx):
        import asyncio

        self.tools.add_task(run_ctx, title="보고서 목차 쓰기", areas=["career"])
        self.called = True
        await asyncio.Event().wait()


async def test_crash_mid_run_no_duplicate_task(tmp_path, conn, state):
    from test_dispatcher_runs import _wait_for

    add = ("add_task", {"title": "보고서 목차 쓰기", "areas": ["career"]})
    first = _env(tmp_path, conn, state)
    first.dispatcher.brain = crashing = _CrashAfterTool(first.tools)
    run = first.runs.ensure(LoopKey.morning_brief, MON_0900)
    first.runs.mark_queued(run.id)
    first.dispatcher.start()
    first.dispatcher.submit_run(first.runs.get(run.id), [])
    await _wait_for(lambda: crashing.called)
    await first.dispatcher.stop(timeout=0.01)  # 끝나지 않는 두뇌: 작업을 취소한다(크래시)
    assert first.runs.get(run.id).status is RunStatus.running

    # 다시 시작: 같은 DB, 새 디스패처. 두뇌가 또 불리면 같은 할 일을 또 만든다
    second = _env(tmp_path, conn, state, [FakeTurn([add], BRIEF)])
    _recover(second)
    second.dispatcher.start()
    await second.dispatcher.stop(timeout=5)

    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    assert second.brain.calls == [] and second.sender.sent == []
    assert second.runs.get(run.id).status is RunStatus.failed


async def test_crash_mid_merged_run_does_not_rerun_merged_alone(tmp_path, conn, state):
    from test_dispatcher_runs import _wait_for

    add = ("add_task", {"title": "보고서 목차 쓰기", "areas": ["career"]})
    first = _env(tmp_path, conn, state)
    first.dispatcher.brain = crashing = _CrashAfterTool(first.tools)
    ret = first.runs.ensure(LoopKey.return_, MON_0900 - timedelta(minutes=5))
    morning = first.runs.ensure(LoopKey.morning_brief, MON_0900)
    for r in (ret, morning):
        first.runs.mark_queued(r.id)
    first.dispatcher.start()
    first.dispatcher.submit_run(first.runs.get(ret.id), [first.runs.get(morning.id)])
    await _wait_for(lambda: crashing.called)
    await first.dispatcher.stop(timeout=0.01)

    # 도구 이벤트는 primary(복귀 인사)에 붙는다. 합쳐진 아침 브리핑도 그 호출의 일부다
    second = _env(tmp_path, conn, state, [FakeTurn([add], BRIEF)])
    _recover(second)
    second.dispatcher.start()
    await second.dispatcher.stop(timeout=5)

    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    assert second.brain.calls == []
    assert second.runs.get(ret.id).status is RunStatus.failed
    assert second.runs.get(morning.id).status is RunStatus.failed


CHECKIN = "오늘 하루 어땠어요? 내일은 목차부터 시작해 볼까요."


async def _failed_evening_with_drafts(tmp_path, conn, state):
    """월 17:30 저녁 체크인: 두뇌가 초안 둘을 제안했고, 전송이 끝내 안 된 채 5분 타이머 전에 멈췄다."""
    from test_dispatcher_runs import RecordingSender, _hold_long_sleeps

    propose = ("propose_tasks", {"tasks": [{"title": t, "areas": ["career"]} for t in ("목차", "초안")]})
    first = _env(tmp_path, conn, state, [FakeTurn([propose], CHECKIN)], start=kst(2026, 10, 26, 17, 31))
    first.sender = first.dispatcher.sender = RecordingSender(fail_times=99)
    _hold_long_sleeps(first)
    run = first.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
    first.runs.mark_queued(run.id)
    await first.process_run(first.runs.get(run.id))
    failed = first.runs.get(run.id)
    assert failed.status is RunStatus.failed and failed.resent == 0 and failed.outbound_text
    return failed


async def test_failed_run_resent_on_start_within_reply_window(tmp_path, conn, state):
    run = await _failed_evening_with_drafts(tmp_path, conn, state)
    second = _env(tmp_path, conn, state, start=kst(2026, 10, 26, 20, 0))
    # 답장 창(12:00)이 지난 아침 브리핑은 다시 보내지 않는다
    morning = second.runs.ensure(LoopKey.morning_brief, MON_0900)
    second.runs.save_outbound(morning.id, BRIEF)
    second.runs.mark_failed(morning.id, "send")

    _recover(second)
    second.dispatcher.start()
    await second.dispatcher.stop(timeout=5)

    assert second.brain.calls == []  # 전송만 다시 한다
    assert [o.text for o in second.sender.sent] == [run.outbound_text]
    out = second.sender.sent[0]
    drafts = conn.execute("SELECT id FROM tasks WHERE status = 'draft' ORDER BY id").fetchall()
    assert out.draft_task_ids == [r[0] for r in drafts] and len(drafts) == 2  # 초안 버튼을 다시 붙인다
    assert out.draft_conversation_id == run.conversation_id
    assert out.ask_condition_for == MON  # 컨디션 버튼도
    after = second.runs.get(run.id)
    assert after.status is RunStatus.done and after.resent == 1
    assert second.runs.get(morning.id).status is RunStatus.failed
    assert second.runs.get(morning.id).resent == 1  # 창 밖: 보내지 않고 다시 보낸 셈으로 기록한다

    # 한 번만: 또 시작해도 다시 보내지 않는다
    third = _env(tmp_path, conn, state, start=kst(2026, 10, 26, 20, 5))
    _recover(third)
    third.dispatcher.start()
    await third.dispatcher.stop(timeout=5)
    assert third.sender.sent == []


async def test_interrupted_after_brain_phase_sends_saved_text_only(tmp_path, conn, state):
    # (a) 두뇌 단계는 끝나 outbound_text가 저장됐고, (b) 전송 도중 멈췄다: 두뇌를 다시 부르지 않는다
    env = _env(tmp_path, conn, state, [FakeTurn([], "다른 답")])
    run = env.runs.ensure(LoopKey.morning_brief, MON_0900)
    env.runs.mark_running(run.id)
    conv = env.convs.open(ConversationKind.run, MON, run_id=run.id)
    env.runs.set_conversation(run.id, conv.id)
    env.runs.save_outbound(run.id, BRIEF)

    _recover(env)
    env.dispatcher.start()
    await env.dispatcher.stop(timeout=5)

    assert env.brain.calls == []
    assert [o.text for o in env.sender.sent] == [BRIEF]
    after = env.runs.get(run.id)
    assert after.status is RunStatus.done and after.resent == 1


async def test_merged_runs_follow_their_primary_on_start(tmp_path, conn, state):
    # 복귀 인사에 아침 브리핑이 합쳐졌고(merged_run_ids), 본문을 저장한 뒤 전송 도중 멈췄다
    env = _env(tmp_path, conn, state, [FakeTurn([], "다른 답")])
    ret = env.runs.ensure(LoopKey.return_, MON_0900 - timedelta(minutes=5))
    morning = env.runs.ensure(LoopKey.morning_brief, MON_0900)
    env.runs.mark_queued(morning.id)
    env.runs.add_merged(ret.id, [morning.id])
    env.runs.mark_running(ret.id)
    conv = env.convs.open(ConversationKind.run, MON, run_id=ret.id)
    env.runs.set_conversation(ret.id, conv.id)
    env.runs.save_outbound(ret.id, BRIEF)

    _recover(env)
    env.dispatcher.start()
    await env.dispatcher.stop(timeout=5)

    assert env.brain.calls == []  # 합쳐진 회차를 따로 다시 실행하지 않는다
    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert env.runs.get(ret.id).status is RunStatus.done
    assert env.runs.get(morning.id).status is RunStatus.done


async def test_carried_review_left_queued_returns_to_pending_and_remerges(tmp_path, conn, state):
    # 티켓 11: 계획 모드 되돌리기 도중(저녁 체크인은 pending, 회고는 아직 queued) 멈췄다. 표시는 남아 있다
    from my_planner.loop.runner import CARRY_REVIEW_KEY, Runner

    env = _env(tmp_path, conn, state, start=kst(2026, 10, 26, 17, 40))
    evening = env.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
    review = env.runs.ensure(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    env.runs.mark_queued(review.id)
    state.set(CARRY_REVIEW_KEY, str(review.id))

    _recover(env)

    assert env.runs.get(review.id).status is RunStatus.pending  # 혼자 다시 실행하지 않는다
    assert state.get(CARRY_REVIEW_KEY) == str(review.id)
    assert env.brain.calls == []

    submitted = []

    class Capture:
        def submit_run(self, run, merged, *, carried_ids=()):
            submitted.append((run.id, [m.id for m in merged], sorted(carried_ids)))

    state.set("installed_at", "2026-10-01T00:00:00+00:00")
    state.set("last_seen_at", to_iso(env.clock.now() - timedelta(minutes=1)))
    Runner(clock=env.clock, settings=env.settings, runs=env.runs, state=state, dispatcher=Capture()).tick()
    assert submitted == [(evening.id, [review.id], [review.id])]  # 다음 tick이 다시 합친다


async def test_carried_review_past_limit_on_start_clears_mark(tmp_path, conn, state):
    from my_planner.loop.runner import CARRY_REVIEW_KEY

    env = _env(tmp_path, conn, state, start=kst(2026, 10, 28, 18, 1))  # 일 18:00 + 3일이 지났다
    review = env.runs.ensure(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    env.runs.mark_queued(review.id)
    state.set(CARRY_REVIEW_KEY, str(review.id))

    _recover(env)

    assert env.runs.get(review.id).status is RunStatus.interrupted
    assert state.get(CARRY_REVIEW_KEY) is None


async def test_rerun_deferred_when_plan_open_goes_back_to_pending(tmp_path, conn, state):
    # 다시 실행하려고 큐에 넣었는데 계획 대화가 열려 있다: interrupted에 갇히지 않고 pending으로 돌아간다
    env = _env(tmp_path, conn, state, [FakeTurn([], BRIEF)])
    run = env.runs.ensure(LoopKey.morning_brief, MON_0900)
    env.runs.mark_queued(run.id)
    env.dispatcher.router.start_plan()

    _recover(env)
    env.dispatcher.start()
    await env.dispatcher.stop(timeout=5)

    assert env.brain.calls == []
    assert env.runs.get(run.id).status is RunStatus.pending

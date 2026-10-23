"""사용자 메시지에 답하는 전송: 바로 3회까지(1초, 2초 간격), 보낸 뒤에만 원문 기록과 처리 완료 (최종 리뷰 Important 2)."""

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst
from test_dispatcher_runs import TimedSender

START = kst(2026, 10, 23, 15, 0)


def _env(tmp_path, conn, state, script, fail_times):
    env = Env(tmp_path, conn, state, script=script, start=START)
    env.sender = env.dispatcher.sender = TimedSender(env.clock, fail_times=fail_times)
    return env


def _gaps(sender):
    return [(b - a).total_seconds() for a, b in zip(sender.times, sender.times[1:], strict=False)]


async def test_message_reply_retried_until_sent(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], "답장")], fail_times=2)
    await env.process(env.inbound("안녕", update_id=3))

    assert env.sender.attempts == 3 and _gaps(env.sender) == [1, 2]
    assert [o.text for o in env.sender.sent] == ["답장"]
    assert len(env.brain.calls) == 1  # 두뇌는 다시 부르지 않는다
    assert state.is_seen_update(3)
    day = env.day_file("2026-10-23").read_text(encoding="utf-8")
    assert day.count("비서 [1]") == 1


def _log_entries(env):
    import json
    import logging

    for h in logging.getLogger().handlers:
        h.flush()
    path = env.settings.paths.state_dir / "logs" / "my-planner.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def test_message_reply_final_send_failure_leaves_update_unmarked(tmp_path, conn, state):
    from my_planner.logging_setup import setup_logging

    env = _env(tmp_path, conn, state, [FakeTurn([], "답장 본문")], fail_times=99)
    setup_logging(env.settings.paths.state_dir, 30)
    await env.process(env.inbound("안녕", update_id=4))

    assert env.sender.attempts == 3 and env.sender.sent == []
    assert not state.is_seen_update(4)  # 다음 시작 때 다시 처리한다
    day = env.day_file("2026-10-23").read_text(encoding="utf-8")
    assert "사용자 [1]" in day and "비서" not in day and "답장 본문" not in day  # 보내지 못한 답은 기록하지 않는다
    failed = [e for e in _log_entries(env) if e.get("msg") == "message_send_failed"]
    assert len(failed) == 1 and failed[0]["error_type"] == "ConnectionError" and failed[0]["update_ids"] == [4]


async def test_fixed_reply_retried_and_marked_only_after_send(tmp_path, conn, state):
    from my_planner.harness.dispatcher import DAILY_CAP_REPLY

    env = _env(tmp_path, conn, state, [], fail_times=2)
    for _ in range(env.settings.limits.daily_brain_calls):
        state.incr_usage(env.dispatcher._today(), "brain_calls")
    await env.process(env.inbound("오늘 뭐 하지", update_id=6))

    assert env.sender.attempts == 3 and _gaps(env.sender) == [1, 2]
    assert [o.text for o in env.sender.sent] == [DAILY_CAP_REPLY]
    assert state.is_seen_update(6)

    env2 = _env(tmp_path, conn, state, [], fail_times=99)
    await env2.process(env2.inbound("또 물어요", update_id=7))
    assert env2.sender.attempts == 3 and not state.is_seen_update(7)
    day = env2.day_file("2026-10-23").read_text(encoding="utf-8")
    assert day.count(DAILY_CAP_REPLY) == 1  # 보내지 못한 두 번째 안내는 기록하지 않는다

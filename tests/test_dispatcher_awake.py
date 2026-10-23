"""디스패처의 절전 방지: 두뇌 호출과 전송 동안만 `keep_awake`를 잡는다 (스펙 5.1 "절전 방지", 티켓 13)."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta

from fakes import FakeSender, FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.domain import LoopKey

MON_0900 = kst(2026, 10, 26, 9, 0)


class FakeAwake:
    """주입하는 가짜 `keep_awake`. 잡고 푼 횟수와 지금 잡혀 있는지 기록한다."""

    def __init__(self):
        self.held = False
        self.events = []

    @contextmanager
    def __call__(self):
        assert not self.held, "디스패처가 이미 잡은 것을 다시 잡았다(참조 카운트는 디스패처가 한다)"
        self.held = True
        self.events.append("hold")
        try:
            yield
        finally:
            self.held = False
            self.events.append("release")


class AwakeSender(FakeSender):
    def __init__(self, awake):
        super().__init__()
        self.awake = awake
        self.held_at_send = []

    async def send(self, out):
        self.held_at_send.append(self.awake.held)
        await super().send(out)


async def test_keep_awake_held_during_brain_and_send(tmp_path, conn, state):
    awake = FakeAwake()
    sender = AwakeSender(awake)
    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "좋은 아침이에요.", delay=1), FakeTurn([], "네, 알겠어요.")],
        start=MON_0900 + timedelta(seconds=30), sender=sender, with_tools=True, keep_awake=awake,
    )
    held_at_brain = []
    brain_run = env.brain.run

    async def run(prompt, **kw):
        held_at_brain.append(awake.held)
        return await brain_run(prompt, **kw)

    env.brain.run = run
    run_row = env.runs.ensure(LoopKey.morning_brief, MON_0900)
    env.runs.mark_queued(run_row.id)

    assert awake.events == []  # 일이 없으면 잡지 않는다
    env.dispatcher.start()
    env.dispatcher.submit_run(env.runs.get(run_row.id), [])
    while not env.brain.calls:  # 회차가 두뇌를 부르는 중에
        await asyncio.sleep(0)
    env.dispatcher.submit_message(env.inbound("오늘 일정 알려 주세요", update_id=1))  # 메시지가 겹친다
    await env.dispatcher.stop(timeout=5)

    assert [o.text for o in sender.sent] == ["좋은 아침이에요.", "네, 알겠어요."]
    assert held_at_brain == [True, True]
    assert sender.held_at_send == [True, True]
    # 회차와 메시지가 겹쳐도 한 번 잡고, 마지막에 한 번 푼다
    assert awake.events == ["hold", "release"]
    assert not awake.held


async def test_keep_awake_released_when_brain_or_send_raises(tmp_path, conn, state):
    awake = FakeAwake()
    sender = AwakeSender(awake)
    env = Env(
        tmp_path, conn, state, script=[FakeTurn([], "답")],
        start=MON_0900 + timedelta(seconds=30), sender=sender, with_tools=True, keep_awake=awake,
    )
    brain_run = env.brain.run
    raised = []

    async def run(prompt, **kw):
        if not raised:  # 회차의 두뇌 호출이 예외를 낸다
            raised.append(True)
            raise RuntimeError("brain crashed")
        return await brain_run(prompt, **kw)

    env.brain.run = run
    run_row = env.runs.ensure(LoopKey.morning_brief, MON_0900)
    env.runs.mark_queued(run_row.id)
    await env.process_run(env.runs.get(run_row.id))
    assert awake.events == ["hold", "release"] and not awake.held

    sender.fail = True  # 메시지 답을 보내다 예외
    await env.process(env.inbound("안녕", update_id=1))
    assert awake.events == ["hold", "release", "hold", "release"] and not awake.held

"""러너 tick: 가짜 시계와 가짜 디스패처 (스펙 5.4)."""

from datetime import timedelta

import pytest
from fakes import make_settings
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock, from_iso, to_iso
from my_planner.domain import LoopKey, RunStatus
from my_planner.loop.runner import Runner
from my_planner.store.repos.runs import RunsRepo


class FakeDispatcher:
    def __init__(self):
        self.submitted = []

    def submit_run(self, run, merged):
        self.submitted.append((run, merged))


class Env:
    def __init__(self, tmp_path, conn, state, start, *, installed=None, last_seen=None):
        self.clock = FakeClock(start)
        self.settings = make_settings(tmp_path)
        self.state = state
        self.runs = RunsRepo(conn, self.clock)
        self.dispatcher = FakeDispatcher()
        if installed is not None:
            state.set("installed_at", to_iso(installed))
        if last_seen is not None:
            state.set("last_seen_at", to_iso(last_seen))
        self.runner = Runner(
            clock=self.clock, settings=self.settings, runs=self.runs, state=state, dispatcher=self.dispatcher
        )


@pytest.fixture
def mon_morning(tmp_path, conn, state):
    # 월 09:00:30, 설치는 지난주, 마지막 tick은 1분 전
    return Env(
        tmp_path, conn, state,
        kst(2026, 10, 26, 9, 0) + timedelta(seconds=30),
        installed=kst(2026, 10, 20, 12, 0),
        last_seen=kst(2026, 10, 26, 8, 59) + timedelta(seconds=30),
    )


def test_tick_creates_runs_and_submits_due(mon_morning):
    env = mon_morning
    env.runner.tick()

    assert len(env.dispatcher.submitted) == 1
    run, merged = env.dispatcher.submitted[0]
    assert merged == []
    assert run.loop is LoopKey.morning_brief
    assert run.scheduled_for == kst(2026, 10, 26, 9, 0)
    assert env.runs.get(run.id).status is RunStatus.queued


def test_run_not_resubmitted_while_queued(mon_morning):
    env = mon_morning
    env.runner.tick()
    env.clock.advance(minutes=1)
    env.runner.tick()

    assert len(env.dispatcher.submitted) == 1
    assert [r.status for r in env.runs.between(kst(2026, 10, 26, 0, 0), env.clock.now())] == [RunStatus.queued]


def test_tick_updates_last_seen_even_when_nothing_due(tmp_path, conn, state):
    start = kst(2026, 10, 26, 14, 0)  # 월 14:00, 이 시각에는 회차가 없다
    env = Env(tmp_path, conn, state, start, installed=start - timedelta(days=1), last_seen=start - timedelta(minutes=1))
    env.runner.tick()
    assert env.dispatcher.submitted == []
    assert from_iso(state.get("last_seen_at")) == start
    env.clock.advance(minutes=1)
    env.runner.tick()
    assert from_iso(state.get("last_seen_at")) == start + timedelta(minutes=1)


def test_daily_jobs_run_once_per_logical_day(tmp_path, conn, state):
    from datetime import date

    start = kst(2026, 10, 26, 14, 0)
    env = Env(tmp_path, conn, state, start, installed=start - timedelta(days=1), last_seen=start)
    seen = []
    env.runner.register_daily(seen.append)
    env.runner.register_daily(lambda d: seen.append(("둘째", d)))

    env.runner.tick()
    assert seen == [date(2026, 10, 26), ("둘째", date(2026, 10, 26))]
    env.clock.set(kst(2026, 10, 26, 20, 0))
    env.runner.tick()
    env.clock.set(kst(2026, 10, 27, 3, 59))  # 화 03:59는 아직 월요일(논리적 날짜)
    env.runner.tick()
    assert len(seen) == 2
    env.clock.set(kst(2026, 10, 27, 4, 0))
    env.runner.tick()
    assert seen[2:] == [date(2026, 10, 27), ("둘째", date(2026, 10, 27))]
    assert state.get("last_daily_jobs_date") == "2026-10-27"


def test_installed_at_set_once(tmp_path, conn, state):
    start = kst(2026, 10, 26, 8, 0)
    env = Env(tmp_path, conn, state, start)  # 첫 실행: installed_at도 last_seen_at도 없다
    env.runner.tick()
    assert from_iso(state.get("installed_at")) == start
    env.clock.set(kst(2026, 10, 26, 9, 0) + timedelta(seconds=30))
    env.runner.tick()
    assert from_iso(state.get("installed_at")) == start
    # 설치 뒤의 회차는 정상으로 나간다
    assert [r.loop for r, _ in env.dispatcher.submitted] == [LoopKey.morning_brief]


async def test_run_forever_ticks_each_interval_and_survives_errors(tmp_path, conn, state):
    clock = FakeClock(kst(2026, 10, 26, 14, 0))
    slept = []

    class Stop(Exception):
        pass

    async def sleep(s):
        slept.append(s)
        clock.advance(seconds=s)
        if len(slept) == 3:
            raise Stop

    runner = Runner(
        clock=clock, settings=make_settings(tmp_path), runs=RunsRepo(conn, clock), state=state,
        dispatcher=FakeDispatcher(), sleep=sleep,
    )
    ticks = []

    def flaky_tick():
        ticks.append(clock.now())
        if len(ticks) == 1:
            raise RuntimeError("boom")

    runner.tick = flaky_tick
    with pytest.raises(Stop):
        await runner.run_forever(interval=60)
    assert slept == [60, 60, 60]
    assert len(ticks) == 2  # 첫 tick은 시작 순서에서 따로 부르고, 이후 interval마다 한 번


def test_expire_drafts_after_3_days(tmp_path, conn, state):
    from my_planner.domain import Area, TaskStatus
    from my_planner.loop.runner import expire_drafts
    from my_planner.store.repos.tasks import TasksRepo

    mon_0400 = kst(2026, 10, 26, 4, 0)
    env = Env(tmp_path, conn, state, mon_0400, installed=mon_0400 - timedelta(days=7), last_seen=mon_0400)
    repo = TasksRepo(conn, env.clock)
    env.runner.register_daily(expire_drafts(repo, env.clock))
    three_days = repo.create("사흘 된 초안", [Area.career], TaskStatus.draft)
    env.clock.set(kst(2026, 10, 26, 5, 0))
    almost = repo.create("2일 23시간 된 초안", [Area.career], TaskStatus.draft)
    opened = repo.create("열린 일", [Area.career], TaskStatus.open)

    env.clock.set(kst(2026, 10, 29, 3, 59))  # 아직 수요일(논리적 날짜). 하루 한 번 작업은 수요일 몫이 이미 돌았다고 둔다
    state.set("last_daily_jobs_date", "2026-10-28")
    state.set("last_seen_at", to_iso(env.clock.now()))
    env.runner.tick()
    assert repo.get(three_days.id).status is TaskStatus.draft
    env.clock.set(kst(2026, 10, 29, 4, 0))  # 목 04:00: 하루 한 번 작업. 첫째는 정확히 3일, 둘째는 2일 23시간
    env.runner.tick()

    assert repo.get(three_days.id).status is TaskStatus.dropped
    assert repo.get(almost.id).status is TaskStatus.draft
    assert repo.get(opened.id).status is TaskStatus.open
    assert env.dispatcher.submitted == []  # 조용히: 아무것도 보내지 않는다
    env.clock.set(kst(2026, 10, 30, 4, 0))
    env.runner.tick()
    assert repo.get(almost.id).status is TaskStatus.dropped

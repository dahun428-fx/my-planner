"""러너 tick: 가짜 시계와 가짜 디스패처 (스펙 5.4)."""

from datetime import date, timedelta

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
        self.carried = []  # 제출마다 넘겨 받은 회고 id

    def submit_run(self, run, merged, *, carried_ids=()):
        self.submitted.append((run, merged))
        self.carried.append(sorted(carried_ids))


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
    env.clock.set(kst(2026, 10, 26, 3, 58))
    older = repo.create("목 03:59에 3일이 넘는 초안", [Area.career], TaskStatus.draft)
    env.clock.set(mon_0400)
    three_days = repo.create("사흘 된 초안", [Area.career], TaskStatus.draft)
    env.clock.set(kst(2026, 10, 26, 5, 0))
    almost = repo.create("2일 23시간 된 초안", [Area.career], TaskStatus.draft)
    opened = repo.create("열린 일", [Area.career], TaskStatus.open)

    def tick_at(at):  # 1분 전에도 tick이 돌았던 것처럼(따라잡기 없이) tick한다
        state.set("last_seen_at", to_iso(at - timedelta(minutes=1)))
        env.clock.set(at)
        env.runner.tick()

    tick_at(kst(2026, 10, 28, 5, 0))  # 수요일 몫의 하루 한 번 작업: 아직 3일 된 초안이 없다
    assert state.get("last_daily_jobs_date") == "2026-10-28"
    tick_at(kst(2026, 10, 29, 3, 59))  # 아직 수요일(논리적 날짜): 작업이 다시 돌지 않는다
    assert repo.get(older.id).status is TaskStatus.draft  # 다시 돌았다면 3일 1분이라 dropped였다
    tick_at(kst(2026, 10, 29, 4, 0))  # 목 04:00: 하루 한 번 작업. 사흘 된 것은 정확히 3일, 다음 것은 2일 23시간

    assert repo.get(older.id).status is TaskStatus.dropped
    assert repo.get(three_days.id).status is TaskStatus.dropped
    assert repo.get(almost.id).status is TaskStatus.draft
    assert repo.get(opened.id).status is TaskStatus.open
    assert env.dispatcher.submitted == []  # 조용히: 아무것도 보내지 않는다
    tick_at(kst(2026, 10, 30, 4, 0))
    assert repo.get(almost.id).status is TaskStatus.dropped


# --- 티켓 09: 따라잡기(R1, 넘겨 받은 회고, 하루 3회 상한, 시계 이상) ---


def _gap_env(tmp_path, conn, state, last_seen, woke):
    return Env(tmp_path, conn, state, woke, installed=last_seen - timedelta(days=30), last_seen=last_seen)


def test_tick_after_25h_gap_creates_single_return_run(tmp_path, conn, state):
    from my_planner.domain import SkipReason

    woke = kst(2026, 10, 25, 18, 30)  # 토 17:00 → 일 18:30
    env = _gap_env(tmp_path, conn, state, kst(2026, 10, 24, 17, 0), woke)
    env.runner.tick()

    assert len(env.dispatcher.submitted) == 1
    run, merged = env.dispatcher.submitted[0]
    assert (run.loop, run.scheduled_for, merged) == (LoopKey.return_, woke, [])
    assert env.runs.get(run.id).status is RunStatus.queued
    others = [r for r in env.runs.between(kst(2026, 10, 24, 0, 0), woke) if r.id != run.id]
    assert [r.loop for r in others if r.status is RunStatus.pending] == [LoopKey.review]
    assert {(r.loop, r.skip_reason) for r in others if r.status is RunStatus.skipped} == {
        (LoopKey.evening_checkin, SkipReason.merged_into_return),
        (LoopKey.morning_brief, SkipReason.merged_into_return),
    }
    assert len(others) == 4


def _tick_at(env, at):
    """1분 전에도 tick이 돌았던 것처럼(공백 없이) tick한다."""
    env.state.set("last_seen_at", to_iso(at - timedelta(minutes=1)))
    env.clock.set(at)
    env.runner.tick()


def test_r1_carried_review_merges_into_next_contact(tmp_path, conn, state):
    woke = kst(2026, 10, 25, 18, 30)  # 토 17:00 → 일 18:30: 일 회고를 넘겨 받는다
    env = _gap_env(tmp_path, conn, state, kst(2026, 10, 24, 17, 0), woke)
    env.runner.tick()
    ret, _ = env.dispatcher.submitted[0]
    env.runs.mark_done(ret.id)
    review = next(r for r in env.runs.pending() if r.loop is LoopKey.review)
    assert state.get("carry_review_run_id") == str(review.id)

    _tick_at(env, kst(2026, 10, 25, 18, 31))  # 다음 정규 연락 전: 회고는 혼자 나가지 않는다
    _tick_at(env, kst(2026, 10, 26, 3, 0))
    assert len(env.dispatcher.submitted) == 1
    assert env.runs.get(review.id).status is RunStatus.pending

    _tick_at(env, kst(2026, 10, 26, 9, 0) + timedelta(seconds=30))  # 월 아침 브리핑에 합친다
    run, merged = env.dispatcher.submitted[1]
    assert run.loop is LoopKey.morning_brief
    assert [m.id for m in merged] == [review.id]
    assert env.runs.get(review.id).status is RunStatus.queued
    assert state.get("carry_review_run_id") is None
    assert env.dispatcher.carried == [[], [review.id]]  # 디스패처가 승격하지 않도록 표시해 넘긴다


def test_r1_carried_review_late_clears_mark(tmp_path, conn, state):
    from my_planner.domain import SkipReason

    env = _gap_env(tmp_path, conn, state, kst(2026, 10, 24, 17, 0), kst(2026, 10, 25, 18, 30))
    env.runner.tick()
    review = next(r for r in env.runs.pending() if r.loop is LoopKey.review)
    _tick_at(env, kst(2026, 10, 28, 18, 1))  # 정규 연락 없이 +3일이 지났다(그 사이 회차는 따로 다루지 않는다)
    assert env.runs.get(review.id).skip_reason is SkipReason.late
    assert state.get("carry_review_run_id") is None


def test_deferred_run_reconsidered_next_tick(tmp_path, conn, state):
    from datetime import date

    from my_planner.domain import SkipReason

    at = kst(2026, 10, 25, 18, 0) + timedelta(seconds=30)  # 일 18:00:30, 오늘 이미 3번 먼저 보냈다
    env = Env(tmp_path, conn, state, at, installed=at - timedelta(days=7), last_seen=at - timedelta(minutes=1))
    for _ in range(3):
        state.incr_usage(date(2026, 10, 25), "proactive_messages")
    env.runner.tick()
    _tick_at(env, at + timedelta(minutes=1))
    assert env.dispatcher.submitted == []
    pend = env.runs.pending()
    assert sorted(r.loop for r in pend) == [LoopKey.evening_checkin, LoopKey.review]
    eve = next(r for r in pend if r.loop is LoopKey.evening_checkin)
    rev = next(r for r in pend if r.loop is LoopKey.review)

    _tick_at(env, kst(2026, 10, 26, 9, 0) + timedelta(seconds=30))  # 새 날(0회): 한계 안은 합치고, 밖은 late
    run, merged = env.dispatcher.submitted[0]
    assert run.loop is LoopKey.morning_brief and [m.id for m in merged] == [rev.id]
    assert env.runs.get(eve.id).skip_reason is SkipReason.late


def test_return_before_morning_skips_that_morning(tmp_path, conn, state):
    # 금 22:00 → 화 08:00 복귀(스펙 표 6행). 화 09:00 tick에는 제출이 없다(월요일 컨디션 버튼을 붙일 아침 브리핑도 없다).
    # 넘겨 받은 일요일 회고는 화 17:30 저녁 체크인에 합친다
    from my_planner.domain import SkipReason

    env = _gap_env(tmp_path, conn, state, kst(2026, 10, 23, 22, 0), kst(2026, 10, 27, 8, 0))
    env.runner.tick()
    assert [r.loop for r, _ in env.dispatcher.submitted] == [LoopKey.return_]
    morning = env.runs.between(kst(2026, 10, 27, 8, 59), kst(2026, 10, 27, 9, 0))
    assert [(r.loop, r.status, r.skip_reason) for r in morning] == [
        (LoopKey.morning_brief, RunStatus.skipped, SkipReason.merged_into_return)
    ]

    _tick_at(env, kst(2026, 10, 27, 9, 0) + timedelta(seconds=30))
    assert len(env.dispatcher.submitted) == 1

    _tick_at(env, kst(2026, 10, 27, 17, 30) + timedelta(seconds=30))
    run, merged = env.dispatcher.submitted[1]
    assert run.loop is LoopKey.evening_checkin
    assert [m.loop for m in merged] == [LoopKey.review]


_STD_ATTRS = set(vars(__import__("logging").makeLogRecord({})))


def test_clock_backwards_logs_warning(mon_morning, caplog):
    import logging

    env = mon_morning
    env.state.set("last_seen_at", to_iso(env.clock.now() + timedelta(hours=2)))  # 시계가 2시간 뒤로 갔다
    with caplog.at_level(logging.INFO, logger="my_planner"):
        env.runner.tick()
    recs = [r for r in caplog.records if r.getMessage() == "clock_went_backwards"]
    assert len(recs) == 1 and recs[0].levelno == logging.WARNING
    assert {k: v for k, v in vars(recs[0]).items() if k not in _STD_ATTRS and k != "message"} == {"gap_seconds": 7200}
    assert from_iso(env.state.get("last_seen_at")) == env.clock.now()  # 하트비트는 지금 시각으로
    assert env.dispatcher.submitted == []  # 창이 비어 회차를 쏟아내지 않는다


def test_clock_backwards_then_forward_does_not_rerun_done_runs(mon_morning):
    # 월 09:00:30에 아침 브리핑을 보냈다(done). 시계가 08:30으로 돌아갔다가 다시 09:01이 된다.
    # 창 (08:30, 09:01]에 09:00 아침 브리핑이 다시 들지만 ensure는 있는 회차를 그대로 돌려주므로 다시 내지 않는다
    env = mon_morning
    env.runner.tick()
    run, _ = env.dispatcher.submitted[0]
    env.runs.mark_done(run.id)

    env.clock.set(kst(2026, 10, 26, 8, 30))
    env.runner.tick()
    env.clock.set(kst(2026, 10, 26, 9, 1))
    env.runner.tick()

    assert len(env.dispatcher.submitted) == 1
    mornings = [r for r in env.runs.between(kst(2026, 10, 26, 0, 0), env.clock.now()) if r.loop is LoopKey.morning_brief]
    assert [(r.id, r.status) for r in mornings] == [(run.id, RunStatus.done)]


def test_stale_carry_mark_cleared_when_run_not_pending(mon_morning):
    # 표시된 회고 회차가 이미 pending이 아니면(예: 다른 경로로 끝남) 표시를 지운다
    from my_planner.domain import Cadence

    env = mon_morning
    review = env.runs.ensure(LoopKey.review, kst(2026, 10, 25, 18, 0), Cadence.week)
    env.runs.mark_done(review.id)
    env.state.set("carry_review_run_id", str(review.id))
    env.runner.tick()
    assert env.state.get("carry_review_run_id") is None
    assert env.dispatcher.carried == [[]]


def test_crash_between_submit_and_heartbeat_leaves_one_return(tmp_path, conn, state):
    # 복귀 인사를 제출한 직후 tick이 죽었다(하트비트 전). 다음 tick이 R1을 다시 적용해 return을 또 만들면 안 된다
    env = _gap_env(tmp_path, conn, state, kst(2026, 10, 24, 17, 0), kst(2026, 10, 25, 18, 30))
    real_submit = env.dispatcher.submit_run

    def submit_then_crash(run, merged, **kw):
        real_submit(run, merged, **kw)
        raise RuntimeError("crash after submit")

    env.dispatcher.submit_run = submit_then_crash
    with pytest.raises(RuntimeError):
        env.runner.tick()
    env.dispatcher.submit_run = real_submit
    env.clock.advance(minutes=1)
    env.runner.tick()

    returns = [r for r in env.runs.between(kst(2026, 10, 24, 0, 0), env.clock.now()) if r.loop is LoopKey.return_]
    assert len(returns) == 1
    assert [r.loop for r, _ in env.dispatcher.submitted] == [LoopKey.return_]


def test_r1_skipped_when_return_already_queued_after_last_seen(tmp_path, conn, state):
    # last_seen_at이 기록되지 않았어도(예전 값 그대로) 그 뒤에 queued/done인 return이 있으면 R1을 다시 적용하지 않는다
    last = kst(2026, 10, 24, 17, 0)
    env = _gap_env(tmp_path, conn, state, last, kst(2026, 10, 25, 18, 30))
    env.runner.tick()
    for status_done in (False, True):
        if status_done:
            env.runs.mark_done(env.dispatcher.submitted[0][0].id)
        state.set("last_seen_at", to_iso(last))
        env.clock.advance(minutes=1)
        env.runner.tick()
    returns = [r for r in env.runs.between(last, env.clock.now()) if r.loop is LoopKey.return_]
    assert len(returns) == 1 and len(env.dispatcher.submitted) == 1


def test_r1_leaves_non_pending_future_morning_alone(tmp_path, conn, state):
    # 그날 아침 브리핑 회차가 이미 있고 pending이 아니면(예: 시계 이상으로 먼저 나감) R1이 상태를 덮어쓰지 않는다
    env = _gap_env(tmp_path, conn, state, kst(2026, 10, 23, 22, 0), kst(2026, 10, 27, 8, 0))
    morning = env.runs.ensure(LoopKey.morning_brief, kst(2026, 10, 27, 9, 0))
    env.runs.mark_done(morning.id)
    env.runner.tick()
    got = env.runs.get(morning.id)
    assert (got.status, got.skip_reason) == (RunStatus.done, None)
    assert [r.loop for r, _ in env.dispatcher.submitted] == [LoopKey.return_]


def test_tick_after_30_day_jump_sends_single_return_within_7_days(tmp_path, conn, state):
    # 시계가 30일 앞으로 갔다(월 13:00): return 하나만 내고, 회차는 7일 창 안의 것만 만든다
    woke = kst(2026, 10, 26, 13, 0)
    env = _gap_env(tmp_path, conn, state, woke - timedelta(days=30), woke)
    env.runner.tick()
    assert [(r.loop, r.scheduled_for) for r, _ in env.dispatcher.submitted] == [(LoopKey.return_, woke)]
    created = env.runs.between(woke - timedelta(days=60), woke)
    assert min(r.scheduled_for for r in created) > woke - timedelta(days=7)
    assert len([r for r in created if r.loop is not LoopKey.return_]) == 15  # 아침 7 + 저녁 7 + 회고 1
    env.clock.advance(minutes=1)
    env.runner.tick()
    assert len(env.dispatcher.submitted) == 1


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda env: env.state.set("pause_until", to_iso(kst(2026, 10, 27, 9, 0))), "paused"),
        (lambda env: env.state.set("limited_until", to_iso(kst(2026, 10, 26, 10, 0))), "rate_limit"),
        (lambda env: [env.state.incr_usage(date(2026, 10, 26), "brain_calls") for _ in range(60)],
         "daily_cap"),
    ],
)
def test_tick_applies_pause_rate_limit_and_daily_cap(mon_morning, setup, reason):
    # app_state.pause_until, limited_until, usage_state.brain_calls를 판정에 넘긴다
    env = mon_morning
    setup(env)
    env.runner.tick()
    assert env.dispatcher.submitted == []
    (run,) = env.runs.between(kst(2026, 10, 26, 8, 0), kst(2026, 10, 26, 10, 0))
    assert run.status is RunStatus.skipped and run.skip_reason == reason

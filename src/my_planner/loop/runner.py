"""1분 tick: 회차 만들기, 따라잡기 판정, 제출, 하트비트, 하루 한 번 작업 (스펙 5.4)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from my_planner.clock import Clock, from_iso, logical_date, to_iso
from my_planner.domain import LoopKey, RunStatus
from my_planner.loop.catchup import decide
from my_planner.loop.schedule import ENABLED_LOOPS, Due, due_between, window_start
from my_planner.store.repos.state import LIMITED_UNTIL_KEY, PAUSE_UNTIL_KEY

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.store.repos.tasks import TasksRepo

log = logging.getLogger(__name__)

DRAFT_EXPIRE_DAYS = 3
CARRY_REVIEW_KEY = "carry_review_run_id"


def _due(run: Run) -> Due:
    return Due(run.loop, run.scheduled_for, run.cadence)


def expire_drafts(tasks: TasksRepo, clock: Clock, *, days: int = DRAFT_EXPIRE_DAYS) -> Callable[[date], None]:
    """하루 한 번 작업: 만든 지 `days`일이 지난 초안을 조용히 `dropped`로 바꾼다(알리지 않음, 스펙 5.7)."""

    def job(today: date) -> None:
        ids = tasks.expire_drafts(clock.now() - timedelta(days=days))
        log.info("drafts_expired", extra={"count": len(ids)})

    job.__name__ = "expire_drafts"
    return job


class RunSubmitter(Protocol):
    def submit_run(self, run: Run, merged: list[Run], *, carried_ids: Iterable[int] = ()) -> None: ...


class Runner:
    def __init__(
        self,
        *,
        clock: Clock,
        settings: Settings,
        runs: RunsRepo,
        state: StateRepo,
        dispatcher: RunSubmitter,
        loops: frozenset[LoopKey] = ENABLED_LOOPS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.clock = clock
        self.settings = settings
        self.runs = runs
        self.state = state
        self.dispatcher = dispatcher
        self.loops = loops
        self._daily: list[Callable[[date], None]] = []
        self._sleep = sleep

    def register_daily(self, job: Callable[[date], None]) -> None:
        """하루 한 번 작업. 논리적 날짜가 바뀐 뒤 첫 tick 끝에서 등록 순서대로 부른다."""
        self._daily.append(job)

    def _get_time(self, key: str) -> datetime | None:
        v = self.state.get(key)
        return from_iso(v) if v else None

    def _carried_review(self) -> Run | None:
        """`app_state.carry_review_run_id`가 가리키는, 아직 pending인 회고 회차."""
        v = self.state.get(CARRY_REVIEW_KEY)
        if not v:
            return None
        run = self.runs.get(int(v))
        if run is None or run.status is not RunStatus.pending:
            self.state.set(CARRY_REVIEW_KEY, None)  # 낡은 표시는 지운다
            return None
        return run

    def _after_started_return(self, last_seen: datetime | None, now: datetime) -> datetime | None:
        """판정에 쓸 마지막 tick 시각. `last_seen` 뒤에 이미 큐에 들었거나 끝난 return이 있으면 그 시각으로 본다.

        하트비트가 기록되지 않은 채 tick이 죽었을 때 복귀 인사를 두 번 만들지 않기 위해서다.
        """
        if last_seen is None or last_seen >= now:
            return last_seen
        started = [
            r.scheduled_for
            for r in self.runs.between(last_seen, now)
            if r.loop is LoopKey.return_ and r.status not in (RunStatus.pending, RunStatus.skipped)
        ]
        return max([last_seen, *started])

    def ensure_installed(self) -> None:
        """첫 실행이면(`installed_at`이 없으면) 지금 시각을 기록한다(스펙 5.1 5단계)."""
        if self.state.get("installed_at") is None:
            self.state.set("installed_at", to_iso(self.clock.now()))

    async def run_forever(self, interval: float = 60) -> None:
        """`interval`초마다 tick한다. 첫 tick은 시작 순서(스펙 5.1 6단계)에서 따로 부른다."""
        while True:
            await self._sleep(interval)
            try:
                self.tick()
            except Exception:  # tick 하나가 안 돼도 루프는 계속 돈다
                log.exception("tick_error")

    def tick(self) -> None:
        s = self.settings
        tz, boundary = s.timezone, s.day_boundary
        # 1. 지금과 이전 last_seen_at
        now = self.clock.now()
        self.ensure_installed()
        last_seen = self._get_time("last_seen_at")
        installed = self._get_time("installed_at")
        judged_from = self._after_started_return(last_seen, now)
        # 2. 창 안의 예정 회차를 runs에 만든다(이미 있으면 그대로)
        for due in due_between(window_start(now, last_seen, installed), now, s, tz, self.loops):
            self.runs.ensure(due.loop, due.scheduled_for, due.cadence)
        # 3. 따라잡기 판정과 적용
        by_due = {_due(r): r for r in self.runs.pending()}
        # 넘겨 받은 회고(R1)는 pending이지만 판정에서 빼고 따로 넘긴다
        carried = self._carried_review()
        carried_due = _due(carried) if carried is not None else None
        usage = self.state.usage(logical_date(now, tz, boundary))
        decision = decide(
            now, judged_from, [d for d in by_due if d != carried_due], carried_review=carried_due,
            paused_until=self._get_time(PAUSE_UNTIL_KEY),
            limited_until=self._get_time(LIMITED_UNTIL_KEY),
            brain_calls_today=usage.brain_calls,
            proactive_today=usage.proactive_messages,
            cfg=s, tz=tz, boundary=boundary,
        )
        if decision.clock_backwards and last_seen is not None:  # 공백은 0으로 봤다. 차이만 남긴다
            log.warning("clock_went_backwards", extra={"gap_seconds": int((last_seen - now).total_seconds())})
        if carried is not None:
            by_due[_due(carried)] = carried
        if decision.create_return:  # R1: 복귀 인사 회차 하나
            ret = self.runs.ensure(LoopKey.return_, now)
            by_due[_due(ret)] = ret
        for due, reason in decision.skipped:
            run = by_due.get(due)
            if run is None:  # 아직 오지 않은 회차(R1의 그날 아침 브리핑): 만들어 두고 skip을 기록한다
                run = self.runs.ensure(due.loop, due.scheduled_for, due.cadence)
                if run.status is not RunStatus.pending:
                    continue
            self.runs.mark_skipped(run.id, reason)
        if carried_due is not None and (
            carried_due in decision.merged or any(d == carried_due for d, _ in decision.skipped)
        ):
            self.state.set(CARRY_REVIEW_KEY, None)  # 합쳐졌거나 late가 됐다
        if decision.carry_review is not None:
            self.state.set(CARRY_REVIEW_KEY, str(by_due[decision.carry_review].id))
        if decision.primary is not None:
            primary = by_due[decision.primary]
            merged = [by_due[d] for d in decision.merged]
            for r in (primary, *merged):
                self.runs.mark_queued(r.id)
            carried_ids = [carried.id] if carried is not None and carried_due in decision.merged else []
            # 제출 전에 하트비트를 먼저 남긴다. 제출 뒤에 tick이 죽어도 다음 tick이 R1을 다시 적용하지 않는다
            self.state.set("last_seen_at", to_iso(now))
            self.dispatcher.submit_run(
                self.runs.get(primary.id), [self.runs.get(r.id) for r in merged], carried_ids=carried_ids
            )
        # 4. 하트비트
        self.state.set("last_seen_at", to_iso(now))
        self._run_daily(logical_date(now, tz, boundary))

    def _run_daily(self, today: date) -> None:
        if self.state.get("last_daily_jobs_date") == today.isoformat():
            return
        for job in self._daily:
            try:
                job(today)
            except Exception:  # 한 작업이 안 돼도 나머지는 돈다. 같은 날 다시 부르지는 않는다
                log.exception("daily_job_error", extra={"job": getattr(job, "__name__", repr(job))})
        self.state.set("last_daily_jobs_date", today.isoformat())

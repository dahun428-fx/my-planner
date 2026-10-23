"""1분 tick: 회차 만들기, 따라잡기 판정, 제출, 하트비트, 하루 한 번 작업 (스펙 5.4)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from my_planner.clock import Clock, from_iso, logical_date, to_iso
from my_planner.domain import LoopKey
from my_planner.loop.catchup import decide
from my_planner.loop.schedule import ENABLED_LOOPS, Due, due_between, window_start

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.store.repos.tasks import TasksRepo

log = logging.getLogger(__name__)

DRAFT_EXPIRE_DAYS = 3


def expire_drafts(tasks: TasksRepo, clock: Clock, *, days: int = DRAFT_EXPIRE_DAYS) -> Callable[[date], None]:
    """하루 한 번 작업: 만든 지 `days`일이 지난 초안을 조용히 `dropped`로 바꾼다(알리지 않음, 스펙 5.7)."""

    def job(today: date) -> None:
        ids = tasks.expire_drafts(clock.now() - timedelta(days=days))
        log.info("drafts_expired", extra={"count": len(ids)})

    job.__name__ = "expire_drafts"
    return job


class RunSubmitter(Protocol):
    def submit_run(self, run: Run, merged: list[Run]) -> None: ...


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
        # 2. 창 안의 예정 회차를 runs에 만든다(이미 있으면 그대로)
        for due in due_between(window_start(now, last_seen, installed), now, s, tz, self.loops):
            self.runs.ensure(due.loop, due.scheduled_for, due.cadence)
        # 3. 따라잡기 판정과 적용
        by_due = {Due(r.loop, r.scheduled_for, r.cadence): r for r in self.runs.pending()}
        decision = decide(now, last_seen, list(by_due), cfg=s, tz=tz, boundary=boundary)
        for due, reason in decision.skipped:
            self.runs.mark_skipped(by_due[due].id, reason)
        if decision.primary is not None:
            primary = by_due[decision.primary]
            merged = [by_due[d] for d in decision.merged]
            for r in (primary, *merged):
                self.runs.mark_queued(r.id)
            self.dispatcher.submit_run(self.runs.get(primary.id), [self.runs.get(r.id) for r in merged])
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

"""1분 tick: 회차 만들기, 따라잡기 판정, 제출, 하트비트, 하루 한 번 작업 (스펙 5.4)."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from my_planner.clock import Clock, from_iso, logical_date, to_iso
from my_planner.domain import LoopKey, RunStatus, SkipReason
from my_planner.harness.dispatcher import MAX_RUN_ATTEMPTS, Inbound
from my_planner.logging_setup import cleanup_logs
from my_planner.loop.catchup import RETURN_GAP, decide, merge_order
from my_planner.loop.schedule import (
    ENABLED_LOOPS,
    Due,
    due_between,
    limit_for,
    window_start,
)
from my_planner.store.backup import daily_backup
from my_planner.store.repos.state import (
    CARRY_REVIEW_KEY,
    LIMITED_UNTIL_KEY,
    PAUSE_UNTIL_KEY,
)

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.harness.conversations import ConversationRouter
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.store.repos.tasks import TasksRepo

log = logging.getLogger(__name__)

DRAFT_EXPIRE_DAYS = 3
RESUME_GAP = timedelta(minutes=3)  # 직전 tick과 이보다 멀면 절전에서 깨어난 것으로 본다(스펙 7, S5)


def _due(run: Run) -> Due:
    return Due(run.loop, run.scheduled_for, run.cadence)


def expire_drafts(tasks: TasksRepo, clock: Clock, *, days: int = DRAFT_EXPIRE_DAYS) -> Callable[[date], None]:
    """하루 한 번 작업: 만든 지 `days`일이 지난 초안을 조용히 `dropped`로 바꾼다(알리지 않음, 스펙 5.7)."""

    def job(today: date) -> None:
        ids = tasks.expire_drafts(clock.now() - timedelta(days=days))
        log.info("drafts_expired", extra={"count": len(ids)})

    job.__name__ = "expire_drafts"
    return job


def backup_daily(conn: sqlite3.Connection, backups_dir: Path, *, keep: int) -> Callable[[date], None]:
    """하루 한 번 작업: DB 백업(스펙 7). 백업이 안 돼도 예외 종류만 남기고 tick은 그대로 간다."""

    def job(today: date) -> None:
        try:
            made = daily_backup(conn, backups_dir, today, keep)
        except Exception as e:  # noqa: BLE001 - 경로와 메시지 없이 종류만 남긴다
            log.warning("backup_error", extra={"error_type": type(e).__name__})
            return
        log.info("backup_done" if made is not None else "backup_exists", extra={"date": today.isoformat()})

    job.__name__ = "daily_backup"
    return job


def cleanup_logs_daily(log_dir: Path, *, keep: int) -> Callable[[date], None]:
    """하루 한 번 작업: 회전된 로그는 최근 `keep`일 치만 남긴다(스펙 7, 30일 보관)."""

    def job(today: date) -> None:
        log.info("logs_cleaned", extra={"count": cleanup_logs(log_dir, keep)})

    job.__name__ = "cleanup_logs"
    return job


UPDATE_KEEP_DAYS = 2


def prune_updates_daily(
    state: StateRepo, clock: Clock, *, days: int = UPDATE_KEEP_DAYS
) -> Callable[[date], None]:
    """하루 한 번 작업: 처리한 지 `days`일이 지난 `update_id`를 지운다(`received_at` 기준)."""

    def job(today: date) -> None:
        count = state.prune_updates(clock.now() - timedelta(days=days))
        log.info("updates_pruned", extra={"count": count})

    job.__name__ = "prune_updates"
    return job


def recover_on_start(runs: RunsRepo, dispatcher: RecoveryTarget, clock: Clock, settings: Settings) -> None:
    """시작 시 복구(스펙 5.1 4단계). 디스패처를 시작하기 전, 첫 tick 전에 부른다.

    `queued`나 `running`으로 남은 회차는 `interrupted`로 바꾸고 재실행 규칙(스펙 5.4-3)을 적용한다.
    합쳐진 회차(primary의 `merged_run_ids`)는 primary를 따른다. 도구 이벤트도 primary에 붙는다.
    - 본문(`outbound_text`)이 이미 저장됐으면 두뇌 단계는 끝났다: `failed`로 두고 전송만 다시 한다(아래).
    - 도구 이벤트가 있으면 다시 실행하지 않고 `failed`(로그만).
    - 한계 밖이거나 두뇌 실행이 이미 2회면 `interrupted`로 둔다.
    - 그 밖에는 한 번 다시 실행한다. 멈출 때 함께 처리하던 회차라 같은 tick의 회차처럼 하나로 합친다.
      큐에서 꺼낼 때 디스패처가 한계, 멈춤, 하루 상한, 사용 한도를 다시 본다.
    `failed`이면서 본문이 있고 아직 다시 보내지 않은 회차는 전송만 한 번 다시 한다(답장 창은 디스패처가 본다).
    """
    tz, boundary = settings.timezone, settings.day_boundary
    now = clock.now()
    left = runs.with_status(RunStatus.queued, RunStatus.running)
    left_ids = {r.id for r in left}
    owner = {m: r.id for r in left for m in r.merged_run_ids if m in left_ids and m != r.id}
    for run in left:
        runs.mark_interrupted(run.id)
        log.info("run_interrupted", extra={"run_id": run.id, "was": run.status.value})

    def past_limit(run: Run) -> bool:
        return now > limit_for(_due(run), settings, tz, boundary)

    fate: dict[int, str] = {}
    for run in left:
        if run.id in owner:
            continue
        if run.outbound_text:
            fate[run.id] = "resend"
        elif runs.has_tool_events(run.id):  # 도구가 이미 데이터를 바꿨다(중복 쓰기 방지)
            fate[run.id] = "failed"
            log.warning("run_interrupted_with_tool_events", extra={"run_id": run.id})
        elif run.attempt >= MAX_RUN_ATTEMPTS or past_limit(run):
            fate[run.id] = "keep"
        else:
            fate[run.id] = "rerun"
    by_id = {r.id: r for r in left}
    for member, primary in owner.items():
        if fate[primary] == "keep":
            # primary를 다시 실행하지 않으면 멤버는 따로 본다: 자기 한계 안이면 pending으로 되돌려 첫 tick이
            # 다시 판정하고(R1, 합치기), 한계 밖이면 skipped(late)
            fate[member] = "late" if past_limit(by_id[member]) else "pending"
        else:
            fate[member] = fate[primary]
    # 공백이 24시간 이상이면 바로 다시 실행하지 않고 pending으로 되돌린다. 첫 tick이 R1로 판정해
    # 복귀 인사 하나만 보내고 회고는 다음 정규 연락에 넘긴다(연달아 두 통 보내지 않는다)
    last_seen = dispatcher.state.get("last_seen_at")
    if last_seen is not None and now - from_iso(last_seen) >= RETURN_GAP:
        fate = {i: ("pending" if f == "rerun" else f) for i, f in fate.items()}
    # 넘겨 받은 회고(R1)는 혼자 실행하지 않는다. 표시가 남은 채 큐에 있었으면(계획 모드 되돌리기 도중 멈춤)
    # 다시 실행할 수 있을 때 pending으로 되돌리고 표시를 둔다: 다음 tick이 다음 정규 연락에 다시 합친다.
    # 그렇지 않으면 표시를 지운다
    carried = dispatcher.state.get(CARRY_REVIEW_KEY)
    carried_id = int(carried) if carried else None
    # 합쳐진 멤버여도 같다(러너는 합칠 때 표시를 지우지 않는다). primary를 다시 실행하든 아니든 회고는 빼서
    # pending으로 되돌린다. primary 본문을 다시 보내는 경우(resend)는 회고도 그 본문에 들어 있으니 따라가고,
    # 보내면 디스패처가 표시를 지운다
    if carried_id in fate:
        f = fate[carried_id]
        if f in ("rerun", "pending"):
            fate[carried_id] = "carry"
        elif f != "resend":
            dispatcher.state.set(CARRY_REVIEW_KEY, None)

    reruns: list[Run] = []
    for run in left:
        f = fate[run.id]
        if f in ("resend", "failed"):
            runs.mark_failed(run.id, "interrupted")
        elif f == "keep":
            log.info("run_interrupted_not_rerun", extra={"run_id": run.id})
        elif f == "carry":
            runs.mark_pending(run.id)
            log.info("carried_review_back_to_pending", extra={"run_id": run.id})
        elif f == "pending":
            runs.mark_pending(run.id)
            log.info("run_back_to_pending", extra={"run_id": run.id})
        elif f == "late":
            runs.mark_skipped(run.id, SkipReason.late)
            log.info("run_skipped_late_on_start", extra={"run_id": run.id})
        else:
            reruns.append(run)
    if reruns:
        reruns.sort(key=lambda r: merge_order(r.loop))
        dispatcher.submit_run(runs.get(reruns[0].id), [runs.get(r.id) for r in reruns[1:]])
        log.info("runs_rerun_on_start", extra={"run_ids": [r.id for r in reruns]})
    for run in runs.with_status(RunStatus.failed):
        if run.outbound_text and not run.resent:
            dispatcher.submit_resend(run)
            log.info("run_resend_on_start", extra={"run_id": run.id})


INBOUND_MAX_ATTEMPTS = 3  # 시작 때 다시 넣는 횟수 상한. 넘으면 inbound_dropped


def resubmit_inbound(state: StateRepo, dispatcher: MessageSubmitter) -> int:
    """시작 시 복구 다음 단계: 받았지만 답하지 못한 메시지(`inbound_pending`)를 받은 순서대로 다시 넣는다.

    본문은 저장해 둔 가린 글이다(가린 정보는 두뇌도 다시 받지 못한다). 받은 시각과 보낸 시각은 처음 그대로라,
    6시간보다 오래된 메시지는 "몇 시간 전" 알림을 붙여 넘긴다. 답을 보내면 처리 완료로 기록하면서 행을 지운다.
    넣을 때마다 `attempts`를 1 올리고, 이미 3회 넣은 행은 버린다(`inbound_dropped`). 다시 넣은 것만 센다.
    """
    submitted: list[int] = []
    for row in state.pending_inbound():
        if row.attempts >= INBOUND_MAX_ATTEMPTS:
            # 시작할 때마다 다시 넣어도 끝내 답하지 못했다. 버리고 이유만 남긴다(본문 없이)
            state.drop_pending_inbound(row.update_id)
            log.warning(
                "inbound_dropped",
                extra={"update_id": row.update_id, "reason": "max_attempts", "attempts": row.attempts},
            )
            continue
        state.bump_inbound_attempts(row.update_id)
        dispatcher.submit_message(
            Inbound(text=row.text, at=row.received_at, sent_at=row.sent_at, update_ids=[row.update_id], recovered=True)
        )
        submitted.append(row.update_id)
    if submitted:
        log.info("inbound_resubmitted_on_start", extra={"update_ids": submitted})
    return len(submitted)


class MessageSubmitter(Protocol):
    def submit_message(self, m: Inbound) -> None: ...


class RunSubmitter(Protocol):
    def submit_run(self, run: Run, merged: list[Run], *, carried_ids: Iterable[int] = ()) -> None: ...


class RecoveryTarget(RunSubmitter, Protocol):
    state: StateRepo

    def submit_resend(self, run: Run) -> None: ...


class Runner:
    def __init__(
        self,
        *,
        clock: Clock,
        settings: Settings,
        runs: RunsRepo,
        state: StateRepo,
        dispatcher: RunSubmitter,
        router: ConversationRouter | None = None,
        loops: frozenset[LoopKey] = ENABLED_LOOPS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_resume: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.clock = clock
        self.router = router
        self.settings = settings
        self.runs = runs
        self.state = state
        self.dispatcher = dispatcher
        self.loops = loops
        self._daily: list[Callable[[date], None]] = []
        self._sleep = sleep
        self._on_resume = on_resume
        self._ticked = False  # 이 프로세스에서 tick을 한 번이라도 했는가
        self._polling_down = False  # 폴링 재시작이 안 됐다: tick마다 다시 해 본다

    def register_daily(self, job: Callable[[date], None]) -> None:
        """하루 한 번 작업. 논리적 날짜가 바뀐 뒤 첫 tick 끝에서 등록 순서대로 부른다."""
        self._daily.append(job)

    def _get_time(self, key: str) -> datetime | None:
        v = self.state.get(key)
        return from_iso(v) if v else None

    def _carried_review(self) -> Run | None:
        """`app_state.carry_review_run_id`가 가리키는, 아직 pending인 회고 회차.

        queued면 표시를 남겨 두고 None이다(계획 모드로 pending에 되돌아가는 중일 수 있다).
        """
        v = self.state.get(CARRY_REVIEW_KEY)
        if not v:
            return None
        run = self.runs.get(int(v))
        if run is not None and run.status is RunStatus.queued:
            return None
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
                await self._resume_if_slept()
            except Exception:  # 복귀 판정이 안 돼도 tick은 돈다
                log.exception("resume_check_error")
            try:
                self.tick()
            except Exception:  # tick 하나가 안 돼도 루프는 계속 돈다
                log.exception("tick_error")

    async def _resume_if_slept(self) -> None:
        """tick을 시작할 때 이전 `last_seen_at`과 지금의 차이가 3분을 넘으면 `on_resume`을 부른다(폴링 재시작).

        프로세스를 시작한 뒤 첫 tick에는 부르지 않는다(첫 tick은 따라잡기만 한다). R1(24시간 이상)과 따로다:
        따라잡기 판정은 tick이 그대로 한다. 시계가 뒤로 갔으면(차이가 음수) 부르지 않는다.
        `on_resume`이 안 되면(복귀 직후 네트워크 없음) polling_down으로 두고, 될 때까지 tick마다 공백과
        상관없이 다시 부른다.
        """
        if self._on_resume is None or not self._ticked:
            return
        if not self._polling_down:
            last_seen = self._get_time("last_seen_at")
            if last_seen is None:
                return
            gap = self.clock.now() - last_seen
            if gap <= RESUME_GAP:
                return
            log.info("resume_detected", extra={"gap_seconds": int(gap.total_seconds())})
        try:
            await self._on_resume()
        except Exception as e:  # noqa: BLE001 - 종류만 남긴다. 다음 tick에 다시 해 본다
            self._polling_down = True
            log.warning("polling_down", extra={"error_type": type(e).__name__})
            return
        if self._polling_down:
            self._polling_down = False
            log.info("polling_recovered")

    def tick(self) -> None:
        self._ticked = True
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
        # 3. 만료된 대화를 닫고(chat 30분, plan 2시간), 따라잡기 판정과 적용
        if self.router is not None:
            self.router.close_expired()
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
            plan_open=self.router is not None and self.router.plan_open(),
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
        if carried_due is not None and any(d == carried_due for d, _ in decision.skipped):
            self.state.set(CARRY_REVIEW_KEY, None)  # late가 됐다
        # 합쳐졌으면 표시를 둔다: 그 작업이 끝날 때(보냄, 같이 건너뜀) 디스패처가 지운다. 도중에 멈춰도
        # 시작 시 복구가 표시를 보고 회고를 넘겨 받은 회고로 되돌린다(혼자 실행하지 않는다)
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

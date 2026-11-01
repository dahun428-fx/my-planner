"""진입점: 창 숨김, 단일 실행 잠금, 로그, DB, 조립, 폴링, 종료 (스펙 5.1).

`[runtime] role = "dev"`(릴리스 흐름 스펙 5.2)이면 텔레그램 앱·폴링을 띄우지 않고 보내기는 로그로만 남긴다.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hmac
import logging
import os
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, ExitStack, nullcontext
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from aiohttp import web
from pydantic import ValidationError
from telegram import Bot, CallbackQuery

from my_planner.api.health import ErrorCounter
from my_planner.api.server import ApiDeps, build_app, start_api, stop_api
from my_planner.bot.callbacks import handle_callback
from my_planner.bot.telegram_io import (
    DisabledTelegramSender,
    TelegramSender,
    build_application,
)
from my_planner.clock import Clock, SystemClock, logical_date, to_iso
from my_planner.config import (
    API_TOKEN_MIN_CHARS,
    PathsConfig,
    RetentionConfig,
    Settings,
    load_settings,
    resolve_root,
)
from my_planner.domain import ConversationKind, LoopKey, RunContext
from my_planner.harness.brain import Brain, ClaudeBrain, set_start_timeout
from my_planner.harness.conversations import ConversationRouter
from my_planner.harness.delivery import Delivery, PushSender, WebPushSender
from my_planner.harness.dispatcher import Dispatcher, Outbound, Sender
from my_planner.harness.moments import claude_config_dir as default_claude_config_dir
from my_planner.harness.stream import AppReplySender
from my_planner.logging_setup import setup_logging
from my_planner.loop.runner import (
    Runner,
    backup_daily,
    cleanup_logs_daily,
    expire_curve_drafts,
    expire_drafts,
    grant_rest_days_daily,
    memos_daily,
    prune_api_state_daily,
    prune_records_daily,
    prune_updates_daily,
    queue_moments_daily,
    recover_on_start,
    reerase_deleted_daily,
    resubmit_inbound,
    retry_summaries_daily,
    standing_daily,
)
from my_planner.platform.windows import (
    AlreadyRunning,
    SingleInstanceLock,
    hide_console,
    keep_awake,
)
from my_planner.store.db import integrity_ok, migrate, open_db, open_ro
from my_planner.store.photos import PhotoFiles
from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo, IdempotencyRepo
from my_planner.store.repos.agents import AgentsRepo
from my_planner.store.repos.body import BodyRepo
from my_planner.store.repos.cards import CardsRepo
from my_planner.store.repos.channels import DeliveriesRepo
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.events import EventsRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.memos import MemosRepo
from my_planner.store.repos.moments import MomentsRepo
from my_planner.store.repos.photos import PhotosRepo
from my_planner.store.repos.push import PushRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.standing import StandingRepo
from my_planner.store.repos.state import StateRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.repos.workout import WorkoutRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

LOCK_FILE = "my-planner.lock"
DB_FILE = "planner.db"
INTEGRITY_NOTICE_MARKER = "integrity_notice_sent"
INTEGRITY_NOTICE = "데이터베이스에 문제가 있어요. 최신 백업으로 복구해야 해요. PC에서 README의 복구 절차를 따라 주세요."
BACKUPS_DIR = "backups"
SHUTDOWN_TIMEOUT_S = 30

ALLOWED_UPDATES = ["message", "callback_query"]

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_BAD_SETTINGS = 2
EXIT_ALREADY_RUNNING = 3


def main() -> int:
    # 0. 창 숨김: 잠금보다 먼저. 결과는 로그 설정 뒤에 남긴다.
    console = hide_console()
    root = resolve_root()
    state_dir = PathsConfig.for_root(root).state_dir
    with ExitStack() as stack:
        # 1. 단일 실행 잠금
        try:
            stack.enter_context(SingleInstanceLock(state_dir / LOCK_FILE))
        except AlreadyRunning:
            return EXIT_ALREADY_RUNNING
        return _run_locked(root, console)
    return EXIT_FATAL  # pragma: no cover (ExitStack가 예외를 삼키지 않는다)


def _run_locked(root: Path, console: str) -> int:
    try:
        settings = load_settings(root)
    except (ValidationError, ValueError, OSError) as e:
        setup_logging(PathsConfig.for_root(root).state_dir, RetentionConfig().log_days)
        fields = (
            [".".join(str(p) for p in err["loc"]) for err in e.errors()]
            if isinstance(e, ValidationError)
            else []
        )
        log.error("settings_invalid", extra={"error_type": type(e).__name__, "fields": fields})
        return EXIT_BAD_SETTINGS

    # 2. 로그 설정
    setup_logging(settings.paths.state_dir, settings.retention.log_days)
    log.info("starting", extra={"pid": os.getpid(), "console": console, "root": str(settings.paths.root)})
    if console == "unavailable":
        log.warning("console_hide_unavailable")
    log.info("runtime_role", extra={"role": settings.runtime.role})

    try:
        asyncio.run(_serve(settings))
    except KeyboardInterrupt:
        log.info("stopped_by_ctrl_c")
    except Exception:
        log.exception("fatal_error")
        return EXIT_FATAL
    log.info("stopped")
    return EXIT_OK


def _open_checked(path: Path) -> sqlite3.Connection | None:
    """DB를 열고 무결성을 본다(`PRAGMA quick_check`). 손상됐으면 None. 파일이 없으면 새로 설치한 것이다.

    손상은 quick_check가 "ok"가 아니거나, `OperationalError`가 아닌 `DatabaseError`("file is not a database"
    같은)일 때만이다. 디스크 I/O, 잠금, 열기 오류(`OperationalError`)는 그대로 올린다: 안전 모드에 들어가지
    않고 끝나서 워치독이 다시 띄운다(건강한 DB를 백업으로 덮지 않게).
    """
    fresh = not path.exists()
    conn: sqlite3.Connection | None = None
    try:
        conn = open_db(path)
        if fresh or integrity_ok(conn):
            return conn
        log.error("db_integrity_failed")
    except sqlite3.OperationalError:
        if conn is not None:
            conn.close()
        raise
    except sqlite3.DatabaseError as e:
        log.error("db_corrupt", extra={"error_type": type(e).__name__})
    if conn is not None:
        conn.close()
    return None


async def enter_safe_mode(state_dir: Path, sender: Sender) -> None:
    """안전 모드(스펙 5.1 3단계): 표식 파일이 없을 때만 알림을 한 번 보내고, 폴링과 tick 없이 기다린다.

    알림이 안 가면 표식을 만들지 않는다(다음 시작 때 다시 보낸다). 자동 복구는 하지 않는다.
    프로세스가 살아 있어야 작업 스케줄러가 계속 다시 띄우지 않는다.
    """
    log.error("safe_mode")
    marker = Path(state_dir) / INTEGRITY_NOTICE_MARKER
    if not marker.exists():
        try:
            await sender.send(Outbound(text=INTEGRITY_NOTICE))
        except Exception as e:  # noqa: BLE001 - 본문 없이 종류만 남긴다
            log.warning("integrity_notice_error", extra={"error_type": type(e).__name__})
        else:
            marker.write_text(to_iso(SystemClock().now()), encoding="utf-8")
            log.info("integrity_notice_sent")
    await _wait_for_shutdown()


@dataclass
class BeParts:
    """조립한 BE 부품. `_serve`와 시험(`tests/be_env.py BeEnv`)이 같은 조립을 쓴다."""

    state: StateRepo
    convs: ConversationsRepo
    runs: RunsRepo
    tasks: TasksRepo
    conditions: ConditionsRepo
    transcripts: TranscriptStore
    tools: Tools
    router: ConversationRouter
    dispatcher: Dispatcher
    runner: Runner
    sender: Sender
    deliveries: DeliveriesRepo
    callbacks: Callable[[CallbackQuery], Awaitable[str]]
    activity: ActivityRepo
    idempotency: IdempotencyRepo
    confirms: ConfirmsRepo
    delivery: Delivery
    pushes: PushRepo
    curve: CurveRepo
    status: StatusRepo
    habits: HabitsRepo | None = None  # 습관(SP7)
    moments: MomentsRepo | None = None  # 이룬 순간(SP8)
    body: BodyRepo | None = None  # 몸 기록(SP8 7장)
    memos: MemosRepo | None = None  # 메모(SP9 6장)
    events: EventsRepo | None = None  # 스케줄(SP9 5장)
    agents: AgentsRepo | None = None  # 사건 기록·받은편지함·관찰(SP14 5장)


def build_be(
    settings: Settings,
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    brain_factory: Callable[[Tools], Brain],
    sender_factory: Callable[[TasksRepo], Sender],
    on_resume: Callable[[], Awaitable[None]] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    keep_awake: Callable[[], AbstractContextManager[Any]] = nullcontext,
    push_sender: PushSender | None = None,
    claude_config_dir: Path | None = None,
) -> BeParts:
    """저장소, 도구, 두뇌, 디스패처, 러너, 버튼 처리기를 조립한다(텔레그램 앱과 API는 밖에서 붙인다).

    `push_sender`: 웹 푸시 전송(시험은 가짜). 없으면 VAPID가 있을 때 `WebPushSender`. VAPID가 없으면 푸시는 꺼진다.
    `claude_config_dir`: 하루 끝 순간 호출 뒤 세션 파일을 지울 CLI 설정 폴더(SP8 6.3). None이면 지우지 않는다(시험).
    """
    paths = settings.paths
    state = StateRepo(conn, clock)
    convs = ConversationsRepo(conn, clock)
    runs = RunsRepo(conn, clock)
    conditions = ConditionsRepo(conn, clock)
    deliveries = DeliveriesRepo(conn, clock)
    activity = ActivityRepo(conn, clock)
    idempotency = IdempotencyRepo(conn, clock)
    confirms = ConfirmsRepo(conn, clock)
    transcripts = TranscriptStore(paths.data_dir, settings.timezone, settings.day_boundary)
    tasks = TasksRepo(conn, clock, tz=settings.timezone, boundary=settings.day_boundary)
    sender = sender_factory(tasks)
    pushes = PushRepo(conn, clock)
    curve = CurveRepo(conn, clock)
    status = StatusRepo(conn, clock)
    habits = HabitsRepo(conn, clock)
    moments = MomentsRepo(conn, clock)
    memos = MemosRepo(conn, clock)
    photos = PhotosRepo(settings.timezone, settings.day_boundary)
    body = BodyRepo(conn, clock)
    events = EventsRepo(conn, clock, settings.timezone)
    workout = WorkoutRepo(conn, clock)
    agents = AgentsRepo(conn, clock)
    if push_sender is None and settings.vapid is not None:
        push_sender = WebPushSender(settings.vapid)
    # 회차·고정 안내의 통로(7.3 D1~D8). 보내기는 `asyncio.to_thread`, 기록은 이 루프 스레드
    delivery = Delivery(
        telegram=sender, push=push_sender, pushes=pushes, state=state, clock=clock, settings=settings, sleep=sleep,
    )
    tools = Tools(
        tasks=tasks,
        transcripts=transcripts,
        export_path=paths.data_dir / "exports" / "tasks.md",
        clock=clock,
        tz=settings.timezone,
        boundary=settings.day_boundary,
        conditions=conditions,
        activity=activity,
        cards=CardsRepo(conn, clock),  # 고정 카드(앱 대화의 카드 도구, `/actions`, SP3-4 10장)
        # 회차 차례의 확인(SP3-4 10.1): 토큰 만료는 그 회차 답장 창 끝(합친 회차는 가장 늦은 끝)
        confirms=confirms,
        reply_until=lambda run_id: _reply_until(runs, settings, run_id),
        # 인생 곡선(SP3-4 10장): 쓰기는 즉시 갈래와 두뇌 도구로만. 기간 기본값은 회고 회차의 대화면 그 회고 날짜
        curve=curve,
        status=status,
        review_date_for=lambda ctx: review_date_for(convs, runs, settings, ctx),
        habits=habits,  # 습관 도구(SP7 5.4), `data/exports/habits.md`(5.8)
        moments=moments,  # 하루 끝 순간 호출의 `save_moments`(SP8 6.3). 내보내기는 없다
        state=state, settings=settings, runs=runs,  # 체크인 시간 바꾸기(SP9 8장)
        memos=memos,  # 메모 도구·동작(SP9 6장). `memos.md`는 하루 한 번 작업이 쓴다
        body=body,  # 몸 기록(SP8 7장): `POST /body`의 `record_body_days`, 56일 정리(`prune_records`)
        events=events,  # 스케줄 도구·동작(SP9 5장), 앞머리 `## 오늘 일정`
        conversations=convs,  # `find_conversations`(SP9 7.5): 제목·요약만
        # 사진(SP10 5.1·5.2): 바이트는 `data/photos/`에만
        photos=photos, photo_files=PhotoFiles(paths.data_dir / "photos"),
        workout=workout,  # 운동메이트 도구·동작(SP12 6~8장), 메이트 앞머리(5.5)
        standing=StandingRepo(conn, clock),  # 측정값 확인 카드·저장(SP13 6.5), 영역 점수 기록의 스냅숏
        agents=agents,  # 쓰기 경로마다 사건 한 줄(SP14 5.1~5.3)
    )
    brain = brain_factory(tools)
    # 디스패처, 러너(계획 모드 대기, 만료된 대화 닫기), /plan /done이 같은 대화 규칙을 쓴다
    router = ConversationRouter(convs, runs, clock=clock, settings=settings)
    dispatcher = Dispatcher(
        brain=brain,
        sender=sender,
        convs=convs,
        state=state,
        transcripts=transcripts,
        clock=clock,
        settings=settings,
        router=router,
        tools=tools,
        runs=runs,
        conditions=conditions,
        data_dir=paths.data_dir,
        keep_awake=keep_awake,
        sleep=sleep,
        deliveries=deliveries,
        activity=activity,
        idempotency=idempotency,
        confirms=confirms,
        app_sender=AppReplySender(),  # 앱 답(`POST /chat`의 스트림, SP3-4 7.5 M4)
        delivery=delivery,
        claude_config_dir=claude_config_dir,
    )
    runner = Runner(
        clock=clock, settings=settings, runs=runs, state=state, dispatcher=dispatcher, router=router,
        on_resume=on_resume, sleep=sleep, checkins=settings.runtime.role == "prod",  # dev는 회차·따라잡기 끔
        events=events, reminder_delivery=delivery,  # 일정 알림 1분 tick(SP9 5.3): 두뇌 없이 주 통로로
        summaries=dispatcher,  # 닫힌 앱 대화의 요약 큐(SP9 7.2)
    )
    # 제안한 지 limits.draft_ttl_days(기본 3일) 지난 초안은 조용히 dropped. 하루 한 번 작업은 즉시 갈래로(4.3)
    runner.register_daily(expire_drafts(dispatcher, clock, days=settings.limits.draft_ttl_days))
    # 사건·챕터 초안은 draft_since에서 같은 일수가 지나면 행을 지운다(SP3-4 5.4)
    runner.register_daily(expire_curve_drafts(dispatcher, clock, days=settings.limits.draft_ttl_days))
    runner.register_daily(grant_rest_days_daily(dispatcher))  # X9 쉬는 날(어제까지, 최대 14일)
    runner.register_daily(prune_api_state_daily(dispatcher))  # 확인 토큰 만료·7일 정리, api_idempotency 2일
    runner.register_daily(prune_records_daily(dispatcher))  # 60일 지난 status_moment_days(SP8 6.4)
    runner.register_daily(memos_daily(dispatcher))  # 30일 지난 지운 메모 완전 삭제, memos.md(SP9 6.1)
    runner.register_daily(standing_daily(dispatcher))  # 지난 분기 위치 스냅숏 따라잡기(SP13)
    # 하루 끝 이룬 순간: 정리할 날을 골라 디스패처에 가장 낮은 차례로(SP8 6.2). 두뇌는 디스패처가 부른다
    runner.register_daily(queue_moments_daily(dispatcher, moments, state))
    runner.register_daily(retry_summaries_daily(dispatcher))  # 요약이 안 된 최근 7일의 앱 대화(SP9 7.2)
    runner.register_daily(reerase_deleted_daily(dispatcher))  # 최근 30일 안에 지운 대화의 원문 다시 지우기(SP9 7.7)
    runner.register_daily(backup_daily(conn, paths.state_dir / BACKUPS_DIR, keep=settings.retention.backup_count))
    runner.register_daily(prune_updates_daily(state, clock))  # 처리한 update_id는 2일 뒤 지운다
    runner.register_daily(cleanup_logs_daily(paths.state_dir / "logs", keep=settings.retention.log_days))
    # 버튼 누름: 두뇌를 거치지 않고 즉시 갈래(`apply_action`)로 바꾼다(스펙 5.7, SP3-4 4.3)
    callbacks = functools.partial(
        handle_callback,
        owner_id=settings.owner_telegram_id,
        tools=tools,
        transcripts=transcripts,
        clock=clock,
        router=router,
        apply=dispatcher.apply_action,
        deliveries=deliveries,
        mark_answered=dispatcher.mark_answered,
        confirms=confirms,  # 회차 차례의 확인 버튼 `k:`(SP3-4 10.1 A5)
        review=dispatcher.review_flow,  # 회고 단계의 사다리 버튼 `l:`와 컨디션 다음 1단계(SP3-4 11.1)
        runs=runs,  # 습관 버튼 다시 그리기: 앱에서 먼저 답한 회차 메시지는 다시 그리지 않는다(SP7 5.7)
    )
    return BeParts(
        state=state, convs=convs, runs=runs, tasks=tasks, conditions=conditions, transcripts=transcripts,
        tools=tools, router=router, dispatcher=dispatcher, runner=runner, sender=sender, deliveries=deliveries,
        callbacks=callbacks, activity=activity, idempotency=idempotency, confirms=confirms, delivery=delivery,
        pushes=pushes, curve=curve, status=status, habits=habits, moments=moments, memos=memos, body=body,
        events=events, agents=agents,
    )


def review_date_for(convs: ConversationsRepo, runs: RunsRepo, settings: Settings, ctx: RunContext) -> date | None:
    """곡선 도구의 기간 기본값(SP3-4 10장): 지금 대화가 회차 대화이고 그 회차(합친 회차 포함)에 주간 회고가 있으면
    그 회고 `scheduled_for`의 논리적 날짜. R1로 넘겨 받은 회고는 합친 회차에 들어 있어 원래 날짜가 나온다."""
    conv = convs.get(ctx.conversation_id) if ctx.conversation_id is not None else None
    if conv is None or conv.kind is not ConversationKind.run or conv.run_id is None:
        return None
    run = runs.get(conv.run_id)
    if run is None:
        return None
    group = [run, *(r for i in run.merged_run_ids if (r := runs.get(i)) is not None)]
    review = next((r for r in group if r.loop is LoopKey.review), None)
    if review is None:
        return None
    return logical_date(review.scheduled_for, settings.timezone, settings.day_boundary)


def _reply_until(runs: RunsRepo, settings: Settings, run_id: int) -> datetime:
    from my_planner.harness.checkins import reply_until

    run = runs.get(run_id)
    assert run is not None, "회차 차례의 회차가 있어야 한다"
    return reply_until(run, runs=runs, settings=settings)


def _bot_token(settings: Settings) -> str:
    assert settings.telegram_bot_token is not None, "role = prod에는 텔레그램 토큰이 있다(설정 검증)"
    return settings.telegram_bot_token.get_secret_value()


def _owner(settings: Settings) -> int:
    assert settings.owner_telegram_id is not None, "role = prod에는 OWNER_TELEGRAM_ID가 있다(설정 검증)"
    return settings.owner_telegram_id


def _api_token(settings: Settings) -> str | None:
    """API를 열 토큰. 꺼져 있으면 None, 없거나 43자 미만이면 경고를 남기고 None(계획 빈 곳 4). 값은 남기지 않는다."""
    if not settings.api.enabled:
        return None
    token = settings.api_token.get_secret_value() if settings.api_token is not None else ""
    if len(token) < API_TOKEN_MIN_CHARS:
        log.warning("api_token_missing", extra={"reason": "too_short" if token else "missing"})
        return None
    return token


def _body_token(settings: Settings, api_token: str) -> str | None:
    """`POST /body`를 열 토큰(SP8 7.2). 없거나 43자 미만이거나 `API_TOKEN`과 같으면 경고 한 줄을 남기고 None: 그 경로만
    열지 않는다(다른 경로는 그대로). 값은 남기지 않는다."""
    token = settings.body_token.get_secret_value() if settings.body_token is not None else ""
    reason = None
    if not token:
        reason = "missing"
    elif len(token) < API_TOKEN_MIN_CHARS:
        reason = "too_short"
    elif hmac.compare_digest(token.encode("utf-8"), api_token.encode("utf-8")):
        reason = "same_as_api"
    if reason is not None:
        log.warning("body_token_missing", extra={"reason": reason})
        return None
    return token


async def _open_api(
    settings: Settings,
    clock: Clock,
    errors: ErrorCounter,
    *,
    read_conn: Callable[[], sqlite3.Connection] | None,
    dispatcher: Dispatcher | None,
    polling_state: Callable[[], str],
    transcripts: TranscriptStore | None = None,
    safe_mode: bool = False,
) -> web.AppRunner | None:
    """설정과 토큰이 맞으면 API를 연다. 못 열어도(꺼짐, 토큰 없음, 포트 사용 중) 텔레그램과 루프는 계속 돈다."""
    token = _api_token(settings)
    if token is None:
        return None
    deps = ApiDeps(
        settings=settings, clock=clock, token=token, read_conn=read_conn, dispatcher=dispatcher, errors=errors,
        polling_state=polling_state, started_at=errors.started_at, transcripts=transcripts, safe_mode=safe_mode,
        body_token=_body_token(settings, token),
    )
    try:
        return await start_api(build_app(deps), settings.api.host, settings.api.port)
    except Exception:  # BE 핵심(텔레그램, 루프)이 API 때문에 멈추지 않는다(스펙 15). 포트 문제는 start_api가 본다
        log.exception("api_start_error")
        return None


async def _serve(settings: Settings) -> None:
    # 오류 수(GET /health의 errors)는 프로세스 시작부터 센다. 메모리에만 둔다
    clock = SystemClock()
    errors = ErrorCounter(clock)
    logging.getLogger().addHandler(errors)
    try:
        await _serve_counted(settings, clock, errors)
    finally:
        logging.getLogger().removeHandler(errors)


async def _serve_counted(settings: Settings, clock: Clock, errors: ErrorCounter) -> None:
    paths = settings.paths
    db_path = paths.state_dir / DB_FILE
    # 3. DB 열기, 무결성 검사, 마이그레이션. 검사가 실패하면 안전 모드(API는 /health만)
    checked = _open_checked(db_path)
    dev = settings.runtime.role == "dev"  # 텔레그램 없음: Bot·앱·폴링을 만들지 않는다
    if checked is None:
        bot = None if dev else Bot(_bot_token(settings))
        api = await _open_api(
            settings, clock, errors, read_conn=None, dispatcher=None, polling_state=lambda: "stopped", safe_mode=True
        )
        try:
            safe_sender: Sender = DisabledTelegramSender() if bot is None else TelegramSender(bot, _owner(settings))
            await enter_safe_mode(paths.state_dir, safe_sender)
        finally:
            await stop_api(api)
        return
    conn = checked
    try:
        log.info("db_ready", extra={"schema_version": migrate(conn, tz=settings.timezone)})
        # 조립: Sender, Brain, Dispatcher. Bot을 앱보다 먼저 만들어 서로를 기다리지 않게 한다.
        bot = None if dev else Bot(_bot_token(settings))
        restarting: list[asyncio.Task[None]] = []  # 진행 중인 폴링 재시작(종료가 끝날 때까지 기다린다)

        async def _restart() -> None:
            # 지난 재시작이 안 됐으면 이미 멈춰 있다. 멈춘 Updater를 다시 멈추면 RuntimeError라 가드한다
            assert application is not None
            if application.updater.running:
                await application.updater.stop()
            await application.updater.start_polling(allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False)
            log.info("polling_restarted")

        async def restart_polling() -> None:
            # 절전 복귀(직전 tick과 3분 넘게 차이, S5): 롱폴링을 다시 시작한다. 공백(초)은 러너가 로그에 남긴다.
            # 안 되면 예외를 그대로 올린다: 러너가 polling_down으로 두고 tick마다 다시 부른다.
            # 종료가 tick 루프를 취소해도 재시작은 끝까지 마친다(shield). 종료 쪽이 그것을 기다린 뒤 멈춘다.
            # `application`은 아래에서 만든다. 러너는 폴링을 시작한 뒤의 tick에서만 이 함수를 부른다
            task = asyncio.create_task(_restart(), name="polling-restart")
            restarting.append(task)
            task.add_done_callback(restarting.remove)
            await asyncio.shield(task)

        set_start_timeout(settings.brain.start_timeout_s)  # SDK 기본 60초는 느린 첫 실행에서 넘친다
        parts = build_be(
            settings,
            conn,
            clock,
            brain_factory=lambda tools: ClaudeBrain(
                tools_factory=lambda: tools,
                workdir=paths.state_dir / "brain-workdir",
                max_turns=settings.limits.max_turns,
                cli_path=settings.brain.cli_path,
            ),
            sender_factory=lambda tasks: DisabledTelegramSender() if bot is None else TelegramSender(
                bot, _owner(settings), tasks=tasks, curve=CurveRepo(tasks.conn, clock),
                habits=HabitsRepo(tasks.conn, clock),  # 저녁 체크인의 습관 줄(SP7 5.7)
            ),
            on_resume=None if bot is None else restart_polling,
            keep_awake=keep_awake,
            claude_config_dir=default_claude_config_dir(),  # 순간 호출 뒤 세션 파일 지우기(SP8 6.3, 결정 18)
        )
        runner, dispatcher = parts.runner, parts.dispatcher
        # 4. 남은 회차 복구: queued/running → interrupted와 재실행 규칙, failed 회차는 전송만 한 번 더.
        # 디스패처 큐에 넣어 두고, 6단계에서 디스패처가 시작하면 처리한다
        try:
            recover_on_start(parts.runs, dispatcher, clock, settings)
        except Exception:  # 복구가 안 돼도 시작은 한다(매번 죽으면 워치독이 5분마다 다시 띄우기만 한다)
            log.exception("recovery_error")
        # 4b. 받았지만 답하지 못한 메시지(inbound_pending)를 다시 넣는다. 메시지가 회차보다 먼저 처리된다
        try:
            resubmit_inbound(parts.state, dispatcher, photos=parts.tools.photos)  # 앱 행의 사진도(SP10 5.5)
        except Exception:
            log.exception("inbound_resubmit_error")
        # 5. 첫 실행이면 installed_at 기록
        runner.ensure_installed()
        application = None if bot is None else build_application(
            settings, dispatcher, parts.state, parts.transcripts,
            bot=bot, clock=clock, tools=parts.tools, callbacks=parts.callbacks, router=parts.router,
            apply=dispatcher.apply_action,
        )

        def polling_state() -> str:
            if application is None:
                return "stopped"
            if runner.polling_down:
                return "down"
            return "running" if application.updater.running else "stopped"

        # 6. 첫 tick 판정 → 폴링 시작 → API 열기 → 1분 tick
        async with application if application is not None else contextlib.AsyncExitStack():
            if application is not None:
                await application.start()
            dispatcher.start()
            try:
                runner.tick()
            except Exception:  # 첫 tick이 안 돼도 폴링과 1분 tick은 시작한다
                log.exception("tick_error")
            if application is not None:
                await application.updater.start_polling(allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False)
                log.info("polling_started")
            api = await _open_api(
                settings, clock, errors, read_conn=lambda: open_ro(db_path), dispatcher=dispatcher,
                polling_state=polling_state, transcripts=parts.transcripts,
            )
            ticking = asyncio.create_task(runner.run_forever(), name="runner")
            try:
                await _wait_for_shutdown()
            finally:
                # 종료 순서: tick 멈춤 → API 닫기 → updater.stop → app.stop → dispatcher.stop(30)
                ticking.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticking
                await runner.drain_reminders()  # 보내는 중인 일정 알림을 기다리고, 못 끝낸 것은 failed로(DB를 닫기 전)
                # 진행 중인 폴링 재시작은 끝나기를 기다린다(안 됐어도 종료는 계속). 끝나면 목록에서 빠지므로 복사한다
                for task in list(restarting):  # noqa: PERF101
                    with contextlib.suppress(Exception):
                        await task
                await stop_api(api)
                if application is not None:
                    if application.updater.running:
                        await application.updater.stop()
                    await application.stop()
                await dispatcher.stop(SHUTDOWN_TIMEOUT_S)
    finally:
        conn.close()


async def _wait_for_shutdown() -> None:
    """콘솔의 Ctrl+C(asyncio.run이 작업을 취소한다)까지 기다린다."""
    await asyncio.Event().wait()

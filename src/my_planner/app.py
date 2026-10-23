"""진입점: 창 숨김, 단일 실행 잠금, 로그, DB, 조립, 폴링, 종료 (스펙 5.1)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
import sqlite3
from contextlib import ExitStack
from pathlib import Path

from pydantic import ValidationError
from telegram import Bot

from my_planner.bot.callbacks import handle_callback
from my_planner.bot.telegram_io import TelegramSender, build_application
from my_planner.clock import SystemClock, to_iso
from my_planner.config import (
    PathsConfig,
    RetentionConfig,
    Settings,
    load_settings,
    resolve_root,
)
from my_planner.harness.brain import ClaudeBrain
from my_planner.harness.conversations import ConversationRouter
from my_planner.harness.dispatcher import Dispatcher, Outbound, Sender
from my_planner.logging_setup import setup_logging
from my_planner.loop.runner import (
    Runner,
    backup_daily,
    cleanup_logs_daily,
    expire_drafts,
    prune_updates_daily,
    recover_on_start,
)
from my_planner.platform.windows import (
    AlreadyRunning,
    SingleInstanceLock,
    hide_console,
    keep_awake,
)
from my_planner.store.db import integrity_ok, migrate, open_db
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.state import StateRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

LOCK_FILE = "my-planner.lock"
DB_FILE = "planner.db"
INTEGRITY_NOTICE_MARKER = "integrity_notice_sent"
INTEGRITY_NOTICE = "데이터베이스에 문제가 있어요. 최신 백업으로 복구해야 해요. PC에서 README의 복구 절차를 따라 주세요."
BACKUPS_DIR = "backups"
SHUTDOWN_TIMEOUT_S = 30

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


async def _serve(settings: Settings) -> None:
    paths = settings.paths
    # 3. DB 열기, 무결성 검사, 마이그레이션. 검사가 실패하면 안전 모드
    checked = _open_checked(paths.state_dir / DB_FILE)
    if checked is None:
        bot = Bot(settings.telegram_bot_token.get_secret_value())
        await enter_safe_mode(paths.state_dir, TelegramSender(bot, settings.owner_telegram_id))
        return
    conn = checked
    try:
        log.info("db_ready", extra={"schema_version": migrate(conn)})
        clock = SystemClock()
        state = StateRepo(conn, clock)
        convs = ConversationsRepo(conn, clock)
        runs = RunsRepo(conn, clock)
        conditions = ConditionsRepo(conn, clock)
        transcripts = TranscriptStore(paths.data_dir, settings.timezone, settings.day_boundary)

        # 조립: Sender, Brain, Dispatcher. Bot을 앱보다 먼저 만들어 서로를 기다리지 않게 한다.
        bot = Bot(settings.telegram_bot_token.get_secret_value())
        tasks = TasksRepo(conn, clock, tz=settings.timezone, boundary=settings.day_boundary)
        sender = TelegramSender(bot, settings.owner_telegram_id, tasks=tasks)
        tools = Tools(
            tasks=tasks,
            transcripts=transcripts,
            export_path=paths.data_dir / "exports" / "tasks.md",
            clock=clock,
            tz=settings.timezone,
            boundary=settings.day_boundary,
            conditions=conditions,
        )
        brain = ClaudeBrain(
            tools_factory=lambda: tools,
            workdir=paths.state_dir / "brain-workdir",
            max_turns=settings.limits.max_turns,
        )
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
        )
        runner = Runner(
            clock=clock, settings=settings, runs=runs, state=state, dispatcher=dispatcher, router=router
        )
        runner.register_daily(expire_drafts(tasks, clock))  # 3일 지난 초안은 조용히 dropped
        runner.register_daily(backup_daily(conn, paths.state_dir / BACKUPS_DIR, keep=settings.retention.backup_count))
        runner.register_daily(prune_updates_daily(state, clock))  # 처리한 update_id는 2일 뒤 지운다
        runner.register_daily(cleanup_logs_daily(paths.state_dir / "logs", keep=settings.retention.log_days))
        # 4. 남은 회차 복구: queued/running → interrupted와 재실행 규칙, failed 회차는 전송만 한 번 더.
        # 디스패처 큐에 넣어 두고, 6단계에서 디스패처가 시작하면 처리한다
        try:
            recover_on_start(runs, dispatcher, clock, settings)
        except Exception:  # 복구가 안 돼도 시작은 한다(매번 죽으면 워치독이 5분마다 다시 띄우기만 한다)
            log.exception("recovery_error")
        # 5. 첫 실행이면 installed_at 기록
        runner.ensure_installed()
        # 버튼 누름: 두뇌를 거치지 않고 하네스가 도구 함수를 직접 부른다(스펙 5.7)
        callbacks = functools.partial(
            handle_callback,
            owner_id=settings.owner_telegram_id,
            tools=tools,
            transcripts=transcripts,
            clock=clock,
            router=router,
        )
        application = build_application(
            settings, dispatcher, state, transcripts,
            bot=bot, clock=clock, tools=tools, callbacks=callbacks, router=router,
        )

        # 6. 첫 tick 판정 → 폴링 시작 → 1분 tick
        async with application:
            await application.start()
            dispatcher.start()
            try:
                runner.tick()
            except Exception:  # 첫 tick이 안 돼도 폴링과 1분 tick은 시작한다
                log.exception("tick_error")
            await application.updater.start_polling(
                allowed_updates=["message", "callback_query"], drop_pending_updates=False
            )
            log.info("polling_started")
            ticking = asyncio.create_task(runner.run_forever(), name="runner")
            try:
                await _wait_for_shutdown()
            finally:
                # 종료 순서: tick 멈춤 → updater.stop → app.stop → dispatcher.stop(30)
                ticking.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticking
                await application.updater.stop()
                await application.stop()
                await dispatcher.stop(SHUTDOWN_TIMEOUT_S)
    finally:
        conn.close()


async def _wait_for_shutdown() -> None:
    """콘솔의 Ctrl+C(asyncio.run이 작업을 취소한다)까지 기다린다."""
    await asyncio.Event().wait()

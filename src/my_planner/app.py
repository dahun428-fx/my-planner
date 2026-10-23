"""진입점: 창 숨김, 단일 실행 잠금, 로그, DB, 조립, 폴링, 종료 (스펙 5.1)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
from contextlib import ExitStack
from pathlib import Path

from pydantic import ValidationError
from telegram import Bot

from my_planner.bot.callbacks import handle_callback
from my_planner.bot.telegram_io import TelegramSender, build_application
from my_planner.clock import SystemClock
from my_planner.config import (
    PathsConfig,
    RetentionConfig,
    Settings,
    load_settings,
    resolve_root,
)
from my_planner.harness.brain import ClaudeBrain
from my_planner.harness.conversations import ConversationRouter
from my_planner.harness.dispatcher import Dispatcher
from my_planner.logging_setup import setup_logging
from my_planner.loop.runner import Runner, expire_drafts
from my_planner.platform.windows import (
    AlreadyRunning,
    SingleInstanceLock,
    hide_console,
    keep_awake,
)
from my_planner.store.db import migrate, open_db
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


async def _serve(settings: Settings) -> None:
    paths = settings.paths
    # 3. DB 열기, 마이그레이션
    conn = open_db(paths.state_dir / DB_FILE)
    try:
        log.info("db_ready", extra={"schema_version": migrate(conn)})
        clock = SystemClock()
        state = StateRepo(conn, clock)
        convs = ConversationsRepo(conn, clock)
        runs = RunsRepo(conn, clock)
        conditions = ConditionsRepo(conn, clock)
        transcripts = TranscriptStore(paths.data_dir, settings.timezone, settings.day_boundary)

        # 4. Sender, Brain, Dispatcher. Bot을 앱보다 먼저 만들어 서로를 기다리지 않게 한다.
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
        # (티켓 12: queued/running 회차 복구가 여기 들어온다)
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

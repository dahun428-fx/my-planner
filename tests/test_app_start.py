import asyncio
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


class FakeUpdater:
    """PTB Updater처럼 `running`을 둔다. 멈춘 것을 다시 멈추면 RuntimeError.

    `fail_starts`번까지 `start_polling`이 예외를 내고 `running=False`로 남는다(복귀 직후 네트워크 없음).
    `stop_yields`만큼 양보한 뒤 멈춤을 마친다(롱폴 요청이 끝나기를 기다리는 동안). `running`은 먼저 False가 된다.
    """

    def __init__(self, calls):
        self.calls = calls
        self.running = False
        self.fail_starts = 0
        self.stop_yields = 0
        self.stopping = False

    async def start_polling(self, **kw):
        self.calls.append(("start_polling", kw))
        if self.fail_starts:
            self.fail_starts -= 1
            raise ConnectionError("network down")
        self.running = True

    async def stop(self):
        if not self.running:
            raise RuntimeError("This Updater is not running!")
        self.calls.append(("updater.stop", None))
        self.running = False
        self.stopping = True
        for _ in range(self.stop_yields):
            await asyncio.sleep(0)
        self.stopping = False


class FakeApplication:
    last = None

    def __init__(self, calls):
        self.calls = calls
        self.updater = FakeUpdater(calls)
        FakeApplication.last = self

    async def __aenter__(self):
        self.calls.append(("app.initialize", None))
        return self

    async def __aexit__(self, *exc):
        self.calls.append(("app.shutdown", None))

    async def start(self):
        self.calls.append(("app.start", None))

    async def stop(self):
        self.calls.append(("app.stop", None))


@pytest.fixture
def started(tmp_path, monkeypatch):
    """임시 루트와 가짜 Bot/Application으로 app.main()의 시작 경로만 지나게 한다."""
    from my_planner import app

    root = tmp_path / "root"
    root.mkdir()
    # SP1 시험은 API를 끈 설정으로 돈다(스펙 15 "api.enabled = false면 SP1과 똑같이 돈다"). API 시험은 _enable_api
    toml = (REPO / "config.toml").read_text(encoding="utf-8")
    assert "[api]\nenabled = true\n" in toml
    (root / "config.toml").write_text(toml.replace("[api]\nenabled = true\n", "[api]\nenabled = false\n"), encoding="utf-8")
    (root / ".env").write_text("TELEGRAM_BOT_TOKEN=123:test-token\nOWNER_TELEGRAM_ID=42\n", encoding="utf-8")
    monkeypatch.setenv("MY_PLANNER_ROOT", str(root))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)

    calls = []
    monkeypatch.setattr(app, "Bot", lambda token: object())
    monkeypatch.setattr(
        app,
        "build_application",
        lambda settings, dispatcher, state, transcripts, **kw: FakeApplication(calls),
    )

    async def no_wait():
        calls.append(("serving", None))

    monkeypatch.setattr(app, "_wait_for_shutdown", no_wait)
    return app, root, calls


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt 잠금은 Windows 전용")
def test_second_instance_exits(started):
    from my_planner.platform.windows import SingleInstanceLock

    app, root, calls = started
    with SingleInstanceLock(root / "state" / "my-planner.lock"):
        t0 = time.monotonic()
        assert app.main() == app.EXIT_ALREADY_RUNNING
        assert time.monotonic() - t0 < 5
    assert calls == []  # 두 번째는 폴링까지 가지 않는다
    assert app.main() == 0  # 잠금이 풀리면 다시 뜬다


def _log_entries(root):
    import json
    import logging

    for h in logging.getLogger().handlers:
        h.flush()
    path = root / "state" / "logs" / "my-planner.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_main_hides_console_first(started, monkeypatch):
    app, root, calls = started
    order = []

    def fake_hide():
        order.append("hide_console")
        return "unavailable"

    class FakeLock:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            order.append("lock")
            return self

        def __exit__(self, *exc):
            order.append("unlock")

    real_setup = app.setup_logging

    def spy_setup(state_dir, keep_days):
        order.append("logging")
        return real_setup(state_dir, keep_days)

    monkeypatch.setattr(app, "hide_console", fake_hide)
    monkeypatch.setattr(app, "SingleInstanceLock", FakeLock)
    monkeypatch.setattr(app, "setup_logging", spy_setup)

    real_stop = app.Dispatcher.stop

    async def spy_stop(self, timeout=30):
        calls.append(("dispatcher.stop", timeout))
        await real_stop(self, timeout)

    monkeypatch.setattr(app.Dispatcher, "stop", spy_stop)

    assert app.main() == 0
    assert order == ["hide_console", "lock", "logging", "unlock"]

    warnings = [e for e in _log_entries(root) if e["level"] == "WARNING"]
    assert [w["msg"] for w in warnings] == ["console_hide_unavailable"]

    # 폴링 시작 인자와 종료 순서(스펙 5.1): updater.stop → app.stop → dispatcher.stop(30) → shutdown
    names = [c[0] for c in calls]
    assert names == [
        "app.initialize",
        "app.start",
        "start_polling",
        "serving",
        "updater.stop",
        "app.stop",
        "dispatcher.stop",
        "app.shutdown",
    ]
    assert ("dispatcher.stop", 30) in calls
    assert calls[2][1] == {"allowed_updates": ["message", "callback_query"], "drop_pending_updates": False}
    assert (root / "state" / "planner.db").exists()


def test_logging_survives_none_stderr(started, monkeypatch):
    app, root, calls = started
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdout", None)

    assert app.main() == 0  # pythonw처럼 표준 스트림이 없어도 시작 경로를 끝까지 지난다
    assert sys.stderr is not None and sys.stdout is not None
    print("devnull로 간다")
    entries = _log_entries(root)
    assert any(e["msg"] == "polling_started" for e in entries)
    assert ("serving", None) in calls


def test_build_application_gets_tools(started, monkeypatch):
    from my_planner.tools.core import Tools

    app, _root, calls = started
    seen = {}

    def fake_build(settings, dispatcher, state, transcripts, **kw):
        seen.update(kw)
        return FakeApplication(calls)

    monkeypatch.setattr(app, "build_application", fake_build)
    assert app.main() == 0
    assert isinstance(seen["tools"], Tools)


def test_first_tick_before_polling_then_run_forever(started, monkeypatch):
    import sqlite3

    app, root, calls = started
    from my_planner.loop import runner as runner_mod

    real_tick = runner_mod.Runner.tick

    def spy_tick(self):
        calls.append(("tick", None))
        real_tick(self)

    def spy_forever(self, interval=60):  # 부르는 순간을 적는다(가짜 종료가 곧바로 취소한다)
        import asyncio

        calls.append(("run_forever", interval))
        return asyncio.sleep(0)

    monkeypatch.setattr(runner_mod.Runner, "tick", spy_tick)
    monkeypatch.setattr(runner_mod.Runner, "run_forever", spy_forever)
    assert app.main() == 0

    names = [c[0] for c in calls]
    # 스펙 5.1: (installed_at) → 첫 tick 판정 → 폴링 → run_forever
    assert names.index("tick") < names.index("start_polling") < names.index("run_forever")
    assert names.count("tick") == 1
    conn = sqlite3.connect(root / "state" / "planner.db")
    keys = {k for (k,) in conn.execute("SELECT key FROM app_state")}
    conn.close()
    assert {"installed_at", "last_seen_at"} <= keys


def test_app_wires_draft_buttons_and_daily_expiry(started, monkeypatch):
    from my_planner.loop import runner as runner_mod

    app, _root, calls = started
    seen = {}

    def fake_build(settings, dispatcher, state, transcripts, **kw):
        seen.update(kw)
        return FakeApplication(calls)

    jobs = []
    real_register = runner_mod.Runner.register_daily

    def spy_register(self, job):
        jobs.append(getattr(job, "__name__", ""))
        real_register(self, job)

    senders = []
    real_sender = app.TelegramSender

    def spy_sender(*a, **kw):
        s = real_sender(*a, **kw)
        senders.append(s)
        return s

    monkeypatch.setattr(app, "build_application", fake_build)
    monkeypatch.setattr(runner_mod.Runner, "register_daily", spy_register)
    monkeypatch.setattr(app, "TelegramSender", spy_sender)
    assert app.main() == 0

    assert callable(seen["callbacks"]) and seen["callbacks"].keywords["owner_id"] == 42
    assert "expire_drafts" in jobs
    assert senders[0].tasks is not None  # 초안 버튼에 제목을 붙인다


def test_app_wires_conditions(started, monkeypatch):
    from my_planner.store.repos.conditions import ConditionsRepo

    app, _root, _calls = started
    seen = {}
    real_dispatcher = app.Dispatcher

    def spy_dispatcher(**kw):
        seen.update(kw)
        return real_dispatcher(**kw)

    monkeypatch.setattr(app, "Dispatcher", spy_dispatcher)
    assert app.main() == 0

    assert isinstance(seen["conditions"], ConditionsRepo)
    assert seen["tools"].conditions is seen["conditions"]  # 도구(버튼)와 디스패처가 같은 표를 본다


def test_draft_expiry_uses_configured_ttl(started, monkeypatch):
    app, root, _calls = started
    toml = root / "config.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace("draft_ttl_days = 3", "draft_ttl_days = 5"), encoding="utf-8"
    )
    seen = []
    real = app.expire_drafts

    def spy(tasks, clock, **kw):
        seen.append(kw)
        return real(tasks, clock, **kw)

    monkeypatch.setattr(app, "expire_drafts", spy)
    assert app.main() == 0
    assert seen == [{"days": 5}]


def _daily_jobs(monkeypatch):
    from my_planner.loop import runner as runner_mod

    jobs = {}
    real_register = runner_mod.Runner.register_daily

    def spy_register(self, job):
        jobs[getattr(job, "__name__", "")] = job
        real_register(self, job)

    monkeypatch.setattr(runner_mod.Runner, "register_daily", spy_register)
    return jobs


def test_log_cleanup_keeps_30_days(started, monkeypatch):
    from datetime import date, timedelta

    app, root, _calls = started
    jobs = _daily_jobs(monkeypatch)
    assert app.main() == 0
    assert {"daily_backup", "prune_updates", "cleanup_logs"} <= set(jobs)

    logs = root / "state" / "logs"
    first = date(2026, 9, 22)
    for i in range(31):  # 표준 핸들러가 회전해 둔 날짜별 파일 31개(9/22 ~ 10/22)
        (logs / f"my-planner.jsonl.{(first + timedelta(days=i)).isoformat()}").write_text("{}\n", encoding="utf-8")
    (logs / "keep-me.txt").write_text("로그가 아니다", encoding="utf-8")

    jobs["cleanup_logs"](date(2026, 10, 23))

    rotated = sorted(p.name for p in logs.glob("my-planner.jsonl.*"))
    assert len(rotated) == 30
    assert rotated[0] == "my-planner.jsonl.2026-09-23"  # 가장 오래된 하루만 지웠다
    assert (logs / "my-planner.jsonl").exists() and (logs / "keep-me.txt").exists()


class FakeBot:
    """안전 모드에서 TelegramSender가 쓰는 봇. 보낸 글을 적는다."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, chat_id, text, reply_markup=None):
        if self.fail:
            raise ConnectionError("fake send failure")
        self.sent.append((chat_id, text))


INTEGRITY_NOTICE = "데이터베이스에 문제가 있어요. 최신 백업으로 복구해야 해요. PC에서 README의 복구 절차를 따라 주세요."


def _corrupt_db(root):
    db = root / "state" / "planner.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"this is not a sqlite database" * 200)
    return db


def test_integrity_failure_notifies_once_and_idles(started, monkeypatch):
    app, root, calls = started
    bot = FakeBot()
    monkeypatch.setattr(app, "Bot", lambda token: bot)
    db = _corrupt_db(root)
    before = db.read_bytes()

    assert app.main() == 0
    assert app.main() == 0  # 두 번 시작해도

    assert bot.sent == [(42, INTEGRITY_NOTICE)]  # 알림은 한 번
    assert (root / "state" / "integrity_notice_sent").exists()
    assert calls == [("serving", None), ("serving", None)]  # 폴링 없이 기다리기만 했다
    assert db.read_bytes() == before  # 자동 복구하지 않는다
    entries = _log_entries(root)
    assert [e["msg"] for e in entries].count("safe_mode") == 2


def test_integrity_notice_retried_when_send_fails(started, monkeypatch):
    app, root, calls = started
    bot = FakeBot(fail=True)
    monkeypatch.setattr(app, "Bot", lambda token: bot)
    _corrupt_db(root)

    assert app.main() == 0
    assert not (root / "state" / "integrity_notice_sent").exists()  # 안 갔으니 표식도 없다
    raw = (root / "state" / "logs" / "my-planner.jsonl").read_text(encoding="utf-8")
    assert "데이터베이스에 문제가" not in raw  # 알림 본문은 로그에 남기지 않는다

    bot.fail = False
    assert app.main() == 0  # 다음 시작에서 다시 보낸다
    assert bot.sent == [(42, INTEGRITY_NOTICE)]
    assert (root / "state" / "integrity_notice_sent").exists()
    assert calls == [("serving", None), ("serving", None)]


def test_main_recovers_left_runs_before_first_tick(started, monkeypatch):
    import sqlite3
    from datetime import UTC, datetime

    from my_planner.clock import FakeClock
    from my_planner.domain import LoopKey
    from my_planner.loop import runner as runner_mod
    from my_planner.store.db import migrate, open_db
    from my_planner.store.repos.runs import RunsRepo

    app, root, calls = started
    conn = open_db(root / "state" / "planner.db")
    migrate(conn)
    runs = RunsRepo(conn, FakeClock(datetime(2026, 10, 1, tzinfo=UTC)))
    old = runs.ensure(LoopKey.morning_brief, datetime(2026, 10, 1, 0, 0, tzinfo=UTC))  # 한계가 한참 지났다
    runs.mark_queued(old.id)
    conn.close()

    real_tick = runner_mod.Runner.tick

    def spy_tick(self):
        calls.append(("tick", self.runs.get(old.id).status.value))
        real_tick(self)

    monkeypatch.setattr(runner_mod.Runner, "tick", spy_tick)
    assert app.main() == 0

    assert ("tick", "interrupted") in calls  # 첫 tick 전에 복구했다
    check = sqlite3.connect(root / "state" / "planner.db")
    assert check.execute("SELECT status FROM runs WHERE id = ?", (old.id,)).fetchone() == ("interrupted",)
    check.close()


def test_recovery_error_does_not_stop_start(started, monkeypatch):
    app, root, calls = started

    def broken(*a, **kw):
        raise ValueError("이상한 행")

    monkeypatch.setattr(app, "recover_on_start", broken)
    assert app.main() == 0  # 시작할 때마다 죽어 워치독이 되살리는 반복에 빠지지 않는다
    assert "start_polling" in [c[0] for c in calls]
    errors = [e for e in _log_entries(root) if e["msg"] == "recovery_error"]
    assert len(errors) == 1 and errors[0]["exc_type"] == "ValueError"


def test_operational_error_exits_without_safe_mode(started, monkeypatch):
    # 디스크 I/O, 잠금, 열기 오류는 손상이 아니다: 안전 모드에 들어가지 않고 끝나서 워치독이 다시 띄운다
    import sqlite3

    from my_planner.store.db import migrate, open_db

    app, root, calls = started
    bot = FakeBot()
    monkeypatch.setattr(app, "Bot", lambda token: bot)
    conn = open_db(root / "state" / "planner.db")
    migrate(conn)
    conn.close()

    def io_error(path):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(app, "open_db", io_error)
    assert app.main() == app.EXIT_FATAL

    assert bot.sent == [] and calls == []
    assert not (root / "state" / "integrity_notice_sent").exists()
    entries = _log_entries(root)
    assert "safe_mode" not in [e["msg"] for e in entries]
    assert any(e.get("exc_type") == "OperationalError" for e in entries)


def test_damaged_pages_fail_quick_check_and_enter_safe_mode(started, monkeypatch):
    # 머리말은 멀쩡해 열리지만 b-tree 페이지가 망가진 DB: quick_check가 "ok"가 아니다
    from my_planner.store.db import migrate, open_db

    app, root, calls = started
    bot = FakeBot()
    monkeypatch.setattr(app, "Bot", lambda token: bot)
    db = root / "state" / "planner.db"
    conn = open_db(db)
    migrate(conn)
    with conn:
        conn.executemany("INSERT INTO app_state (key, value) VALUES (?, ?)", [(f"k{i}", "v" * 50) for i in range(2000)])
    root_page = conn.execute("SELECT rootpage FROM sqlite_master WHERE name = 'app_state'").fetchone()[0]
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    data = bytearray(db.read_bytes())
    root_at = (root_page - 1) * page
    assert data[root_at] == 0x05  # app_state의 뿌리는 내부 페이지다. 머리 8~11바이트가 맨 오른쪽 자식 페이지 번호
    leaf = int.from_bytes(data[root_at + 8 : root_at + 12], "big")
    end = leaf * page  # 잎 페이지 끝의 셀 내용을 지운다(머리나 뿌리를 망가뜨리면 quick_check가 예외를 낸다)
    data[end - 96 : end] = b"\x00" * 96
    db.write_bytes(bytes(data))

    assert app.main() == 0
    assert bot.sent == [(42, INTEGRITY_NOTICE)]
    assert calls == [("serving", None)]
    assert "db_integrity_failed" in [e["msg"] for e in _log_entries(root)]


def test_resume_restarts_polling(started, monkeypatch):
    app, root, calls = started
    runners = []
    real_init = app.Runner.__init__

    def spy_init(self, **kw):
        real_init(self, **kw)
        runners.append(self)

    async def resume_then_stop():  # 폴링 중에 러너가 절전 복귀를 알린다
        await runners[0]._on_resume()

    monkeypatch.setattr(app.Runner, "__init__", spy_init)
    monkeypatch.setattr(app, "_wait_for_shutdown", resume_then_stop)
    assert app.main() == 0

    names = [c[0] for c in calls]
    assert names[:6] == ["app.initialize", "app.start", "start_polling", "updater.stop", "start_polling", "updater.stop"]
    polling = {"allowed_updates": ["message", "callback_query"], "drop_pending_updates": False}
    assert calls[2][1] == polling and calls[4][1] == polling
    assert any(e["msg"] == "polling_restarted" for e in _log_entries(root))


def test_restart_after_failed_restart_skips_stop_and_shutdown_stays_in_order(started, monkeypatch):
    app, _root, calls = started
    runners = []
    real_init = app.Runner.__init__

    def spy_init(self, **kw):
        real_init(self, **kw)
        runners.append(self)

    async def two_resumes():
        updater = FakeApplication.last.updater
        updater.fail_starts = 1  # 복귀 직후 첫 재시작은 네트워크가 없어 안 된다
        with pytest.raises(ConnectionError):
            await runners[0]._on_resume()
        assert not updater.running
        await runners[0]._on_resume()  # 다음 기회: 멈춘 것을 다시 멈추지 않고 바로 시작한다
        assert updater.running

    monkeypatch.setattr(app.Runner, "__init__", spy_init)
    monkeypatch.setattr(app, "_wait_for_shutdown", two_resumes)
    assert app.main() == 0
    assert [c[0] for c in calls] == [
        "app.initialize", "app.start", "start_polling",
        "updater.stop", "start_polling",  # 첫 재시작(안 됨)
        "start_polling",  # 두 번째 재시작: stop 없이
        "updater.stop", "app.stop", "app.shutdown",
    ]


def test_shutdown_during_restart_waits_for_it_and_keeps_order(started, monkeypatch):
    app, _root, calls = started

    async def forever_resumes(self, interval=60):  # tick 루프가 절전 복귀로 폴링을 다시 시작하는 중
        await self._on_resume()
        await asyncio.Event().wait()

    async def shutdown_mid_restart():  # Ctrl+C가 재시작의 updater.stop() 대기 중에 온다
        updater = FakeApplication.last.updater
        updater.stop_yields = 20
        while not updater.stopping:
            await asyncio.sleep(0)

    real_stop = app.Dispatcher.stop

    async def spy_stop(self, timeout=30):
        calls.append(("dispatcher.stop", timeout))
        await real_stop(self, timeout)

    monkeypatch.setattr(app.Runner, "run_forever", forever_resumes)
    monkeypatch.setattr(app, "_wait_for_shutdown", shutdown_mid_restart)
    monkeypatch.setattr(app.Dispatcher, "stop", spy_stop)
    assert app.main() == 0
    # 재시작은 끝까지 마치고(멈춘 채 남은 폴링 작업이 없게), 그다음 종료 순서 그대로
    assert [c[0] for c in calls] == [
        "app.initialize", "app.start", "start_polling",
        "updater.stop", "start_polling",
        "updater.stop", "app.stop", "dispatcher.stop", "app.shutdown",
    ]
    assert not FakeApplication.last.updater.running


def test_main_resubmits_pending_inbound_after_recovery_before_first_tick(started, monkeypatch):
    from my_planner.loop import runner as runner_mod

    app, _root, calls = started
    real_recover, real_resubmit = app.recover_on_start, app.resubmit_inbound

    def spy_recover(*a, **kw):
        calls.append(("recover", None))
        return real_recover(*a, **kw)

    def spy_resubmit(state, dispatcher):
        calls.append(("resubmit", dispatcher._worker is None))  # 디스패처를 시작하기 전
        return real_resubmit(state, dispatcher)

    real_tick = runner_mod.Runner.tick

    def spy_tick(self):
        calls.append(("tick", None))
        real_tick(self)

    monkeypatch.setattr(app, "recover_on_start", spy_recover)
    monkeypatch.setattr(app, "resubmit_inbound", spy_resubmit)
    monkeypatch.setattr(runner_mod.Runner, "tick", spy_tick)
    assert app.main() == 0

    names = [c[0] for c in calls]
    assert names.index("recover") < names.index("resubmit") < names.index("tick") < names.index("start_polling")
    assert ("resubmit", True) in calls


def test_resubmit_error_does_not_stop_start(started, monkeypatch):
    app, root, calls = started

    def broken(*a, **kw):
        raise ValueError("이상한 행")

    monkeypatch.setattr(app, "resubmit_inbound", broken)
    assert app.main() == 0
    assert "start_polling" in [c[0] for c in calls]
    errors = [e for e in _log_entries(root) if e["msg"] == "inbound_resubmit_error"]
    assert len(errors) == 1 and errors[0]["exc_type"] == "ValueError"


# --- SP3-4 티켓 01: API 시작·종료 (스펙 15) ---

API_TOKEN = "a" * 43  # 꾸며 낸 값


def _enable_api(root, *, token=API_TOKEN, port=8787):
    toml = root / "config.toml"
    text = toml.read_text(encoding="utf-8").replace("[api]\nenabled = false\n", "[api]\nenabled = true\n")
    toml.write_text(text.replace("port = 8787", f"port = {port}"), encoding="utf-8")
    env = root / ".env"
    if token is not None:
        env.write_text(env.read_text(encoding="utf-8") + f"API_TOKEN={token}\n", encoding="utf-8")


def _fake_api(monkeypatch, app, calls, apps=None):
    async def fake_start(web_app, host, port):
        calls.append(("start_api", (host, port)))
        if apps is not None:
            apps.append(web_app)
        return "api-runner"

    async def fake_stop(runner):
        calls.append(("stop_api", runner))

    monkeypatch.setattr(app, "start_api", fake_start)
    monkeypatch.setattr(app, "stop_api", fake_stop)


def test_api_starts_after_polling_and_stops_before_updater(started, monkeypatch):
    app, root, calls = started
    _enable_api(root)
    _fake_api(monkeypatch, app, calls)
    real_stop = app.Dispatcher.stop

    async def spy_stop(self, timeout=30):
        calls.append(("dispatcher.stop", timeout))
        await real_stop(self, timeout)

    monkeypatch.setattr(app.Dispatcher, "stop", spy_stop)
    assert app.main() == 0
    assert [c[0] for c in calls] == [
        "app.initialize", "app.start", "start_polling", "start_api", "serving",
        "stop_api", "updater.stop", "app.stop", "dispatcher.stop", "app.shutdown",
    ]
    assert ("start_api", ("127.0.0.1", 8787)) in calls
    assert ("stop_api", "api-runner") in calls
    assert not [e for e in _log_entries(root) if e["level"] == "WARNING" and e["msg"].startswith("api_")]


def test_api_disabled_runs_like_sp1(started, monkeypatch):
    app, root, calls = started  # 기본 시험 설정은 api.enabled = false
    (root / ".env").write_text((root / ".env").read_text(encoding="utf-8") + f"API_TOKEN={API_TOKEN}\n",
                               encoding="utf-8")
    _fake_api(monkeypatch, app, calls)
    assert app.main() == 0
    assert "start_api" not in [c[0] for c in calls]
    assert [c[0] for c in calls][:4] == ["app.initialize", "app.start", "start_polling", "serving"]
    assert "api_token_missing" not in [e["msg"] for e in _log_entries(root)]


@pytest.mark.parametrize(("token", "reason"), [(None, "missing"), ("", "missing"), ("b" * 42, "too_short")])
def test_missing_or_short_token_logs_and_skips_api(started, monkeypatch, token, reason):
    app, root, calls = started
    _enable_api(root, token=token)
    _fake_api(monkeypatch, app, calls)
    assert app.main() == 0
    names = [c[0] for c in calls]
    assert "start_api" not in names and "serving" in names  # 텔레그램과 루프는 그대로
    warned = [e for e in _log_entries(root) if e["msg"] == "api_token_missing"]
    assert len(warned) == 1 and warned[0]["level"] == "WARNING" and warned[0]["reason"] == reason
    raw = (root / "state" / "logs" / "my-planner.jsonl").read_text(encoding="utf-8")
    assert "b" * 42 not in raw


def test_port_in_use_logs_api_bind_error_and_keeps_polling(started):
    import socket

    app, root, calls = started
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        _enable_api(root, port=port)
        assert app.main() == 0
    names = [c[0] for c in calls]
    assert names[:4] == ["app.initialize", "app.start", "start_polling", "serving"]
    errors = [e for e in _log_entries(root) if e["msg"] == "api_bind_error"]
    assert len(errors) == 1 and errors[0]["port"] == port and errors[0]["error_type"]


def test_safe_mode_opens_health_only_api(started, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    app, root, calls = started
    monkeypatch.setattr(app, "Bot", lambda token: FakeBot())
    _corrupt_db(root)
    _enable_api(root)
    apps = []
    _fake_api(monkeypatch, app, calls, apps)
    assert app.main() == 0
    assert [c[0] for c in calls] == ["start_api", "serving", "stop_api"]

    async def probe():
        client = TestClient(TestServer(apps[0]))
        await client.start_server()
        try:
            auth = {"Authorization": f"Bearer {API_TOKEN}"}
            health = await client.get("/api/v1/health", headers=auth)
            today = await client.get("/api/v1/today", headers=auth)
            return health.status, (await health.json())["status"], today.status
        finally:
            await client.close()

    assert asyncio.run(probe()) == (200, "safe_mode", 503)


def test_build_be_same_wiring_as_serve(started, monkeypatch):
    app, _root, calls = started
    built = []
    seen = {}
    real = app.build_be

    def spy_build_be(*a, **kw):
        parts = real(*a, **kw)
        built.append((parts, kw))
        return parts

    def fake_build(settings, dispatcher, state, transcripts, **kw):
        seen.update(dispatcher=dispatcher, state=state, transcripts=transcripts, **kw)
        return FakeApplication(calls)

    monkeypatch.setattr(app, "build_be", spy_build_be)
    monkeypatch.setattr(app, "build_application", fake_build)
    assert app.main() == 0
    assert len(built) == 1
    parts, kw = built[0]
    assert seen["dispatcher"] is parts.dispatcher and seen["state"] is parts.state
    assert seen["callbacks"] is parts.callbacks and seen["tools"] is parts.tools and seen["router"] is parts.router
    assert parts.dispatcher.deliveries is parts.deliveries
    assert parts.dispatcher.tools is parts.tools and parts.tools.conditions is parts.conditions
    assert parts.runner._on_resume is kw["on_resume"]
    assert isinstance(parts.sender, app.TelegramSender) and parts.sender.tasks is parts.tasks
    assert isinstance(parts.dispatcher.brain, app.ClaudeBrain)


async def test_start_api_serves_on_loopback_and_stops(tmp_path):
    import socket

    import aiohttp
    from fakes import make_settings

    from my_planner.api.health import ErrorCounter
    from my_planner.api.server import ApiDeps, build_app, start_api, stop_api
    from my_planner.clock import SystemClock

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    clock = SystemClock()
    deps = ApiDeps(settings=make_settings(tmp_path), clock=clock, token=API_TOKEN, read_conn=None, dispatcher=None,
                   errors=ErrorCounter(clock), polling_state=lambda: "stopped", started_at=clock.now(), safe_mode=True)
    runner = await start_api(build_app(deps), "127.0.0.1", port)
    assert runner is not None
    try:
        auth = {"Authorization": f"Bearer {API_TOKEN}"}
        async with aiohttp.ClientSession() as http, http.get(f"http://127.0.0.1:{port}/api/v1/health",
                                                             headers=auth) as resp:
            assert resp.status == 200
    finally:
        await stop_api(runner)
    with socket.socket() as again:  # 닫았으니 같은 포트를 다시 잡을 수 있다
        again.bind(("127.0.0.1", port))

import shutil
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


class FakeUpdater:
    def __init__(self, calls):
        self.calls = calls

    async def start_polling(self, **kw):
        self.calls.append(("start_polling", kw))

    async def stop(self):
        self.calls.append(("updater.stop", None))


class FakeApplication:
    def __init__(self, calls):
        self.calls = calls
        self.updater = FakeUpdater(calls)

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
    shutil.copy(REPO / "config.toml", root / "config.toml")
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

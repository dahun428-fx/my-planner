"""명령줄 (SP3-4 티켓 01): 인자 없으면 BE, `gen-token`."""

import subprocess
import sys

from my_planner import cli
from my_planner.config import API_TOKEN_MIN_CHARS


def test_gen_token(capsys):
    assert cli.main(["gen-token"]) == 0
    first = capsys.readouterr().out.strip()
    assert cli.main(["gen-token"]) == 0
    second = capsys.readouterr().out.strip()
    assert len(first) == API_TOKEN_MIN_CHARS == 43
    assert first != second
    assert all(c.isalnum() or c in "-_" for c in first)


def test_no_args_calls_app_main(monkeypatch):
    from my_planner import app

    calls = []
    monkeypatch.setattr(app, "main", lambda: calls.append("main") or 7)
    assert cli.main([]) == 7
    assert calls == ["main"]


def test_unknown_command_prints_usage(capsys):
    assert cli.main(["nope"]) == cli.EXIT_USAGE
    assert "사용법" in capsys.readouterr().err


def test_module_entry_runs_cli():
    out = subprocess.run(
        [sys.executable, "-m", "my_planner", "gen-token"], check=True, capture_output=True, text=True, timeout=60
    )
    assert len(out.stdout.strip()) == 43

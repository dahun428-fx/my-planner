"""명령줄 (SP3-4 티켓 01): 인자 없으면 BE, `gen-token`."""

import os
import subprocess
import sys
from pathlib import Path

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
    # 자식 프로세스는 pytest의 pythonpath를 물려받지 않는다: 이 체크아웃의 src를 먼저 보게 한다
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")]))}
    out = subprocess.run(
        [sys.executable, "-m", "my_planner", "gen-token"], check=True, capture_output=True, text=True, timeout=60,
        env=env,
    )
    assert len(out.stdout.strip()) == 43


def test_gen_vapid_prints_key_pair_usable_by_pywebpush(capsys):
    import base64

    from py_vapid import Vapid

    assert cli.main(["gen-vapid"]) == 0
    captured = capsys.readouterr()
    lines = dict(line.split("=", 1) for line in captured.out.strip().splitlines())
    assert set(lines) == {"VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"}
    pub, priv = lines["VAPID_PUBLIC_KEY"], lines["VAPID_PRIVATE_KEY"]
    assert "VAPID_SUBJECT" in captured.err

    def raw(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    assert len(raw(pub)) == 65 and raw(pub)[0] == 4  # 비압축 P-256 점(applicationServerKey)
    assert len(raw(priv)) == 32
    v = Vapid.from_string(private_key=priv)  # pywebpush가 받는 모양
    from cryptography.hazmat.primitives import serialization

    assert v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    ) == raw(pub)
    assert cli.main(["gen-vapid"]) == 0
    assert capsys.readouterr().out != captured.out  # 매번 새 키


# --- 기기 연결 스펙 4.7: `pair` ---


def _pair_env(monkeypatch, tmp_path, *, token="t" * 43):
    from fakes import make_settings

    settings = make_settings(tmp_path, api_token=token) if token else make_settings(tmp_path)
    monkeypatch.setattr("my_planner.config.load_settings", lambda root: settings)
    return settings


def test_cli_pair_prints_code(monkeypatch, tmp_path, capsys):
    settings = _pair_env(monkeypatch, tmp_path)
    seen = []

    def fake_post(url, token):
        seen.append((url, token))
        return 201, {"code": "482913", "expires_at": "2026-10-26T05:05:00Z"}

    monkeypatch.setattr(cli, "_post_local", fake_post)
    assert cli.main(["pair"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "연결 코드: 482 913 (5분 동안, 한 번만)"
    assert seen == [(f"http://127.0.0.1:{settings.api.port}/api/v1/devices/pair", "t" * 43)]
    assert "t" * 43 not in out.out + out.err


def test_cli_pair_be_down_exit_1(monkeypatch, tmp_path, capsys):
    _pair_env(monkeypatch, tmp_path)

    def down(url, token):
        raise ConnectionRefusedError

    monkeypatch.setattr(cli, "_post_local", down)
    assert cli.main(["pair"]) == 1
    assert "BE가 꺼져 있어요" in capsys.readouterr().err


def test_cli_pair_401_exit_1(monkeypatch, tmp_path, capsys):
    _pair_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_post_local", lambda url, token: (401, {"error": {"code": "unauthorized"}}))
    assert cli.main(["pair"]) == 1
    assert "API_TOKEN이 BE와 달라요" in capsys.readouterr().err


def test_cli_pair_safe_mode_exit_1(monkeypatch, tmp_path, capsys):
    _pair_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_post_local", lambda url, token: (503, {"error": {"code": "safe_mode"}}))
    assert cli.main(["pair"]) == 1
    assert "안전 모드" in capsys.readouterr().err


def test_cli_pair_no_token_exit_1(monkeypatch, tmp_path, capsys):
    _pair_env(monkeypatch, tmp_path, token=None)
    assert cli.main(["pair"]) == 1
    assert "API_TOKEN이 없어요" in capsys.readouterr().err


async def test_cli_pair_against_real_api(tmp_path, monkeypatch):
    """실제 `_post_local`이 돌고 있는 API에서 코드를 받는다(127.0.0.1, 프록시 없이)."""
    import asyncio
    import socket

    from be_env import TEST_TOKEN, BeEnv
    from test_dispatcher_messages import kst

    from my_planner.api.server import build_app, start_api, stop_api

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 14, 0)) as env:
        runner = await start_api(build_app(env.deps), "127.0.0.1", port)
        try:
            status, body = await asyncio.to_thread(
                cli._post_local, f"http://127.0.0.1:{port}/api/v1/devices/pair", TEST_TOKEN
            )
        finally:
            await stop_api(runner)
    assert status == 201 and len(body["code"]) == 6


def test_cli_standing_import_routes(monkeypatch, tmp_path, capsys):
    import json

    monkeypatch.setenv("MY_PLANNER_ROOT", str(tmp_path))
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"version": 1, "measures": [
        {"metric": "height_cm", "value": 999, "measured_on": "2020-01-01"}]}), encoding="utf-8")
    assert cli.main(["standing", "import", str(f), "--dry-run"]) == 5
    assert "invalid: 0 height_cm" in capsys.readouterr().out
    assert "999" not in capsys.readouterr().out

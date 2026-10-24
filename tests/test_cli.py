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

"""개발용 결함 주입(SP6 스펙 12장 인수 시험, `my_planner.probe`): 표지 파일이 없으면 아무 일도 없다."""

import json
import logging
import subprocess

import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner import probe
from my_planner.logging_setup import setup_logging
from my_planner_medic.signals import log_signals

START = kst(2026, 10, 24, 13, 0)


def _git_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "a"],
        check=True,
    )
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_command_probe_needs_marker(tmp_path):
    assert not probe.command_probe_on(tmp_path)
    (tmp_path / "state" / "probe").mkdir(parents=True)
    (tmp_path / "state" / "probe" / "command").write_text("", encoding="utf-8")
    assert probe.command_probe_on(tmp_path)


def test_health_probe_fails_only_off_the_written_commit(tmp_path):
    head = _git_repo(tmp_path)
    assert not probe.health_probe_fails(tmp_path)  # 표지 없음
    marker = tmp_path / "state" / "probe" / "health"
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="utf-8")
    assert not probe.health_probe_fails(tmp_path)  # 빈 표지
    marker.write_text(head[:12] + "\n", encoding="utf-8")
    assert not probe.health_probe_fails(tmp_path)  # 적힌 커밋 그대로
    marker.write_text("0" * 40, encoding="utf-8")
    assert probe.health_probe_fails(tmp_path)  # 다른 커밋으로 돈다


def _entries(state_dir):
    for h in logging.getLogger().handlers:
        h.flush()
    raw = (state_dir / "logs" / "my-planner.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in raw.splitlines()]


async def test_probe_command_off_replies(tmp_path, monkeypatch):
    monkeypatch.setattr("my_planner.bot.commands.command_probe_on", lambda: False)
    async with BeEnv.start(tmp_path, start=START) as env:
        resp, raw = await env.chat("/medic_probe")
    assert resp.status == 200
    assert "개발용 명령이에요" in raw.decode()


async def test_probe_command_on_leaves_a_medic_fingerprint(tmp_path, monkeypatch):
    """앱 `/chat`의 예상 못 한 예외도 프레임이 로그에 남아 medic이 `be:KeyError …:run_command` 지문을 만든다."""
    monkeypatch.setattr("my_planner.bot.commands.command_probe_on", lambda: True)
    async with BeEnv.start(tmp_path, start=START) as env:
        state_dir = env.settings.paths.state_dir
        setup_logging(state_dir, 30)
        resp, _ = await env.chat("/medic_probe")
        entries = _entries(state_dir)
    assert resp.status == 500
    err = next(e for e in entries if e.get("msg") == "api_internal_error")
    assert err["exc_type"] == "KeyError" and "probe" not in json.dumps(err["exc_where"])
    root = probe._ROOT
    sigs = log_signals([err], root, now=START, warn_window={})
    assert [s.fingerprint for s in sigs] == ["be:KeyError src/my_planner/bot/commands.py:run_command"]


@pytest.mark.parametrize("fails", [False, True])
async def test_health_probe(tmp_path, monkeypatch, fails):
    monkeypatch.setattr("my_planner.api.server.health_probe_fails", lambda: fails)
    async with BeEnv.start(tmp_path, start=START) as env:
        resp = await env.get("/health")
    assert resp.status == (500 if fails else 200)

from __future__ import annotations

from datetime import time
from pathlib import Path

from my_planner_medic.config import load_config

TOKEN = "t" * 43
GH = "ghp_secretgithubtoken"
TG = "123456:telegram-secret"


def _write_root(root: Path, *, api_token: str = TOKEN) -> None:
    (root / "config.medic.toml").write_text(
        "enabled = true\nwatch_interval_s = 120\nmax_notices_per_day = 5\n", encoding="utf-8"
    )
    (root / "config.toml").write_text(
        'timezone = "Asia/Seoul"\nday_boundary = "04:00"\n'
        '[schedule.morning_brief]\nweekday = "09:00"\nweekend = "10:00"\n'
        '[schedule.review.week]\nday = "sun"\ntime = "18:00"\n'
        '[api]\nenabled = true\nhost = "127.0.0.1"\nport = 8787\n',
        encoding="utf-8",
    )
    (root / ".env").write_text(
        f"# comment\nAPI_TOKEN={api_token}\nMEDIC_GITHUB_TOKEN=\"{GH}\"\n"
        f"TELEGRAM_BOT_TOKEN='{TG}'\nOWNER_TELEGRAM_ID=42\n",
        encoding="utf-8",
    )


def test_load_config_merges_three_files(tmp_path: Path) -> None:
    _write_root(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.root == tmp_path
    assert cfg.enabled is True
    assert cfg.watch_interval_s == 120
    assert cfg.repo == "dahun428-fx/my-planner"
    assert cfg.api_base == "http://127.0.0.1:8787/api/v1"
    assert cfg.api_enabled is True
    assert cfg.api_token == TOKEN
    assert cfg.github_token == GH
    assert cfg.telegram_token == TG
    assert cfg.owner_telegram_id == "42"
    assert cfg.timezone == "Asia/Seoul"
    assert cfg.day_boundary == time(4, 0)
    assert cfg.schedule["review"]["week"]["day"] == "sun"
    assert cfg.schedule["morning_brief"]["weekday"] == "09:00"


def test_short_api_token_disables_api_checks(tmp_path: Path) -> None:
    _write_root(tmp_path, api_token="short")
    assert load_config(tmp_path).api_enabled is False


def test_repr_hides_tokens(tmp_path: Path) -> None:
    _write_root(tmp_path)
    text = repr(load_config(tmp_path))
    for secret in (TOKEN, GH, TG):
        assert secret not in text
    assert "***" in text


def test_env_parsing_edge_cases(tmp_path: Path) -> None:
    (tmp_path / ".env").write_bytes(
        b"\xef\xbb\xbfAPI_TOKEN=a=b==\nexport MEDIC_GITHUB_TOKEN=gh\nTELEGRAM_BOT_TOKEN=\n"
    )
    cfg = load_config(tmp_path, environ={})
    assert cfg.api_token == "a=b=="
    assert cfg.github_token == "gh"
    assert cfg.telegram_token is None


def test_missing_env_and_api_enabled_defaults_true(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[api]\nport = 9000\n", encoding="utf-8")
    cfg = load_config(tmp_path, environ={"API_TOKEN": TOKEN})
    assert cfg.api_enabled is True
    assert cfg.api_base == "http://127.0.0.1:9000/api/v1"
    assert load_config(tmp_path, environ={}).api_enabled is False


def test_environ_takes_precedence_over_env_file(tmp_path: Path) -> None:
    _write_root(tmp_path)
    cfg = load_config(tmp_path, environ={"MEDIC_GITHUB_TOKEN": "fromenv", "OWNER_TELEGRAM_ID": "7"})
    assert cfg.github_token == "fromenv"
    assert cfg.owner_telegram_id == "7"
    assert cfg.telegram_token == TG


def test_day_boundary_accepts_seconds(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('day_boundary = "04:00:00"\n', encoding="utf-8")
    assert load_config(tmp_path, environ={}).day_boundary == time(4, 0)

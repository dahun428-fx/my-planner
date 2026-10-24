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


def test_local_toml_overrides_api_port(tmp_path: Path) -> None:
    # 릴리스 흐름 5.2: medic-dev가 개발용 BE(8788)를 검사한다. 나머지 [api] 키는 config.toml 그대로
    _write_root(tmp_path)
    (tmp_path / "config.local.toml").write_text('[api]\nport = 8788\n[schedule.review.week]\ntime = "19:00"\n',
                                                encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.api_base == "http://127.0.0.1:8788/api/v1"
    assert cfg.api_enabled is True
    assert cfg.schedule["review"]["week"] == {"day": "sun", "time": "19:00"}
    assert cfg.schedule["morning_brief"]["weekday"] == "09:00"


def test_medic_local_toml_overlays_medic_toml(tmp_path: Path) -> None:
    _write_root(tmp_path)
    (tmp_path / "config.medic.local.toml").write_text(
        'watch_interval_s = 30\nbranch = "develop"\nheartbeat = false\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.watch_interval_s == 30
    assert cfg.max_notices_per_day == 5 and cfg.enabled is True  # 덮어쓰지 않은 키는 그대로(모르는 키는 무시)


def test_without_local_files_unchanged(tmp_path: Path) -> None:
    _write_root(tmp_path)
    assert load_config(tmp_path).api_base == "http://127.0.0.1:8787/api/v1"


# --- medic-dev (릴리스 흐름 스펙 5.3) ---------------------------------------


def _dev_overlay(root: Path) -> None:
    (root / "config.medic.local.toml").write_text(
        'branch = "develop"\nbe_task_name = "my-planner-dev"\nverify_minutes = 30\n'
        "watch_incidents = false\nheartbeat = false\npost_commit_status = true\n",
        encoding="utf-8",
    )


def test_new_fields_default_to_production_values(tmp_path: Path) -> None:
    _write_root(tmp_path)
    cfg = load_config(tmp_path)
    assert (cfg.watch_incidents, cfg.heartbeat, cfg.post_commit_status) == (True, True, False)


def test_local_medic_overlay_sets_dev_fields(tmp_path: Path) -> None:
    _write_root(tmp_path)
    _dev_overlay(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.branch == "develop"
    assert cfg.be_task_name == "my-planner-dev"
    assert cfg.verify_minutes == 30
    assert cfg.watch_incidents is False
    assert cfg.heartbeat is False
    assert cfg.post_commit_status is True
    assert cfg.max_notices_per_day == 5  # 덮지 않은 키는 config.medic.toml 값 그대로


def test_dev_role_drops_telegram(tmp_path: Path) -> None:
    _write_root(tmp_path)
    (tmp_path / "config.local.toml").write_text('[runtime]\nrole = "dev"\n', encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.telegram_token is None
    assert cfg.owner_telegram_id is None
    assert cfg.github_token == GH  # 텔레그램만 뺀다


def test_prod_role_keeps_telegram(tmp_path: Path) -> None:
    _write_root(tmp_path)
    (tmp_path / "config.local.toml").write_text('[runtime]\nrole = "prod"\n', encoding="utf-8")
    cfg = load_config(tmp_path)
    assert (cfg.telegram_token, cfg.owner_telegram_id) == (TG, "42")
    (tmp_path / "config.local.toml").unlink()
    cfg = load_config(tmp_path)  # role이 없으면 "prod"
    assert (cfg.telegram_token, cfg.owner_telegram_id) == (TG, "42")

"""`config.local.toml` 겹쳐 읽기와 `[runtime] role` (릴리스 흐름 스펙 5.2, 10장). 값은 꾸며 낸 것이다."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from my_planner.config import load_settings
from my_planner_medic.toml_overlay import deep_merge, read_overlaid

REPO = Path(__file__).resolve().parents[1]
SECRETS = "TELEGRAM_BOT_TOKEN=123:fake\nOWNER_TELEGRAM_ID=42\n"


@pytest.fixture(autouse=True)
def _no_env_secrets(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID", "API_TOKEN", "BODY_TOKEN"):
        monkeypatch.delenv(k, raising=False)


def _root(tmp_path, *, local: str | None = None, env: str = SECRETS) -> Path:
    (tmp_path / "config.toml").write_text((REPO / "config.toml").read_text(encoding="utf-8"), encoding="utf-8")
    if local is not None:
        (tmp_path / "config.local.toml").write_text(local, encoding="utf-8")
    (tmp_path / ".env").write_text(env, encoding="utf-8")
    return tmp_path


def test_deep_merge_tables_recursive_lists_and_scalars_replace():
    base = {"a": 1, "t": {"x": 1, "y": [1, 2], "n": {"p": 1, "q": 2}}, "l": [1, 2, 3]}
    over = {"t": {"y": [9], "n": {"q": 5}, "z": 3}, "l": [7], "b": 2}
    merged = deep_merge(base, over)
    assert merged == {"a": 1, "t": {"x": 1, "y": [9], "n": {"p": 1, "q": 5}, "z": 3}, "l": [7], "b": 2}
    assert base["t"]["n"] == {"p": 1, "q": 2}  # 원본은 그대로


def test_deep_merge_type_change_replaces_wholesale():
    assert deep_merge({"t": {"x": 1}}, {"t": 3}) == {"t": 3}
    assert deep_merge({"t": 3}, {"t": {"x": 1}}) == {"t": {"x": 1}}


def test_read_overlaid_missing_files(tmp_path):
    assert read_overlaid(tmp_path / "a.toml", tmp_path / "b.toml") == {}
    (tmp_path / "a.toml").write_text("k = 1\n", encoding="utf-8")
    assert read_overlaid(tmp_path / "a.toml", tmp_path / "b.toml") == {"k": 1}


def test_local_overrides_port_and_keeps_other_api_keys(tmp_path):
    base = load_settings(_root(tmp_path))
    (tmp_path / "config.local.toml").write_text(
        '[api]\nport = 8788\ncors_origins = ["https://staging.example.invalid"]\n'
        "[limits.reply_window]\nreview_hours = 12\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path)
    assert s.api.port == 8788
    assert s.api.host == base.api.host and s.api.enabled is base.api.enabled and s.api.max_body_kb == base.api.max_body_kb
    assert s.api.cors_origins == ["https://staging.example.invalid"]  # 목록은 통째로 바뀐다
    assert s.limits.reply_window.review_hours == 12
    assert s.limits.reply_window.morning_brief_until == base.limits.reply_window.morning_brief_until
    assert s.limits.daily_brain_calls == base.limits.daily_brain_calls


def test_missing_local_file_reads_config_toml_only(tmp_path):
    s = load_settings(_root(tmp_path))
    assert s.api.port == 8787 and s.runtime.role == "prod"


@pytest.mark.parametrize("local", [
    'telegram_bot_token = "x"\n',
    "owner_telegram_id = 1\n",
    'api_token = "x"\n',
    'body_token = "x"\n',
    '[vapid]\npublic_key = "x"\n',
    '[paths]\nroot = "C:/x"\n',
])
def test_secret_keys_banned_in_local_file(tmp_path, local):
    with pytest.raises(ValueError, match="두지 않는다"):
        load_settings(_root(tmp_path, local=local))


def test_dev_role_loads_without_telegram_secrets(tmp_path):
    s = load_settings(_root(tmp_path, local='[runtime]\nrole = "dev"\n', env="API_TOKEN=" + "t" * 43 + "\n"))
    assert s.runtime.role == "dev"
    assert s.telegram_bot_token is None and s.owner_telegram_id is None
    assert s.api_token is not None


def test_dev_role_still_reads_telegram_secrets_when_given(tmp_path):
    s = load_settings(_root(tmp_path, local='[runtime]\nrole = "dev"\n'))
    assert s.owner_telegram_id == 42


def test_prod_role_still_requires_telegram_secrets(tmp_path):
    with pytest.raises(ValidationError) as e:
        load_settings(_root(tmp_path, env=""))
    assert {".".join(str(p) for p in err["loc"]) for err in e.value.errors()} == {
        "TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID",
    }
    with pytest.raises(ValidationError):
        load_settings(_root(tmp_path, local='[runtime]\nrole = "prod"\n', env=""))


def test_unknown_role_rejected(tmp_path):
    with pytest.raises(ValidationError):
        load_settings(_root(tmp_path, local='[runtime]\nrole = "staging"\n'))


def test_body_token_read_from_env_file(tmp_path):
    """SP8 7.2: `BODY_TOKEN`은 `.env`에서만 읽는다(꾸며 낸 값). 없으면 None."""
    fake = "b" * 43
    s = load_settings(_root(tmp_path, env=SECRETS + f"BODY_TOKEN={fake}\n"))
    assert s.body_token is not None and s.body_token.get_secret_value() == fake
    assert fake not in repr(s)
    assert load_settings(_root(tmp_path)).body_token is None

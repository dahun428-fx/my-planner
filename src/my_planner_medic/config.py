"""medic 설정: config.medic.toml + config.toml 일부 + .env. 표준 라이브러리만 쓴다."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from datetime import time
from pathlib import Path
from typing import Any

API_TOKEN_MIN_CHARS = 43  # BE(my_planner.config)와 같은 기준
_SECRET_FIELDS = ("api_token", "github_token", "telegram_token")


@dataclass(frozen=True)
class MedicConfig:
    root: Path
    enabled: bool
    api_base: str
    api_enabled: bool
    api_token: str | None
    github_token: str | None
    telegram_token: str | None
    owner_telegram_id: str | None
    timezone: str
    day_boundary: time
    schedule: dict[str, Any] = field(default_factory=dict)
    watch_interval_s: int = 120
    deploy_interval_s: int = 300
    heartbeat_minutes: int = 30
    late_run_grace_minutes: int = 15
    no_reply_minutes: int = 10
    health_fail_streak: int = 3
    verify_minutes: int = 10
    web_verify_minutes: int = 60
    max_notices_per_day: int = 5
    keep_pre_deploy: int = 5
    keep_failed: int = 3
    repo: str = "dahun428-fx/my-planner"

    def __repr__(self) -> str:
        parts = []
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in _SECRET_FIELDS and value is not None:
                value = "***"
            parts.append(f"{f.name}={value!r}")
        return f"MedicConfig({', '.join(parts)})"


def parse_env(text: str) -> dict[str, str]:
    """KEY=VALUE 줄, # 주석, 감싼 따옴표 벗김만 지원한다."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def load_config(root: Path) -> MedicConfig:
    medic = _read_toml(root / "config.medic.toml")
    base = _read_toml(root / "config.toml")
    env_path = root / ".env"
    env = parse_env(env_path.read_text(encoding="utf-8")) if env_path.exists() else {}

    api = base.get("api", {})
    host = api.get("host", "127.0.0.1")
    port = api.get("port", 8787)
    token = env.get("API_TOKEN") or None
    api_enabled = bool(api.get("enabled", False)) and token is not None and (
        len(token) >= API_TOKEN_MIN_CHARS
    )
    known = {f.name for f in fields(MedicConfig)}
    overrides = {k: v for k, v in medic.items() if k in known and k not in _RESERVED}
    return MedicConfig(
        root=root,
        enabled=bool(medic.get("enabled", True)),
        api_base=f"http://{host}:{port}/api/v1",
        api_enabled=api_enabled,
        api_token=token,
        github_token=env.get("MEDIC_GITHUB_TOKEN") or None,
        telegram_token=env.get("TELEGRAM_BOT_TOKEN") or None,
        owner_telegram_id=env.get("OWNER_TELEGRAM_ID") or None,
        timezone=base.get("timezone", "Asia/Seoul"),
        day_boundary=_parse_time(base.get("day_boundary", "04:00")),
        schedule=base.get("schedule", {}),
        **overrides,
    )


_RESERVED = {
    "root", "enabled", "api_base", "api_enabled", "api_token", "github_token",
    "telegram_token", "owner_telegram_id", "timezone", "day_boundary", "schedule",
}

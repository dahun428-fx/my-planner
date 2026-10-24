"""medic 설정: config.medic.toml + config.toml 일부 + .env. 표준 라이브러리만 쓴다.

두 toml은 저마다 `*.local.toml`(있으면)을 깊은 병합으로 겹쳐 읽는다(릴리스 흐름 스펙 5.2, 5.3).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import time
from pathlib import Path
from typing import Any

from my_planner_medic.toml_overlay import read_overlaid

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
    branch: str = "main"  # 업데이터가 따라가는 브랜치(스테이징 인스턴스는 develop)
    be_task_name: str = "my-planner"  # 업데이터가 끄고 켜는 BE 작업 스케줄러 작업
    db_restore_max_age_minutes: int = 60  # 배포 뒤 이보다 늦은 확인 실패에는 바뀐 DB를 되돌리지 않는다
    # medic-dev(릴리스 흐름 스펙 5.3): config.medic.local.toml에서만 바꾼다. 기본값이 운영 값이다
    watch_incidents: bool = True  # 끄면 이슈 동기화·Actions 이슈 가져오기·ci:main 닫기·결과 알림을 모두 하지 않는다
    heartbeat: bool = True  # 끄면 하트비트 이슈를 쓰지 않는다
    post_commit_status: bool = False  # 켜면 확인이 끝난 머리 SHA에 `staging/be` 커밋 상태를 올린다
    # 웹 확인이 보는 Vercel 커밋 상태 컨텍스트(최종 리뷰 I-3). 기본값은 scripts/promote_check.py와 같다
    # (저장소 변수 VERCEL_CONTEXT_APP·VERCEL_CONTEXT_DASHBOARD를 바꾸면 여기도 같이 바꾼다). 대시는 en dash(–)
    vercel_context_app: str = "Vercel – my-planner"
    vercel_context_dashboard: str = "Vercel – my-planner-dashboard"

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
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _parse_time(value: str) -> time:
    parts = [int(p) for p in value.split(":")]
    if len(parts) not in (2, 3):
        raise ValueError(f"bad time: {value!r}")
    return time(*parts)


def load_config(root: Path, environ: Mapping[str, str] | None = None) -> MedicConfig:
    medic = read_overlaid(root / "config.medic.toml", root / "config.medic.local.toml")
    base = read_overlaid(root / "config.toml", root / "config.local.toml")  # [api] port를 여기서 읽는다(medic-dev → 8788)
    env_path = root / ".env"
    file_env = parse_env(env_path.read_text(encoding="utf-8-sig")) if env_path.exists() else {}
    process_env = os.environ if environ is None else environ

    def secret(key: str) -> str | None:
        # BE(pydantic-settings)와 같은 우선순위: 프로세스 환경변수 > .env
        return process_env.get(key) or file_env.get(key) or None

    api = base.get("api", {})
    host = api.get("host", "127.0.0.1")
    port = api.get("port", 8787)
    token = secret("API_TOKEN")
    api_enabled = bool(api.get("enabled", True)) and token is not None and (
        len(token) >= API_TOKEN_MIN_CHARS
    )
    # [runtime] role = "dev"(개발용 체크아웃): 개발용 .env에 운영 텔레그램 값이 잘못 들어가도 알리지 않는다
    runtime = base.get("runtime")
    dev = isinstance(runtime, dict) and runtime.get("role") == "dev"
    known = {f.name for f in fields(MedicConfig)}
    overrides = {k: v for k, v in medic.items() if k in known and k not in _RESERVED}
    return MedicConfig(
        root=root,
        enabled=bool(medic.get("enabled", True)),
        api_base=f"http://{host}:{port}/api/v1",
        api_enabled=api_enabled,
        api_token=token,
        github_token=secret("MEDIC_GITHUB_TOKEN"),
        telegram_token=None if dev else secret("TELEGRAM_BOT_TOKEN"),
        owner_telegram_id=None if dev else secret("OWNER_TELEGRAM_ID"),
        timezone=base.get("timezone", "Asia/Seoul"),
        day_boundary=_parse_time(base.get("day_boundary", "04:00")),
        schedule=base.get("schedule", {}),
        **overrides,
    )


_RESERVED = {
    "root", "enabled", "api_base", "api_enabled", "api_token", "github_token",
    "telegram_token", "owner_telegram_id", "timezone", "day_boundary", "schedule",
}

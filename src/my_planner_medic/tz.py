"""시간대. Windows에서 tzdata는 venv 패키지라, venv가 깨져도 medic이 돌도록 고정 오프셋으로 물러선다."""

from __future__ import annotations

from datetime import UTC, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_FIXED = {"Asia/Seoul": timezone(timedelta(hours=9), "Asia/Seoul")}  # 서머타임 없음


def zone(name: str) -> tzinfo:
    """`ZoneInfo(name)`. 못 찾으면 Asia/Seoul은 고정 +09:00, 그 밖은 UTC."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return _FIXED.get(name, UTC)

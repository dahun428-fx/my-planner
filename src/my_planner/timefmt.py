"""API 경계의 시각 모양 (SP3-4 스펙 6.1). `api/`와 `tools/`(즉시 갈래의 `result`)가 함께 쓴다.

응답의 시각은 UTC ISO 8601(`2026-10-24T09:00:00Z`)이다. 저장소와 도구 결과는 오프셋 붙은 ISO(`+00:00`, `+09:00`)를
주므로 `to_api_times`가 경계에서 바꾼다. 날짜(`2026-10-24`)와 기간은 그대로 둔다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

# 오프셋(또는 Z)이 붙은 ISO 시각만. 날짜만 있는 값과 오프셋 없는 시각은 건드리지 않는다
_OFFSET_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$")


def api_time(dt: datetime) -> str:
    """UTC `Z` 형식. 마이크로초가 0이면 초까지만 쓴다."""
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# 시각 필드 이름(스펙 6.1 "시각 필드를 변환"). 이 이름이거나 `_at`으로 끝나는 키의 값만 바꾼다
TIME_KEYS = frozenset({"now", "at", "scheduled_for", "since", "limited_until", "paused_until", "reply_until"})


def is_time_key(key: str | None) -> bool:
    return key is not None and (key in TIME_KEYS or key.endswith("_at"))


def to_api_times(value: Any, *, key: str | None = None) -> Any:
    """dict·list 안의 시각 필드(`is_time_key`) 값 가운데 오프셋 붙은 ISO 문자열을 UTC `Z`로 바꾼다.

    키를 본다: 할 일 제목이나 메모가 우연히 시각 모양이어도 바꾸지 않는다. `datetime` 값은 늘 바꾼다.
    """
    if isinstance(value, dict):
        return {k: to_api_times(v, key=k) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_api_times(v, key=key) for v in value]
    if isinstance(value, datetime):
        return api_time(value)
    if isinstance(value, str) and is_time_key(key) and _OFFSET_ISO.match(value):
        try:
            return api_time(datetime.fromisoformat(value))
        except ValueError:
            return value
    return value

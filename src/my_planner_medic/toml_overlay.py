"""`*.local.toml` 겹쳐 읽기 (릴리스 흐름 스펙 5.2, 5.3). 표준 라이브러리만 쓴다.

BE(`my_planner.config.load_settings`)와 medic(`config.load_config`)이 같은 병합을 쓴다. medic은 `my_planner`를
가져오지 않으므로 이 모듈이 medic 쪽에 있다.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def deep_merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """키 단위 깊은 병합: 둘 다 표면 재귀로 합치고, 표가 아닌 값과 목록은 `over` 값으로 통째로 바꾼다. 원본은 그대로."""
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def read_overlaid(path: Path, local: Path) -> dict[str, Any]:
    """`path` 위에 `local`(있으면)을 깊은 병합으로 겹친다. 둘 다 없으면 빈 표."""
    return deep_merge(read_toml(path), read_toml(local))

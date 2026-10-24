"""도구 모듈이 함께 쓰는 꾸밈 함수 (`tools/core.py`, `tools/habits.py`). 두 모듈이 서로 가져오지 않게 여기 둔다."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from my_planner.domain import RunContext


def _err(msg: str) -> dict[str, Any]:
    return {"error": msg}


def _tool(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """부른 도구 이름(인자 없이)을 `ctx.tool_names`에 남긴다. 원문 기록의 `> 도구:` 줄과 로그가 쓴다."""

    @functools.wraps(fn)
    def wrapper(self: Any, ctx: RunContext, *args: Any, **kwargs: Any) -> dict[str, Any]:
        ctx.tool_names.append(fn.__name__)
        return fn(self, ctx, *args, **kwargs)

    return wrapper

"""이룬 순간 도구 (SP8 스펙 6.3 M1~M5, ADR 0013). `Tools`가 이 mixin을 상속한다.

`save_moments`는 하루 끝 순간 호출(`RunContext.kind == "moments"`)에만 있다(`mcp_adapter.tool_names_for`). 여기서 한 번
더 막는다. 순간의 글은 `status_moments`에만 쓴다: 활동 `summary`, 도구 이벤트, 로그에는 날짜와 개수만 남긴다.
경험치는 주지 않는다(6.6).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import TYPE_CHECKING, Any

from my_planner.domain import Area, RunContext, ToolEvent
from my_planner.store.db import transaction
from my_planner.tools._base import _err, _tool
from my_planner.tools.ui import banned_words

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.moments import MomentsRepo

MOMENTS_PER_DAY = 3
MOMENT_TEXT_MAX = 60  # 코드포인트(SQLite `length()`와 같다)
SOURCES_MIN, SOURCES_MAX = 1, 5
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LINE_BREAKS = frozenset("\u0085\u2028\u2029")
_BIDI = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")

# 부록 A "도구 오류"
MSG_NOT_HERE = "쓸 수 없는 도구예요."
MSG_OTHER_DATE = "이 날짜만 정리할 수 있어요."
MSG_TOO_MANY = "이룬 순간은 하루 3개까지예요."
MSG_SOURCES = "근거로 쓸 수 없는 항목이 있어요."
# 계획 문구 표(`add_milestone` 영역 오류와 같은 글)
MSG_AREA = "area는 career, finance, health, relationships, learning, quality_of_life 가운데 하나예요."
# 부록 A 밖(SP8-03이 더함, H4 확인): 글 모양 오류
MSG_TEXT = "이룬 순간은 앞뒤 공백을 뺀 1~60자 한 줄로 써 주세요."


def moments_summary(n: int, d: date) -> str:
    """활동 한 줄(부록 A): 날짜와 개수만. 순간의 글은 넣지 않는다."""
    return f"이룬 순간 {n}개 정리 ({d.month}/{d.day})"


def moments_target(d: date) -> str:
    return f"moments:{d.isoformat()}"


def _bad_char(text: str) -> bool:
    """줄바꿈·제어 문자·방향 문자."""
    return any(unicodedata.category(c) == "Cc" or c in _LINE_BREAKS or c in _BIDI for c in text)


def _check_item(item: Any, refs: frozenset[str]) -> tuple[str, str | None, list[str]] | str:
    """(글, 영역, 근거) 또는 오류 문구(M2)."""
    if not isinstance(item, dict):
        return MSG_TEXT
    text = item.get("text")
    if not isinstance(text, str):
        return MSG_TEXT
    text = text.strip()
    if not 1 <= len(text) <= MOMENT_TEXT_MAX or _bad_char(text):
        return MSG_TEXT
    area = item.get("area")
    if area is not None:
        try:
            area = Area(area).value
        except ValueError:
            return MSG_AREA
    sources = item.get("sources")
    if (
        not isinstance(sources, list)
        or not SOURCES_MIN <= len(sources) <= SOURCES_MAX
        or not all(isinstance(s, str) and s in refs for s in sources)
    ):
        return MSG_SOURCES
    return text, area, list(dict.fromkeys(sources))


class MomentTools:
    """`save_moments` 하나. `Tools`의 공통 부품(`_record`)을 쓴다."""

    moments: MomentsRepo | None

    if TYPE_CHECKING:
        clock: Clock

        def _record(self, ctx: RunContext, kind: str, target: str | None, summary: str | None,
                    undo: dict[str, Any] | None, *, targets: list[str] | None = None) -> None: ...

    @_tool
    def save_moments(self, ctx: RunContext, date: Any = None, moments: Any = None) -> dict[str, Any]:
        """그날의 이룬 순간 0~3개를 저장하고 그날을 `done`으로(M1~M5). 금지어가 든 항목만 버린다(M3)."""
        if ctx.kind != "moments" or self.moments is None:
            return _err(MSG_NOT_HERE)
        day = ctx.moments_date
        if day is None or not (isinstance(date, str) and _ISO_DATE.fullmatch(date)) or date != day.isoformat():
            return _err(MSG_OTHER_DATE)  # M1
        current = self.moments.day(day)
        if current is not None and current.state == "done":
            return {"already": True}  # M4
        if not isinstance(moments, list) or len(moments) > MOMENTS_PER_DAY:
            return _err(MSG_TOO_MANY)  # M2
        checked: list[tuple[str, str | None, list[str]]] = []
        for item in moments:
            got = _check_item(item, ctx.moments_refs)
            if isinstance(got, str):
                return _err(got)  # M2: 하나라도 틀리면 아무것도 저장하지 않는다
            checked.append(got)
        words = banned_words()
        kept = [c for c in checked if not any(w in c[0] for w in words)]  # M3
        rejected = len(checked) - len(kept)
        now = self.clock.now()
        with transaction(self.moments.conn):  # M5
            self.moments.save_day(day, kept, now)
            if kept:
                self._record(ctx, "moments_saved", moments_target(day), moments_summary(len(kept), day), None)
        data = {"date": day.isoformat(), "saved": len(kept), "rejected": rejected}
        ctx.events.append(ToolEvent("moments_saved", None, data))
        return {"saved": len(kept), "rejected": rejected}

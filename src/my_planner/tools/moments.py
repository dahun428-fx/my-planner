"""이룬 순간 도구 (SP8 스펙 6.3 M1~M5, 6.4, ADR 0013). `Tools`가 이 mixin을 상속한다.

숨기기·다시 보이기·지우기(`hide_moment`, `unhide_moment`, `delete_moment`)는 앱 상태창의 `/actions`에만 있다(두뇌
도구 목록에는 없다). 활동 `summary`에는 날짜만 넣는다.

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
from my_planner.tools.activity import SUPERSEDED, moment_target, register_undo
from my_planner.tools.ui import banned_words

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.moments import Moment, MomentsRepo

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
MSG_SHAPE = "moments는 0~3개의 배열로 보내 주세요."
MSG_NO_MOMENT = "없는 순간이에요."  # 계획 문구 표(6.4 `404 not_found`)
NOT_FOUND = "not_found"  # 도구 결과의 `error_code`: 즉시 갈래가 `404 not_found`로 바꾼다(계획 결정 9)


def moments_summary(n: int, d: date) -> str:
    """활동 한 줄(부록 A): 날짜와 개수만. 순간의 글은 넣지 않는다."""
    return f"이룬 순간 {n}개 정리 ({d.month}/{d.day})"


def moment_line(kind: str, d: date) -> str:
    """숨기기·다시 보이기·지우기 활동 한 줄(부록 A): 날짜만."""
    verb = {"moment_hidden": "숨김", "moment_unhidden": "다시 보임", "moment_deleted": "지움"}[kind]
    return f"이룬 순간 {verb} ({d.month}/{d.day})"


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


def _not_found() -> dict[str, Any]:
    return {"error": MSG_NO_MOMENT, "error_code": NOT_FOUND}


class MomentTools:
    """`save_moments`(두뇌, 순간 호출만)와 숨기기·다시 보이기·지우기(`/actions`). `Tools`의 공통 부품(`_record`)을 쓴다."""

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
        if not isinstance(moments, list):
            return _err(MSG_SHAPE)  # M2
        if len(moments) > MOMENTS_PER_DAY:
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

    def _moment(self, id: Any) -> Moment | None:
        if self.moments is None or not isinstance(id, int) or isinstance(id, bool):
            return None
        return self.moments.get(id)

    @_tool
    def hide_moment(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """숨긴다(6.4, low, 24시간 되돌리기). 이미 숨겼으면 바꾸지 않고 `already`. 없는 순간은 `not_found`."""
        m = self._moment(id)
        if m is None or self.moments is None:
            return _not_found()
        if m.hidden_at is not None:
            return {"already": True}
        with transaction(self.moments.conn):
            self.moments.hide(m.id, self.clock.now())
            self._record(ctx, "moment_hidden", moment_target(m.id), moment_line("moment_hidden", m.date),
                         {"moment_id": m.id, "hidden_at": None})
        return {"id": m.id, "date": m.date.isoformat(), "hidden": True}

    @_tool
    def unhide_moment(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """다시 보이게 한다(되돌리면 이전 `hidden_at`으로 다시 숨긴다). 숨기지 않은 순간은 `already`."""
        m = self._moment(id)
        if m is None or self.moments is None:
            return _not_found()
        if m.hidden_at is None:
            return {"already": True}
        with transaction(self.moments.conn):
            prev = self.moments.unhide(m.id)
            self._record(ctx, "moment_unhidden", moment_target(m.id), moment_line("moment_unhidden", m.date),
                         {"moment_id": m.id, "hidden_at": prev})
        return {"id": m.id, "date": m.date.isoformat(), "hidden": False}

    @_tool
    def delete_moment(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """행을 지운다(되돌릴 수 없다). 그날은 다시 정리하지 않는다(날 행 `done` 그대로, 6.4)."""
        m = self._moment(id)
        if m is None or self.moments is None:
            return _not_found()
        with transaction(self.moments.conn):
            self.moments.delete(m.id)
            self._record(ctx, "moment_deleted", moment_target(m.id), moment_line("moment_deleted", m.date), None)
        return {"id": m.id, "date": m.date.isoformat(), "deleted": True}


def _undo_moment_hidden(tools: Any, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """`hidden_at`을 활동 전 값으로(숨기기 → NULL, 다시 보이기 → 이전 값). 행이 없으면(지웠으면) superseded."""
    repo = tools.moments
    if repo is None or not repo.restore_hidden(undo["moment_id"], undo["hidden_at"]):
        return SUPERSEDED
    return None


register_undo("moment_hidden", _undo_moment_hidden)
register_undo("moment_unhidden", _undo_moment_hidden)

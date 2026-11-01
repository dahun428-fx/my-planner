"""패널 쓰기 도구 (SP15 스펙 5.4, 7장, 9장, 10장). `Tools`가 이 mixin을 상속한다.

지금은 뼈대다: 도구 목록(`mcp_adapter.PANEL_WRITE_TOOLS`, `REPORT_TOOLS`)이 서버를 만들 수 있게 이름만 둔다.
`propose_suggestion`·`save_statement`·`record_prediction`은 계획 Task 8이, `save_life_report`는 Task 13이 채운다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from my_planner.domain import RunContext
from my_planner.tools._base import _err, _tool

if TYPE_CHECKING:
    from my_planner.store.repos.panel import PanelRepo

MSG_NOT_YET = "아직 없어요."


class PanelTools:
    """라이프 매니저의 쓰기 도구(제안 카드, 내가 한 말, 예측, 인생 리포트)."""

    panel: PanelRepo | None

    @_tool
    def propose_suggestion(self, ctx: RunContext, **_: Any) -> dict[str, Any]:
        return _err(MSG_NOT_YET)

    @_tool
    def save_statement(self, ctx: RunContext, **_: Any) -> dict[str, Any]:
        return _err(MSG_NOT_YET)

    @_tool
    def record_prediction(self, ctx: RunContext, **_: Any) -> dict[str, Any]:
        return _err(MSG_NOT_YET)

    @_tool
    def save_life_report(self, ctx: RunContext, **_: Any) -> dict[str, Any]:
        return _err(MSG_NOT_YET)

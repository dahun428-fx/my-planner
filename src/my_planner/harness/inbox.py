"""받은편지함 사건 줄 (SP14 스펙 6.2, 7장). 하루 끝 판단 입력과 즉시 판단 블록이 같은 줄 모양을 쓴다.

줄에는 종류·`ref`(id)·영역·날짜만 있다(제목·본문·값 없음, 스펙 1장 8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_planner.store.repos.agents import AgentEvent


def event_line(e: AgentEvent) -> str:
    """`- {kind} {ref} · {area} · {day}`. 영역이 없으면 그 칸을 뺀다."""
    parts = [f"{e.kind} {e.ref}", *([e.area] if e.area else []), e.day.isoformat()]
    return "- " + " · ".join(parts)

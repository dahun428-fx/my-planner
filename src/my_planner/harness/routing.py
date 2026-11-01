"""사건 → 받은편지함 상대 (SP14 스펙 5.3). 코드 규칙이고 두뇌는 부르지 않는다."""

from __future__ import annotations

from my_planner.domain import EVENT_KINDS, EventKind, InboxAgent

_BOTH: tuple[InboxAgent, ...] = ("mate", "manager")
_MANAGER: tuple[InboxAgent, ...] = ("manager",)
_MATE_ALSO = frozenset({
    "condition_logged", "body_logged", "workout_logged", "event_added", "event_changed", "event_removed",
})


def route(kind: EventKind, area: str | None, *, handoff_to: InboxAgent | None = None) -> tuple[InboxAgent, ...]:
    """받을 상대. 튜플 순서는 늘 `("mate", "manager")`. `handoff`만 `handoff_to`가 필요하다."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"모르는 사건 종류: {kind}")
    if kind == "handoff":
        if handoff_to is None:
            raise ValueError("handoff에는 handoff_to가 필요해요.")
        return (handoff_to,)
    if handoff_to is not None:
        raise ValueError("handoff_to는 handoff에만 줄 수 있어요.")
    if kind in _MATE_ALSO or (kind == "measure_saved" and area == "health"):
        return _BOTH
    return _MANAGER

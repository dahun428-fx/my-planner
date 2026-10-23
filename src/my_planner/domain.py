"""도메인 이름 (GLOSSARY.md의 코드 식별자)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Area(StrEnum):
    career = "career"
    finance = "finance"
    health = "health"
    relationships = "relationships"
    learning = "learning"
    quality_of_life = "quality_of_life"


class Cadence(StrEnum):
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"


class TaskStatus(StrEnum):
    draft = "draft"
    open = "open"
    done = "done"
    dropped = "dropped"


class RunStatus(StrEnum):
    pending = "pending"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"
    interrupted = "interrupted"


class SkipReason(StrEnum):
    late = "late"
    merged_into_return = "merged_into_return"
    paused = "paused"
    auth = "auth"
    rate_limit = "rate_limit"
    daily_cap = "daily_cap"


class LoopKey(StrEnum):
    morning_brief = "morning_brief"
    evening_checkin = "evening_checkin"
    review = "review"
    return_ = "return"  # `return`은 예약어라서 멤버 이름에 밑줄을 붙인다


class ConversationKind(StrEnum):
    run = "run"
    chat = "chat"
    plan = "plan"  # 용어집의 계획 모드


@dataclass
class ToolEvent:
    kind: str
    task_id: int | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    """도구 호출 한 묶음의 맥락. 버튼과 명령은 `conversation_id=None`으로 만든다."""

    conversation_id: int | None
    run_id: int | None
    events: list[ToolEvent] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)  # 부른 도구 이름(인자 없이). 원문 기록과 로그에 쓴다

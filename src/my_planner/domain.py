"""도메인 이름 (GLOSSARY.md의 코드 식별자)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


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


Channel = Literal["telegram", "app"]  # 대화 통로 (SP3-4 스펙 5.1)
ActivityChannel = Literal["app", "telegram", "scheduler"]  # 활동 통로 (5.2)
Actor = Literal["secretary", "user"]  # 활동 행위자 (5.2)
Risk = Literal["low", "confirm"]  # 활동 위험 (5.2, 6.4.2)


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
    inbound_id: int | None = None  # 사용자 메시지 처리면 묶음의 첫 update_id(`inbound_pending`, 도구 호출 기록에 잇는다)
    # 활동 기록(SP3-4 스펙 5.2, 6.4.4). 두뇌가 바꾸면 `secretary` + 그 대화의 통로, 버튼·`/actions`는 `user`
    actor: Actor = "secretary"
    activity_channel: ActivityChannel | None = None  # None이면 `channel`. 회차 첫 호출과 하루 한 번 작업은 `scheduler`
    channel: Channel = "telegram"
    risk: Risk = "low"  # `confirm`: 확인 토큰으로 적용한 변경(되돌릴 수 없다, 6.4.2)
    activity_ids: list[int] = field(default_factory=list)  # 이 묶음에서 생긴 활동 id
    undo_ids: list[int] = field(default_factory=list)  # 그 가운데 되돌릴 수 있는 것
    # 앱 채팅의 조각 쓰개(`harness.stream.UiMessageWriter`, 6.4.1). 있으면 도구마다 `tool-*` 조각을 쓴다
    stream: Any = None

    @property
    def run_turn(self) -> bool:
        """회차 차례(SP3-4 10.1 A1): 회차를 실행하는 두뇌 호출. 통로와 상관없다.

        사용자 메시지에 답하는 차례(회차 대화의 답 포함)는 `inbound_id`가 있다(A3). 버튼과 `/actions`는 `run_id`가 없다.
        """
        return self.run_id is not None and self.inbound_id is None

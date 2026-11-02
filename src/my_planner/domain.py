"""도메인 이름 (GLOSSARY.md의 코드 식별자)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Literal, get_args

from my_planner.status.xp import XpGain


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
# 대화 상대 (SP12 스펙 5.1). 도구 목록·지시문·앞머리를 고르는 열쇠. 메이트 대화는 늘 앱 통로의 `chat`이다
Agent = Literal["secretary", "mate", "manager"]
Risk = Literal["low", "confirm"]  # 활동 위험 (5.2, 6.4.2)
# 두뇌 호출의 종류 (SP8 스펙 6.3). 회차 호출은 `run`, 하루 끝 순간은 `moments`, 대화 요약은 `summary`(SP9 7.2, 도구 없음),
# 사진 읽기는 `photo_read`(SP10 5.4, 도구 없음)
RunKind = Literal["chat", "run", "moments", "summary", "photo_read", "dayend"]

# 사건 기록(SP14 스펙 5.1~5.3). 종류 18개, 출처 5개, 받은편지함이 있는 아래층 상대 둘
EventKind = Literal[
    "task_done", "task_postponed", "task_added", "task_dropped", "event_added", "event_changed", "event_removed",
    "memo_saved", "habit_checked", "condition_logged", "body_logged", "workout_logged", "measure_saved",
    "moment_saved", "review_answered", "suggestion_accepted", "suggestion_dismissed", "handoff",
]
EVENT_KINDS: tuple[str, ...] = get_args(EventKind)
EventOrigin = Literal["app", "telegram", "scheduler", "brain", "import"]
EVENT_ORIGINS: tuple[str, ...] = get_args(EventOrigin)
InboxAgent = Literal["mate", "manager"]
INBOX_AGENTS: tuple[InboxAgent, ...] = ("mate", "manager")


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
    # 이 답에서 두뇌 화면 도구가 스트림에 쓴 조각 수(SP6 10.4 `mcp_adapter.UI_PARTS_PER_REPLY`). 하네스 조각은 세지 않는다
    ui_drawn: int = 0
    # 그 조각들의 컴포넌트 이름(그린 순서, SP9c 4.4). 칩 카드 보장이 두뇌가 이미 그린 카드를 본다
    ui_drawn_names: list[str] = field(default_factory=list)
    # 이 묶음의 도구가 쌓은 경험치와 넘긴 레벨(`status.xp.XpGain`, SP3-4 9.2). 레벨 오름 한 줄은 이것으로만 정한다
    xp: XpGain = field(default_factory=XpGain)
    # 두뇌 호출의 종류(SP8 6.3). `moments`면 도구는 `save_moments` 하나뿐이다(`mcp_adapter.tool_names_for`)
    kind: RunKind = "chat"
    moments_date: date | None = None  # 하루 끝 작업이 정리하는 그 날(M1)
    moments_refs: frozenset[str] = frozenset()  # 그 입력에 나온 참조(`task:<id>`, `habit:<id>`, `workout:<id>`, `condition`, `chat`, M2)
    # 두뇌가 호출 중에 처음 본 세션 id(두뇌 구현이 적는다). 시간 초과·취소로 결과가 없어도 순간 호출 뒤
    # 세션 파일을 지울 수 있게(SP8 6.3, 계획 결정 18)
    brain_session_id: str | None = None
    # 앱 퀵 칩(SP9c 4.2). `chip_text`는 메모 칩 차례에만, 가리기·자르기 전 원문(메모리로만, 저장·로그 없음, 4.5)
    chip: str | None = None
    chip_text: str | None = None
    agent: Agent = "secretary"  # 대화 상대(SP12 5.1). `mate`면 `mate.md`와 `MATE_TOOLS`
    in_brain: bool = False  # 두뇌 호출 안의 도구 호출(SP14 Task 2)
    dayend_day: date | None = None  # 하루 끝 판단이 판단하는 날(Task 3)
    notes_written: int = 0  # 이 호출에서 저장한 관찰 수(Task 3)
    panel_rejects: int = 0  # 이 호출에서 거절된 패널 제안 수(SP15 Task 8)
    full_diagnosis: bool = False  # "전체 진단" 호출(SP15 Task 12)

    @property
    def run_turn(self) -> bool:
        """회차 차례(SP3-4 10.1 A1): 회차를 실행하는 두뇌 호출. 통로와 상관없다.

        사용자 메시지에 답하는 차례(회차 대화의 답 포함)는 `inbound_id`가 있다(A3). 버튼과 `/actions`는 `run_id`가 없다.
        """
        return self.run_id is not None and self.inbound_id is None

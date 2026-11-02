"""전문가 서브에이전트 (SP15 스펙 6.1·6.2, 스파이크 S1).

라이프 매니저 두뇌 호출 안에서 SDK 서브에이전트로 부르는 전문가 여섯. 전문가는 읽기 도구만 받고 Dahun에게 직접 말하지
않는다. `SubagentGate`는 한 메시지의 전문가 수를 막고 SDK 내장 서브에이전트(`general-purpose` 같은)를 늘 거절한다.
`collect_expert_notes`는 본 스레드가 받은 소견 원문을 부른 순서로 모은다.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any, Literal

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from my_planner.harness import prompts
from my_planner.tools.mcp_adapter import EXPERT_TOOLS, SERVER_NAME

Expert = Literal["career", "finance", "health", "image", "relationship", "psych"]
EXPERTS: tuple[Expert, ...] = ("career", "finance", "health", "image", "relationship", "psych")
EXPERT_LABELS: dict[Expert, str] = {
    "career": "커리어 전략가",
    "finance": "재무설계사",
    "health": "건강 전문의",
    "image": "이미지 컨설턴트",
    "relationship": "관계 코치",
    "psych": "심리 코치",
}
# 라이프 매니저가 서브에이전트 정의를 고를 때 보는 한 줄 관점(AgentDefinition.description)
EXPERT_VIEWS: dict[Expert, str] = {
    "career": "일의 방향, 시장에서 보이는 증거, 옮길 때와 머물 때를 봅니다",
    "finance": "현금 흐름, 빚과 비상금, 큰 결정 전의 여유를 봅니다",
    "health": "몸의 기록, 근력·식사·수면·검진 수치의 균형을 봅니다",
    "image": "피부·머리·옷·사진 인상처럼 겉으로 보이는 첫인상을 봅니다",
    "relationship": "만남이 생기는 길과 사람 사이의 꾸준한 접점을 봅니다",
    "psych": "마음의 여력, 비교와 자기 평가, 쉼과 회복을 봅니다",
}

EXPERTS_PER_MESSAGE = 2
EXPERTS_FULL = 6
EXPERT_MAX_TURNS = 6

# 스파이크 S1: 모델이 부르는 도구 이름과 훅의 `tool_name`은 "Agent"다. `init` 도구 목록에는 "Task"로 나와 둘 다 본다
SUBAGENT_TOOL = "Agent"
SUBAGENT_TOOL_NAMES: tuple[str, ...] = (SUBAGENT_TOOL, "Task")
SUBAGENT_HOOK_MATCHER = "|".join(SUBAGENT_TOOL_NAMES)

NOT_EXPERT_REASON = "부를 수 있는 전문가가 아니에요."


@dataclass(frozen=True)
class ExpertNote:
    expert: Expert
    text: str


def expert_definitions() -> dict[str, AgentDefinition]:
    """전문가마다 SDK 서브에이전트 정의. 도구는 자기 읽기 도구(`EXPERT_TOOLS`)만, 모델은 본 스레드와 같게."""
    return {
        k: AgentDefinition(
            description=f"{EXPERT_LABELS[k]}. {EXPERT_VIEWS[k]}",
            prompt=prompts.load(f"experts/{k}.md"),
            tools=[f"mcp__{SERVER_NAME}__{t}" for t in EXPERT_TOOLS[k]],
            model="inherit",
            maxTurns=EXPERT_MAX_TURNS,
        )
        for k in EXPERTS
    }


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


class SubagentGate:
    """`PreToolUse` 훅 콜백. 두뇌 호출 하나에 하나를 새로 만든다.

    전문가가 아닌 `subagent_type`(SDK 내장 서브에이전트는 본 스레드 도구를 물려받아 쓰기 도구에 닿는다)은 늘 거절하고
    세지 않는다. 전문가인지는 전역 `EXPERTS`로 본다(이 호출의 `agents`에 없는 이름은 CLI가 어차피 거절한다).
    `count`는 전문가 호출 시도 수다: `cap`을 넘어 거절된 호출도 센다. `allowed_ids`는 통과시킨 호출의 `tool_use_id`
    (소견 모으기가 이것만 짝짓는다).
    """

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.count = 0
        self.allowed_ids: set[str] = set()

    async def __call__(self, input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if input_data.get("tool_name") not in SUBAGENT_TOOL_NAMES:
            return {}
        tool_input = input_data.get("tool_input") or {}
        if tool_input.get("subagent_type") not in EXPERTS:
            return _deny(NOT_EXPERT_REASON)
        self.count += 1
        if self.count > self.cap:
            return _deny(f"전문가는 한 메시지에 {self.cap}명까지예요.")
        if tool_use_id is not None:
            self.allowed_ids.add(tool_use_id)
        return {}


# CLI(번들 2.1.309)가 끝난 서브에이전트 결과를 싸는 틀. 머리말 뒤 "The report follows:" 다음이 보고(줄마다 들여쓰기)이고,
# Explore·Plan이 아닌 서브에이전트는 끝에 "agentId: ... <usage>...</usage>" 꼬리가 붙는다(같은 글 블록이나 따로 된 블록)
HANDBACK_MARK = "[Subagent hand-back]"
HANDBACK_REPORT = "The report follows:"
_TRAILER_BLOCK = re.compile(r"^agentId: .*<usage>.*</usage>$", re.DOTALL)
TRAILER_START = "\nagentId: "


def _result_text(content: Any) -> str:
    """서브에이전트 결과 글에서 CLI 틀(머리말·꼬리)을 걷어 낸 보고 원문. 틀이 없는 글은 그대로(앞뒤 공백만)."""
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [
            b["text"] for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
    else:
        return ""
    blocks = [b for b in blocks if not _TRAILER_BLOCK.match(b.strip())]
    text = "\n".join(blocks)
    mark = text.find(HANDBACK_MARK)
    if mark >= 0:
        report = text.find(HANDBACK_REPORT, mark)
        if report >= 0:
            text = text[report + len(HANDBACK_REPORT):]
    tail = text.rfind(TRAILER_START)
    if tail >= 0 and "<usage>" in text[tail:] and text.rstrip().endswith("</usage>"):
        text = text[:tail]
    return textwrap.dedent(text).strip()


def collect_expert_notes(messages: list[object], allowed_ids: set[str] | None = None) -> tuple[ExpertNote, ...]:
    """본 스레드의 전문가 호출과 그 결과 글을 부른 순서로 짝짓는다. 모르는 전문가·빈 글·오류 결과·서브에이전트 안 호출은 뺀다.

    `allowed_ids`(`SubagentGate.allowed_ids`)가 있으면 문지기가 통과시킨 호출만 짝짓는다.
    """
    calls: dict[str, Expert] = {}  # 부른 순서(dict 순서)
    texts: dict[str, str] = {}
    for m in messages:
        if getattr(m, "parent_tool_use_id", None) is not None:
            continue
        if isinstance(m, AssistantMessage):
            for block in m.content:
                if isinstance(block, ToolUseBlock) and block.name in SUBAGENT_TOOL_NAMES:
                    st = block.input.get("subagent_type")
                    if st in EXPERTS and (allowed_ids is None or block.id in allowed_ids):
                        calls[block.id] = st
        elif isinstance(m, UserMessage) and isinstance(m.content, list):
            for block in m.content:
                # 거절된 호출(상한·훅)은 거절 사유가 `is_error` 결과로 온다. 소견이 아니다
                if isinstance(block, ToolResultBlock) and not block.is_error:
                    texts[block.tool_use_id] = _result_text(block.content)
    return tuple(ExpertNote(expert, texts[tid]) for tid, expert in calls.items() if texts.get(tid))

"""도구 함수를 Agent SDK in-process MCP 서버 `planner`로 노출한다 (ADR 0005)."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

from my_planner.domain import RunContext

SERVER_NAME = "planner"

# 두뇌가 부를 수 있는 도구 이름(스펙 5.5 표 순서). 티켓마다 늘어난다.
TOOL_NAMES: list[str] = [
    "add_task",
    "update_task",
    "move_task",
    "complete_task",
    "reopen_task",
    "drop_task",
    "list_tasks",
    "read_transcript",
]

_AREAS = ["career", "finance", "health", "relationships", "learning", "quality_of_life"]
_DATE = {"type": ["string", "null"], "description": "논리적 날짜 YYYY-MM-DD"}
_DATETIME = {
    "type": ["string", "null"],
    "description": "시각이 있는 일의 날짜와 시각. 한국 시간 기준 ISO 8601, 예: 2026-10-25T14:00",
}
_ID = {"type": "integer", "description": "할 일 번호"}


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


# (이름, 설명, 입력 스키마). JSON 스키마의 "from"은 파이썬 이름 `from_`으로 넘기지 않고 그대로 받는다.
_SPECS: dict[str, tuple[str, dict[str, Any]]] = {
    "add_task": (
        "사용자가 직접 추가해 달라고 한 할 일을 바로 추가합니다. 비서가 제안하는 것에는 쓰지 않습니다.",
        _schema(
            {
                "title": {"type": "string", "description": "1~200자"},
                "areas": {
                    "type": "array",
                    "items": {"enum": _AREAS},
                    "minItems": 1,
                    "description": "영역 하나 이상",
                },
                "planned_for": _DATE,
                "scheduled_at": _DATETIME,
                "parent_id": {"type": ["integer", "null"], "description": "첫 걸음이면 부모 할 일 번호"},
                "note": {"type": ["string", "null"]},
            },
            ["title", "areas"],
        ),
    ),
    "update_task": (
        "할 일의 제목, 영역, 메모, 시각을 바꿉니다. 날짜는 move_task로 바꿉니다.",
        _schema(
            {
                "id": _ID,
                "title": {"type": "string"},
                "areas": {"type": "array", "items": {"enum": _AREAS}, "minItems": 1},
                "note": {"type": "string"},
                "scheduled_at": _DATETIME,
            },
            ["id"],
        ),
    ),
    "move_task": (
        "할 일을 하려는 날만 옮깁니다. planned_for가 null이면 날짜 없음으로 둡니다.",
        _schema({"id": _ID, "planned_for": _DATE}, ["id", "planned_for"]),
    ),
    "complete_task": ("할 일을 완료로 바꿉니다.", _schema({"id": _ID}, ["id"])),
    "reopen_task": (
        "완료했거나 내려놓은 할 일을 다시 엽니다.",
        _schema({"id": _ID}, ["id"]),
    ),
    "drop_task": ("할 일을 내려놓습니다.", _schema({"id": _ID}, ["id"])),
    "list_tasks": (
        "할 일을 조회합니다. status를 안 주면 열린 것과 초안을 돌려줍니다. 최대 50개.",
        _schema(
            {
                "status": {"enum": ["draft", "open", "done", "dropped"]},
                "from": _DATE,
                "to": _DATE,
                "area": {"enum": _AREAS},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            [],
        ),
    ),
    "read_transcript": (
        "지난 대화 원문 기록을 읽습니다. 최대 7일.",
        _schema({"from": {"type": "string"}, "to": {"type": "string"}}, ["from", "to"]),
    ),
}


def build_planner_tools(tools: Any, ctx: RunContext) -> list[SdkMcpTool[Any]]:
    """도구마다 `ctx`를 클로저로 감싼 SDK 도구 정의. 테스트는 `.handler`를 직접 await한다."""
    out: list[SdkMcpTool[Any]] = []
    for name in TOOL_NAMES:
        description, schema = _SPECS[name]
        out.append(
            SdkMcpTool(name=name, description=description, input_schema=schema,
                       handler=_handler(tools, ctx, name))
        )
    return out


def _handler(tools: Any, ctx: RunContext, name: str) -> Any:
    method = getattr(tools, name)

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        result = method(ctx, **args)
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "is_error": "error" in result,
        }

    return handler


def allowed_tool_patterns() -> list[str]:
    return [f"mcp__{SERVER_NAME}__*"]


def build_planner_server(tools: Any, ctx: RunContext) -> McpSdkServerConfig:
    """호출마다 새로 만든다. `ctx`는 도구 핸들러의 클로저로 넘긴다."""
    handlers = build_planner_tools(tools, ctx) if tools is not None else []
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=handlers)

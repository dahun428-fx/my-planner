"""도구 함수를 Agent SDK in-process MCP 서버 `planner`로 노출한다 (ADR 0005)."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

from my_planner.domain import Channel, RunContext
from my_planner.timefmt import to_api_times
from my_planner.tools.ui import BRAIN_COMPONENTS, UI_COMPONENTS

SERVER_NAME = "planner"

# 두뇌가 부를 수 있는 도구 이름(스펙 5.5 표 순서). 티켓마다 늘어난다.
TOOL_NAMES: list[str] = [
    "add_task",
    "propose_tasks",
    "confirm_tasks",
    "update_task",
    "move_task",
    "complete_task",
    "reopen_task",
    "drop_task",
    "set_priorities",
    "list_tasks",
    "record_condition",
    "read_transcript",
]

# 앱 대화에만 주는 도구(SP3-4 6.4.7, 10장): 화면 도구 셋(그리기만), 카드 도구 셋. 텔레그램 대화에는 없다
APP_ONLY_TOOLS: list[str] = [*BRAIN_COMPONENTS, "pin_card", "unpin_card", "reorder_cards"]

_AREAS = ["career", "finance", "health", "relationships", "learning", "quality_of_life"]
_DATE = {"type": ["string", "null"], "description": "논리적 날짜 YYYY-MM-DD"}
_DATETIME = {
    "type": ["string", "null"],
    "description": "시각이 있는 일의 날짜와 시각. 한국 시간 기준 ISO 8601, 예: 2026-10-25T14:00",
}
_ID = {"type": "integer", "description": "할 일 번호"}


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_NEW_TASK = _schema(
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
)

# (이름, 설명, 입력 스키마). JSON 스키마의 "from"은 파이썬 이름 `from_`으로 넘기지 않고 그대로 받는다.
_SPECS: dict[str, tuple[str, dict[str, Any]]] = {
    "add_task": (
        "사용자가 직접 추가해 달라고 한 할 일을 바로 추가합니다. 비서가 제안하는 것에는 쓰지 않습니다.",
        _NEW_TASK,
    ),
    "propose_tasks": (
        (
            "비서가 제안하는 할 일을 초안(draft)으로 저장합니다. 브리핑, 체크인, 회고, 계획 의논에서 비서가 "
            "먼저 꺼낸 할 일에 씁니다. 하네스가 메시지 아래에 초안마다 추가·빼기 버튼을 붙이므로 "
            "답에서 확정했다고 말하지 않습니다. 한 번에 최대 10개."
        ),
        _schema(
            {
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": _NEW_TASK,
                }
            },
            ["tasks"],
        ),
    ),
    "confirm_tasks": (
        (
            "초안을 열린(open) 할 일로 확정합니다. 사용자가 글로 \"좋아, 다 넣어\"처럼 동의했을 때 부릅니다. "
            "초안이 아닌 번호는 바꾸지 않고 skipped_ids로 돌려줍니다. 초안 번호는 list_tasks(status=draft)로 찾습니다."
        ),
        _schema({"ids": {"type": "array", "items": _ID, "minItems": 1}}, ["ids"]),
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
        "완료했거나, 열린 채로 내려놓은 할 일을 다시 엽니다. 확정하지 않은 초안은 열지 않습니다.",
        _schema({"id": _ID}, ["id"]),
    ),
    "drop_task": ("할 일을 내려놓습니다.", _schema({"id": _ID}, ["id"])),
    "set_priorities": (
        (
            "그 기간의 우선순위를 통째로 바꿉니다. task_ids는 최대 3개이고 순서가 순위입니다. "
            "열린(open) 할 일만 올릴 수 있고 초안은 안 됩니다. 사용자가 정해 달라고 하거나 확인한 뒤에 부릅니다."
        ),
        _schema(
            {
                "cadence": {"enum": ["day", "week", "month", "quarter", "year"]},
                "period": {
                    "type": "string",
                    "description": "일 2026-10-23, 주 2026-W43(ISO 주), 월 2026-10, 분기 2026-Q4, 년 2026",
                },
                "task_ids": {"type": "array", "items": _ID, "maxItems": 3},
            },
            ["cadence", "period", "task_ids"],
        ),
    ),
    "list_tasks": (
        "할 일을 조회합니다. status를 안 주면 열린(open) 할 일만 돌려줍니다. 초안은 status=draft로 따로 묻습니다. 최대 50개.",
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
    "record_condition": (
        (
            "그날 컨디션을 1~5로 기록합니다. date를 안 주면 오늘(논리적 날짜)입니다. 같은 날 다시 기록하면 덮어씁니다. "
            "사용자가 한 줄 메모를 말하면 note에 넣습니다. note를 안 주면 전에 남긴 메모는 그대로 둡니다."
        ),
        _schema(
            {
                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                "date": _DATE,
                "note": {"type": ["string", "null"], "description": "한 줄 메모"},
            },
            ["score"],
        ),
    ),
    "read_transcript": (
        "지난 대화 원문 기록을 읽습니다. 최대 7일.",
        _schema({"from": {"type": "string"}, "to": {"type": "string"}}, ["from", "to"]),
    ),
}


_CARD_ID = {"type": "integer", "description": "고정 카드 번호"}
_SPECS.update({
    "ui_todo_list": (
        (
            "앱 화면에 할 일 목록 조각을 그립니다(그리기만 합니다). task_ids는 할 일 번호이고 최대 30개입니다. "
            "제목과 상태는 앱이 지금 값으로 보여 줍니다. 같은 뜻을 답 글에도 씁니다."
        ),
        UI_COMPONENTS["ui_todo_list"]["schema"],
    ),
    "ui_choice": (
        (
            "앱 화면에 고르기 조각을 그립니다(그리기만 합니다). 보기는 2~4개이고, 사용자가 고르면 그 label이 "
            "새 메시지로 옵니다. 같은 질문을 답 글에도 씁니다."
        ),
        UI_COMPONENTS["ui_choice"]["schema"],
    ),
    "ui_summary_card": (
        "앱 화면에 요약 카드를 그립니다(그리기만 합니다). lines는 최대 8줄, 줄마다 120자까지입니다.",
        UI_COMPONENTS["ui_summary_card"]["schema"],
    ),
    "pin_card": (
        (
            "화면 조각(ui_todo_list, ui_choice, ui_summary_card)을 앱의 고정 카드로 맨 뒤에 둡니다. "
            "props는 그 조각의 형식과 같아야 합니다. 사용자가 고정해 달라고 할 때만 부릅니다."
        ),
        _schema(
            {"component": {"enum": list(BRAIN_COMPONENTS)}, "props": {"type": "object"}},
            ["component", "props"],
        ),
    ),
    "unpin_card": ("고정 카드를 내립니다.", _schema({"id": _CARD_ID}, ["id"])),
    "reorder_cards": (
        "고정 카드의 순서를 바꿉니다. ids에는 고정한 카드 번호를 모두 새 순서로 넣습니다.",
        _schema({"ids": {"type": "array", "items": _CARD_ID, "minItems": 1}}, ["ids"]),
    ),
})


def tool_names_for(channel: Channel) -> list[str]:
    """그 통로 대화에 주는 도구(SP3-4 10장). 화면 도구(`ui_*`)와 카드 도구는 앱 대화에만 준다(6.4.7)."""
    return [*TOOL_NAMES, *APP_ONLY_TOOLS] if channel == "app" else list(TOOL_NAMES)


def _stream_output(tools: Any, name: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """스트림에 보낼 도구 출력(6.4.1). 할 일을 가리키는 `ui_todo_list`는 `data.todos`(지금 값 `TodoRef`, 초안·
    소프트 삭제 뺌)를 붙인다. 두뇌가 받는 결과는 `{"ok": true}` 그대로다."""
    if name == "ui_todo_list":
        return {**result, "data": {"todos": tools.ui_todo_refs(args.get("task_ids"), drafts=False)}}
    return result


def call_tool(tools: Any, ctx: RunContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """도구 하나를 부른다. `ctx.stream`(앱 채팅)이 있으면 입력 검증을 지난 뒤 `tool-input-available`을, 끝나면
    `tool-output-available`(결과의 시각은 UTC로, 6.1) 또는 `tool-output-error`(도구 오류 문구)를 쓴다(6.4.1).

    화면 도구(`ui_*`)는 부작용이 없으므로 먼저 부르고, props가 스키마에 맞을 때만 두 조각을 쓴다. 맞지 않으면 도구
    오류로 돌려주고 조각을 보내지 않는다(6.4.7).

    두뇌가 받는 결과는 그대로(현지 시각)다. 로그에는 아무것도 남기지 않는다.
    """
    w = ctx.stream
    ui = name in BRAIN_COMPONENTS
    call_id = w.next_tool_call_id() if w is not None and not ui else None  # 화면 도구는 조각을 쓸 때 받는다
    if w is not None and not ui:
        w.tool_input(call_id, name, args)
    try:
        result = getattr(tools, name)(ctx, **args)
    except Exception:
        if w is not None and not ui:
            w.tool_error(call_id, "도구를 실행하지 못했어요.")
        raise
    if w is not None:
        if ui:
            if "error" not in result:
                call_id = w.next_tool_call_id()
                w.tool_input(call_id, name, args)
                w.tool_output(call_id, to_api_times(_stream_output(tools, name, args, result)))
        elif "error" in result:
            w.tool_error(call_id, str(result["error"]))
        else:
            w.tool_output(call_id, to_api_times(result))
    return result


def build_planner_tools(tools: Any, ctx: RunContext) -> list[SdkMcpTool[Any]]:
    """도구마다 `ctx`를 클로저로 감싼 SDK 도구 정의. 테스트는 `.handler`를 직접 await한다."""
    out: list[SdkMcpTool[Any]] = []
    for name in tool_names_for(ctx.channel):
        description, schema = _SPECS[name]
        out.append(
            SdkMcpTool(name=name, description=description, input_schema=schema,
                       handler=_handler(tools, ctx, name))
        )
    return out


def _handler(tools: Any, ctx: RunContext, name: str) -> Any:
    getattr(tools, name)  # 없는 도구는 서버를 만들 때 바로 알린다

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        result = call_tool(tools, ctx, name, args)
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

"""도구 함수를 Agent SDK in-process MCP 서버 `planner`로 노출한다 (ADR 0005)."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

from my_planner.domain import Channel, RunContext
from my_planner.timefmt import to_api_times
from my_planner.tools.ui import BRAIN_COMPONENTS, PINNABLE_COMPONENTS, UI_COMPONENTS

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
    # 인생 곡선과 상태창(SP3-4 10장 표 순서)
    "record_ladder_score",
    "record_area_scores",
    "add_milestone",
    "confirm_milestones",
    "propose_chapter",
    "confirm_chapters",
    "drop_curve_drafts",
    "get_curve",
    "get_status",
    "grant_xp",
    # 습관(SP7 5.4 표 순서)
    "add_habit",
    "update_habit",
    "set_habit_status",
    "check_habit",
    "uncheck_habit",
    "list_habits",
]

# 앱 대화에만 주는 도구(SP3-4 6.4.7, 10장): 화면 도구 셋(그리기만), 카드 도구 셋. 텔레그램 대화에는 없다.
# 카탈로그의 두뇌 조각(`BRAIN_COMPONENTS`)을 그대로 쓰지 않는다: SP6의 새 넷은 앱이 그릴 수 있게 된 뒤 G-BE2가 더한다
APP_ONLY_TOOLS: list[str] = [*PINNABLE_COMPONENTS, "pin_card", "unpin_card", "reorder_cards"]

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

# (이름, 설명, 입력 스키마). JSON 스키마의 "from"은 부르기 전에 파이썬 이름 `from_`으로 바꾼다(`_py_args`).
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


_MONTH = {"type": "string", "description": "달 YYYY-MM, 예: 2019-03"}
_SCORE_10 = {"type": "integer", "minimum": 0, "maximum": 10}
_BY_AREA_TEXT = {
    "type": "object", "properties": {a: {"type": "string"} for a in _AREAS}, "additionalProperties": False,
}
_CURVE_IDS = {"type": "array", "items": {"type": "integer"}, "minItems": 1}
_SPECS.update({
    "record_ladder_score": (
        (
            "사용자가 말한 사다리 점수(0~10)를 그 달에 기록합니다. now는 지금, future는 5년 뒤입니다. 둘 가운데 하나는 "
            "있어야 하고, 없는 쪽은 그 달 기존 값을 둡니다. 비서가 점수를 매기지 않습니다. period를 안 주면 회고 대화는 "
            "그 회고의 달, 아니면 이번 달입니다. 아직 오지 않은 달은 기록할 수 없습니다."
        ),
        _schema(
            {
                "period": {"type": "string", "description": "달 YYYY-MM"},
                "now": {**_SCORE_10, "type": ["integer", "null"]},
                "future": {**_SCORE_10, "type": ["integer", "null"]},
                "note": {"type": ["string", "null"]},
            },
            [],
        ),
    ),
    "record_area_scores": (
        (
            "사용자가 말한 영역 점수(1~10)를 그 분기에 기록합니다. 말한 영역만 넣습니다. 비서가 점수를 매기지 않습니다. "
            "recovery_quests는 지난 분기보다 내려간 영역에만, 15~30분짜리 하나씩(80자까지) 넣습니다. period를 안 주면 "
            "회고 대화는 그 회고의 분기, 아니면 이번 분기입니다."
        ),
        _schema(
            {
                "period": {"type": "string", "description": "분기 YYYY-Qn, 예: 2026-Q4"},
                "scores": {
                    "type": "object",
                    "properties": {a: {"type": "integer", "minimum": 1, "maximum": 10} for a in _AREAS},
                    "additionalProperties": False,
                    "minProperties": 1,
                },
                "notes": _BY_AREA_TEXT,
                "recovery_quests": {
                    "type": "object",
                    "properties": {a: {"type": "string", "maxLength": 80} for a in _AREAS},
                    "additionalProperties": False,
                },
            },
            ["scores"],
        ),
    ),
    "add_milestone": (
        (
            "사용자가 이야기한 과거의 일을 인생 곡선의 사건 **초안**으로 남깁니다. 추측해서 만들지 않고, \"곡선에 남길까요?\"와 "
            "함께 냅니다. 하네스가 답 아래에 저장·빼기 버튼을 붙이므로 저장했다고 말하지 않습니다. date는 기억하는 만큼 "
            "YYYY, YYYY-MM, YYYY-MM-DD로 씁니다. sensitive는 사용자가 민감하다고 말했을 때만 true입니다."
        ),
        _schema(
            {
                "date": {"type": "string", "description": "YYYY | YYYY-MM | YYYY-MM-DD"},
                "kind": {"enum": ["high", "low", "turning_point"], "description": "고점, 저점, 전환점"},
                "title": {"type": "string", "description": "1~100자"},
                "note": {"type": ["string", "null"]},
                "chapter_id": {"type": ["integer", "null"], "description": "속한 챕터 번호"},
                "sensitive": {"type": "boolean"},
            },
            ["date", "kind", "title"],
        ),
    ),
    "confirm_milestones": (
        (
            "사건 초안을 확정합니다. 사용자가 글로 \"응 저장해\"처럼 동의했을 때 부릅니다. 고점과 전환점은 칭호가 생깁니다. "
            "초안이 아닌 번호는 바꾸지 않고 skipped_ids로 돌려줍니다."
        ),
        _schema({"ids": _CURVE_IDS}, ["ids"]),
    ),
    "propose_chapter": (
        (
            "인생의 한 시기를 챕터 **초안**으로 남깁니다(연말 회고). start, end는 YYYY-MM이고 end가 없으면 지금까지입니다. "
            "하네스가 저장·빼기 버튼을 붙입니다."
        ),
        _schema(
            {
                "title": {"type": "string", "description": "1~100자"},
                "theme": {"type": ["string", "null"], "description": "주제 한 줄"},
                "start": _MONTH,
                "end": {**_MONTH, "type": ["string", "null"]},
            },
            ["title", "start"],
        ),
    ),
    "confirm_chapters": (
        "챕터 초안을 확정합니다. 사용자가 글로 동의했을 때 부릅니다. 초안이 아닌 번호는 skipped_ids로 돌려줍니다.",
        _schema({"ids": _CURVE_IDS}, ["ids"]),
    ),
    "drop_curve_drafts": (
        (
            "사건·챕터 **초안**을 뺍니다(\"그거 빼 줘\"). 확정한 것은 뺄 수 없고, 하나라도 있으면 아무것도 빼지 않습니다."
        ),
        _schema(
            {
                "milestone_ids": {"type": "array", "items": {"type": "integer"}},
                "chapter_ids": {"type": "array", "items": {"type": "integer"}},
            },
            [],
        ),
    ),
    "get_curve": (
        (
            "확정한 인생 곡선을 읽습니다: 챕터, 사건(민감한 것은 제목 대신 \"(민감)\"), 사다리, 영역 점수, 컨디션 평균. "
            "zoom 기본은 month입니다. from, to를 안 주면 확대 단위의 기본 범위입니다."
        ),
        _schema(
            {"from": _DATE, "to": _DATE, "zoom": {"enum": ["day", "week", "month", "quarter", "year"]}},
            [],
        ),
    ),
    "get_status": ("상태창을 읽습니다: 레벨, 경험치, HP, 스탯과 디버프, 퀘스트, 칭호.", _schema({}, [])),
    "grant_xp": (
        (
            "사용자가 했다고 말한 일 가운데 하네스가 경험치를 주지 않는 일(할 일 완료, 회차 답, 컨디션, 회고 점수 말고)에 "
            "경험치를 줍니다. amount는 5 또는 10, reason은 60자까지의 짧은 사유입니다. 하루 3번까지이고 넘으면 거절됩니다. "
            "추측해서 주지 않습니다."
        ),
        _schema(
            {"amount": {"enum": [5, 10]}, "reason": {"type": "string", "description": "1~60자"}},
            ["amount", "reason"],
        ),
    ),
})

_HABIT_ID = {"type": "integer", "description": "습관 번호"}
_HABIT_TARGET = {"type": ["integer", "null"], "minimum": 1, "maximum": 6, "description": "주 몇 번(weekly일 때 1~6)"}
_HABIT_DATE = {"type": ["string", "null"], "description": "논리적 날짜 YYYY-MM-DD. 안 주면 오늘. 오늘 포함 7일 안만"}
_SPECS.update({
    "add_habit": (
        (
            "사용자가 직접 추가해 달라고 한 습관만 추가합니다. 비서가 먼저 떠올린 습관은 말로 제안하고 사용자가 원할 때 "
            "부릅니다. kind는 daily(매일) 또는 weekly(주 N회)이고, weekly면 target_per_week에 1~6을 넣습니다. "
            "주 7회는 daily로 만듭니다. 제목은 40자까지, 활성 습관은 10개까지입니다."
        ),
        _schema(
            {
                "title": {"type": "string", "description": "1~40자"},
                "area": {"enum": _AREAS},
                "kind": {"enum": ["daily", "weekly"]},
                "target_per_week": _HABIT_TARGET,
            },
            ["title", "area", "kind"],
        ),
    ),
    "update_habit": (
        "습관의 제목, 영역, 주기(kind), 주 목표(target_per_week)를 고칩니다. 바꿀 것만 넣습니다.",
        _schema(
            {
                "id": _HABIT_ID,
                "title": {"type": "string", "description": "1~40자"},
                "area": {"enum": _AREAS},
                "kind": {"enum": ["daily", "weekly"]},
                "target_per_week": _HABIT_TARGET,
            },
            ["id"],
        ),
    ),
    "set_habit_status": (
        (
            "습관을 쉬어 가기(paused), 다시 시작(active), 그만두기(archived)로 바꿉니다. 기록은 남습니다. "
            "사용자가 원할 때만 부릅니다."
        ),
        _schema({"id": _HABIT_ID, "status": {"enum": ["active", "paused", "archived"]}}, ["id", "status"]),
    ),
    "check_habit": (
        (
            "사용자가 했다고 말한 습관을 그날(date, 기본 오늘)로 체크합니다. 추측해서 체크하지 않습니다. "
            "이미 체크했으면 바꾸지 않고 already: true를 돌려줍니다."
        ),
        _schema({"id": _HABIT_ID, "date": _HABIT_DATE}, ["id"]),
    ),
    "uncheck_habit": (
        "사용자가 취소해 달라고 한 습관 체크를 지웁니다. 체크가 없으면 바꾸지 않고 already: true를 돌려줍니다.",
        _schema({"id": _HABIT_ID, "date": _HABIT_DATE}, ["id"]),
    ),
    "list_habits": (
        "습관 목록과 그날(date, 기본 오늘) 체크 여부, 그 주 체크 수를 읽습니다. status 기본은 active입니다.",
        _schema({"status": {"enum": ["active", "paused", "archived", "all"]}, "date": _DATE}, []),
    ),
})

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
            {"component": {"enum": list(PINNABLE_COMPONENTS)}, "props": {"type": "object"}},
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
        result = getattr(tools, name)(ctx, **_py_args(args))
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


def _py_args(args: dict[str, Any]) -> dict[str, Any]:
    """도구 스키마의 키 `from`은 파이썬 예약어라 메서드 인자 `from_`으로 바꿔 넘긴다(`method(ctx, **args)`)."""
    return {("from_" if k == "from" else k): v for k, v in args.items()}


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

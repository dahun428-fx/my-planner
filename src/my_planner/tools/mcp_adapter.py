"""도구 함수를 Agent SDK in-process MCP 서버 `planner`로 노출한다 (ADR 0005)."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

from my_planner.domain import InboxAgent, RunContext
from my_planner.standing.metrics import METRICS
from my_planner.timefmt import to_api_times
from my_planner.tools.events import ui_event_items
from my_planner.tools.panel import EXPERT_KEYS
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

# 앱 대화에만 주는 도구(SP3-4 6.4.7, 10장): 카탈로그의 두뇌 화면 도구(그리기만, 카탈로그 순서), 카드 도구 셋.
# 텔레그램 대화에는 없다. SP6의 새 넷은 앱(G-A2)이 그릴 수 있게 된 뒤 G-BE2가 더했다
# SP9: 새 도구는 여기에만 더한다(텔레그램 목록은 그대로, Q14)
APP_ONLY_TOOLS: list[str] = [
    *(n for n in BRAIN_COMPONENTS if n != "ui_events"), "pin_card", "unpin_card", "reorder_cards", "set_checkin_time",
    # 메모(SP9 6.3): 찾기·읽기·만들기만. 고치기·지우기 도구는 없다(Q5)
    "search_memos", "read_memo", "create_memo",
    # 지난 대화(SP9 7.5): 제목·요약만. 원문을 주는 도구가 아니다
    "find_conversations",
    # 스케줄(SP9 5.5): 시간이 정해진 일. 고치기(시각류)·지우기는 확인을 거친다
    "list_events", "create_event", "update_event", "delete_event",
    "ui_events",  # 그날 일정 카드(9.8), 그리기만
    "propose_measures",  # SP13 6.5: 측정값 확인 카드만 낸다(저장은 카드의 "저장")
]
assert set(BRAIN_COMPONENTS) <= set(APP_ONLY_TOOLS)

# 한 답에 두뇌 화면 도구가 쓰는 조각 수 상한(SP6 10.4). 하네스 조각과 `pin_card`는 세지 않는다
UI_PARTS_PER_REPLY = 2
UI_CAP_ERROR = "한 답에 화면 조각은 2개까지예요."

_AREAS = ["career", "finance", "health", "relationships", "learning", "quality_of_life"]
_DATE = {"type": ["string", "null"], "description": "논리적 날짜 YYYY-MM-DD"}
_ID = {"type": "integer", "description": "할 일 번호"}


def _ui_input_schema(component: str) -> dict[str, Any]:
    """화면 조각의 카탈로그 스키마를 도구 입력 스키마로(SP6 10.1). OpenAPI 확장 `discriminator`는 뺀다: 카탈로그의
    바깥 `children` 구분 표는 `group`을 `$ref` 문자열이 아니라 안쪽 스키마(`layout`으로 가르는 유니언)로 가리켜 맞는
    mapping이 아니고, 판정은 어차피 `oneOf` + `type`·`layout`의 `const`가 한다. 카탈로그(`GET /ui/catalog`)는 그대로다."""

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "discriminator"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(UI_COMPONENTS[component]["schema"])


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
        "parent_id": {"type": ["integer", "null"], "description": "첫 걸음이면 부모 할 일 번호"},
        "note": {"type": ["string", "null"]},
    },
    ["title", "areas"],
)

# (이름, 설명, 입력 스키마). JSON 스키마의 "from"은 부르기 전에 파이썬 이름 `from_`으로 바꾼다(`_py_args`).
_SPECS: dict[str, tuple[str, dict[str, Any]]] = {
    "add_task": (
        (
            "사용자가 직접 추가해 달라고 한 할 일을 바로 추가합니다. 비서가 제안하는 것에는 쓰지 않습니다. "
            "할 일에는 시각을 붙이지 않습니다(시간이 정해진 일은 할 일이 아니라 일정입니다). "
            "planned_for는 꼭 넣습니다. 날짜가 분명하지 않으면 가장 그럴듯한 날(\"다음 주\"면 다음 주 월요일, 모르면 오늘)로 "
            "넣습니다. 빼면 오늘로 들어갑니다(첫 걸음은 날짜 없이 둘 수 있습니다)."
        ),
        _NEW_TASK,
    ),
    "propose_tasks": (
        (
            "비서가 제안하는 할 일을 초안(draft)으로 저장합니다. 브리핑, 체크인, 회고, 계획 의논에서 비서가 "
            "먼저 꺼낸 할 일에 씁니다. 하네스가 메시지 아래에 초안마다 추가·빼기 버튼을 붙이므로 "
            "답에서 확정했다고 말하지 않습니다. 한 번에 최대 10개. 하려는 날이 있으면 planned_for를 넣습니다."
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
        (
            "할 일의 제목, 영역, 메모를 바꿉니다. 날짜는 move_task로 바꿉니다. 할 일에는 시각을 붙이지 않습니다"
            "(시간이 정해진 일은 할 일이 아니라 일정입니다)."
        ),
        _schema(
            {
                "id": _ID,
                "title": {"type": "string"},
                "areas": {"type": "array", "items": {"enum": _AREAS}, "minItems": 1},
                "note": {"type": "string"},
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
            "YYYY, YYYY-MM, YYYY-MM-DD로 씁니다. sensitive는 사용자가 민감하다고 말했을 때만 true입니다. area는 "
            "사용자의 말에서 그 일의 대표 영역이 분명할 때만 넣고, 애매하면 비워 둡니다."
        ),
        _schema(
            {
                "date": {"type": "string", "description": "YYYY | YYYY-MM | YYYY-MM-DD"},
                "kind": {"enum": ["high", "low", "turning_point"], "description": "높은 때, 힘든 때, 전환점"},
                "title": {"type": "string", "description": "1~100자"},
                "note": {"type": ["string", "null"]},
                "chapter_id": {"type": ["integer", "null"], "description": "속한 챕터 번호"},
                "sensitive": {"type": "boolean"},
                "area": {
                    "type": ["string", "null"], "enum": [*_AREAS, None],
                    "description": "대표 영역 하나(분명할 때만)",
                },
            },
            ["date", "kind", "title"],
        ),
    ),
    "confirm_milestones": (
        (
            "사건 초안을 확정합니다. 사용자가 글로 \"응 저장해\"처럼 동의했을 때 부릅니다. 높은 때와 전환점은 칭호가 생깁니다. "
            "초안이 아닌 번호는 바꾸지 않고 skipped_ids로 돌려줍니다."
        ),
        _schema({"ids": _CURVE_IDS}, ["ids"]),
    ),
    "propose_chapter": (
        (
            "인생의 한 시기를 챕터 **초안**으로 남깁니다(연말 회고). start, end는 YYYY-MM이고 end가 없으면 지금까지입니다. "
            "하네스가 저장·빼기 버튼을 붙입니다. ladder는 그 시기를 돌아보며 사용자가 직접 말한 사다리 칸(0~10)만 넣고, "
            "추측하지 않습니다."
        ),
        _schema(
            {
                "title": {"type": "string", "description": "1~100자"},
                "theme": {"type": ["string", "null"], "description": "주제 한 줄"},
                "start": _MONTH,
                "end": {**_MONTH, "type": ["string", "null"]},
                "ladder": {"type": ["integer", "null"], "minimum": 0, "maximum": 10,
                           "description": "사용자가 말한 그 시기의 사다리 칸"},
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
            "제목과 상태는 앱이 지금 값으로 보여 줍니다."
        ),
        UI_COMPONENTS["ui_todo_list"]["schema"],
    ),
    "ui_choice": (
        (
            "앱 화면에 고르기 조각을 그립니다(그리기만 합니다). 보기는 2~4개이고, 사용자가 고르면 그 label이 "
            "새 메시지로 옵니다."
        ),
        UI_COMPONENTS["ui_choice"]["schema"],
    ),
    "ui_summary_card": (
        "앱 화면에 요약 카드를 그립니다(그리기만 합니다). lines는 최대 8줄, 줄마다 120자까지입니다.",
        UI_COMPONENTS["ui_summary_card"]["schema"],
    ),
    # SP6 9.3
    "ui_date_choice": (
        (
            "앱 화면에 날짜 고르기 조각을 그립니다(그리기만 합니다). task_id는 시각이 없는 열린 할 일 번호이고(날짜는 "
            "있어도 됩니다), candidates는 2~4개의 날짜(오늘부터 90일 안)와 짧은 메모입니다. 사용자가 고르면 앱이 그 "
            "날짜로 옮깁니다. 시각이 잡힌 할 일에는 쓰지 않습니다."
        ),
        _ui_input_schema("ui_date_choice"),
    ),
    "ui_result": (
        (
            "이번 답에서 바꾼 할 일 1~2개의 결과(전과 뒤, 되돌리기)를 앱 화면에 그립니다(그리기만 합니다). 바꾸는 "
            "도구를 부른 뒤에 부릅니다. 3개 이상이면 ui_period_list를 씁니다."
        ),
        _ui_input_schema("ui_result"),
    ),
    "ui_period_list": (
        (
            "하루(day) 또는 한 주(week, 예: 2026-W44)의 할 일을 날짜별로 앱 화면에 그립니다(그리기만 합니다). "
            "highlight_task_ids에는 이번 답에서 바꾼 할 일을 넣습니다."
        ),
        _ui_input_schema("ui_period_list"),
    ),
    "ui_block": (
        (
            "기본 부품을 쌓은 카드를 앱 화면에 그립니다(그리기만 합니다). 부품: heading, text(**굵게**·줄바꿈만), "
            "stat, progress, todo_rows, tags, bullets, buttons(send·open·complete), divider, group(row: "
            "stat·progress 2~3개, stack: 2~6개). 부품은 모두 12개까지, group은 한 단계, buttons는 하나만 맨 끝에, "
            "todo_rows는 둘까지입니다."
        ),
        _ui_input_schema("ui_block"),
    ),
    "ui_habit_check": (
        (
            "앱 화면에 오늘 습관 줄 묶음을 그립니다(그리기만 합니다). date는 YYYY-MM-DD입니다. 체크 여부는 앱이 지금 값으로 "
            "보여 줍니다. 체크는 check_habit로 따로 합니다."
        ),
        UI_COMPONENTS["ui_habit_check"]["schema"],
    ),
    "ui_events": (
        (
            "앱 화면에 그날 일정 카드를 그립니다(그리기만 합니다). items는 list_events 결과 항목을 그대로 1~10개 넘깁니다."
        ),
        UI_COMPONENTS["ui_events"]["schema"],
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


_SPECS.update({
    "set_checkin_time": (
        (
            "아침 브리핑·저녁 체크인 시각을 바꾸자고 확인을 묻습니다(언제나 확인, 바로 바꾸지 않습니다). loop는 "
            "morning_brief(아침) 또는 evening_checkin(저녁), day_type은 weekday(평일) 또는 weekend(주말)입니다. "
            "time은 HH:MM, 아침 05:00~11:30, 저녁 15:00~23:30, 10분 단위입니다. 주말 저녁은 일요일 주간 회고 "
            "시각이기도 합니다. 결과는 needs_confirm이고 앱에 확인 카드가 붙습니다: 바꿨다고 말하지 않습니다. "
            "사용자가 바꿔 달라고 할 때만 부릅니다."
        ),
        _schema(
            {
                "loop": {"enum": ["morning_brief", "evening_checkin"]},
                "day_type": {"enum": ["weekday", "weekend"]},
                "time": {"type": "string", "description": "HH:MM, 10분 단위"},
            },
            ["loop", "day_type", "time"],
        ),
    ),
})


_MEMO_ID = {"type": "integer", "description": "메모 번호"}
_SPECS["find_conversations"] = (
    (
        "앱에서 나눈 지난 대화를 찾습니다. 사용자가 지난 대화를 언급하거나(\"어제 얘기한 거\") 앞머리와 다른 도구로 알 수 "
        "없는 맥락이 필요할 때만 부릅니다. 결과는 대화마다 id, 날짜, 제목, 요약이고 원문은 없습니다. query가 없으면 "
        "최근 대화입니다. days 기본 14(최대 90), limit 기본 5(최대 20)."
    ),
    _schema(
        {
            "query": {"type": ["string", "null"], "description": "제목·요약에서 찾을 말. 3글자 이상이면 더 정확합니다"},
            "days": {"type": "integer", "minimum": 1, "maximum": 90},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        [],
    ),
)
_SPECS.update({
    "search_memos": (
        (
            "사용자가 적어 둔 메모에서 찾습니다. 사용자가 메모 내용을 물어볼 때만 부릅니다(\"지난번에 적은 책 이름 뭐였지?\"). "
            "결과는 메모마다 id, 제목, 앞 200자 미리보기, 고친 시각이고 가릴 정보는 [가림]으로 바뀌어 있습니다. "
            "본문 전체가 필요하면 read_memo를 부릅니다. limit 기본 5, 최대 20."
        ),
        _schema(
            {
                "query": {"type": "string", "description": "찾을 말. 3글자 이상이면 더 정확합니다"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            ["query"],
        ),
    ),
    "read_memo": (
        "메모 하나의 본문을 읽습니다(8,000자까지, 가릴 정보는 [가림]). 사용자가 메모 내용을 물어볼 때만 부릅니다.",
        _schema({"id": _MEMO_ID}, ["id"]),
    ),
    "create_memo": (
        (
            "사용자가 \"메모해줘\", \"적어둬\"처럼 부탁할 때만 메모를 만듭니다. body는 1~20,000자이고 첫 줄이 제목입니다. 메모 칩 차례에서는 body 없이 부릅니다. "
            "쓸 수 있는 서식은 목록 \"- \", 번호 \"1. \", 체크박스 \"- [ ]\", 굵게 \"**\"입니다. area는 영역 하나 또는 null. "
            "만든 메모는 고치거나 지울 수 없습니다(사용자가 앱에서 합니다). "
            "photo_ids에는 이번 대화에서 받은 사진 번호(이미지 앞 [사진 #12]의 12)만 넣으면 그 사진을 순서대로 메모에 붙입니다(10장까지)."
        ),
        _schema(
            {
                "body": {"type": "string", "description": "1~20,000자, 첫 줄이 제목"},
                "area": {"type": ["string", "null"], "enum": [*_AREAS, None]},
                # SP10 5.5: 앱 통로만(이 도구는 앱 대화에만 있다). 다른 대화의 사진은 `photo_not_in_conversation`
                "photo_ids": {
                    "type": "array", "items": {"type": "integer"}, "maxItems": 10,
                    "description": "이번 대화에서 받은 사진 번호([사진 #12]의 12). 없으면 빼세요",
                },
            },
            # 필수가 아니다: 메모 칩 차례(SP9c 4.5)는 `body` 없이 부르면 원문을 쓴다. 그 밖에 빠지면 도구가 거절한다
            [],
        ),
    ),
})


_EVENT_ID = {"type": "integer", "description": "일정 번호(앞머리의 #e12는 12)"}
_LOCAL_DATE = {"type": "string", "description": "현지 날짜 YYYY-MM-DD(논리적 날짜가 아니다: 새벽 1시 일정은 그 달력 날)"}
_EVENT_FIELDS: dict[str, Any] = {
    "title": {"type": "string", "description": "1~100자"},
    "date": {**_LOCAL_DATE, "description": "첫 날의 현지 날짜 YYYY-MM-DD"},
    "time": {"type": ["string", "null"], "description": "현지 시각 HH:MM. 하루 종일이면 null"},
    "all_day": {"type": "boolean", "description": "하루 종일 일정(기본 false)"},
    "duration_min": {"type": ["integer", "null"], "minimum": 5, "maximum": 1440, "description": "길이(분)"},
    "repeat": {"enum": ["none", "daily", "weekly", "monthly"], "description": "반복 없음, 매일, 매주(요일), 매달(같은 날짜)"},
    "weekdays": {
        "type": ["array", "null"], "items": {"enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
        "description": "매주 반복의 요일. 첫 날(date)의 요일이 들어 있어야 합니다",
    },
    "repeat_until": {"type": ["string", "null"], "description": "반복의 마지막이 될 수 있는 날 YYYY-MM-DD(포함)"},
    "remind_min": {
        "type": ["integer", "null"], "enum": [0, 10, 30, 60, 1440, None],
        "description": "알림: 0 정시, 10·30·60분 전, 1440 하루 전, null 없음. 하루 종일은 0(그날 09:00)이나 1440만",
    },
    "area": {"type": ["string", "null"], "enum": [*_AREAS, None]},
    "note": {"type": ["string", "null"], "description": "1,000자까지"},
}
_SPECS.update({
    "list_events": (
        "스케줄에서 기간(현지 날짜, 포함, 62일까지)의 일정을 날짜·시각순으로 읽습니다. 건너뛴 날은 빠져 있습니다.",
        _schema({"start": _LOCAL_DATE, "end": _LOCAL_DATE}, ["start", "end"]),
    ),
    "create_event": (
        (
            "시간이 정해진 일을 스케줄에 일정으로 만듭니다(\"내일 14:00 치과\", \"매주 월 10:00 팀 회의\"). 할 일과 다릅니다: "
            "끝내기·밀림이 없습니다. 사용자가 말한 일정만 만듭니다. remind_min을 빼면 10분 전(하루 종일은 그날 09:00) "
            "알림입니다. 매주 반복은 weekdays에 요일을 넣고, 매달 반복은 첫 날의 날짜(없는 달은 그 달 마지막 날)입니다. "
            "비서가 먼저 꺼낸 차례(회차)에서는 needs_confirm이 오고 사용자가 확인해야 만들어집니다."
        ),
        _schema(_EVENT_FIELDS, ["title", "date"]),
    ),
    "update_event": (
        (
            "일정을 고칩니다. 바꿀 칸만 넣습니다. 제목·메모·영역은 바로 바뀝니다. 날짜·시각·하루 종일·길이·반복·알림을 "
            "바꾸면 결과가 needs_confirm이고 앱에 확인 카드가 붙습니다: 바꿨다고 말하지 않습니다. 반복 중 하루만 시각을 "
            "바꾸는 것은 없습니다(그날을 건너뛰고 한 번짜리를 새로 만듭니다)."
        ),
        _schema({"id": _EVENT_ID, **_EVENT_FIELDS}, ["id"]),
    ),
    "delete_event": (
        (
            "일정을 지웁니다. 언제나 needs_confirm이고 앱에 확인 카드가 붙습니다: 지웠다고 말하지 않습니다. scope는 "
            "one(그날만 건너뛰기, date 필요), following(date부터 반복 끝내기, date 필요), all(모두 지우기)입니다. "
            "한 번짜리 일정은 scope와 상관없이 지웁니다."
        ),
        _schema(
            {"id": _EVENT_ID, "scope": {"enum": ["one", "following", "all"]}, "date": _LOCAL_DATE},
            ["id", "scope"],
        ),
    ),
})


# 측정값(SP13 6.3~6.5). 앱 대화에만(`APP_ONLY_TOOLS`)
_SPECS["propose_measures"] = (
    (
        "결과지 사진(인바디, 검진표, 급여명세, 자산 화면)이나 사용자가 말한 숫자를 측정값 확인 카드로 냅니다. 저장하지 "
        "않습니다: 사용자가 카드에서 고치고 \"저장\"을 누르면 저장됩니다. 줄 하나라도 틀리면 카드 없이 errors(index, "
        "message)가 오니 그 줄을 고쳐 다시 부릅니다. 금액은 원 단위(5,500만 원 = 55000000), measured_on은 결과지의 "
        "날짜입니다(올린 날이 아니라). source_kind는 사진이면 photo(source_ref에 \"photo:<사진 번호>\"), PDF면 pdf, "
        "말로 들은 값이면 manual입니다."
    ),
    _schema(
        {
            "rows": {
                "type": "array",
                "minItems": 1,
                "maxItems": 30,
                "items": _schema(
                    {
                        "metric": {"enum": list(METRICS), "description": "측정값 이름"},
                        "value": {
                            "type": ["number", "string"],
                            "description": "숫자 지표는 수, 범주 지표는 정해진 값(예: \"m\", \"seoul_mid_low\", \"toeic:825\")",
                        },
                        "measured_on": {"type": "string", "description": "측정일 YYYY-MM-DD"},
                    },
                    ["metric", "value", "measured_on"],
                ),
            },
            "source_kind": {"enum": ["photo", "pdf", "manual"]},
            "source_ref": {"type": ["string", "null"], "description": "photo:<사진 번호> 또는 null"},
        },
        ["rows", "source_kind"],
    ),
)

# 하루 끝 순간 호출(`RunContext.kind == "moments"`, SP8 6.3)에만 주는 도구. 대화·회차 목록(`TOOL_NAMES`, `APP_ONLY_TOOLS`)에는 없다
MOMENTS_TOOLS: list[str] = ["save_moments"]
_SPECS["save_moments"] = (
    (
        "그날의 이룬 순간 0~3개를 저장하고 그날을 정리한 날로 적습니다. date는 입력의 날짜(YYYY-MM-DD)입니다. "
        "text는 앞뒤 공백을 뺀 60자 안의 한 줄(줄바꿈 없음), area는 영역 하나 또는 null, sources는 입력에 나온 참조"
        "(task:<번호>, habit:<번호>, workout:<번호>, condition, chat) 1~5개입니다. 쓸 거리가 없으면 moments를 빈 배열로 부릅니다."
    ),
    _schema(
        {
            "date": {"type": "string", "description": "정리하는 날 YYYY-MM-DD"},
            "moments": {
                "type": "array",
                "maxItems": 3,
                "items": _schema(
                    {
                        "text": {"type": "string", "maxLength": 60, "description": "해요체 과거형 한 줄"},
                        "area": {"type": ["string", "null"], "enum": [*_AREAS, None]},
                        "sources": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
                    },
                    ["text", "sources"],
                ),
            },
        },
        ["date", "moments"],
    ),
)


NO_TOOL_KINDS = frozenset({"summary", "photo_read"})  # 도구를 주지 않는 실행 종류

# 메이트 대화(`RunContext.agent == "mate"`, SP12 5.3)에 주는 도구. 이 목록에 있는 것만 쓴다(할 일·습관·메모·일정·
# 카드 도구는 비서 몫이다). 운동 도구 여덟과 측정값 읽기(SP14, ADR 0019 덧붙임)는 메이트에만 있다(`TOOL_NAMES`,
# `APP_ONLY_TOOLS`에 없다)
MATE_TOOLS: list[str] = [
    "get_mate_context", "save_body_note", "drop_body_note", "set_workout_plan", "log_workout", "update_workout_log",
    "delete_workout_log", "list_workouts", "get_measures",
    "record_condition", "find_conversations", "ui_block", "ui_choice", "ui_summary_card",
]

# 운동메이트 도구(SP12 5.3, 6장, 7.3, 8장)
_NOTE_ID = {"type": "integer", "description": "몸 메모 번호"}
_LOG_ID = {"type": "integer", "description": "운동 기록 번호"}


def _null_int(lo: int, hi: int, desc: str) -> dict[str, Any]:
    return {"type": ["integer", "null"], "minimum": lo, "maximum": hi, "description": desc}


_PLAN_ITEM = _schema(
    {
        "name": {"type": "string", "description": "1~30자. 최근 기록과 같은 이름을 씁니다"},
        "sets": _null_int(1, 10, "세트 수"),
        "reps": {"type": ["string", "null"], "description": "1~10자 글: \"10\", \"8-10\", \"최대\""},
        "weight_kg": {"type": ["number", "null"], "minimum": 0, "maximum": 500,
                      "description": "0.5 단위. 맨몸이거나 무게를 모르면 null"},
        "minutes": _null_int(1, 180, "유산소·스트레칭 시간(분)"),
        "note": {"type": ["string", "null"], "description": "60자까지"},
    },
    ["name"],
)
_LOG_ITEM = _schema(
    {
        "name": {"type": "string", "description": "1~30자"},
        "sets": _null_int(1, 20, "세트 수"),
        "reps": _null_int(1, 200, "한 세트 횟수(정수)"),
        "weight_kg": {"type": ["number", "null"], "minimum": 0, "maximum": 500,
                      "description": "세트마다 다르면 가장 무거운 세트 무게"},
        "minutes": _null_int(1, 600, "시간(분)"),
        "distance_km": {"type": ["number", "null"], "minimum": 0, "maximum": 200, "description": "거리(km)"},
    },
    ["name"],
)
_LOG_ITEMS = {"type": ["array", "null"], "items": _LOG_ITEM, "maxItems": 20, "description": "한 운동에 한 줄, 20줄까지"}
_LOG_DATE = {"type": ["string", "null"], "description": "논리적 날짜 YYYY-MM-DD. 빼면 오늘. 오늘 포함 7일 안만"}
_SPECS.update({
    "get_mate_context": (
        "앞머리와 같은 내용(오늘 몸, 오늘 일정, 몸 메모, 지금 플랜, 최근 기록)을 지금 값으로 다시 읽습니다. 긴 대화 중간에 씁니다.",
        _schema({}, []),
    ),
    "save_body_note": (
        (
            "몸 메모 한 줄을 더하거나(id 없음) 고칩니다(id). 장비, 부상·통증, 선호, 운동할 수 있는 때를 들으면 묻지 않고 "
            "부릅니다. 저장했다고 따로 말하지 않습니다. 같은 뜻의 메모가 있으면 새로 더하지 않고 그 id로 고칩니다. "
            "kind는 equipment(장비), injury(부상·통증), preference(선호), availability(가능한 때), other(기타)입니다. "
            "text는 120자까지, 메모는 30개까지입니다. 비밀번호, 계좌번호 같은 정보는 쓰지 않습니다."
        ),
        _schema(
            {
                "kind": {"enum": ["equipment", "injury", "preference", "availability", "other"]},
                "text": {"type": "string", "description": "1~120자"},
                "id": {"type": ["integer", "null"], "description": "고칠 몸 메모 번호. 더할 때는 뺍니다"},
            },
            ["kind", "text"],
        ),
    ),
    "drop_body_note": (
        "몸 메모를 지웁니다. 사용자가 \"이제 무릎 괜찮아\"처럼 그 메모가 더는 맞지 않다고 말할 때 부릅니다.",
        _schema({"id": _NOTE_ID}, ["id"]),
    ),
    "set_workout_plan": (
        (
            "운동 플랜을 통째로 바꿉니다. 작은 변경(\"목요일만 빼줘\")도 지금 플랜을 고친 전체를 보냅니다. 앞 플랜은 남습니다. "
            "sessions는 1~7개이고 position은 1부터 차례로, weekdays는 0(월)~6(일) 배열 또는 요일 자유면 null, items는 "
            "세션마다 1~12개입니다. 사용자가 플랜 없이 하겠다고 하면 sessions를 빈 배열로 부릅니다(지금 플랜을 내립니다)."
        ),
        _schema(
            {
                "title": {"type": ["string", "null"], "description": "1~30자. 내릴 때는 null"},
                "note": {"type": ["string", "null"], "description": "300자까지"},
                "sessions": {
                    "type": "array",
                    "maxItems": 7,
                    "items": _schema(
                        {
                            "position": {"type": "integer", "minimum": 1, "maximum": 7},
                            "label": {"type": "string", "description": "1~20자. \"하체\", \"가볍게 걷기\""},
                            "weekdays": {"type": ["array", "null"], "items": {"type": "integer", "minimum": 0,
                                                                              "maximum": 6}},
                            "items": {"type": "array", "items": _PLAN_ITEM, "minItems": 1, "maxItems": 12},
                        },
                        ["position", "label", "weekdays", "items"],
                    ),
                },
            },
            ["title", "note", "sessions"],
        ),
    ),
    "log_workout": (
        (
            "사용자가 한 운동을 말할 때만 기록 하나를 남깁니다. 숫자가 빠졌으면 빈칸(null)으로 두고 되묻지 않습니다. "
            "\"스쿼트 60kg 5x5\"는 sets 5, reps 5, weight_kg 60입니다. 운동 줄 없이 note만 남겨도 됩니다. "
            "date는 빼면 오늘이고 오늘 포함 7일 안만 됩니다. 플랜의 세션을 했으면 session_id를 넣습니다. "
            "effort는 힘든 정도 1(가벼움)~5(아주 힘듦)입니다."
        ),
        _schema(
            {
                "title": {"type": "string", "description": "1~30자. \"하체\", \"걷기\""},
                "date": _LOG_DATE,
                "session_id": {"type": ["integer", "null"], "description": "지금 플랜의 세션 번호"},
                "effort": _null_int(1, 5, "힘든 정도"),
                "note": {"type": ["string", "null"], "description": "200자까지"},
                "items": _LOG_ITEMS,
            },
            ["title"],
        ),
    ),
    "update_workout_log": (
        (
            "운동 기록을 고칩니다(\"아 60이 아니라 65였어\"). 바꿀 칸만 넣습니다. items를 넣으면 운동 줄 전체를 바꿉니다."
        ),
        _schema(
            {
                "id": _LOG_ID,
                "title": {"type": "string", "description": "1~30자"},
                "date": _LOG_DATE,
                "session_id": {"type": ["integer", "null"]},
                "effort": _null_int(1, 5, "힘든 정도"),
                "note": {"type": ["string", "null"], "description": "200자까지"},
                "items": _LOG_ITEMS,
            },
            ["id"],
        ),
    ),
    "delete_workout_log": (
        (
            "운동 기록을 지우자고 확인을 묻습니다(바로 지우지 않습니다). 결과는 needs_confirm이고 앱에 확인 카드가 붙습니다: "
            "지웠다고 말하지 않습니다. 사용자가 지워 달라고 할 때만 부릅니다."
        ),
        _schema({"id": _LOG_ID}, ["id"]),
    ),
    "list_workouts": (
        (
            "운동 기록을 찾습니다. days는 오늘 포함 기간(기본 28, 최대 180), name은 운동 이름 부분 일치입니다. "
            "최근 것부터 나옵니다."
        ),
        _schema(
            {
                "days": {"type": "integer", "minimum": 1, "maximum": 180},
                "name": {"type": ["string", "null"], "description": "1~30자"},
            },
            [],
        ),
    ),
})


# 하루 끝 판단(`RunContext.kind == "dayend"`, SP14 6.2)에 주는 도구: 그 상대의 읽기 도구 + 관찰 도구 둘. 쓰기 도구는 없다.
# `write_note`·`hand_off`는 여기에만 있다(`TOOL_NAMES`·`APP_ONLY_TOOLS`·`MATE_TOOLS`에 없다). SP15가 "manager" 줄을 더한다
DAYEND_READ_TOOLS: dict[InboxAgent, list[str]] = {
    "mate": ["get_mate_context", "list_workouts", "get_measures", "list_events", "find_conversations"],
}
DAYEND_TOOLS: list[str] = ["write_note", "hand_off"]
_NOTE_REFS = {
    "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5,
    "description": "근거로 본 참조(workout:12, event:7 같은 것) 1~5개",
}
_NOTE_TEXT = {"type": "string", "maxLength": 120, "description": "1~120자 한 줄(줄바꿈 없음). 판단과 근거를 함께"}
_SPECS.update({
    "get_measures": (
        "건강·외모 측정값(체성분, 혈압·혈당 같은 검진 수치, 체력 기록)의 지표마다 가장 최근 값을 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "write_note": (
        (
            "하루 끝 판단의 관찰 한 줄을 남깁니다. 한 번에 2개까지이고, 관찰이 없으면 부르지 않습니다. text는 120자 안의 "
            "한 줄로 판단과 근거를 함께 씁니다. priority는 건강이나 돈의 위험처럼 꼭 알려야 할 때만 1, 그 밖은 2입니다. "
            "refs에는 근거로 본 참조(workout:12, event:7 같은 것)를 1~5개 넣습니다."
        ),
        _schema({"text": _NOTE_TEXT, "priority": {"enum": [1, 2]}, "refs": _NOTE_REFS}, ["text", "priority", "refs"]),
    ),
    "hand_off": (
        (
            "다른 상대가 알아야 할 것을 한 줄로 넘깁니다. 받는 상대가 다음 판단 때 읽습니다(아침 브리핑에는 붙지 않습니다). "
            "하루 2번까지이고 자기 자신에게는 넘기지 않습니다. text와 refs는 write_note와 같습니다."
        ),
        _schema(
            {"to": {"enum": ["mate", "manager"]}, "text": _NOTE_TEXT, "refs": _NOTE_REFS}, ["to", "text", "refs"],
        ),
    ),
})


def _days(lo: int, hi: int, default: int) -> dict[str, Any]:
    return {"type": "integer", "minimum": lo, "maximum": hi, "description": f"오늘 포함 일수(기본 {default})"}


# 라이프 매니저·전문가 읽기 도구(SP15 6.1). 결과는 id(근거 참조 ref)·날짜·값이다
_SPECS.update({
    "read_conditions": (
        "최근 컨디션 점수(1~5)를 날짜마다 읽습니다(메모 없음). 근거 참조는 checkin:<날짜>. 읽기만 합니다.",
        _schema({"days": _days(1, 56, 28)}, []),
    ),
    "read_body_days": (
        "최근 날짜마다 걸음 수와 잠잔 시간(분)을 읽습니다. 근거 참조는 body_day:<날짜>. 읽기만 합니다.",
        _schema({"days": _days(1, 56, 28)}, []),
    ),
    "read_moments": (
        "최근 이룬 순간(숨긴 것 뺌)의 id, 날짜, 글, 영역을 읽습니다. 근거 참조는 moment:<id>. 읽기만 합니다.",
        _schema({"days": _days(1, 180, 90)}, []),
    ),
    "read_reviews": (
        "분기 회고의 영역 점수와 메모를 ref(review:<분기>:<영역>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_measures_all": (
        "프로필을 뺀 모든 측정값의 지표마다 가장 최근 값을 ref(measure:<id>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_measures_career": (
        "직업 측정값(연봉, 회사, 직무, 경력 같은 것)의 가장 최근 값을 ref와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_measures_finance": (
        "경제 측정값(순자산, 저축, 실수령)과 연봉의 가장 최근 값을 ref와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_measures_looks": (
        "외모 측정값(키, 몸무게, 체성분, 허리둘레, 얼굴·관리 평가)의 가장 최근 값을 ref와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_measures_relationships": (
        "관계 측정값(기댈 사람, 모임, 연애 상태, 외로움)의 가장 최근 값을 ref와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_tasks_career": (
        "커리어 영역의 열린 할 일과 지난 56일에 끝내거나 버린 할 일(50개까지)을 ref(task:<id>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_tasks_finance": (
        "경제 영역의 열린 할 일과 지난 56일에 끝내거나 버린 할 일(50개까지)을 ref(task:<id>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_tasks_relationships": (
        "관계 영역의 열린 할 일과 지난 56일에 끝내거나 버린 할 일(50개까지)을 ref(task:<id>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_schedule_shape": (
        "오늘부터 며칠의 일정을 제목·메모 없이 날짜, 시작 시각, 길이(분), 영역만 ref(event:<id>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({"days": {"type": "integer", "minimum": 1, "maximum": 28, "description": "오늘부터 일수(기본 14)"}}, []),
    ),
    "list_statements": (
        "지우지 않은 내가 한 말(사실, 선호, 결정)을 ref(statement:<id>, 결정은 decision:<key>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({}, []),
    ),
    "read_benchmark": (
        "외부 기준표(SP13)의 표 하나를 출처, 연도, 추정 여부와 함께 ref(bench:<key>)로 읽습니다(key를 빼면 키 목록). 읽기만 합니다.",
        _schema({"key": {"type": ["string", "null"], "description": "기준표 맨 위 키(height, looks, income 같은 것)"}}, []),
    ),
    "read_panel_results": (
        "최근 몇 주 패널 제안의 제목, 영역, 결과(받음·버림·지남)와 버린 이유를 ref(suggestion:<id>)와 함께 읽습니다. 읽기만 합니다.",
        _schema({"weeks": {"type": "integer", "minimum": 1, "maximum": 12, "description": "이번 주 포함 주 수(기본 8)"}}, []),
    ),
    "list_chat_photos": (
        "이 라이프 매니저 대화에 올린 사진의 번호, 날짜, 사진에서 읽은 글을 읽습니다(이미지는 없음). 읽기만 합니다.",
        _schema({}, []),
    ),
})
# 패널 쓰기 도구(SP15 5.4, 7장, 9장, 10장). 값의 범위·근거·주간 수는 도구가 다시 본다(`tools/panel.py`).
# `save_life_report`는 아직 뼈대다: 계획 Task 13이 설명과 입력을 채운다
_EVIDENCE = {
    "type": "array",
    "minItems": 1,
    "maxItems": 8,
    "description": "근거 1~8개. 내 기록(record)이나 내가 한 말(statement)이 하나는 있어야 합니다",
    "items": _schema(
        {
            "type": {"enum": ["record", "statement", "external"]},
            "ref": {
                "type": "string",
                "description": (
                    "record: task:<id>, event:<id>, habit:<id>, checkin:<날짜>, body_day:<날짜>, workout:<id>, "
                    "measure:<id>, moment:<id>, suggestion:<id> / statement: statement:<id>, memo:<id>, "
                    "review:<분기>:<영역>, decision:<key> / external: bench:<기준표 키>"
                ),
            },
            "note": {"type": "string", "description": "카드의 \"근거 보기\"에 보일 한 줄(120자 이하)"},
        },
        ["type", "ref", "note"],
    ),
}
_SPECS.update({
    "propose_suggestion": (
        (
            "패널 제안 카드 하나를 냅니다(할 일 또는 습관). 사용자가 카드에서 \"받기\"를 눌러야 할 일·습관이 생깁니다. "
            "근거는 읽기 도구가 준 ref만 씁니다. 거절되면 error와 rejected(이유 코드)가 옵니다: unknown_ref·"
            "no_personal_evidence면 근거를 고치거나 질문으로 바꾸고, budget_exhausted면 이번 주는 더 내지 않고, "
            "too_big_again이면 더 작게, not_interested_recent면 다른 것을 냅니다. 한 메시지에 다시 내기는 1번입니다."
        ),
        _schema(
            {
                "kind": {"enum": ["task", "habit"]},
                "title": {"type": "string", "description": "카드 제목 한 줄(60자 이하)"},
                "area": {"enum": _AREAS},
                "size_min": {"type": "integer", "minimum": 5, "maximum": 120, "description": "예상 소요(분)"},
                "per_week": {
                    "type": ["integer", "null"], "minimum": 1, "maximum": 7,
                    "description": "습관이면 주 몇 번(1~7), 할 일이면 null",
                },
                "due_hint": {"type": ["string", "null"], "description": "논리적 날짜 YYYY-MM-DD(오늘~60일 뒤) 또는 null"},
                "experts": {
                    "type": "array", "items": {"enum": list(EXPERT_KEYS)}, "minItems": 1, "maxItems": 6,
                    "uniqueItems": True, "description": "이 제안을 낸 전문가 키",
                },
                "evidence": _EVIDENCE,
            },
            ["kind", "title", "area", "size_min", "experts", "evidence"],
        ),
    ),
    "save_statement": (
        (
            "사용자가 직접 한 말(사실, 선호, 결정) 한 줄을 확인 카드 없이 저장하고 ref를 돌려받습니다. 질문에 대한 "
            "답이나 \"나는 ~하고 싶어\" 같은 말만, 사용자의 말 그대로에 가깝게 씁니다. 결정(decision)에는 짧은 영문 "
            "key가 있어야 합니다. 비밀번호·주민번호·전화번호 같은 식별 정보는 저장하지 않습니다."
        ),
        _schema(
            {
                "kind": {"enum": ["fact", "preference", "decision"]},
                "area": {"type": ["string", "null"], "enum": [*_AREAS, None], "description": "영역 또는 null"},
                "text": {"type": "string", "description": "한 줄(200자 이하)"},
                "key": {"type": ["string", "null"], "description": "결정만: 영문 소문자와 _ 3~30자(예: career_first)"},
            },
            ["kind", "text"],
        ),
    ),
    "record_prediction": (
        (
            "숫자 목표에 기한을 붙여 말했을 때 그 예측 하나를 남깁니다(한 대화 2개까지). 기한이 지나면 실제 값과 "
            "맞춰 봅니다. metric은 숫자 측정값 이름이나 axis:<축>입니다."
        ),
        _schema(
            {
                "metric": {
                    "type": "string",
                    "description": "숫자 측정값 이름(예: body_fat_pct, weight_kg) 또는 axis:career 같은 축",
                },
                "predicted": {"type": "number", "description": "예측 값(측정값이면 그 범위 안)"},
                "due": {"type": "string", "description": "기한 YYYY-MM-DD(내일~365일 뒤)"},
            },
            ["metric", "predicted", "due"],
        ),
    ),
    "save_life_report": ("전체 진단의 인생 리포트를 저장합니다. 아직 준비 중입니다.", _schema({}, [])),
})


# 라이프 매니저 대화(`RunContext.agent == "manager"`, SP15 6.1)의 도구. 비서 도구로 새지 않게 따로 둔다.
# 읽기 도구(본 스레드), 쓰기는 패널 초안·내가 한 말·예측·측정값 확인 카드뿐이다. 리포트 저장은 "전체 진단" 칩에만
MANAGER_READ_TOOLS: list[str] = [
    "list_tasks", "list_events", "list_habits", "read_conditions", "read_body_days", "list_workouts", "read_moments",
    "get_curve", "read_reviews", "read_measures_all", "list_statements", "read_benchmark", "read_panel_results",
    "find_conversations",
]
PANEL_WRITE_TOOLS: list[str] = ["propose_suggestion", "save_statement", "record_prediction", "propose_measures"]
REPORT_TOOLS: list[str] = ["save_life_report"]
# 전문가 서브에이전트마다 주는 읽기 도구(스펙 6.1 표 그대로). 쓰기 도구는 없다
EXPERT_TOOLS: dict[str, list[str]] = {
    "career": ["read_tasks_career", "read_measures_career", "search_memos", "read_memo", "list_statements",
               "read_benchmark"],
    "finance": ["read_measures_finance", "read_tasks_finance", "list_statements", "read_benchmark"],
    "health": ["get_measures", "read_body_days", "list_workouts", "read_conditions", "read_benchmark"],
    "image": ["read_measures_looks", "list_chat_photos", "read_benchmark"],
    "relationship": ["read_schedule_shape", "read_measures_relationships", "list_statements",
                     "read_tasks_relationships", "read_benchmark"],
    "psych": ["read_conditions", "read_moments", "get_curve", "read_reviews", "read_panel_results", "read_benchmark"],
}
_MANAGER_OWN = [*MANAGER_READ_TOOLS, *PANEL_WRITE_TOOLS, *REPORT_TOOLS]
# 전문가만 쓰는 도구(전문가 순서, 중복 없이). 서브에이전트가 받으려면 같은 서버에 있어야 하므로 매니저 호출에 함께
# 싣는다. 본 스레드에서 막을 후보다(계획 Task 11이 스파이크 결과대로 쓴다)
MANAGER_HIDDEN_TOOLS: list[str] = list(dict.fromkeys(
    n for names in EXPERT_TOOLS.values() for n in names if n not in _MANAGER_OWN
))


def manager_tool_names(ctx: RunContext) -> list[str]:
    """라이프 매니저 대화의 도구: 읽기 + 패널 쓰기 + ("전체 진단"이면) 리포트 저장 + 전문가 전용 읽기."""
    report = REPORT_TOOLS if ctx.chip == "manager_full" else []
    return [*MANAGER_READ_TOOLS, *PANEL_WRITE_TOOLS, *report, *MANAGER_HIDDEN_TOOLS]


def tool_names_for(ctx: RunContext) -> list[str]:
    """그 호출에 주는 도구(SP3-4 10장, SP8 6.3). 하루 끝 순간 호출은 `save_moments` 하나뿐, 대화 요약(SP9 7.2)·사진 읽기(SP10 5.4)는 없음.

    메이트 대화(SP12 5.3)는 `MATE_TOOLS`만, 라이프 매니저 대화(SP15)는 `manager_tool_names`. 호출 종류(순간·하루 끝 판단·요약·사진 읽기)가 상대보다 먼저다.
    그 밖에는 통로 규칙: 화면 도구(`ui_*`)와 카드 도구는 앱 대화에만 준다(6.4.7).
    """
    if ctx.kind == "moments":
        return list(MOMENTS_TOOLS)
    if ctx.kind == "dayend":  # SP14 6.2: 읽기 도구 + 관찰 도구. 상대보다 먼저
        return [*DAYEND_READ_TOOLS[ctx.agent], *DAYEND_TOOLS]  # type: ignore[index]
    # 대화 요약(SP9 7.2), 사진 읽기(SP10 5.4): 도구 없음. 사진 속 글이 지시처럼 보여도 쓸 도구가 없다
    if ctx.kind in NO_TOOL_KINDS:
        return []
    if ctx.agent == "mate":
        return list(MATE_TOOLS)
    if ctx.agent == "manager":
        return manager_tool_names(ctx)
    return [*TOOL_NAMES, *APP_ONLY_TOOLS] if ctx.channel == "app" else list(TOOL_NAMES)


def _stream_output(
    tools: Any, ctx: RunContext, name: str, args: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """스트림에 보낼 도구 출력(SP3-4 6.4.1, SP6 10.2 표): 화면 조각에 지금 값 `data`를 붙인다(`TodoRef`는 초안·소프트
    삭제 뺌, `today`는 논리적 날짜). 두뇌가 받는 결과는 `{"ok": true}` 그대로다. 읽기만 한다."""
    if name == "ui_todo_list":
        return {**result, "data": {"todos": tools.ui_todo_refs(args.get("task_ids"), drafts=False)}}
    if name == "ui_habit_check":
        return {**result, "data": {"habits": tools.ui_habit_list(args.get("date"))}}
    if name == "ui_date_choice":
        refs = tools.ui_todo_refs([args.get("task_id")], drafts=False)
        return {**result, "data": {"today": tools.today().isoformat(), "todo": refs[0] if refs else None}}
    if name == "ui_result":
        items = tools.ui_result_items(ctx, args.get("task_ids"))
        return {**result, "data": {"today": tools.today().isoformat(), "items": items}}
    if name == "ui_period_list":
        return {**result, "data": tools.ui_period_data(args)}
    if name == "ui_block":
        return {**result, "data": tools.ui_block_data(args)}
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
    if ui and w is not None and ctx.ui_drawn >= UI_PARTS_PER_REPLY:  # 10.4: 부르지 않고 조각도 없다
        return {"error": UI_CAP_ERROR}
    if name == "ui_habit_check" and args.get("date") is None:  # 날짜를 빼면 오늘: 조각 입력에도 채워 앱이 그릴 수 있게
        args = {**args, "date": tools.today().isoformat()}
    # 사용자가 시킨 할 일은 늘 날짜가 있다: 빼면 오늘(날짜 없는 할 일이 목록에서 안 보였다). 첫 걸음과 초안
    # (`propose_tasks`, 회고의 기간 목표 후보 등)은 날짜 없이 둘 수 있다.
    if name == "add_task" and args.get("planned_for") is None and args.get("parent_id") is None:
        args = {**args, "planned_for": tools.today().isoformat()}
    if name == "ui_events":  # `list_events` 항목 그대로 받는다: 조각 입력은 카탈로그 칸만(앱이 엄격히 읽는다)
        args = {**args, "items": ui_event_items(args.get("items"))}
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
                w.tool_output(call_id, to_api_times(_stream_output(tools, ctx, name, args, result)))
                ctx.ui_drawn += 1
                ctx.ui_drawn_names.append(name)
        elif "error" in result:
            w.tool_error(call_id, str(result["error"]))
        else:
            w.tool_output(call_id, to_api_times(result))
    return result


def _py_args(args: dict[str, Any]) -> dict[str, Any]:
    """도구 스키마의 키 `from`은 파이썬 예약어라 메서드 인자 `from_`으로 바꿔 넘긴다(`method(ctx, **args)`)."""
    return {("from_" if k == "from" else k): v for k, v in args.items()}


# 앱 대화에만 붙이는 설명(텔레그램에는 일정 도구가 없다, SP9 5.4)
_APP_NOTES = {
    "read_transcript": " 앱에서는 이 대화의 지난 원문만 읽습니다. 다른 대화는 find_conversations로 요약만 봅니다.",
    "add_task": " 시간이 정해진 일(\"내일 14:00 치과\")은 create_event로 일정을 만듭니다.",
    "propose_tasks": " 시간이 정해진 일은 초안이 아니라 create_event로 일정을 만듭니다.",
    "update_task": " 시각을 붙이려면 create_event로 일정을 만듭니다.",
}


def tool_description(name: str, ctx: RunContext) -> str:
    """도구 설명. 앱 대화면 `_APP_NOTES`를 덧붙인다."""
    description = _SPECS[name][0]
    return description + _APP_NOTES.get(name, "") if ctx.channel == "app" else description


def build_planner_tools(tools: Any, ctx: RunContext) -> list[SdkMcpTool[Any]]:
    """도구마다 `ctx`를 클로저로 감싼 SDK 도구 정의. 테스트는 `.handler`를 직접 await한다."""
    out: list[SdkMcpTool[Any]] = []
    for name in tool_names_for(ctx):
        _, schema = _SPECS[name]
        description = tool_description(name, ctx)
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

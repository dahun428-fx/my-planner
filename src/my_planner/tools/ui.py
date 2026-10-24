"""생성형 UI 카탈로그 (SP3-4 스펙 6.4.7, SP6 스펙 5~7장, 10.1, 10.3): 컴포넌트 이름, 출처, props의 JSON 스키마.

두뇌가 부르는 화면 도구(`ui_todo_list`, `ui_choice`, `ui_summary_card`, SP6의 `ui_date_choice`, `ui_result`,
`ui_period_list`, `ui_block`)와 하네스가 만드는 조각이 같은 카탈로그를 쓴다.
`validate_props`는 props를 스키마·쌓기 규칙·글 규칙으로 검사하기만 한다: DB와 파일을 건드리지 않는다. 오류 문구에는
값을 넣지 않는다(할 일 제목, 메모가 로그나 도구 오류로 새지 않게. 위치와 오류 종류만).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from functools import cache
from itertools import pairwise
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

UI_CATALOG_VERSION = "2026-10-24.4"

AreaName = Literal["career", "finance", "health", "relationships", "learning", "quality_of_life"]

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
_WEEK_PATTERN = r"^\d{4}-W\d{2}$"
_UNIQUE = {"uniqueItems": True}  # 정수 목록의 서로 다름은 앱 검사기도 본다(빈 곳 10)


def _text(lo: int, hi: int, **kw: Any) -> Any:
    """글자 수 상한(유니코드 코드 포인트, SP6 5.1)."""
    return Field(min_length=lo, max_length=hi, **kw)


def _distinct(values: list[Any]) -> None:
    if len(set(values)) != len(values):
        raise PydanticCustomError("not_unique", "서로 달라야 해요")


class _Props(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TodoListProps(_Props):
    title: str = Field(min_length=1)
    task_ids: list[int] = Field(min_length=1, max_length=30)


class ChoiceOption(_Props):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class ChoiceProps(_Props):
    question: str = Field(min_length=1)
    options: list[ChoiceOption] = Field(min_length=2, max_length=4)


class SummaryCardProps(_Props):
    title: str = Field(min_length=1)
    lines: list[Annotated[str, Field(max_length=120)]] = Field(min_length=1, max_length=8)


# --- SP6 완성 카드 셋 (스펙 6.2~6.4) ---


class DateCandidate(_Props):
    date: str = Field(pattern=_DATE_PATTERN)
    note: str | None = _text(1, 12, default=None)


class DateChoiceProps(_Props):
    """후보 날짜의 오늘~90일 범위는 G-BE2의 뜻 검사가 본다(스키마는 시계를 모른다, 빈 곳 9)."""

    task_id: int
    question: str = _text(1, 60)
    candidates: list[DateCandidate] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def _dates_distinct(self) -> DateChoiceProps:
        _distinct([c.date for c in self.candidates])
        return self


class ResultProps(_Props):
    task_ids: list[int] = Field(min_length=1, max_length=2, json_schema_extra=_UNIQUE)

    @model_validator(mode="after")
    def _ids_distinct(self) -> ResultProps:
        _distinct(self.task_ids)
        return self


class PeriodListProps(_Props):
    day: str | None = Field(default=None, pattern=_DATE_PATTERN)
    week: str | None = Field(default=None, pattern=_WEEK_PATTERN)
    highlight_task_ids: list[int] = Field(default=[], max_length=30, json_schema_extra=_UNIQUE)

    @model_validator(mode="after")
    def _one_period(self) -> PeriodListProps:
        if (self.day is None) == (self.week is None):
            raise PydanticCustomError("period_one", "day와 week 가운데 꼭 하나만 있어야 해요")
        _distinct(self.highlight_task_ids)
        return self


class HabitCheckProps(_Props):
    """오늘 습관 줄 묶음(SP7 스펙 9장). 지금 값은 BE가 `data.habits`로 붙인다. 달력에 없는 날짜는 도구가 거른다."""

    date: str = Field(pattern=_DATE_PATTERN)


# --- SP6 기본 부품 열 가지 (스펙 5장) ---


class HeadingEl(_Props):
    type: Literal["heading"]
    text: str = _text(1, 40)


class TextEl(_Props):
    type: Literal["text"]
    md: str = _text(1, 280)


class Delta(_Props):
    text: str = _text(1, 8)
    trend: Literal["up", "down", "same"]


class StatEl(_Props):
    type: Literal["stat"]
    label: str = _text(1, 16)
    value: str = _text(1, 10)
    delta: Delta | None = None


class ProgressEl(_Props):
    type: Literal["progress"]
    label: str = _text(1, 16)
    value: int = Field(ge=0)
    max: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def _within_max(self) -> ProgressEl:
        if self.value > self.max:
            raise PydanticCustomError("value_over_max", "value는 max 이하여야 해요")
        return self


class TodoRowsEl(_Props):
    type: Literal["todo_rows"]
    task_ids: list[int] = Field(min_length=1, max_length=10, json_schema_extra=_UNIQUE)
    checkable: bool = True  # 빈 곳 3: 지금 `ui_todo_list`처럼 체크할 수 있음

    @model_validator(mode="after")
    def _ids_distinct(self) -> TodoRowsEl:
        _distinct(self.task_ids)
        return self


class TextTag(_Props):
    text: str = _text(1, 12)


class AreaTag(_Props):
    area: AreaName


class TagsEl(_Props):
    type: Literal["tags"]
    items: list[TextTag | AreaTag] = Field(min_length=1, max_length=6)


class BulletsEl(_Props):
    type: Literal["bullets"]
    items: list[Annotated[str, _text(1, 80)]] = Field(min_length=1, max_length=6)


OpenScreen = Literal["today", "todos_day", "todos_week", "todos_month", "activity", "settings"]


class SendDo(_Props):
    kind: Literal["send"]


class OpenDo(_Props):
    kind: Literal["open"]
    screen: OpenScreen


class CompleteDo(_Props):
    kind: Literal["complete"]
    task_id: int


class Button(_Props):
    label: str = _text(1, 16)
    do: Annotated[SendDo | OpenDo | CompleteDo, Field(discriminator="kind")]


class ButtonsEl(_Props):
    type: Literal["buttons"]
    items: list[Button] = Field(min_length=1, max_length=3)


class DividerEl(_Props):
    type: Literal["divider"]


RowChild = Annotated[StatEl | ProgressEl, Field(discriminator="type")]
# 묶음 안(`stack`)에 오는 부품: `group`, `buttons`를 뺀 여덟(B2·B3)
Inner = Annotated[
    HeadingEl | TextEl | StatEl | ProgressEl | TodoRowsEl | TagsEl | BulletsEl | DividerEl,
    Field(discriminator="type"),
]


class RowGroup(_Props):
    type: Literal["group"]
    layout: Literal["row"]
    children: list[RowChild] = Field(min_length=2, max_length=3)


class StackGroup(_Props):
    type: Literal["group"]
    layout: Literal["stack"]
    children: list[Inner] = Field(min_length=2, max_length=6)


# 구분 유니언 두 단계(10.1): `type` 하나로는 두 묶음을 가를 수 없어 안쪽을 `layout`으로 가른다
GroupEl = Annotated[RowGroup | StackGroup, Field(discriminator="layout")]
Element = Annotated[
    HeadingEl | TextEl | StatEl | ProgressEl | TodoRowsEl | TagsEl | BulletsEl | ButtonsEl | DividerEl | GroupEl,
    Field(discriminator="type"),
]

BLOCK_MAX_PARTS = 12
_CONTENT = (TextEl, StatEl, ProgressEl, TodoRowsEl, TagsEl, BulletsEl)


def _rule(code: str) -> PydanticCustomError:
    return PydanticCustomError(code, _HINTS[code])


class BlockProps(_Props):
    """조립 카드 (7장). 스키마가 B2·B3과 길이·개수를, 이 검사가 B1, B4~B8을 본다(B9는 `validate_props`)."""

    title: str = _text(1, 40)
    children: list[Element] = Field(min_length=1, max_length=BLOCK_MAX_PARTS)

    @model_validator(mode="after")
    def _stacking(self) -> BlockProps:
        groups = [c for c in self.children if isinstance(c, RowGroup | StackGroup)]
        flat = [x for c in self.children for x in ([c, *c.children] if isinstance(c, RowGroup | StackGroup) else [c])]
        # B1: 묶음 하나는 1 + 아이 수
        if len(flat) > BLOCK_MAX_PARTS:
            raise _rule("block_too_many")
        # B4: 버튼 줄은 하나, 맨 위 단계의 끝(묶음 안에는 스키마가 막는다)
        buttons = [i for i, c in enumerate(self.children) if isinstance(c, ButtonsEl)]
        if len(buttons) > 1 or (buttons and buttons[0] != len(self.children) - 1):
            raise _rule("buttons_place")
        # B5
        rows = [x for x in flat if isinstance(x, TodoRowsEl)]
        if len(rows) > 2:
            raise _rule("todo_rows_too_many")
        # B6: 처음·끝이 아니고 둘이 붙지 않음(묶음 안에서도)
        for seq in (self.children, *(g.children for g in groups)):
            kinds = [isinstance(x, DividerEl) for x in seq]
            if kinds[0] or kinds[-1] or any(a and b for a, b in pairwise(kinds)):
                raise _rule("divider_place")
        # B7
        if not any(isinstance(x, _CONTENT) for x in flat):
            raise _rule("block_no_content")
        # B8
        row_ids = {i for r in rows for i in r.task_ids}
        for b in (c for c in self.children if isinstance(c, ButtonsEl)):
            if any(isinstance(it.do, CompleteDo) and it.do.task_id not in row_ids for it in b.items):
                raise _rule("complete_not_in_rows")
        return self


# --- 하네스 조각 ---


class TodoDraftProps(_Props):
    task_ids: list[int] = Field(min_length=1)


class ConditionPickerProps(_Props):
    date: str = Field(pattern=_DATE_PATTERN)


class LadderPickerProps(_Props):
    period: str = Field(min_length=1)
    field: Literal["now", "future"]


class AreaScoresProps(_Props):
    period: str = Field(min_length=1)
    previous: dict[AreaName, Annotated[int, Field(ge=1, le=10)]]


class MilestoneDraftProps(_Props):
    milestone_ids: list[int] = Field(min_length=1, max_length=10)


class ChapterDraftProps(_Props):
    chapter_ids: list[int] = Field(min_length=1, max_length=5)


class ConfirmProps(_Props):
    summary: str
    confirm_token: str
    action: str
    args: dict[str, Any]


Origin = Literal["brain", "harness"]

# 스펙 6.4.7 표의 순서. 두뇌가 부르는 것이 먼저(기존 셋, SP6 넷), 하네스가 뒤
_COMPONENTS: dict[str, tuple[Origin, type[_Props]]] = {
    "ui_todo_list": ("brain", TodoListProps),
    "ui_choice": ("brain", ChoiceProps),
    "ui_summary_card": ("brain", SummaryCardProps),
    "ui_date_choice": ("brain", DateChoiceProps),
    "ui_result": ("brain", ResultProps),
    "ui_period_list": ("brain", PeriodListProps),
    "ui_block": ("brain", BlockProps),
    "ui_habit_check": ("brain", HabitCheckProps),
    "ui_todo_draft": ("harness", TodoDraftProps),
    "ui_condition_picker": ("harness", ConditionPickerProps),
    "ui_ladder_picker": ("harness", LadderPickerProps),
    "ui_area_scores": ("harness", AreaScoresProps),
    "ui_milestone_draft": ("harness", MilestoneDraftProps),
    "ui_chapter_draft": ("harness", ChapterDraftProps),
    "ui_confirm": ("harness", ConfirmProps),
}

UI_COMPONENTS: dict[str, dict[str, Any]] = {
    name: {"origin": origin, "schema": model.model_json_schema()} for name, (origin, model) in _COMPONENTS.items()
}

# 화면 도구 판정(`mcp_adapter.call_tool`). 두뇌에게 주는 목록은 `mcp_adapter.APP_ONLY_TOOLS`가 따로 정한다
BRAIN_COMPONENTS = tuple(n for n, (origin, _) in _COMPONENTS.items() if origin == "brain")
# 고정 카드가 될 수 있는 조각(`pin_card`). SP6의 넷은 그때의 값이라 오늘 화면에 남으면 낡는다(스펙 15장 2)
PINNABLE_COMPONENTS = ("ui_todo_list", "ui_choice", "ui_summary_card")

# --- 검사 (10.3, 7.2 B9, 부록 B) ---

PROPS_MAX_BYTES = 8192
TEXT_MD_MAX_NEWLINES = 4
APP_BANNED_WORDS = ("연속", "스트릭", "달성률")  # SP5 10장

# 두뇌가 고칠 수 있게 새 `code` 뒤에 붙이는 한 마디(부록 B)
_HINTS = {
    "block_too_many": "부품은 모두 12개까지예요",
    "buttons_place": "버튼 줄은 하나만, 맨 끝에 둬요",
    "todo_rows_too_many": "할 일 줄은 둘까지예요",
    "divider_place": "구분선은 처음·끝에 두지 않고 둘을 붙이지 않아요",
    "block_no_content": "내용 부품이 하나는 있어야 해요",
    "complete_not_in_rows": "완료 버튼의 할 일은 같은 카드의 할 일 줄에 있어야 해요",
    "too_large": "조각이 너무 커요",
    "bad_char": "쓸 수 없는 글자가 있어요",
    "banned_word": "쓰지 않는 말이 있어요",
    "slash": "/로 시작하는 글은 쓸 수 없어요",
}
# `model_validator`가 내는 code: 위치는 늘 `props`다
_PROPS_LEVEL = frozenset({
    "block_too_many", "buttons_place", "todo_rows_too_many", "divider_place", "block_no_content",
    "complete_not_in_rows", "period_one", "value_over_max", "not_unique",
})

_BANNED_BLOCK = re.compile(r"<!-- banned-words:start -->(.*?)<!-- banned-words:end -->", re.DOTALL)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BIDI = re.compile(r"[\u202a-\u202e\u2066-\u2069]")


@cache
def banned_words() -> tuple[str, ...]:
    """`system.md`의 `banned-words` 블록(정본 하나) + 앱용 셋. 한 번 읽어 둔다."""
    from my_planner.harness import prompts

    block = _BANNED_BLOCK.search(prompts.load("system.md"))
    if block is None:  # 표지가 깨지면 금지어 검사가 조용히 약해지지 않게
        raise RuntimeError("system.md에 banned-words 블록이 없어요")
    words = re.findall(r'"([^"]+)"', block.group(1))
    return (*dict.fromkeys(w.strip() for w in words if w.strip()), *APP_BANNED_WORDS)


def _fail(where: str, code: str) -> str:
    hint = _HINTS.get(code)
    return f"{where}: {code} ({hint})" if hint else f"{where}: {code}"


def _strings(value: Any, loc: tuple[Any, ...], parent: Any = None) -> Iterator[tuple[tuple[Any, ...], str, Any]]:
    """props 안의 글 값을 차례대로 `(위치, 글, 그 글을 가진 dict 또는 None)`으로."""
    if isinstance(value, str):
        yield loc, value, parent
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, (*loc, k), value)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, (*loc, i), None)


def _text_error(component: str, props: dict[str, Any]) -> str | None:
    """두뇌 조각의 글 검사(10.3): 제어 문자·방향 문자 `bad_char`, 금지어 `banned_word`, `/` 시작 `slash`."""
    words = banned_words()
    for loc, s, parent in _strings(props, ()):
        key = loc[-1]
        is_md = component == "ui_block" and key == "md" and isinstance(parent, dict) and parent.get("type") == "text"
        controls = _CONTROL.findall(s)
        if (controls and not (is_md and set(controls) == {"\n"} and len(controls) <= TEXT_MD_MAX_NEWLINES)) or (
            _BIDI.search(s)
        ):
            return _fail(_where(loc), "bad_char")
        if any(w in s for w in words):
            return _fail(_where(loc), "banned_word")
        sends = key == "label" and isinstance(parent, dict) and (
            (component == "ui_choice" and loc[0] == "options")
            or (isinstance(parent.get("do"), dict) and parent["do"].get("kind") == "send")
        )
        if sends and s.strip().startswith("/"):  # `bot.commands.command_of`처럼 앞뒤 공백(U+3000 포함)을 뺀다
            return _fail(_where(loc), "slash")
    return None


def _where(loc: tuple[Any, ...]) -> str:
    return ".".join(str(p) for p in loc) or "props"


def validate_props(component: str, props: Any) -> str | None:
    """카탈로그에 맞으면 None, 아니면 사람용 오류 한 줄 `"{위치}: {code}"`(값은 담지 않는다).

    순서: (1) 스키마와 쌓기 규칙 (2) B9 크기 (3) 두뇌 조각만 글 검사(10.3). 하네스 조각은 (3)을 하지 않는다."""
    entry = _COMPONENTS.get(component)
    if entry is None:
        return "알 수 없는 화면 조각이에요."
    if not isinstance(props, dict):
        return "props는 객체여야 해요."
    origin, model = entry
    try:
        model.model_validate(props)
    except ValidationError as e:
        first = e.errors(include_input=False, include_url=False, include_context=False)[0]
        code = first["type"]
        loc = first["loc"][:-1] if code == "extra_forbidden" else first["loc"]  # 두뇌가 지은 키 이름도 담지 않는다
        return _fail("props" if code in _PROPS_LEVEL else _where(loc), code)
    if len(json.dumps(props, ensure_ascii=False).encode()) > PROPS_MAX_BYTES:
        return _fail("props", "too_large")
    if origin == "brain":
        return _text_error(component, props)
    return None


def catalog() -> dict[str, Any]:
    """`GET /ui/catalog`의 본문."""
    return {"version": UI_CATALOG_VERSION, "components": UI_COMPONENTS}

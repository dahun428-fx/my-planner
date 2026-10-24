"""생성형 UI 카탈로그 (SP3-4 스펙 6.4.7): 컴포넌트 이름, 출처, props의 JSON 스키마.

두뇌가 부르는 화면 도구(`ui_todo_list`, `ui_choice`, `ui_summary_card`)와 하네스가 만드는 조각이 같은 카탈로그를 쓴다.
`validate_props`는 props를 스키마로 검사하기만 한다: DB와 파일을 건드리지 않는다. 오류 문구에는 값을 넣지 않는다
(할 일 제목, 메모가 로그나 도구 오류로 새지 않게. 위치와 오류 종류만).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

UI_CATALOG_VERSION = "2026-10-24.2"

AreaName = Literal["career", "finance", "health", "relationships", "learning", "quality_of_life"]


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


class TodoDraftProps(_Props):
    task_ids: list[int] = Field(min_length=1)


class ConditionPickerProps(_Props):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


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

# 스펙 6.4.7 표의 순서. 두뇌가 부르는 셋이 먼저
_COMPONENTS: dict[str, tuple[Origin, type[_Props]]] = {
    "ui_todo_list": ("brain", TodoListProps),
    "ui_choice": ("brain", ChoiceProps),
    "ui_summary_card": ("brain", SummaryCardProps),
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

BRAIN_COMPONENTS = tuple(n for n, (origin, _) in _COMPONENTS.items() if origin == "brain")


def validate_props(component: str, props: Any) -> str | None:
    """카탈로그 스키마에 맞으면 None, 아니면 사람용 오류 한 줄(값은 담지 않는다)."""
    entry = _COMPONENTS.get(component)
    if entry is None:
        return "알 수 없는 화면 조각이에요."
    if not isinstance(props, dict):
        return "props는 객체여야 해요."
    try:
        entry[1].model_validate(props)
    except ValidationError as e:
        first = e.errors(include_input=False, include_url=False)[0]
        where = ".".join(str(p) for p in first["loc"]) or "props"
        return f"{where}: {first['type']}"
    return None


def catalog() -> dict[str, Any]:
    """`GET /ui/catalog`의 본문."""
    return {"version": UI_CATALOG_VERSION, "components": UI_COMPONENTS}

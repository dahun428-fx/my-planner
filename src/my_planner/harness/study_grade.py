"""공부 앱 단어 설명 채점 (ADR 0025): 학생이 AI 용어를 자기 말로 설명하면 두뇌가 채점하고 짧은 피드백을 준다.

- 실행 종류 `study_grade`의 **도구 없는 한 번 호출**(`mcp_adapter.tool_names_for`가 빈 목록). 사진 읽기·대화 요약과
  같은 틀이다: `persist_session=False`, `max_turns=1`, 세션 이어 가기 없음. 두뇌 큐·`brain_calls` 셈·세션 파일
  지우기·상한은 부르는 쪽(디스패처의 `grade_study`)이 한다.
- 지시문(system)은 `prompts/study_grade.md`(맨 앞 HTML 주석은 뺀다). 입력은 용어, 참고 뜻풀이, `<answer>`로 싼 학생 설명.
- 두뇌 답은 JSON 하나(`{"score", "good", "missing", "wrong", "tip"}`). `parse_grade`가 읽고 자른다. 모양이 틀리면 None.
- 비서의 기억(원문 기록, 활동 기록, 경험치)에는 아무것도 남기지 않는다. 로그에는 점수와 글자 수만 남긴다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from my_planner.domain import RunContext
from my_planner.harness import prompts

if TYPE_CHECKING:
    from my_planner.harness.brain import BrainResult

log = logging.getLogger(__name__)

PROMPT_FILE = "study_grade.md"
GRADE_MAX_TURNS = 1
TERM_MAX = 80
MEANING_MAX = 1000
ANSWER_MAX = 1000
ITEMS_MAX = 3  # good·missing·wrong 각각
ITEM_MAX_CHARS = 120
TIP_MAX_CHARS = 200

Verdict = Literal["great", "close", "retry"]
_Text = Annotated[str, StringConstraints(strip_whitespace=True)]


class GradeRequest(BaseModel):
    """`POST /study/grade`의 본문. 모르는 필드는 거절한다. `answer`가 비면 거절(앱이 빈 설명은 보내지 않는다)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    term: Annotated[_Text, Field(min_length=1, max_length=TERM_MAX)]
    meaning: Annotated[_Text, Field(max_length=MEANING_MAX)] = ""
    answer: Annotated[_Text, Field(min_length=1, max_length=ANSWER_MAX)]


def parse_request(value: Any) -> GradeRequest | None:
    """받은 값(JSON 객체)을 검증한다. 틀리면 None(무엇이 틀렸는지는 돌려주지 않는다)."""
    try:
        return GradeRequest.model_validate(value)
    except ValidationError:
        return None


@dataclass(frozen=True)
class GradeResult:
    score: int
    good: tuple[str, ...]
    missing: tuple[str, ...]
    wrong: tuple[str, ...]
    tip: str

    @property
    def verdict(self) -> Verdict:
        """앱이 보일 한 단어 판정. 지시문의 점수 구간과 같다."""
        if self.score >= 80:
            return "great"
        return "close" if self.score >= 50 else "retry"

    def dump(self) -> dict[str, Any]:
        return {
            "score": self.score, "verdict": self.verdict, "good": list(self.good), "missing": list(self.missing),
            "wrong": list(self.wrong), "tip": self.tip,
        }


class StudyGradeFailed(Exception):
    """두뇌가 답하지 못했거나 답 모양이 틀렸다. 503(앱은 스스로 채점으로 넘어간다)."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class StudyGradeLimit(Exception):
    """채점에 쓸 두뇌 호출이 오늘 남지 않았다(비서 몫은 남겨 둔다). 429."""


class StudyGradeBrain(Protocol):
    async def run(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext,
        system_prompt: str | None = None, max_turns: int | None = None, persist_session: bool = True,
    ) -> BrainResult: ...


_COMMENT = re.compile(r"^\s*<!--.*?-->\s*", re.DOTALL)


@cache
def system_prompt() -> str:
    return _COMMENT.sub("", prompts.load(PROMPT_FILE)).strip()


def build_prompt(req: GradeRequest) -> str:
    """사용자 메시지 하나. 학생 설명 안의 `</answer>`는 끝 표시로 읽히지 않게 바꾼다."""
    answer = req.answer.replace("</answer>", "</ answer>")
    meaning = req.meaning or "(없음: 네가 아는 뜻으로 채점한다)"
    return f"용어: {req.term}\n참고 뜻풀이: {meaning}\n\n<answer>\n{answer}\n</answer>"


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _items(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    out = [v.strip()[:ITEM_MAX_CHARS] for v in value if isinstance(v, str) and v.strip()]
    return tuple(out[:ITEMS_MAX])


def parse_grade(text: str) -> GradeResult | None:
    """두뇌 답(JSON)을 읽는다. 코드 블록 표시와 앞뒤 글은 벗긴다. 점수는 0~100으로 묶고 목록·팁은 자른다.
    점수가 숫자가 아니거나 목록 모양이 틀리면 None."""
    raw = _FENCE.sub("", text.strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data: Any = json.loads(raw[start: end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    good, missing, wrong = _items(data.get("good", [])), _items(data.get("missing", [])), _items(data.get("wrong", []))
    if good is None or missing is None or wrong is None:
        return None
    tip = data.get("tip", "")
    tip = tip.strip()[:TIP_MAX_CHARS] if isinstance(tip, str) else ""
    return GradeResult(score=max(0, min(100, round(score))), good=good, missing=missing, wrong=wrong, tip=tip)


async def grade(brain: StudyGradeBrain, req: GradeRequest) -> GradeResult:
    """두뇌를 한 번 부른다. 실패나 모양 틀림은 `StudyGradeFailed`."""
    run_ctx = RunContext(None, None, kind="study_grade", actor="secretary", activity_channel="app", channel="app")
    result = await brain.run(
        build_prompt(req), session_id=None, run_ctx=run_ctx, system_prompt=system_prompt(),
        max_turns=GRADE_MAX_TURNS, persist_session=False,
    )
    if result.status != "ok":
        raise StudyGradeFailed(result.status)
    got = parse_grade(result.text)
    if got is None:
        raise StudyGradeFailed("bad_reply")
    return got

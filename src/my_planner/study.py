"""공부 앱(AI 듀오링고)의 진도: 모양 검증과 합치기 (ADR 0024).

공부 앱은 다른 저장소의 정적 PWA이고, 진도는 기기마다 `localStorage`에 있다. BE는 기기들이 보낸 진도를 합친 한 벌을
`app_state.study_progress`에 둔다. 합치기는 순서와 반복에 상관없이 같은 결과가 되게 한다(교환·결합·멱등):

- `done`(끝낸 레슨), `days`(공부한 날): 합집합.
- `best`(레슨마다 최고 정답률), `spoke`(레슨마다 말해 본 횟수): 키마다 큰 값.
- `xp_by`(기기마다 그 기기에서 번 XP): 키마다 큰 값. 총 XP는 값의 합이다. 기기마다 자기 칸만 올리므로, 두 기기가
  따로 번 XP가 합쳐질 때 어느 쪽도 사라지지 않는다.

이 모듈은 저장소도 HTTP도 모른다. 진도 값은 로그에 넣지 않는다.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

LESSONS_MAX = 500
DAYS_MAX = 2000
DEVICES_MAX = 50
XP_MAX = 10_000_000
SPOKE_MAX = 100_000

LessonId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")]
DeviceKey = Annotated[str, Field(pattern=r"^[a-z0-9]{8,32}$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class StudyProgress(BaseModel):
    """`GET`/`PUT /study/progress`의 본문. 모르는 필드와 소수·불리언 숫자는 거절한다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    v: Literal[1] = 1
    done: list[LessonId] = Field(default_factory=list, max_length=LESSONS_MAX)
    days: list[Day] = Field(default_factory=list, max_length=DAYS_MAX)
    best: dict[LessonId, Annotated[int, Field(ge=0, le=100)]] = Field(default_factory=dict, max_length=LESSONS_MAX)
    spoke: dict[LessonId, Annotated[int, Field(ge=0, le=SPOKE_MAX)]] = Field(
        default_factory=dict, max_length=LESSONS_MAX
    )
    xp_by: dict[DeviceKey, Annotated[int, Field(ge=0, le=XP_MAX)]] = Field(
        default_factory=dict, max_length=DEVICES_MAX
    )

    @field_validator("days")
    @classmethod
    def _real_days(cls, days: list[str]) -> list[str]:
        for d in days:
            date.fromisoformat(d)  # 2026-02-30 같은 없는 날은 ValueError → 검증 오류
        return days


def parse(value: Any) -> StudyProgress | None:
    """받은 값(JSON 객체)을 검증한다. 틀리면 None(무엇이 틀렸는지는 돌려주지 않는다)."""
    try:
        return StudyProgress.model_validate(value)
    except ValidationError:
        return None


def load(raw: str | None) -> StudyProgress:
    """`app_state`에 둔 글. 없거나 읽을 수 없으면 빈 진도(다음 `PUT`이 다시 채운다)."""
    if not raw:
        return StudyProgress()
    try:
        return StudyProgress.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        return StudyProgress()


def _max_by_key(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: max(a.get(k, 0), b.get(k, 0)) for k in sorted({*a, *b})}


def merge(a: StudyProgress, b: StudyProgress) -> StudyProgress | None:
    """두 진도를 합친다. 합친 결과가 상한(레슨·날·기기 수)을 넘으면 None."""
    merged = {
        "v": 1,
        "done": sorted({*a.done, *b.done}),
        "days": sorted({*a.days, *b.days}),
        "best": _max_by_key(a.best, b.best),
        "spoke": _max_by_key(a.spoke, b.spoke),
        "xp_by": _max_by_key(a.xp_by, b.xp_by),
    }
    return parse(merged)


def dump(p: StudyProgress) -> dict[str, Any]:
    """응답과 저장에 쓰는 JSON 값. 목록은 정렬돼 있다."""
    return p.model_dump(mode="json")


def dumps(p: StudyProgress) -> str:
    return json.dumps(dump(p), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

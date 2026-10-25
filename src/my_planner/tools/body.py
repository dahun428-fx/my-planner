"""몸 기록 도구 (SP8 스펙 7.2, 7.3). `Tools`가 이 mixin을 상속한다.

`record_body_days`는 `POST /body`만 부르는 즉시 갈래의 내부 동작이다(`ActionSpec(endpoint="body")`): 두뇌 도구 목록에도
`/actions`에도 없다. 검증은 처리기(`api/body.parse_body_days`)가 하고, 여기서는 모양을 한 번 더 본다.
활동 기록·경험치는 없다(센서 값이고 자동 전송이다). 숫자는 로그·결과에 넣지 않는다(결과는 날 수만).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from my_planner.domain import RunContext
from my_planner.store.repos.body import BodyDay
from my_planner.tools._base import _err, _tool

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.body import BodyRepo

MSG_NO_BODY = "몸 기록을 쓸 수 없어요."
MSG_SHAPE = "걸음 수와 잠만 받아요."  # 부록 A "몸 기록 API 오류"
_KEYS = frozenset({"date", "steps", "sleep_minutes"})


def _value(v: Any) -> int | None | str:
    if v is None:
        return None
    return v if type(v) is int else MSG_SHAPE


def _days(days: Any) -> list[BodyDay] | str:
    if not isinstance(days, list) or not days:
        return MSG_SHAPE
    out = []
    for item in days:
        if not isinstance(item, dict) or not set(item) <= _KEYS or not isinstance(item.get("date"), str):
            return MSG_SHAPE
        try:
            d = date.fromisoformat(item["date"])
        except ValueError:
            return MSG_SHAPE
        steps, sleep = _value(item.get("steps")), _value(item.get("sleep_minutes"))
        if isinstance(steps, str) or isinstance(sleep, str) or (steps is None and sleep is None):
            return MSG_SHAPE
        out.append(BodyDay(d, steps, sleep))
    return out


class BodyTools:
    body: BodyRepo | None

    if TYPE_CHECKING:
        clock: Clock

    @_tool
    def record_body_days(self, ctx: RunContext, days: Any = None) -> dict[str, Any]:
        """날짜마다 보낸 값만 넣거나 바꾼다(`BodyRepo.upsert`, 한 트랜잭션). 결과는 저장한 날 수만."""
        if self.body is None:
            return _err(MSG_NO_BODY)
        parsed = _days(days)
        if isinstance(parsed, str):
            return _err(parsed)
        return {"saved": self.body.upsert(parsed, self.clock.now())}

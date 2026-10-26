"""일정 정리 알림 설정 바꾸기 (SP9b 스펙 5장, 5.1). `Tools`가 이 mixin을 상속한다.

- 설정은 `app_state.digest_settings`(`StateRepo.get_digest_settings`)에 종류마다 `{"on", "time"}`로 둔다. 없는 칸은
  config.toml `[schedule.digest]` 값이다. 러너는 tick마다 다시 읽는다(재시작 없음).
- 허용 범위: 아침 04:00~11:50, 밤 18:00~23:50, 10분 단위(`loop.digests.validate_digest_time`). 벗어나거나 모르는
  종류면 API는 `422 digest_time_invalid`.
- 즉시 갈래(앱 설정 `PUT /settings/digests`)만 부른다(`endpoint="push"`). 채팅 도구와 확인 카드는 없다. 지금과 같은
  값이면 아무것도 적지 않고 활동·되돌리기도 없다(자연 멱등, 멱등 키 없음).
- 적용 시점(`applies`): 논리적 오늘의 그 종류 슬롯이 아직 판정 전이고 보낼 시각이 지금보다 뒤면 오늘, 아니면 내일.
- 활동 `kind = "digest_set"`, 대상 `digest:<kind>`. 되돌리기는 바꾸기 전 값을 다시 적는다(`digest_last`는 그대로).
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from my_planner.loop.digests import (
    DIGEST_KINDS,
    DigestKind,
    DigestSetting,
    validate_digest_time,
)
from my_planner.tools._base import _err
from my_planner.tools.activity import record_activity, register_undo
from my_planner.tools.confirmations import digest_set_line

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.domain import RunContext
    from my_planner.store.repos.state import StateRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

ACTION = "set_digest_settings"
KIND = "digest_set"

Applies = Literal["today", "tomorrow"]

MSG_INVALID = "일정 정리 알림 시간은 아침 04:00~11:50, 밤 18:00~23:50 사이에서 10분 단위로 정할 수 있어요."
MSG_ON = "on은 true, false 중 하나예요."
MSG_UNAVAILABLE = "일정 정리 알림을 바꿀 수 없어요."


def digest_target(kind: str) -> str:
    return f"digest:{kind}"


def parse_digest_kind(v: Any) -> DigestKind | None:
    return v if v in DIGEST_KINDS else None


def _setting_json(s: DigestSetting) -> dict[str, Any]:
    return {"on": s.on, "time": f"{s.time:%H:%M}"}


class DigestSettingTools:
    """`Tools`가 상속한다. `self.state`, `self.settings`가 없으면 거절한다."""

    state: StateRepo | None
    settings: Settings | None

    def _digest_applies(self: Tools, kind: DigestKind, at: time) -> Applies:
        """논리적 오늘 슬롯(그 날짜 + `at`, 현지)이 아직 판정 전이고 지금보다 뒤면 `today`. 범위가 04:00 경계 뒤라
        슬롯의 달력 날짜는 논리적 오늘과 같다."""
        assert self.state is not None and self.settings is not None
        today = self.today()
        done = self.state.get_digest_last()[kind]
        if done is not None and done >= today:
            return "tomorrow"
        due = datetime.combine(today, at, ZoneInfo(self.settings.timezone))
        return "today" if due > self.clock.now() else "tomorrow"

    def apply_digest_settings(
        self: Tools, ctx: RunContext, kind: Any = None, on: Any = None, time: Any = None
    ) -> dict[str, Any]:
        """즉시 갈래(앱 설정): 한 종류를 바로 적용하고 되돌릴 수 있게 활동을 남긴다(한 트랜잭션).
        지금과 같은 값이면 `{"unchanged": True}`(아무것도 적지 않는다)."""
        if self.state is None or self.settings is None:
            return _err(MSG_UNAVAILABLE)
        k = parse_digest_kind(kind)
        new_time = validate_digest_time(k, time) if k is not None else None
        if k is None or new_time is None:
            return _err(MSG_INVALID)
        if not isinstance(on, bool):
            return _err(MSG_ON)
        settings = self.state.get_digest_settings(self.settings.schedule.digest)
        before, after = settings[k], DigestSetting(on, new_time)
        if before == after:
            return {"unchanged": True}
        # 끄기는 옛 시각으로 본다(오늘 그 시각에 보낼 것이 사라지는지)
        applies = self._digest_applies(k, after.time if after.on else before.time)
        settings[k] = after
        with self.tasks.transaction():
            self.state.set_digest_settings(settings)
            record_activity(
                self.activity, ctx, kind=KIND, target=digest_target(k), summary=digest_set_line(k, before, after),
                risk="low", undo={"kind": k, "setting": _setting_json(before)},
            )
        log.info("digest_set", extra={"kind": k, "on": after.on, "applies": applies})
        return {"kind": k, "on": after.on, "time": f"{after.time:%H:%M}", "applies": applies}


def _undo_digest_settings(tools: Tools, payload: dict[str, Any], ctx: RunContext) -> str | None:
    """되돌리기 = 바꾸기 전 값을 그 종류에 다시 적기. `digest_last`는 건드리지 않는다(이미 판정한 슬롯을 되살리지
    않는다). 다른 종류는 지금 값 그대로다."""
    assert tools.state is not None and tools.settings is not None
    kind: DigestKind = payload["kind"]
    old = payload["setting"]
    settings = tools.state.get_digest_settings(tools.settings.schedule.digest)
    settings[kind] = DigestSetting(bool(old["on"]), time.fromisoformat(old["time"]))
    tools.state.set_digest_settings(settings)
    return None


register_undo(KIND, _undo_digest_settings)

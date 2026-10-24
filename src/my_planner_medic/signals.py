"""신호 모델. 티켓 05가 이 파일에 함수를 더한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Part = Literal["be", "app", "dashboard", "vercel", "ci"]
Kind = Literal["exception", "warn_burst", "client_error", "health", "late_run", "no_reply", "record"]


@dataclass(frozen=True)
class Signal:
    fingerprint: str
    part: Part
    kind: Kind
    at: datetime

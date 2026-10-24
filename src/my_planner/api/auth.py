"""Bearer 토큰 검사와 실패 횟수 제한 (SP3-4 스펙 6.1, 14).

토큰은 `Authorization: Bearer <API_TOKEN>` 헤더로만 받는다(쿼리 문자열, 쿠키 안 됨). 비교는 상수 시간.
1분에 실패 10회면 1분 동안 모든 요청을 `429`로 거절한다. 토큰은 로그, 오류 응답 어디에도 쓰지 않는다.
"""

from __future__ import annotations

import hmac
from collections import deque
from datetime import datetime, timedelta

from my_planner.clock import Clock

_SCHEME = "Bearer "


def bearer_ok(header: str | None, token: str) -> bool:
    """`Authorization` 헤더 값이 `Bearer <token>`과 같은가. 빈 토큰은 언제나 거절한다."""
    if not token or not header or not header.startswith(_SCHEME):
        return False
    return hmac.compare_digest(header[len(_SCHEME):].encode("utf-8"), token.encode("utf-8"))


class AuthLimiter:
    """창(`window`) 안의 실패가 `max_failures`에 닿으면 그때부터 `window` 동안 막는다."""

    def __init__(self, clock: Clock, *, max_failures: int = 10, window: timedelta = timedelta(minutes=1)) -> None:
        self.clock = clock
        self.max_failures = max_failures
        self.window = window
        self._failures: deque[datetime] = deque()
        self._blocked_until: datetime | None = None

    def blocked(self) -> bool:
        now = self.clock.now()
        if self._blocked_until is None:
            return False
        if now < self._blocked_until:
            return True
        self._blocked_until = None
        self._failures.clear()
        return False

    def record_failure(self) -> bool:
        """실패를 하나 센다. 이번 실패로 막히기 시작했으면 True."""
        now = self.clock.now()
        while self._failures and now - self._failures[0] >= self.window:
            self._failures.popleft()
        self._failures.append(now)
        if len(self._failures) >= self.max_failures and self._blocked_until is None:
            self._blocked_until = now + self.window
            return True
        return False

"""push_subscriptions 표 (SP3-4 스펙 5.3). 이 티켓은 읽기만 한다(쓰기는 티켓 08, 즉시 갈래).

구독 `endpoint`는 비밀값처럼 다룬다: 돌려주지도, 로그에 남기지도 않는다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from my_planner.clock import from_iso


class PushRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def count_active(self) -> int:
        """`disabled_at IS NULL`인 구독 수."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM push_subscriptions WHERE disabled_at IS NULL"
        ).fetchone()[0]

    def last_success_at(self) -> datetime | None:
        """가장 늦은 `last_success_at`(꺼진 구독 포함)."""
        v = self.conn.execute("SELECT MAX(last_success_at) FROM push_subscriptions").fetchone()[0]
        return from_iso(v) if v else None

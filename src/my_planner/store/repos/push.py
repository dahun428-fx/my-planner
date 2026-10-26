"""push_subscriptions 표 (SP3-4 스펙 5.3, 7.3 D4).

구독 `endpoint`는 비밀값처럼 다룬다: 로그, 활동 기록, 오류 응답에 넣지 않는다. 이 저장소의 쓰기는
추가·삭제가 즉시 갈래(`apply_action`), 성공·실패 기록이 `harness/delivery.py`다(4.3).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.store.db import transaction

MAX_CONSECUTIVE_FAILURES = 5  # 연속 5번 안 된 구독은 끈다(7.3 D4)


@dataclass(frozen=True)
class PushSubscription:
    id: int
    endpoint: str = field(repr=False)  # repr에도 넣지 않는다(예외·디버그 출력으로 새지 않게)
    p256dh: str = field(repr=False)
    auth: str = field(repr=False)
    label: str | None
    created_at: datetime
    last_success_at: datetime | None
    failure_count: int
    disabled_at: datetime | None


def _row(r: sqlite3.Row) -> PushSubscription:
    return PushSubscription(
        id=r["id"],
        endpoint=r["endpoint"],
        p256dh=r["p256dh"],
        auth=r["auth"],
        label=r["label"],
        created_at=from_iso(r["created_at"]),
        last_success_at=from_iso(r["last_success_at"]) if r["last_success_at"] else None,
        failure_count=r["failure_count"],
        disabled_at=from_iso(r["disabled_at"]) if r["disabled_at"] else None,
    )


class PushRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None) -> None:
        self.conn = conn
        self.clock = clock  # `upsert`의 `created_at`(읽기만 하면 없어도 된다)

    def count_active(self) -> int:
        """`disabled_at IS NULL`인 구독 수."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM push_subscriptions WHERE disabled_at IS NULL"
        ).fetchone()[0]

    def last_success_at(self) -> datetime | None:
        """가장 늦은 `last_success_at`(꺼진 구독 포함)."""
        v = self.conn.execute("SELECT MAX(last_success_at) FROM push_subscriptions").fetchone()[0]
        return from_iso(v) if v else None

    def get(self, id: int) -> PushSubscription | None:
        r = self.conn.execute("SELECT * FROM push_subscriptions WHERE id = ?", (id,)).fetchone()
        return _row(r) if r is not None else None

    def active(self) -> list[PushSubscription]:
        """켜진 구독, id 순."""
        rows = self.conn.execute(
            "SELECT * FROM push_subscriptions WHERE disabled_at IS NULL ORDER BY id"
        ).fetchall()
        return [_row(r) for r in rows]

    def upsert(
        self, endpoint: str, p256dh: str, auth: str, label: str | None, *, at: datetime | None = None,
        device_id: int | None = None,
    ) -> int:
        """같은 `endpoint`면 키와 이름을 갱신하고 다시 켠다(실패 수 0). 같은 id를 돌려준다(6.4.8).

        `device_id`는 마지막으로 구독한 쪽으로 덮는다(기기 연결 스펙 4.6). API 토큰으로 구독하면 NULL."""
        if at is None:
            assert self.clock is not None, "upsert에는 시각이나 시계가 있어야 한다"
            at = self.clock.now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO push_subscriptions (endpoint, p256dh, auth, label, created_at, device_id) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth, "
                "label = excluded.label, failure_count = 0, disabled_at = NULL, device_id = excluded.device_id",
                (endpoint, p256dh, auth, label, to_iso(at), device_id),
            )
            r = self.conn.execute("SELECT id FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()
        return int(r["id"])

    def delete(self, id: int) -> bool:
        """행을 지운다. 없으면 False."""
        with transaction(self.conn):
            cur = self.conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (id,))
        return cur.rowcount > 0

    def record_ok(self, id: int, at: datetime) -> None:
        """받았다: 마지막 성공 시각, 연속 실패 0."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE push_subscriptions SET last_success_at = ?, failure_count = 0 WHERE id = ?",
                (to_iso(at), id),
            )

    def apply_result(self, id: int, result: str, at: datetime, *, count_failure: bool = True) -> bool:
        """전송 결과 하나(`ok` | `gone` | `failed`)를 적는 단 하나의 길. 이번에 껐으면 True.

        `count_failure=False`(시험 푸시): `failed`는 연속 실패 수를 올리지 않는다. `ok`, `gone`(404/410)은 그대로 적는다.
        """
        if result == "ok":
            self.record_ok(id, at)
            return False
        if result == "gone" or count_failure:
            return self.record_failure(id, gone=result == "gone", at=at)
        return False

    def record_failure(self, id: int, *, gone: bool, at: datetime) -> bool:
        """못 받았다: 연속 실패 +1. `gone`(404/410)이거나 연속 5번이면 끈다. 이번에 껐으면 True."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE push_subscriptions SET failure_count = failure_count + 1 WHERE id = ?", (id,)
            )
            cur = self.conn.execute(
                "UPDATE push_subscriptions SET disabled_at = ? WHERE id = ? AND disabled_at IS NULL "
                "AND (? OR failure_count >= ?)",
                (to_iso(at), id, 1 if gone else 0, MAX_CONSECUTIVE_FAILURES),
            )
        return cur.rowcount > 0

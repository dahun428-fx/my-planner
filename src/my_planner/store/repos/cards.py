"""app_cards 표 (SP3-4 스펙 5.3): 운영 앱의 고정 카드. 할 일은 props의 id로만 가리킨다.

고정한 카드는 `unpinned_at IS NULL`이고 `sort_order` 순이다(`GET /today`의 `cards`, 6.3.2). 순서는 1부터 센다.
고정을 풀면 행을 지우지 않고 `unpinned_at`을 적는다(되돌리기가 그 행을 되살린다, 6.4.3).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from my_planner.clock import Clock, from_iso, to_iso
from my_planner.store.db import transaction


@dataclass
class Card:
    id: int
    component: str
    props: dict[str, Any]
    sort_order: int
    pinned_at: datetime
    unpinned_at: datetime | None
    conversation_id: int | None


def _card(r: sqlite3.Row) -> Card:
    return Card(
        id=r["id"],
        component=r["component"],
        props=json.loads(r["props_json"]),
        sort_order=r["sort_order"],
        pinned_at=from_iso(r["pinned_at"]),
        unpinned_at=from_iso(r["unpinned_at"]) if r["unpinned_at"] else None,
        conversation_id=r["conversation_id"],
    )


class CardsRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    def get(self, card_id: int) -> Card | None:
        r = self.conn.execute("SELECT * FROM app_cards WHERE id = ?", (card_id,)).fetchone()
        return _card(r) if r is not None else None

    def active(self) -> list[Card]:
        """고정한 카드, `sort_order` 순(같으면 먼저 만든 것)."""
        rows = self.conn.execute(
            "SELECT * FROM app_cards WHERE unpinned_at IS NULL ORDER BY sort_order, id"
        ).fetchall()
        return [_card(r) for r in rows]

    def order(self) -> list[int]:
        return [c.id for c in self.active()]

    def pin(self, component: str, props: dict[str, Any], *, conversation_id: int | None = None) -> Card:
        """맨 뒤에 고정한다. props는 부르는 쪽이 카탈로그 스키마로 검증한 값이다."""
        with transaction(self.conn):
            top = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM app_cards WHERE unpinned_at IS NULL"
            ).fetchone()[0]
            cur = self.conn.execute(
                "INSERT INTO app_cards (component, props_json, sort_order, pinned_at, unpinned_at, conversation_id) "
                "VALUES (?, ?, ?, ?, NULL, ?)",
                (component, json.dumps(props, ensure_ascii=False), top + 1, to_iso(self.clock.now()),
                 conversation_id),
            )
        got = self.get(int(cur.lastrowid or 0))
        assert got is not None
        return got

    def unpin(self, card_id: int) -> Card | None:
        """고정을 푼다. 없거나 이미 풀린 카드는 None(아무것도 바꾸지 않는다)."""
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE app_cards SET unpinned_at = ? WHERE id = ? AND unpinned_at IS NULL",
                (to_iso(self.clock.now()), card_id),
            )
        return self.get(card_id) if cur.rowcount else None

    def reorder(self, ids: list[int]) -> list[Card]:
        """새 순서. `ids`가 고정한 카드 전부(겹침 없이)가 아니면 `ValueError`."""
        if len(set(ids)) != len(ids) or set(ids) != set(self.order()):
            raise ValueError("reorder needs every pinned card exactly once")
        self.restore_order(ids)
        return self.active()

    def restore(self, card: Card) -> None:
        """되돌리기: 그 행을 `card` 그대로 둔다(고정 여부, 순서 포함)."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE app_cards SET component = ?, props_json = ?, sort_order = ?, pinned_at = ?, "
                "unpinned_at = ?, conversation_id = ? WHERE id = ?",
                (card.component, json.dumps(card.props, ensure_ascii=False), card.sort_order,
                 to_iso(card.pinned_at), to_iso(card.unpinned_at) if card.unpinned_at else None,
                 card.conversation_id, card.id),
            )

    def restore_order(self, order: list[int]) -> None:
        """`order`의 카드에 1부터 순서를 다시 매긴다(검사하지 않는다. 되돌리기와 `reorder`가 쓴다)."""
        with transaction(self.conn):
            for n, card_id in enumerate(order, start=1):
                self.conn.execute("UPDATE app_cards SET sort_order = ? WHERE id = ?", (n, card_id))

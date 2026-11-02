"""패널 제안 근거 검사 (SP15 스펙 7.2). 두뇌가 낸 근거를 서버가 모양·존재로 확인한다.

근거는 `{"type", "ref", "note"}`. `ref` 모양은 SP14 관찰 참조(`tools.agents._REF`)와 같고, 종류는 접두어로 정한다.
존재 확인은 표마다 "보이는 행"만 친다(지운 것·숨긴 것·초안은 없다). 이 모듈은 로그를 남기지 않는다.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from my_planner.standing.bench import load_bench
from my_planner.tools.moments import _bad_char
from my_planner.tools.ui import banned_words

EvidenceType = Literal["record", "statement", "external"]

EVIDENCE_MAX = 8
EVIDENCE_NOTE_MAX = 120  # 코드포인트
# 카드 글의 덧붙인 금지어(ADR 0006: 비율, 하지 않은 것 탓하기, 비교로 깎기). 정본은 여기, `tools/panel.py`가 가져다 쓴다
PANEL_EXTRA_BANNED = ("%", "못 했", "못했", "뒤처졌")

RECORD_PREFIXES = ("task", "event", "habit", "checkin", "body_day", "workout", "measure", "moment", "suggestion")
STATEMENT_PREFIXES = ("statement", "memo", "review", "decision")
EXTERNAL_PREFIXES = ("bench",)

MSG_SIZE = f"근거는 1~{EVIDENCE_MAX}개예요."
MSG_NOTE = f"근거 note는 {EVIDENCE_NOTE_MAX}자 안의 한 줄이에요."
MSG_TYPE = "근거 종류와 참조가 맞지 않아요: {ref}"
MSG_BANNED = "근거에 쓰지 않는 말이 있어요: {word}"

_REF = re.compile(r"^[a-z_]+:[0-9A-Za-z_:-]+$")  # SP14 `tools.agents._REF`와 같은 모양
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REVIEW = re.compile(r"^(\d{4}-Q[1-4]):([a-z_]+)$")
_BENCH_META = frozenset({"version", "effective_from"})

_TYPES: dict[str, EvidenceType] = {
    **dict.fromkeys(RECORD_PREFIXES, "record"),
    **dict.fromkeys(STATEMENT_PREFIXES, "statement"),
    **dict.fromkeys(EXTERNAL_PREFIXES, "external"),
}
# id 하나로 찾는 참조: 접두어 → (표, 보이는 행 조건)
_BY_ID: dict[str, tuple[str, str]] = {
    "task": ("tasks", "deleted_at IS NULL AND status <> 'draft'"),
    "event": ("events", "deleted_at IS NULL"),
    "habit": ("habits", "deleted_at IS NULL"),
    "workout": ("workout_logs", "deleted_at IS NULL"),
    "measure": ("standing_measures", "deleted_at IS NULL"),
    "moment": ("status_moments", "hidden_at IS NULL"),
    "suggestion": ("panel_suggestions", "1 = 1"),
    "statement": ("owner_statements", "retired_at IS NULL"),
    "memo": ("memos", "deleted_at IS NULL"),
    "note": ("agent_notes", "1 = 1"),
}
_BY_DATE: dict[str, str] = {"checkin": "conditions", "body_day": "body_days"}
# 카드 링크(스펙 7.4). `event`·`memo`는 행 값을 넣는다
_HREF: dict[str, str | None] = {
    "task": "/todos/", "habit": "/habits/", "checkin": "/activity/", "body_day": "/workout/", "workout": "/workout/",
    "measure": "/status/standing/", "moment": "/status/", "review": "/status/", "statement": "/more/#statements",
    "decision": "/more/#statements", "suggestion": None, "bench": None,
}


@dataclass(frozen=True)
class EvidenceItem:
    type: EvidenceType
    ref: str
    note: str


def _split(ref: str) -> tuple[str, str] | None:
    if not isinstance(ref, str) or not _REF.match(ref):
        return None
    prefix, _, rest = ref.partition(":")
    return prefix, rest


def ref_type(ref: str) -> EvidenceType | None:
    """접두어로 정한 근거 종류. 모양이 틀렸거나 모르는 접두어(`note` 포함)면 `None`."""
    parts = _split(ref)
    return _TYPES.get(parts[0]) if parts is not None else None


def _one(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...]) -> bool:
    return conn.execute(sql, args).fetchone() is not None


def _row_exists(conn: sqlite3.Connection, prefix: str, rest: str) -> bool:
    """DB 행으로 찾는 참조(`bench` 밖 전부)."""
    if prefix in _BY_ID:
        if not rest.isdigit():
            return False
        table, visible = _BY_ID[prefix]
        return _one(conn, f"SELECT 1 FROM {table} WHERE id = ? AND {visible}", (int(rest),))
    if prefix in _BY_DATE:
        return bool(_DATE.match(rest)) and _one(conn, f"SELECT 1 FROM {_BY_DATE[prefix]} WHERE date = ?", (rest,))
    if prefix == "review":
        m = _REVIEW.match(rest)
        return m is not None and _one(
            conn, "SELECT 1 FROM curve_area_scores WHERE period = ? AND area = ?", (m.group(1), m.group(2))
        )
    if prefix == "decision":
        return _one(
            conn, "SELECT 1 FROM owner_statements WHERE kind = 'decision' AND key = ? AND retired_at IS NULL", (rest,)
        )
    return False


def ref_exists(conn: sqlite3.Connection, ref: str, *, today: date) -> bool:
    """그 참조가 가리키는 보이는 행이 있는가(`note:<id>`는 관찰 참조에서만 쓴다). 모르는 접두어는 `False`.

    `bench:<키>`는 `today`에 맞는 기준표의 맨 위 표 키(`version`·`effective_from` 아님, 점 든 하위 경로 없음).
    """
    parts = _split(ref)
    if parts is None:
        return False
    prefix, rest = parts
    if prefix == "bench":
        raw = load_bench(today).raw
        return rest not in _BENCH_META and isinstance(raw.get(rest), Mapping)
    return _row_exists(conn, prefix, rest)


def _check_item(raw: Any) -> EvidenceItem | str:
    if not isinstance(raw, dict):
        return MSG_NOTE
    type_, ref, note = raw.get("type"), raw.get("ref"), raw.get("note")
    if not (isinstance(type_, str) and isinstance(ref, str) and isinstance(note, str)):
        return MSG_NOTE
    note = note.strip()
    if not 1 <= len(note) <= EVIDENCE_NOTE_MAX or _bad_char(note):
        return MSG_NOTE
    if ref_type(ref) is None or ref_type(ref) != type_:
        return MSG_TYPE.format(ref=ref)
    for word in (*banned_words(), *PANEL_EXTRA_BANNED):
        if word in note:
            return MSG_BANNED.format(word=word)
    return EvidenceItem(type=type_, ref=ref, note=note)  # type: ignore[arg-type]


def parse_evidence(raw: Any) -> list[EvidenceItem] | str:
    """모양 검사(존재는 `check_evidence`). 같은 `ref`는 처음 것 하나만 남긴다. 오류 문구에는 note 글을 넣지 않는다."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= EVIDENCE_MAX:
        return MSG_SIZE
    items: dict[str, EvidenceItem] = {}
    for one in raw:
        checked = _check_item(one)
        if isinstance(checked, str):
            return checked
        items.setdefault(checked.ref, checked)
    return list(items.values())


def check_evidence(
    conn: sqlite3.Connection, items: list[EvidenceItem], *, today: date
) -> Literal["ok", "unknown_ref", "no_personal_evidence"]:
    """없는 참조가 하나라도 있으면 `unknown_ref`(먼저). 아니면 내 기록·내 말이 하나도 없을 때 `no_personal_evidence`."""
    if not all(ref_exists(conn, it.ref, today=today) for it in items):
        return "unknown_ref"
    if not any(it.type in ("record", "statement") for it in items):
        return "no_personal_evidence"
    return "ok"


def evidence_href(conn: sqlite3.Connection, ref: str) -> str | None:
    """카드에서 근거로 가는 앱 경로. 없는 참조·링크 없는 종류(`suggestion`·`bench`)는 `None`."""
    parts = _split(ref)
    if parts is None or ref_type(ref) is None:
        return None
    prefix, rest = parts
    if prefix == "event":
        if not rest.isdigit():
            return None
        row = conn.execute(
            "SELECT start_date FROM events WHERE id = ? AND deleted_at IS NULL", (int(rest),)
        ).fetchone()
        return f"/schedule/?date={row[0]}" if row is not None else None
    if _HREF.get(prefix, "") is None or not _row_exists(conn, prefix, rest):
        return None
    if prefix == "memo":
        return f"/memos/view/?id={int(rest)}"
    return _HREF[prefix]

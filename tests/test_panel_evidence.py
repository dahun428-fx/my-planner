"""SP15-04: 패널 근거 검사 `panel/evidence.py` (스펙 7.2). 값은 모두 지어낸 것이다."""

from __future__ import annotations

from datetime import date

import pytest

from my_planner.panel.evidence import (
    EvidenceItem,
    check_evidence,
    evidence_href,
    parse_evidence,
    ref_exists,
    ref_type,
)
from my_planner.store.db import transaction

TODAY = date(2026, 11, 1)
AT = "2026-11-01T00:00:00+00:00"


def _seed(conn) -> dict[str, int]:
    """할 일 1(열림)·초안 할 일·메모·측정값·지운 측정값·지운 말·활성 말·일정·습관·운동·순간 둘·제안·관찰."""
    ids: dict[str, int] = {}
    with transaction(conn):
        ids["task"] = conn.execute(
            "INSERT INTO tasks (title, status, created_at, updated_at) VALUES ('가짜 할 일', 'open', ?, ?)", (AT, AT)
        ).lastrowid
        ids["draft"] = conn.execute(
            "INSERT INTO tasks (title, status, created_at, updated_at) VALUES ('가짜 초안', 'draft', ?, ?)", (AT, AT)
        ).lastrowid
        ids["memo"] = conn.execute(
            "INSERT INTO memos (body, origin, created_at, updated_at) VALUES ('가짜 메모', 'user', ?, ?)", (AT, AT)
        ).lastrowid
        ids["measure"] = conn.execute(
            "INSERT INTO standing_measures (metric, value_num, measured_on, source_kind, created_at) "
            "VALUES ('body_fat_pct', 21.5, '2026-10-01', 'manual', ?)", (AT,)
        ).lastrowid
        ids["measure_gone"] = conn.execute(
            "INSERT INTO standing_measures (metric, value_num, measured_on, source_kind, created_at, deleted_at) "
            "VALUES ('salary_krw', 1234, '2026-10-01', 'manual', ?, ?)", (AT, AT)
        ).lastrowid
        ids["statement_gone"] = conn.execute(
            "INSERT INTO owner_statements (kind, area, text, created_at, retired_at) "
            "VALUES ('fact', 'health', '가짜 지운 말', ?, ?)", (AT, AT)
        ).lastrowid
        ids["statement"] = conn.execute(
            "INSERT INTO owner_statements (kind, area, text, created_at) VALUES ('preference', 'health', '가짜 말', ?)",
            (AT,),
        ).lastrowid
        ids["decision_gone"] = conn.execute(
            "INSERT INTO owner_statements (kind, area, key, text, created_at, retired_at) "
            "VALUES ('decision', 'finance', 'old_choice', '가짜 결정', ?, ?)", (AT, AT)
        ).lastrowid
        ids["event"] = conn.execute(
            "INSERT INTO events (title, start_date, start_time, origin, created_at, updated_at) "
            "VALUES ('가짜 일정', '2026-11-03', '10:00', 'user', ?, ?)", (AT, AT)
        ).lastrowid
        ids["habit"] = conn.execute(
            "INSERT INTO habits (title, area, kind, sort_order, created_at, updated_at) "
            "VALUES ('가짜 습관', 'health', 'daily', 1, ?, ?)", (AT, AT)
        ).lastrowid
        ids["workout"] = conn.execute(
            "INSERT INTO workout_logs (date, title, created_at, updated_at) VALUES ('2026-10-31', '가짜 운동', ?, ?)",
            (AT, AT),
        ).lastrowid
        ids["moment"] = conn.execute(
            "INSERT INTO status_moments (date, slot, text, created_at) VALUES ('2026-10-31', 1, '가짜 순간', ?)", (AT,)
        ).lastrowid
        ids["moment_hidden"] = conn.execute(
            "INSERT INTO status_moments (date, slot, text, created_at, hidden_at) "
            "VALUES ('2026-10-31', 2, '가짜 숨긴 순간', ?, ?)", (AT, AT)
        ).lastrowid
        ids["suggestion"] = conn.execute(
            "INSERT INTO panel_suggestions (kind, title, area, size_min, experts, evidence_json, week, state, "
            "created_at) VALUES ('task', '가짜 제안', 'career', 30, 'career', '[]', '2026-W44', 'proposed', ?)", (AT,)
        ).lastrowid
        ids["note"] = conn.execute(
            "INSERT INTO agent_notes (agent, day, text, priority, refs_json, created_at) "
            "VALUES ('mate', '2026-10-31', '가짜 관찰', 2, '[]', ?)", (AT,)
        ).lastrowid
        conn.execute("INSERT INTO conditions (date, score, recorded_at) VALUES ('2026-10-30', 3, ?)", (AT,))
        conn.execute("INSERT INTO body_days (date, steps, updated_at) VALUES ('2026-10-29', 7000, ?)", (AT,))
        conn.execute(
            "INSERT INTO curve_area_scores (period, area, score, recorded_at) VALUES ('2026-Q3', 'career', 6, ?)", (AT,)
        )
    return ids


def _items(*pairs: tuple[str, str]) -> list[EvidenceItem]:
    return [EvidenceItem(type=t, ref=r, note="가짜 근거") for t, r in pairs]  # type: ignore[arg-type]


@pytest.mark.parametrize(("pairs", "expected"), [
    ([("external", "bench:income")], "no_personal_evidence"),
    ([("record", "task:999")], "unknown_ref"),
    ([("record", "task:{task}"), ("record", "task:999")], "unknown_ref"),
    ([("statement", "statement:{statement_gone}")], "unknown_ref"),
    ([("statement", "decision:career_first")], "ok"),
    ([("record", "task:{task}"), ("external", "bench:income")], "ok"),
    ([("statement", "memo:{memo}")], "ok"),
    ([("external", "bench:nope")], "unknown_ref"),
])
def test_check_evidence_cases(conn, pairs, expected):
    ids = _seed(conn)
    items = _items(*((t, r.format(**ids)) for t, r in pairs))
    assert check_evidence(conn, items, today=TODAY) == expected


def test_ref_exists_table(conn):
    ids = _seed(conn)
    yes = [
        f"task:{ids['task']}", f"event:{ids['event']}", f"habit:{ids['habit']}", "checkin:2026-10-30",
        "body_day:2026-10-29", f"workout:{ids['workout']}", f"measure:{ids['measure']}", f"moment:{ids['moment']}",
        f"suggestion:{ids['suggestion']}", f"statement:{ids['statement']}", f"memo:{ids['memo']}",
        "review:2026-Q3:career", "decision:career_first", "bench:income", "bench:health", f"note:{ids['note']}",
    ]
    no = [
        "task:999", f"task:{ids['draft']}", "event:999", "habit:999", "checkin:2026-10-31", "body_day:2026-10-30",
        "workout:999", "measure:999", f"measure:{ids['measure_gone']}", "moment:999", f"moment:{ids['moment_hidden']}",
        "suggestion:999", "statement:999", f"statement:{ids['statement_gone']}", "memo:999", "review:2026-Q2:career",
        "review:2026-Q3:health", "decision:nope", "decision:old_choice", "bench:nope", "bench:version",
        "bench:effective_from", "bench:income.estimate", "note:999", "task:abc", "foo:1", "장보기",
    ]
    for ref in yes:
        assert ref_exists(conn, ref, today=TODAY), ref
    for ref in no:
        assert not ref_exists(conn, ref, today=TODAY), ref
    assert ref_type("task:1") == "record" and ref_type("decision:x") == "statement"
    assert ref_type("bench:income") == "external" and ref_type("note:1") is None and ref_type("foo:1") is None


SIZE = "근거는 1~8개예요."
NOTE = "근거 note는 120자 안의 한 줄이에요."


def _ev(ref: str = "task:1", type_: str = "record", note: object = "가짜 근거") -> dict[str, object]:
    return {"type": type_, "ref": ref, "note": note}


@pytest.mark.parametrize(("raw", "expected"), [
    ([], SIZE),
    ("task:1", SIZE),
    ([_ev(f"task:{i}") for i in range(1, 10)], SIZE),
    ([_ev(note="가" * 121)], NOTE),
    ([_ev(note="첫 줄\n둘째 줄")], NOTE),
    ([_ev(note="   ")], NOTE),
    ([_ev(note=3)], NOTE),
    ([{"type": "record", "ref": 1, "note": "가짜"}], NOTE),
    (["task:1"], NOTE),
    ([_ev("memo:1", "record")], "근거 종류와 참조가 맞지 않아요: memo:1"),
    ([_ev("장보기", "record")], "근거 종류와 참조가 맞지 않아요: 장보기"),
    ([_ev(note="걸음이 50% 줄었어요")], "근거에 쓰지 않는 말이 있어요: %"),
    ([_ev(note="어제 못 했어요")], "근거에 쓰지 않는 말이 있어요: 못 했"),
], ids=range(13))
def test_parse_evidence_shape(raw, expected):
    assert parse_evidence(raw) == expected


def test_parse_evidence_dedupes_ref():
    out = parse_evidence([_ev(note="  앞 근거  "), _ev(note="뒤 근거"), _ev("bench:income", "external")])
    assert out == [EvidenceItem("record", "task:1", "앞 근거"), EvidenceItem("external", "bench:income", "가짜 근거")]
    assert len(parse_evidence([_ev(f"task:{i}") for i in range(1, 9)])) == 8  # type: ignore[arg-type]


def test_evidence_href(conn):
    ids = _seed(conn)
    assert evidence_href(conn, f"event:{ids['event']}") == "/schedule/?date=2026-11-03"
    assert evidence_href(conn, f"memo:{ids['memo']}") == f"/memos/view/?id={ids['memo']}"
    assert evidence_href(conn, "bench:income") is None
    assert evidence_href(conn, "task:9") is None
    assert evidence_href(conn, f"task:{ids['task']}") == "/todos/"
    assert evidence_href(conn, f"habit:{ids['habit']}") == "/habits/"
    assert evidence_href(conn, "checkin:2026-10-30") == "/activity/"
    assert evidence_href(conn, "body_day:2026-10-29") == "/workout/"
    assert evidence_href(conn, f"workout:{ids['workout']}") == "/workout/"
    assert evidence_href(conn, f"measure:{ids['measure']}") == "/status/standing/"
    assert evidence_href(conn, f"moment:{ids['moment']}") == "/status/"
    assert evidence_href(conn, "review:2026-Q3:career") == "/status/"
    assert evidence_href(conn, f"statement:{ids['statement']}") == "/more/#statements"
    assert evidence_href(conn, "decision:career_first") == "/more/#statements"
    assert evidence_href(conn, f"suggestion:{ids['suggestion']}") is None
    assert evidence_href(conn, f"note:{ids['note']}") is None

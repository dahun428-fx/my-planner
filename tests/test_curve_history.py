"""인생 히스토리 읽기 모델 `curve_history` (SP8 스펙 8.2). 고정 자료는 SQL, 내용은 모두 꾸며 낸 것이다."""

import json
from datetime import UTC, date, datetime

from curve_sql import chapter, ladder, milestone

from my_planner.api.models import CurveHistory
from my_planner.clock import FakeClock
from my_planner.curve.history import curve_history
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.curve import CurveRepo

TODAY = date(2026, 10, 25)
EMPTY_HIDDEN = {"count": 0, "years": []}


def _history(conn, *, include_sensitive=False):
    clock = FakeClock(datetime(2026, 10, 25, 3, 0, tzinfo=UTC))
    body = curve_history(CurveRepo(conn, clock), ConditionsRepo(conn, clock), today=TODAY,
                         include_sensitive=include_sensitive)
    CurveHistory.model_validate(body)  # 응답 모델과 같은 모양
    return body


def _condition(conn, d):
    conn.execute("INSERT INTO conditions (date, score, note, recorded_at) VALUES (?, 3, NULL, ?)",
                 (d, "2026-10-01T00:00:00.000000+00:00"))


def test_chapters_recent_first_events_inside_recent_first(conn):
    old = chapter(conn, "꾸민 옛 시절", "2010-03", "2014-02")
    now = chapter(conn, "꾸민 지금", "2020-01")
    mid = chapter(conn, "꾸민 중간", "2014-03", "2019-12")
    milestone(conn, "꾸민 첫 일", "2021", chapter_id=now)
    milestone(conn, "꾸민 둘째 일", "2023-05-02", kind="low", chapter_id=now)
    milestone(conn, "꾸민 셋째 일", "2022-07", kind="turning_point", chapter_id=now)
    milestone(conn, "꾸민 옛 일", "2012", chapter_id=old)
    conn.commit()
    body = _history(conn)
    assert [c["id"] for c in body["chapters"]] == [now, mid, old]
    assert [e["title"] for e in body["chapters"][0]["events"]] == ["꾸민 둘째 일", "꾸민 셋째 일", "꾸민 첫 일"]
    assert body["chapters"][1]["events"] == [] and body["chapters"][1]["hidden_sensitive"] == EMPTY_HIDDEN
    first = body["chapters"][0]
    assert set(first) == {"id", "title", "theme", "start", "end", "sketch", "certainty", "ladder", "events",
                          "hidden_sensitive"}
    assert set(first["events"][0]) == {"id", "date", "precision", "kind", "kind_certainty", "title", "note", "area",
                                       "origin", "certainty", "sensitive"}


def test_unassigned_group(conn):
    ch = chapter(conn, "꾸민 챕터", "2020-01")
    draft_ch = chapter(conn, "꾸민 초안 챕터", "2015-01", status="draft")
    milestone(conn, "꾸민 안의 일", "2021", chapter_id=ch)
    milestone(conn, "꾸민 바깥 일", "2018")
    milestone(conn, "꾸민 초안 챕터의 일", "2016", chapter_id=draft_ch)  # 확정 챕터가 아니면 시기 없음
    milestone(conn, "꾸민 민감 바깥 일", "2017", sensitive=1)
    conn.commit()
    body = _history(conn)
    assert [e["title"] for e in body["unassigned"]["events"]] == ["꾸민 바깥 일", "꾸민 초안 챕터의 일"]
    assert body["unassigned"]["hidden_sensitive"] == {"count": 1, "years": [2017]}
    assert [c["title"] for c in body["chapters"]] == ["꾸민 챕터"]


def test_ladder_source_remembered_then_recorded_avg_then_null(conn):
    remembered = chapter(conn, "꾸민 기억", "2026-01", ladder_remembered=6)
    recorded = chapter(conn, "꾸민 기록", "2025-01", "2025-12")
    empty = chapter(conn, "꾸민 빈 시기", "2010-01", "2012-12")
    for period, now in (("2025-02", 6), ("2025-03", 7), ("2025-04", 6), ("2025-05", 6)):
        ladder(conn, period, now=now)
    ladder(conn, "2025-06", future=9)  # 5년 뒤만 있는 달은 평균에 넣지 않는다
    ladder(conn, "2026-03", now=1)  # 기억한 값이 있으면 기록보다 앞선다
    ladder(conn, "2024-12", now=10)  # 기간 밖
    conn.commit()
    by_id = {c["id"]: c["ladder"] for c in _history(conn)["chapters"]}
    assert by_id[remembered] == {"value": 6, "source": "remembered"}
    assert by_id[recorded] == {"value": 6.3, "source": "recorded"}  # 6.25 → 6.3 (반올림 0.5 올림)
    assert by_id[empty] is None


def test_ladder_recorded_open_chapter_runs_to_today(conn):
    ch = chapter(conn, "꾸민 지금", "2026-09")
    ladder(conn, "2026-10", now=5)
    ladder(conn, "2026-11", now=9)  # 오늘 달 뒤
    conn.commit()
    assert _history(conn)["chapters"][0]["ladder"] == {"value": 5, "source": "recorded"}
    assert _history(conn)["chapters"][0]["id"] == ch


def test_sensitive_hidden_count_years_and_title_absent_from_body(conn):
    ch = chapter(conn, "꾸민 챕터", "2015-01")
    milestone(conn, "꾸민 보이는 일", "2020", chapter_id=ch)
    milestone(conn, "꾸민 가린 제목 하나", "2021-04", kind="low", chapter_id=ch, sensitive=1, note="꾸민 가린 메모")
    milestone(conn, "꾸민 가린 제목 둘", "2018", chapter_id=ch, sensitive=1)
    milestone(conn, "꾸민 가린 제목 셋", "2021-09", kind="turning_point", chapter_id=ch, sensitive=1)
    conn.commit()
    body = _history(conn)
    text = json.dumps(body, ensure_ascii=False)
    for secret in ("꾸민 가린 제목", "꾸민 가린 메모"):
        assert secret not in text
    first = body["chapters"][0]
    assert [e["title"] for e in first["events"]] == ["꾸민 보이는 일"]
    assert first["hidden_sensitive"] == {"count": 3, "years": [2018, 2021]}
    # 옆 요약도 가린 사건을 세지 않는다
    assert body["summary"]["events"] == 1
    assert body["summary"]["turning_points"] == {"count": 0, "years": []}


def test_include_sensitive_true_marks_and_zero_hidden(conn):
    ch = chapter(conn, "꾸민 챕터", "2015-01")
    milestone(conn, "꾸민 보이는 일", "2020", chapter_id=ch)
    milestone(conn, "꾸민 민감 일", "2021-04", kind="turning_point", chapter_id=ch, sensitive=1, note="꾸민 메모")
    milestone(conn, "꾸민 민감 바깥 일", "2019", sensitive=1)
    conn.commit()
    body = _history(conn, include_sensitive=True)
    first = body["chapters"][0]
    assert [(e["title"], e["sensitive"]) for e in first["events"]] == [("꾸민 민감 일", True), ("꾸민 보이는 일", False)]
    assert first["events"][0]["note"] == "꾸민 메모"
    assert first["hidden_sensitive"] == EMPTY_HIDDEN and body["unassigned"]["hidden_sensitive"] == EMPTY_HIDDEN
    assert [e["title"] for e in body["unassigned"]["events"]] == ["꾸민 민감 바깥 일"]
    assert body["summary"]["events"] == 3
    assert body["summary"]["turning_points"] == {"count": 1, "years": [2021]}


def test_summary_values(conn):
    a = chapter(conn, "꾸민 긴 시절", "1994-03", "2013-02", ladder_remembered=6)  # 227달 → 18.9 → 19년
    b = chapter(conn, "꾸민 짧은 시절", "2013-03", "2016-08", ladder_remembered=4)
    c = chapter(conn, "꾸민 지금", "2019-01", ladder_remembered=6)  # 같은 6이면 최근 챕터. 2026-10까지 93달 → 8년
    milestone(conn, "꾸민 전환 하나", "2012", kind="turning_point", chapter_id=a)
    milestone(conn, "꾸민 전환 둘", "2019-03", kind="turning_point", chapter_id=c)
    milestone(conn, "꾸민 전환 셋", "2019-09", kind="turning_point", chapter_id=c)
    milestone(conn, "꾸민 전환 넷", "2023", kind="turning_point")
    milestone(conn, "꾸민 높은 때", "2015", chapter_id=b)
    milestone(conn, "꾸민 초안 전환", "2024", kind="turning_point", status="draft")
    ladder(conn, "2026-09", now=5)
    _condition(conn, "2026-08-02")
    conn.commit()
    body = _history(conn)
    assert body["since_year"] == 1994
    assert body["summary"] == {
        "chapters": 3, "events": 5,
        "highest": {"chapter_id": c, "title": "꾸민 지금", "ladder": 6},
        "turning_points": {"count": 4, "years": [2012, 2019, 2023]},
        "longest": {"chapter_id": a, "title": "꾸민 긴 시절", "years": 19},
        "records_since": 2026,
    }


def test_records_since_earliest_of_condition_or_ladder_and_since_year_from_event(conn):
    milestone(conn, "꾸민 이른 일", "1999")
    chapter(conn, "꾸민 챕터", "2005-01", "2005-06")  # 5달 → 0.4 → 0년
    ladder(conn, "2024-11", future=8)  # 5년 뒤만 있는 달은 기록의 시작이 아니다
    _condition(conn, "2026-02-01")
    conn.commit()
    body = _history(conn)
    assert body["since_year"] == 1999
    assert body["summary"]["records_since"] == 2026
    ladder(conn, "2025-03", now=5)
    conn.commit()
    assert _history(conn)["summary"]["records_since"] == 2025
    assert body["summary"]["longest"]["years"] == 0
    assert body["summary"]["highest"] is None


def test_empty_db_shape(conn):
    assert _history(conn) == {
        "since_year": None,
        "chapters": [],
        "unassigned": {"events": [], "hidden_sensitive": EMPTY_HIDDEN},
        "summary": {"chapters": 0, "events": 0, "highest": None, "turning_points": {"count": 0, "years": []},
                    "longest": None, "records_since": None},
    }


def test_drafts_excluded(conn):
    ch = chapter(conn, "꾸민 초안 챕터", "2020-01", status="draft", ladder_remembered=9)
    milestone(conn, "꾸민 초안 일", "2021", status="draft", chapter_id=ch)
    milestone(conn, "꾸민 초안 바깥 일", "2022", status="draft")
    conn.commit()
    body = _history(conn)
    assert body["chapters"] == [] and body["unassigned"]["events"] == []
    assert body["summary"]["chapters"] == 0 and body["summary"]["highest"] is None
    assert "꾸민 초안" not in json.dumps(body, ensure_ascii=False)

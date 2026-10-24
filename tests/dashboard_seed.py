"""대시보드 고정 자료 (SP3-4 티켓 16, 스펙 13장·16장). 내용은 모두 꾸며 낸 것이다.

`seed_dashboard_db(conn, clock)`이 SQL로 바로 넣는다(쓰기 도구를 거치지 않는다): 할 일·우선순위, 컨디션 30일 중
21일, 오늘 회차와 전달, 챕터·사건·사다리·영역 점수, 경험치 원장·칭호. 시각은 `clock.now()`를 기준으로 잡는다.
`tests/test_dashboard_fixtures.py`가 이 DB의 `GET` 응답을 `web/dashboard/src/test/fixtures/`와 비교한다.
티켓 17·18은 그 표에 행만 더한다.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, time, timedelta

from curve_sql import area_default, area_scores, chapter, ladder, milestone, title, xp

from my_planner.clock import Clock, logical_date, to_iso

# 꾸며 낸 할 일: (제목, 상태, 오늘부터 며칠 뒤, 영역)
TASKS = (
    ("수채화 밑그림 그리기", "open", 0, ("quality_of_life",)),
    ("동네 도서관 책 반납", "done", 0, ("learning",)),
    ("저녁 산책 30분", "open", 0, ("health",)),
    ("이력서 한 줄 고치기", "open", 1, ("career",)),
    ("이번 달 구독 정리", "open", 2, ("finance",)),
    ("친구에게 안부 문자", "open", None, ("relationships",)),
)
# 컨디션: 30일 가운데 21일만 기록(오늘에서 며칠 전, 점수). 빈 날은 그대로 빈 날이다.
CONDITION_GAPS = frozenset({2, 5, 9, 12, 16, 19, 23, 26, 29})
CONDITION_SCORES = (4, 3, 3, 4, 5, 2, 3, 4, 4, 3)


def _kst(day: datetime, h: int, mi: int = 0) -> datetime:
    """`day`(KST 자정 기준 UTC 시각)의 h:mi KST를 UTC로."""
    return day + timedelta(hours=h, minutes=mi)


def seed_dashboard_db(conn: sqlite3.Connection, clock: Clock) -> None:
    """`clock`은 SP1 기본 설정(Asia/Seoul, 04:00 경계)의 BE와 같은 시계다."""
    now = clock.now().astimezone(UTC)
    # The BE's logical date (Asia/Seoul, day starts at 04:00, SP1), so runs and usage line up with /health
    # even for a clock between 00:00 and 03:59.
    today = logical_date(now, "Asia/Seoul", time(4, 0))
    midnight = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(hours=9)  # 오늘 00:00 KST
    ts = to_iso(now)

    # --- 할 일·우선순위 ---
    ids: list[int] = []
    for name, status, days, areas in TASKS:
        planned = (today + timedelta(days=days)).isoformat() if days is not None else None
        done_at = to_iso(_kst(midnight, 11, 20)) if status == "done" else None
        cur = conn.execute(
            "INSERT INTO tasks (title, status, planned_for, created_at, updated_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, status, planned, ts, ts, done_at),
        )
        tid = int(cur.lastrowid or 0)
        ids.append(tid)
        conn.executemany("INSERT INTO task_areas (task_id, area) VALUES (?, ?)", [(tid, a) for a in areas])
    iso_year, iso_week, _ = today.isocalendar()
    conn.executemany(
        "INSERT INTO priorities (cadence, period, rank, task_id) VALUES (?, ?, ?, ?)",
        [
            ("day", today.isoformat(), 1, ids[0]),
            ("day", today.isoformat(), 2, ids[2]),
            ("week", f"{iso_year}-W{iso_week:02d}", 1, ids[3]),
            ("month", f"{today.year}-{today.month:02d}", 1, ids[4]),
        ],
    )

    # --- 컨디션: 30일 중 21일 ---
    for back in range(30):
        if back in CONDITION_GAPS:
            continue
        d = today - timedelta(days=back)
        conn.execute(
            "INSERT INTO conditions (date, score, note, recorded_at) VALUES (?, ?, NULL, ?)",
            (d.isoformat(), CONDITION_SCORES[back % len(CONDITION_SCORES)], ts),
        )

    # --- 오늘 회차와 전달: 아침 브리핑은 앱으로 보내고 답을 받음, 저녁 체크인은 예정 ---
    brief_at = _kst(midnight, 10)
    cur = conn.execute(
        "INSERT INTO runs (loop, cadence, scheduled_for, status, attempt, started_at, finished_at, outbound_text, "
        "created_at, answered_at, answered_via) VALUES ('morning_brief', 'day', ?, 'done', 1, ?, ?, ?, ?, ?, 'app')",
        (to_iso(brief_at), to_iso(brief_at), to_iso(brief_at + timedelta(seconds=40)), "꾸민 아침 브리핑",
         to_iso(brief_at), to_iso(brief_at + timedelta(minutes=12))),
    )
    brief_id = int(cur.lastrowid or 0)
    conn.execute(
        "INSERT INTO run_deliveries (run_id, channel, mode, status, push_ok, at) VALUES (?, 'app', 'full', 'sent', 1, ?)",
        (brief_id, to_iso(brief_at + timedelta(seconds=41))),
    )
    conn.execute(
        "INSERT INTO runs (loop, cadence, scheduled_for, status, created_at) VALUES ('evening_checkin', 'day', ?, "
        "'pending', ?)",
        (to_iso(_kst(midnight, 18)), ts),
    )

    # --- 상태와 하루 사용량 ---
    for key, value in (
        ("brain_auth_state", "ok"),
        ("brain_auth_checked_at", to_iso(brief_at + timedelta(seconds=41))),
        ("last_seen_at", to_iso(now.replace(second=0, microsecond=0))),
        ("notify_primary", "app"),
    ):
        conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (key, value))
    conn.execute(
        "INSERT OR REPLACE INTO usage_state (date, brain_calls, proactive_messages) VALUES (?, 23, 1)",
        (today.isoformat(),),
    )
    conn.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth, label, created_at, last_success_at) "
        "VALUES ('https://push.example/dashboard-fixture', 'k', 'a', '꾸민 폰', ?, ?)",
        (ts, to_iso(brief_at + timedelta(seconds=41))),
    )

    # --- 인생 곡선: 챕터·사건·사다리·영역 점수 ---
    ch = chapter(conn, "꾸민 새 출발", "2025-03", sketch="↗", certainty="estimate")
    chapter(conn, "꾸민 배움의 해", "2023-01", "2025-02")
    m1 = milestone(conn, "꾸민 첫 전시", "2025-09", kind="high", chapter_id=ch)
    milestone(conn, "꾸민 이사", "2026-02-14", kind="turning_point", chapter_id=ch)
    milestone(conn, "꾸민 긴 감기", "2026-06", kind="low")
    for period, n, f in (("2026-08", 5, 7), ("2026-09", 6, 7), ("2026-10", 6, 8)):
        ladder(conn, period, now=n, future=f)
    area_scores(conn, "2026-Q3", career=6, finance=5, health=6, relationships=7, learning=7, quality_of_life=6)
    area_default(conn, "health", "꾸민 회복 퀘스트: 20분 걷기")

    # --- 상태창: 경험치 원장·칭호 ---
    xp(conn, f"task:{ids[1]}", 10, to_iso(_kst(midnight, 11, 20)))
    xp(conn, f"run:{brief_id}", 5, to_iso(brief_at + timedelta(minutes=12)), label="회차 답", kind="checkin_reply")
    yday = midnight - timedelta(days=1)
    xp(conn, f"date:{(today - timedelta(days=1)).isoformat()}", 3, to_iso(_kst(yday, 21)), label="컨디션 기록",
       kind="condition")
    title(conn, m1)

    conn.commit()

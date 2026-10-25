"""대시보드 고정 자료 (SP3-4 티켓 16, 스펙 13장·16장). 내용은 모두 꾸며 낸 것이다.

`seed_dashboard_db(conn, clock)`이 SQL로 바로 넣는다(쓰기 도구를 거치지 않는다): 할 일·우선순위·일정·전에 잡은 일,
분기 메인 퀘스트와 첫 걸음, 컨디션 30일 중 21일(과 그 앞 두 달), 오늘 회차와 전달, 챕터·사건·사다리·영역 점수(지난 분기와 이번 분기),
경험치 원장(합계 1380 = 레벨 6, 130 / 400)·칭호, 지난 4주의 끝낸 할 일과 건강 습관 체크(SP8 스탯 보너스).
시각은 `clock.now()`를 기준으로 잡는다.
`tests/test_dashboard_fixtures.py`가 이 DB의 `GET` 응답을 `web/dashboard/src/test/fixtures/`와 비교한다.
티켓 17·18은 그 표에 행만 더한다.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, time, timedelta

from curve_sql import (
    area_default,
    area_scores,
    chapter,
    ladder,
    milestone,
    recovery,
    title,
    xp,
)

from my_planner.clock import Clock, logical_date, to_iso

# 꾸며 낸 할 일: (제목, 상태, 오늘부터 며칠 뒤, 영역)
TASKS = (
    ("수채화 밑그림 그리기", "open", 0, ("quality_of_life",)),
    ("동네 도서관 책 반납", "done", 0, ("learning",)),
    ("저녁 산책 30분", "open", 0, ("health",)),
    ("이력서 한 줄 고치기", "open", 1, ("career",)),
    ("이번 달 구독 정리", "open", 2, ("finance",)),
    ("친구에게 안부 문자", "open", None, ("relationships",)),
    ("세탁소에 겨울 외투 맡기기", "open", -2, ("quality_of_life",)),  # 전에 잡았지만 아직 열린 일
)
# 오늘 시각이 있는 일정(KST 시, 분)
SCHEDULED = (("치과 정기 검진", 14, 0),)
# 이번 분기 메인 퀘스트와 그 첫 걸음: (제목, 상태, 오늘부터 며칠 뒤)
MAIN_QUEST = "꾸민 작은 그림책 만들기"
FIRST_STEPS = (
    ("이야기 줄거리 쓰기", "done", None),
    ("등장인물 스케치", "done", None),
    ("판형 정하기", "done", None),
    ("첫 장면 색칠하기", "open", 0),
    ("인쇄소 견적 묻기", "open", None),
)
# 지난 4주에 끝낸 할 일(SP8 보너스): (제목, 오늘에서 며칠 전, 영역). 모두 이번 주 앞이라 `/week`에는 없다.
PAST_DONE = (
    ("포트폴리오 사진 고르기", 8, ("career",)),
    ("이력서 경력 칸 다듬기", 10, ("career",)),
    ("면접 질문 목록 쓰기", 13, ("career",)),
    ("업계 모임 신청", 15, ("career", "relationships")),
    ("자격증 교재 1장 읽기", 17, ("learning", "career")),
    ("작업물 정리 폴더 만들기", 22, ("career",)),
    ("스케치북 새로 사기", 9, ("quality_of_life",)),
)
# 건강 습관 하나: 지난 27일 중 체크하지 않은 날(오늘은 아직 체크 전)
HABIT = "저녁에 걷기"
HABIT_GAPS = frozenset({3, 6, 11, 18, 20, 25})
BRIEF_TEXT = "좋은 아침이에요. 오늘은 수채화 밑그림과 저녁 산책이 우선이에요.\n14:00에 치과 정기 검진이 있어요."
# 이번 분기 영역 점수(지난 분기보다 건강만 낮다: 디버프 하나)
THIS_QUARTER = {"career": 6, "finance": 5, "health": 4, "relationships": 7, "learning": 6, "quality_of_life": 5}
LAST_QUARTER = {"career": 6, "finance": 5, "health": 6, "relationships": 7, "learning": 6, "quality_of_life": 5}
# 컨디션: 30일 가운데 21일만 기록(오늘에서 며칠 전, 점수). 빈 날은 그대로 빈 날이다.
CONDITION_GAPS = frozenset({2, 5, 9, 12, 16, 19, 23, 26, 29})
CONDITION_SCORES = (4, 3, 3, 4, 5, 2, 3, 4, 4, 3)
# 인생 곡선 사다리 (달, 지금, 5년 뒤): 2026-03은 5년 뒤만, 2026-04는 빈 달(선이 끊긴다)
CURVE_LADDER = (
    ("2025-11", 4, 6), ("2025-12", 4, 6), ("2026-01", 5, 7), ("2026-02", 6, 7), ("2026-03", None, 7),
    ("2026-05", 5, 7), ("2026-06", 3, 6), ("2026-07", 7, 8), ("2026-08", 5, 7), ("2026-09", 6, 7),
    ("2026-10", 6, 8),
)
# 30일 창보다 앞선 달의 컨디션(짝수 날마다): 7월은 기억보다 버거웠고 8월은 기억보다 괜찮았다(안심 보기 8.3)
CURVE_CONDITIONS = {
    "2026-07": (2, 3, 2, 3, 2, 3, 2, 3, 3, 2),
    "2026-08": (5, 4, 5, 4, 5, 4, 5, 4, 5, 4, 5, 4),
}


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
    for name, h, mi in SCHEDULED:
        conn.execute(
            "INSERT INTO tasks (title, status, planned_for, scheduled_at, created_at, updated_at) "
            "VALUES (?, 'open', ?, ?, ?, ?)",
            (name, today.isoformat(), to_iso(_kst(midnight, h, mi)), ts, ts),
        )
    cur = conn.execute(
        "INSERT INTO tasks (title, status, created_at, updated_at) VALUES (?, 'open', ?, ?)", (MAIN_QUEST, ts, ts)
    )
    quest = int(cur.lastrowid or 0)
    conn.execute("INSERT INTO task_areas (task_id, area) VALUES (?, 'quality_of_life')", (quest,))
    quarter = f"{today.year}-Q{(today.month - 1) // 3 + 1}"
    conn.execute("INSERT INTO priorities (cadence, period, rank, task_id) VALUES ('quarter', ?, 1, ?)",
                 (quarter, quest))
    for name, status, days in FIRST_STEPS:
        planned = (today + timedelta(days=days)).isoformat() if days is not None else None
        conn.execute(
            "INSERT INTO tasks (title, status, planned_for, parent_id, created_at, updated_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, status, planned, quest, ts, ts, ts if status == "done" else None),
        )

    # --- 지난 4주 활동(SP8 5장 보너스): 이번 주 앞의 끝낸 할 일, 건강 습관 체크 ---
    for name, back, areas in PAST_DONE:
        d = midnight - timedelta(days=back)
        cur = conn.execute(
            "INSERT INTO tasks (title, status, created_at, updated_at, completed_at) VALUES (?, 'done', ?, ?, ?)",
            (name, ts, ts, to_iso(_kst(d, 19, 30))),
        )
        conn.executemany("INSERT INTO task_areas (task_id, area) VALUES (?, ?)",
                         [(int(cur.lastrowid or 0), a) for a in areas])
    cur = conn.execute(
        "INSERT INTO habits (title, area, kind, status, sort_order, created_at, updated_at) "
        "VALUES (?, 'health', 'daily', 'active', 1, ?, ?)", (HABIT, ts, ts),
    )
    habit_id = int(cur.lastrowid or 0)
    conn.executemany(
        "INSERT INTO habit_checks (habit_id, date, checked_at) VALUES (?, ?, ?)",
        [(habit_id, (today - timedelta(days=back)).isoformat(), ts) for back in range(1, 28)
         if back not in HABIT_GAPS],
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
        (to_iso(brief_at), to_iso(brief_at), to_iso(brief_at + timedelta(seconds=40)), BRIEF_TEXT,
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
    m1 = milestone(conn, "꾸민 첫 전시", "2025-09", kind="high", chapter_id=ch, note="꾸민 메모: 작은 카페 벽에 세 점")
    m2 = milestone(conn, "꾸민 이사 결정", "2026-02-14", kind="turning_point", chapter_id=ch)
    milestone(conn, "꾸민 긴 감기", "2026-06", kind="low")
    milestone(conn, "꾸민 첫 자전거", "2019", kind="high")  # 가장 이른 챕터보다 앞선 사건(년 확대가 `from`을 준다)
    milestone(conn, "꾸민 조용한 겨울", "2025-12", kind="low", sensitive=1, note="꾸민 메모: 민감 표시 확인용")
    for period, n, f in CURVE_LADDER:
        ladder(conn, period, now=n, future=f)
    for month, scores in CURVE_CONDITIONS.items():
        for day, score in enumerate(scores, start=1):
            conn.execute(
                "INSERT INTO conditions (date, score, note, recorded_at) VALUES (?, ?, NULL, ?)",
                (f"{month}-{day * 2:02d}", score, ts),
            )
    q = (today.month - 1) // 3 + 1
    last_quarter = f"{today.year}-Q{q - 1}" if q > 1 else f"{today.year - 1}-Q4"
    area_scores(conn, last_quarter, **LAST_QUARTER)
    area_scores(conn, quarter, **THIS_QUARTER)
    recovery(conn, quarter, "health", "저녁에 20분 걷기")
    area_default(conn, "health", "꾸민 회복 퀘스트: 20분 걷기")

    # --- 상태창: 경험치 원장·칭호 ---
    xp(conn, f"task:{ids[1]}", 10, to_iso(_kst(midnight, 11, 20)))
    xp(conn, f"run:{brief_id}", 5, to_iso(brief_at + timedelta(minutes=12)), label="회차 답", kind="checkin_reply")
    yday = midnight - timedelta(days=1)
    xp(conn, f"date:{(today - timedelta(days=1)).isoformat()}", 5, to_iso(_kst(yday, 21)), label="컨디션 기록",
       kind="condition")
    # 지난 기록: 쉬는 날 2일(5씩), 주간 회고 12번(30씩), 할 일 99개(10씩). 합계 20 + 10 + 360 + 990 = 1380
    for back in (2, 40):
        d = midnight - timedelta(days=back)
        xp(conn, f"date:{(today - timedelta(days=back)).isoformat()}", 5, to_iso(_kst(d, 4, 10)), label="쉬는 날",
           kind="rest_day")
    for n in range(12):
        d = midnight - timedelta(days=7 * n + 6)
        xp(conn, f"run:{9000 + n}", 30, to_iso(_kst(d, 20)), label="주간 회고", kind="review_week")
    for n in range(99):
        d = midnight - timedelta(days=3 + n // 3)
        xp(conn, f"task:{9000 + n}", 10, to_iso(_kst(d, 9 + n % 3 * 4)))
    title(conn, m1, to_iso(_kst(midnight - timedelta(days=30), 12)))
    title(conn, m2, to_iso(_kst(midnight - timedelta(days=20), 12)))

    conn.commit()

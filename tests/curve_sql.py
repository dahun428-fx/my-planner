"""곡선·상태창 시험 고정 자료: SQL로 직접 넣는다(쓰기 도구는 이후 티켓). 내용은 모두 꾸며 낸 것이다."""

TS = "2026-10-01T00:00:00.000000+00:00"


def chapter(conn, title, start, end=None, *, status="confirmed", sketch=None, certainty="fact",
            ladder_remembered=None):
    cur = conn.execute(
        "INSERT INTO curve_chapters (title, theme, start_month, end_month, sketch, certainty, status, origin, "
        "draft_since, created_at, updated_at, ladder_remembered) VALUES (?, '꾸민 주제', ?, ?, ?, ?, ?, 'seed', ?, ?, ?, ?)",
        (title, start, end, sketch, certainty, status, TS if status == "draft" else None, TS, TS, ladder_remembered),
    )
    return cur.lastrowid


def milestone(
    conn, title, date_text, *, kind="high", status="confirmed", sensitive=0, precision=None, chapter_id=None,
    title_label=None, note=None, area=None, origin="seed", kind_certainty="fact", certainty="fact",
):
    precision = precision or {4: "year", 7: "month", 10: "day"}[len(date_text)]
    sort_date = {"year": date_text + "-01-01", "month": date_text + "-01", "day": date_text}[precision]
    cur = conn.execute(
        "INSERT INTO curve_milestones (chapter_id, date_text, precision, sort_date, kind, title, note, sensitive, "
        "status, origin, title_label, draft_since, created_at, confirmed_at, updated_at, area, kind_certainty, "
        "certainty) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (chapter_id, date_text, precision, sort_date, kind, title, note, sensitive, status, origin, title_label,
         TS if status == "draft" else None, TS, TS if status == "confirmed" else None, TS, area, kind_certainty,
         certainty),
    )
    return cur.lastrowid


def ladder(conn, period, now=None, future=None, note=None):
    conn.execute(
        "INSERT INTO curve_ladder_scores (period, now, future, note, recorded_at) VALUES (?, ?, ?, ?, ?)",
        (period, now, future, note, TS),
    )


def area_scores(conn, period, **scores):
    for area, score in scores.items():
        conn.execute(
            "INSERT INTO curve_area_scores (period, area, score, recorded_at) VALUES (?, ?, ?, ?)",
            (period, area, score, TS),
        )


def recovery(conn, period, area, text):
    conn.execute("UPDATE curve_area_scores SET recovery_quest = ? WHERE period = ? AND area = ?", (text, period, area))


def area_default(conn, area, text):
    conn.execute("INSERT INTO curve_area_defaults (area, recovery_quest, updated_at) VALUES (?, ?, ?)", (area, text, TS))


def xp(conn, source_ref, amount, at, label="할 일 완료", kind="task_done"):
    conn.execute(
        "INSERT INTO status_xp_ledger (at, logical_date, source_kind, source_ref, amount, label) "
        "VALUES (?, substr(?, 1, 10), ?, ?, ?, ?)",
        (at, at, kind, source_ref, amount, label),
    )


def title(conn, milestone_id, granted_at=TS):
    conn.execute("INSERT INTO status_titles (milestone_id, granted_at) VALUES (?, ?)", (milestone_id, granted_at))

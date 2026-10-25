"""텔레그램 `/status` (SP3-4 스펙 11.4, 부록 A). `GET /status`와 같은 `status_snapshot`에서 나온다. 내용은 꾸며 낸 것이다."""

from datetime import date, timedelta

from be_env import BeEnv
from curve_sql import area_scores, milestone
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.bot.commands import EMPTY_STATS, HELP_TEXT, command_of, status_text

SAT_1300 = kst(2026, 10, 24, 13, 0)
TS = "2026-10-01T00:00:00.000000+00:00"


def _stat(area, label, score, period="2026-Q4", *, prev=None, debuff=False, quest=None):
    return {"area": area, "label": label, "score": score, "period": period if score is not None else None,
            "prev_score": prev, "prev_period": "2026-Q3" if prev is not None else None, "debuff": debuff,
            "recovery_quest": quest}


def _snap(**over):
    snap = {
        "level": 6, "xp_total": 1380, "xp_into_level": 130, "xp_for_next": 400,
        "hp": {"date": "2026-10-24", "score": 4},
        "stats": [
            _stat("career", "커리어", 6), _stat("finance", "경제", 5),
            _stat("health", "건강", 4, prev=6, debuff=True, quest="저녁에 20분 걷기"),
            _stat("relationships", "관계", 7), _stat("learning", "배움", 6), _stat("quality_of_life", "삶의 질", 5),
        ],
        "main_quests": [{"task_id": 31, "title": "꾸민 목표", "rank": 1, "period": "2026-Q4",
                         "first_steps": {"open": 2, "done": 3}}],
        "daily_quests": [{"task_id": 52, "title": "꾸민 첫 걸음", "parent_id": 31, "parent_title": "꾸민 목표",
                          "planned_for": "2026-10-24"}],
        "titles": [{"milestone_id": i, "title": t, "kind": "turning_point", "date": "2023-05", "granted_at": None}
                   for i, t in enumerate(["「꾸민 결심」을 지나온 사람", "둘", "셋"], start=1)],
        "recent_xp": [],
    }
    snap.update(over)
    return snap


def test_status_text_format():
    assert status_text(_snap()) == (
        "상태창\n"
        "레벨 6 · 경험치 130/400\n"
        "HP 4/5 (오늘 컨디션)\n"
        "\n"
        "스탯 (2026-Q4)\n"
        "커리어 6 · 경제 5 · 건강 4 ↓ · 관계 7 · 배움 6 · 삶의 질 5\n"
        "↓ 건강 6 → 4: 회복 퀘스트 \"저녁에 20분 걷기\"\n"
        "\n"
        "메인 퀘스트\n"
        "1. 꾸민 목표 (첫 걸음 3/5)\n"
        "\n"
        "오늘의 퀘스트\n"
        "- 꾸민 첫 걸음\n"
        "\n"
        "칭호: 「꾸민 결심」을 지나온 사람 외 2개"
    )


def test_status_text_partial_blocks():
    stats = [_stat("career", "커리어", 6), _stat("finance", "경제", 5, "2026-Q3"), _stat("health", "건강", None)]
    text = status_text(_snap(hp={"date": "2026-10-24", "score": None}, stats=stats, main_quests=[], daily_quests=[],
                             titles=_snap()["titles"][:1]))
    assert text == (
        "상태창\n레벨 6 · 경험치 130/400\nHP 기록 없음 (오늘 컨디션)\n\n"
        "스탯 (2026-Q4)\n커리어 6 · 경제 5 (2026-Q3) · 건강 -\n\n"
        "칭호: 「꾸민 결심」을 지나온 사람"
    )


def test_status_empty_stats_copy():
    stats = [_stat(a, label, None) for a, label in (("career", "커리어"), ("health", "건강"))]
    text = status_text(_snap(stats=stats, main_quests=[], daily_quests=[], titles=[]))
    assert text == "상태창\n레벨 6 · 경험치 130/400\nHP 4/5 (오늘 컨디션)\n\n" + EMPTY_STATS
    assert EMPTY_STATS == "영역 점수는 분기 마지막 주 회고에서 함께 정해요."  # 부록 A


def test_help_lists_status():
    assert "/status  레벨, 스탯, 퀘스트\n" in HELP_TEXT
    assert command_of("/status") == "/status" and command_of("/status@꾸민봇") == "/status"


async def test_status_command_and_api_same_numbers(tmp_path):
    add = ("add_task", {"title": "꾸민 목표", "areas": ["learning"]})
    prio = ("set_priorities", {"cadence": "quarter", "period": "2026-Q4", "task_ids": [1]})
    step = ("add_task", {"title": "꾸민 첫 걸음", "areas": ["learning"], "parent_id": 1, "planned_for": "2026-10-24"})
    script = [FakeTurn([add, prio, step], "올렸어요")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        await env.telegram("꾸민 목표를 이번 분기 목표로")
        _, done = await env.action("add_task", {"title": "꾸민 일", "areas": ["health"]})
        await env.action("complete_task", {"id": done["result"]["id"]})
        await env.action("record_condition", {"score": 4})
        area_scores(env.conn, "2026-Q3", health=6, career=5)
        area_scores(env.conn, "2026-Q4", health=4, career=5)
        milestone(env.conn, "꾸민 결심", "2023-05", kind="turning_point")
        hidden = milestone(env.conn, "꾸민 민감", "2024-01", kind="high", sensitive=1)
        for mid in (1, hidden):
            env.conn.execute("INSERT INTO status_titles (milestone_id, granted_at) VALUES (?, ?)",
                             (mid, "2026-10-01T00:00:00.000000+00:00"))
        env.conn.commit()
        await env.telegram("/status")
        telegram = env.bot.sent[-1][1]
        api = await (await env.get("/status")).json()
        _, raw = await env.chat("/status")

    assert telegram == status_text(api)
    assert (api["level"], api["xp_total"], api["xp_into_level"]) == (1, 15, 15)  # X1 10 + X4 5
    assert telegram.startswith("상태창\n레벨 1 · 경험치 15/150\nHP 4/5 (오늘 컨디션)")
    assert "↓ 건강 6 → 4: 회복 퀘스트 \"20분 걷기\"" in telegram  # 부록 A 기본 회복 퀘스트
    assert "1. 꾸민 목표 (첫 걸음 0/1)" in telegram and "- 꾸민 첫 걸음" in telegram
    assert telegram.endswith("칭호: 「꾸민 결심」을 지나온 사람")  # 민감 사건 칭호는 뺀다
    assert "레벨 1 · 경험치 15/150" in raw.decode()  # 앱도 같은 `run_command`


async def test_telegram_status_text_unchanged_by_bonus(tmp_path):
    """SP8 D7: 보너스 필드가 있는 스냅샷에서도 텔레그램 `/status` 글은 SP7 그대로다(새 줄·"요즘"·"+1.5" 없음)."""
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 25, 13, 0), script=[]) as env:
        area_scores(env.conn, "2026-Q3", health=6)
        area_scores(env.conn, "2026-Q4", career=6, health=4)
        hid = env.conn.execute(
            "INSERT INTO habits (title, area, kind, sort_order, created_at, updated_at) "
            "VALUES ('꾸민 걷기', 'health', 'daily', 1, ?, ?)", (TS, TS),
        ).lastrowid
        env.conn.executemany(
            "INSERT INTO habit_checks (habit_id, date, checked_at) VALUES (?, ?, ?)",
            [(hid, (date(2026, 10, 25) - timedelta(days=d)).isoformat(), TS) for d in range(28)],
        )
        env.conn.commit()
        await env.telegram("/status")
        telegram = env.bot.sent[-1][1]
        api = await (await env.get("/status")).json()

    health = next(s for s in api["stats"] if s["area"] == "health")
    assert (health["bonus"], health["effective_score"]) == (1.5, 5.5)
    assert telegram == status_text(api) == (
        "상태창\n"
        "레벨 1 · 경험치 0/150\n"
        "HP 기록 없음 (오늘 컨디션)\n"
        "\n"
        "스탯 (2026-Q4)\n"
        "커리어 6 · 경제 - · 건강 4 ↓ · 관계 - · 배움 - · 삶의 질 -\n"
        "↓ 건강 6 → 4: 회복 퀘스트 \"20분 걷기\""
    )
    assert "요즘" not in telegram and "+1.5" not in telegram and "5.5" not in telegram

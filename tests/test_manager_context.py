"""SP15-10: 라이프 매니저 앞머리 `harness/manager_context.py` (스펙 5.3, T17). 자료는 모두 지어낸 값이다."""

from __future__ import annotations

import logging
import re
from datetime import date, time, timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.harness.manager_context import budget_block, build_manager_preamble
from my_planner.panel.budget import week_key
from my_planner.store.db import transaction
from my_planner.store.migrations.hooks import SEED_DECISION_KEY, SEED_DECISION_TEXT
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.panel import PanelRepo
from my_planner.store.repos.standing import StandingRepo
from my_planner.store.repos.tasks import TasksRepo

NOW = kst(2026, 11, 1, 14, 0)  # 일요일 오후
TODAY = date(2026, 11, 1)
TZ = "Asia/Seoul"
B = time(4, 0)
HEADS = ["## 지금", "## 상태", "## 내 속도 표", "## 주간 제안", "## 결정", "## 내가 한 말", "## 예측", "## 다른 상대"]


def _build(conn, clock) -> str:
    return build_manager_preamble(conn, clock, now=clock.now(), tz=TZ, boundary=B)


def _section(text: str, head: str) -> list[str]:
    """그 제목 아래 줄들(다음 `## ` 전까지)."""
    out: list[str] = []
    on = False
    for line in text.splitlines():
        if line.startswith("## "):
            on = line == head
            continue
        if on and line:
            out.append(line)
    return out


def _seed(conn, clock) -> None:
    now = clock.now()
    panel = PanelRepo(conn, clock)
    with transaction(conn):
        st = StandingRepo(conn, clock)
        st.add("profile_birth_year", 1992, date(2026, 1, 1), "import", None, "high", now)
        st.add("profile_sex", "m", date(2026, 1, 1), "import", None, "high", now)
        st.add("body_fat_pct", 21.5, date(2026, 10, 1), "import", None, "mid", now)
        panel.add_suggestion(
            conversation_id=None, kind="task", title="지어낸 제안", area="career", size_min=20, per_week=None,
            due_hint=None, experts=["career"], evidence=[{"ref": "statement:1", "note": "가짜"}],
            week=week_key(TODAY), now=now,
        )
        panel.add_statement("fact", "career", "지어낸 사실", now=now)
        panel.add_statement("preference", None, "지어낸 바람", now=now + timedelta(seconds=1))
        panel.add_prediction("body_fat_pct", 21.5, TODAY - timedelta(days=3), conversation_id=None, now=now)
    TasksRepo(conn, clock, tz=TZ, boundary=B).create("지어낸 할 일", ["career"])
    CurveRepo(conn, clock).set_area_scores("2026-Q3", {"career": 6, "finance": 5})


def test_preamble_blocks_in_order(conn):
    clock = FakeClock(NOW)
    _seed(conn, clock)
    text = _build(conn, clock)
    heads = [line for line in text.splitlines() if line.startswith("## ")]
    assert heads == HEADS
    assert _section(text, "## 지금") == ["2026-11-01 (일) 14:00"]
    status = _section(text, "## 상태")
    assert status[-1] == "- 영역 만족(2026-Q3): 커리어 6 · 경제 5"
    assert any(line.startswith("- 빈칸: ") for line in status)
    assert all(re.fullmatch(r"- .+ \d+ \(신뢰도 (high|mid|low)\)", ln) for ln in status if "빈칸" not in ln
               and "영역 만족" not in ln)
    budget = _section(text, "## 주간 제안")
    assert budget[0].startswith("- 이번 주 더 낼 수 있는 수: ")
    assert re.fullmatch(r"- 열린 제안: suggestion:\d+ 지어낸 제안 · 커리어 · proposed", budget[1])
    said = _section(text, "## 내가 한 말")
    assert re.fullmatch(r"- statement:\d+ - 지어낸 바람", said[0])  # 최신 먼저, 영역 없으면 "-"
    assert re.fullmatch(r"- statement:\d+ 커리어 지어낸 사실", said[1])
    assert _section(text, "## 다른 상대") == ["- 없음"]


def test_decision_career_first_on_top(conn):
    clock = FakeClock(NOW)
    panel = PanelRepo(conn, clock)
    with transaction(conn):
        panel.add_statement("decision", None, "지어낸 결정", key="made_up", now=NOW - timedelta(days=400))
    lines = _section(_build(conn, clock), "## 결정")
    assert lines[0] == f"- decision:{SEED_DECISION_KEY} {SEED_DECISION_TEXT}"
    assert lines[1] == "- decision:made_up 지어낸 결정"


def test_prediction_lines(conn):
    clock = FakeClock(NOW)
    panel = PanelRepo(conn, clock)
    with transaction(conn):
        hit = panel.add_prediction("body_fat_pct", 21.5, TODAY - timedelta(days=2), conversation_id=None, now=NOW)
        panel.set_actual(hit, 20.0, NOW)
        panel.add_prediction("waist_cm", 80, TODAY - timedelta(days=1), conversation_id=None, now=NOW)
        panel.add_prediction("steps", 9000, TODAY + timedelta(days=5), conversation_id=None, now=NOW)  # 기한 전
        closed = panel.add_prediction("bench_kg", 60, TODAY - timedelta(days=20), conversation_id=None, now=NOW)
        panel.set_actual(closed, None, NOW)  # 창이 닫혀 값 없이 맞춰 봄
    lines = _section(_build(conn, clock), "## 예측")
    assert sorted(lines) == sorted([
        "- body_fat_pct 예측 21.5 · 기한 2026-10-30 · 실제 20 · 차이 -1.5",
        "- waist_cm 예측 80 · 기한 2026-10-31 · 측정 필요",
    ])


def test_empty_preamble_blocks_say_none(conn):
    clock = FakeClock(NOW)
    with transaction(conn):
        conn.execute("UPDATE owner_statements SET retired_at = ?", ("2026-10-01T00:00:00Z",))
    text = _build(conn, clock)
    for head in ("## 결정", "## 내가 한 말", "## 예측", "## 다른 상대"):
        assert _section(text, head) == ["- 없음"], head
    assert _section(text, "## 주간 제안") == ["- 이번 주 더 낼 수 있는 수: 2", "- 열린 제안: 없음"]
    assert budget_block(conn, clock, TODAY) == "## 주간 제안\n- 이번 주 더 낼 수 있는 수: 2\n- 열린 제안: 없음"


async def test_other_agents_summaries_only(tmp_path):
    script = [FakeTurn([], "좋아요")]
    async with BeEnv.start(tmp_path, start=NOW, script=script) as env:
        resp, _ = await env.chat("원문비밀XYZ", agent="mate")
        cid = int(resp.headers["x-conversation-id"])
        convs = ConversationsRepo(env.conn, env.clock)
        convs.set_summary(cid, "지어낸 제목", "가짜 요약", env.clock.now())
        text = _build(env.conn, env.clock)
    assert _section(text, "## 다른 상대") == ["- 운동메이트 11/1 지어낸 제목: 가짜 요약"]
    assert "원문비밀XYZ" not in text


async def test_resumed_manager_gets_budget_block(tmp_path):
    script = [FakeTurn([], "네"), FakeTurn([], "좋아요")]
    async with BeEnv.start(tmp_path, start=NOW, script=script) as env:
        resp, _ = await env.chat("이번 주 뭐부터?", agent="manager")
        cid = int(resp.headers["x-conversation-id"])
        env.clock.advance(timedelta(minutes=1))
        await env.chat("그다음은?", agent="manager", conversation_id=cid)
        first, second = env.brain.prompts[0], env.brain.prompts[1]
        sessions = env.brain.session_ids
    assert sessions[1] is not None  # 둘째는 이어진 세션
    assert "## 상태" in first and first.index("## 주간 제안") < first.index("## 메시지")
    assert first.count("## 주간 제안") == 1
    assert "## 상태" not in second and "## 내 속도 표" not in second
    assert second.count("## 주간 제안") == 1
    assert second.index("## 주간 제안") < second.index("## 메시지")


async def test_preamble_numbers_not_logged(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    async with BeEnv.start(tmp_path, start=NOW, script=[FakeTurn([], "네")]) as env:
        panel = PanelRepo(env.conn, env.clock)
        with transaction(env.conn):
            panel.add_prediction("salary_krw", 1234, TODAY - timedelta(days=2), conversation_id=None, now=NOW)
        await env.chat("요즘 어때요?", agent="manager")
        prompt = env.brain.prompts[0]
    assert "salary_krw 예측 1234" in prompt  # 프롬프트에는 들어간다
    assert "1234" not in caplog.text


def test_now_block_shows_logical_date_before_boundary(conn):
    """Task 10 검토: 00:00~04:00에는 시계 날짜와 함께 주 계산이 쓰는 논리적 날짜를 적는다."""
    text = _build(conn, FakeClock(kst(2026, 11, 2, 2, 0)))
    assert _section(text, "## 지금") == ["2026-11-02 (월) 02:00, 오늘(논리적 날짜)은 2026-11-01 (일)"]

"""회고 단계: 월말 사다리, 분기 영역 점수, 연말 (SP3-4 스펙 11.1~11.2, 부록 A, 계획 빈 곳 12·14).

내용은 모두 꾸며 낸 것이다.
"""

from datetime import date, timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.domain import Cadence, LoopKey
from my_planner.harness import prompts
from my_planner.harness.review_steps import ReviewSteps, review_steps
from my_planner.store.reviews import save_weekly_review

SUN_1129 = kst(2026, 11, 29, 18, 0)  # 11월의 마지막 일요일(다섯 번째)
SUN_1227 = kst(2026, 12, 27, 18, 0)  # 월말 + 4분기 + 연말


def _queued_sunday(env, at):
    eve = env.runs.ensure(LoopKey.evening_checkin, at)
    review = env.runs.ensure(LoopKey.review, at, Cadence.week)
    for r in (eve, review):
        env.runs.mark_queued(r.id)
    return env.runs.get(eve.id), env.runs.get(review.id)


# --- 슬라이스 1: 판정, 지시문, 회고 파일 ---


def test_last_sunday_in_five_sunday_month():
    assert review_steps(date(2026, 11, 29)) == ReviewSteps(month=True)
    assert not review_steps(date(2026, 11, 22))
    assert review_steps(date(2026, 11, 22)) == ReviewSteps()
    assert review_steps(date(2026, 11, 29)).prompt_files() == ["review_month.md"]
    # 일요일이 아니면 월말 회고가 아니다
    assert not review_steps(date(2026, 11, 30))


def test_1227_month_quarter_year_overlap():
    steps = review_steps(date(2026, 12, 27))
    assert steps == ReviewSteps(month=True, quarter=True, year=True)
    assert steps.prompt_files() == ["review_month.md", "review_quarter.md", "review_year.md"]
    assert review_steps(date(2026, 9, 27)) == ReviewSteps(month=True, quarter=True)
    assert review_steps(date(2026, 12, 20)) == ReviewSteps()


async def test_carried_review_uses_original_date(tmp_path, conn, state):
    # 11/29 회고가 늦어 R1로 12/1(화) 아침 브리핑에 넘겨 받았다: 단계는 원래 날짜(11/29)로 판정한다
    env = Env(tmp_path, conn, state, script=[FakeTurn([], "꾸민 아침 인사")], start=kst(2026, 12, 1, 9, 0),
              with_tools=True, with_conditions=True)
    review = env.runs.ensure(LoopKey.review, SUN_1129, Cadence.week)
    brief = env.runs.ensure(LoopKey.morning_brief, kst(2026, 12, 1, 9, 0))
    for r in (brief, review):
        env.runs.mark_queued(r.id)
    env.dispatcher.start()
    env.dispatcher.submit_run(env.runs.get(brief.id), [env.runs.get(review.id)], carried_ids=[review.id])
    await env.dispatcher.stop(timeout=5)

    prompt = env.brain.prompts[0]
    assert prompts.load("review_month.md") in prompt
    assert prompts.load("review_quarter.md") not in prompt
    path = env.settings.paths.data_dir / "reviews" / "week" / "2026-W48.md"
    assert "포함: 월간(2026-11)" in path.read_text(encoding="utf-8")


async def test_prompts_appended_in_order(tmp_path, conn, state):
    env = Env(tmp_path, conn, state, script=[FakeTurn([], "꾸민 연말 회고")], start=SUN_1227 + timedelta(minutes=1),
              with_tools=True, with_conditions=True)
    eve, review = _queued_sunday(env, SUN_1227)
    await env.process_run(eve, [review])

    prompt = env.brain.prompts[0]
    order = [prompt.index(prompts.load(n)) for n in (
        "evening_checkin.md", "review_week.md", "review_month.md", "review_quarter.md", "review_year.md"
    )]
    assert order == sorted(order)

    # 월말이 아닌 회고에는 붙지 않는다
    env2 = Env(tmp_path / "b", conn, state, script=[FakeTurn([], "꾸민 회고")], start=kst(2026, 11, 22, 18, 1),
               with_tools=True, with_conditions=True)
    eve2, review2 = _queued_sunday(env2, kst(2026, 11, 22, 18, 0))
    await env2.process_run(eve2, [review2])
    assert prompts.load("review_month.md") not in env2.brain.prompts[0]


def test_review_file_includes_line(tmp_path):
    path = save_weekly_review(tmp_path, "2026-W52", "꾸민 회고 본문", included="포함: 월간(2026-12), 분기(2026-Q4)")
    assert path.read_text(encoding="utf-8") == (
        "# 주간 회고 2026-W52\n\n포함: 월간(2026-12), 분기(2026-Q4)\n\n꾸민 회고 본문\n"
    )
    plain = save_weekly_review(tmp_path, "2026-W47", "꾸민 회고 본문")
    assert plain.read_text(encoding="utf-8") == "# 주간 회고 2026-W47\n\n꾸민 회고 본문\n"
    assert ReviewSteps(month=True, quarter=True, year=True).included_line(date(2026, 12, 27)) == (
        "포함: 월간(2026-12), 분기(2026-Q4), 연간(2026)"
    )
    assert ReviewSteps().included_line(date(2026, 11, 22)) is None


async def test_open_seed_question_on_month_end_review(tmp_path):
    from be_env import BeEnv

    # 열린 시드 질문은 월말 회고마다 하나만 두뇌에게 준다(11.1-5). 실은 질문은 `asked`가 된다
    async with BeEnv.start(tmp_path, start=SUN_1129 + timedelta(seconds=30),
                           script=[FakeTurn([], "꾸민 월말 회고")]) as env:
        first = env.parts.curve.add_question("꾸민 질문 하나")
        env.parts.curve.add_question("꾸민 질문 둘")
        await env.tick()
        prompt = env.brain.prompts[0]
        rows = env.conn.execute("SELECT text, status FROM curve_questions ORDER BY id").fetchall()

    assert prompt.endswith("## 이번에 물을 질문\n꾸민 질문 하나")
    assert "꾸민 질문 둘" not in prompt
    assert [(r["text"], r["status"]) for r in rows] == [("꾸민 질문 하나", "asked"), ("꾸민 질문 둘", "open")]
    assert first is not None

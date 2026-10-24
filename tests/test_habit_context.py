"""두뇌가 보는 습관: 앞머리 `## 오늘 습관`, 주간 회고 `## 이번 주 습관`, `## 습관 버튼` 메모 (SP7 스펙 5.7, 부록 A).

가짜 두뇌 + 가짜 시계(`BeEnv`). 날짜는 2026-10-24(토) 저녁 체크인 18:00, 10/25(일) 주간 회고 18:00, 10/26(월) 아침.
내용은 모두 꾸며 낸 것이다.
"""

from datetime import date, timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.domain import LoopKey
from my_planner.harness.context import build_preamble, habit_week_block
from my_planner.harness.dispatcher import _habit_buttons_note

SAT = date(2026, 10, 24)
SUN = date(2026, 10, 25)
SAT_EVENING = kst(2026, 10, 24, 18, 0) + timedelta(seconds=30)
SUN_EVENING = kst(2026, 10, 25, 18, 0) + timedelta(seconds=30)
MON_MORNING = kst(2026, 10, 26, 9, 0) + timedelta(seconds=30)
BUTTONS_NOTE = (
    "## 습관 버튼\n메시지 아래에 오늘 습관 버튼이 붙습니다. 습관을 글로 하나하나 묻지 말고, "
    "'오늘 챙긴 습관은 아래에서 눌러 주세요'처럼 한 줄로 부탁합니다."
)


def habit(env, title, *, kind="daily", target=None, status="active"):
    h = env.parts.habits.add(title, "health", kind, target, env.clock.now())
    if status != "active":
        h = env.parts.habits.set_status(h.id, status, env.clock.now())
    return h


def check(env, h, *days):
    for d in days:
        env.parts.habits.check(h.id, d, env.clock.now())


def preamble(env, **kw):
    s = env.settings
    return build_preamble(
        now=env.clock.now(), tz=s.timezone, boundary=s.day_boundary, tasks=env.parts.tasks,
        habits=env.parts.habits, **kw,
    )


# --- 슬라이스 1: 앞머리 ---


async def test_preamble_today_habits_block(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_EVENING) as env:
        water = habit(env, "물 마시기")
        habit(env, "스트레칭")
        run_h = habit(env, "운동", kind="weekly", target=3)
        habit(env, "쉬는 습관", status="paused")
        check(env, water, SAT)
        check(env, run_h, date(2026, 10, 19), SAT)
        text = preamble(env, include_habits=True)

    assert "## 오늘 습관\n- 물 마시기 (매일): 오늘 ✓\n- 스트레칭 (매일)\n- 운동 (주 3회): 이번 주 2번" in text
    assert "쉬는 습관" not in text


async def test_preamble_no_block_without_habits(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_EVENING) as env:
        assert "## 오늘 습관" not in preamble(env, include_habits=True)  # 활성 습관이 없다
        habit(env, "쉬는 습관", status="paused")
        assert "## 오늘 습관" not in preamble(env, include_habits=True)
        habit(env, "물 마시기")
        assert "## 오늘 습관" not in preamble(env)  # include_habits 기본값은 거짓
        assert "## 오늘 습관" in preamble(env, include_habits=True)


async def test_morning_brief_preamble_has_no_habits(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_MORNING, script=[FakeTurn([], "좋은 아침이에요")]) as env:
        habit(env, "물 마시기")
        await env.tick()
        prompt = env.brain.prompts[0]

    assert "## 지금" in prompt
    assert "## 오늘 습관" not in prompt and "## 습관 버튼" not in prompt and "## 이번 주 습관" not in prompt


async def test_evening_checkin_and_chat_prompts_have_habits(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_EVENING, script=[FakeTurn([], "수고했어요")]) as env:
        habit(env, "물 마시기")
        await env.tick()
        evening = env.brain.prompts[0]
    async with BeEnv.start(tmp_path / "chat", start=kst(2026, 10, 24, 13, 0), script=[FakeTurn([], "네")]) as env:
        habit(env, "물 마시기")
        await env.chat("안녕")
        chat = env.brain.prompts[0]

    assert "## 오늘 습관\n- 물 마시기 (매일)" in evening and BUTTONS_NOTE in evening
    assert "## 이번 주 습관" not in evening  # 토요일은 주간 회고가 아니다
    assert "## 오늘 습관" in chat and "## 습관 버튼" not in chat


# --- 슬라이스 2: 주간 회고 블록과 버튼 메모 ---


async def test_review_week_block_four_weeks_with_zero(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_EVENING) as env:
        h = habit(env, "운동", kind="weekly", target=3)
        water = habit(env, "물 마시기")
        check(env, h, date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23))  # 4주 전: 3번
        check(env, h, date(2026, 9, 28), date(2026, 10, 4))  # 3주 전: 2번
        check(env, h, date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 11))  # 2주 전: 3번
        check(env, h, date(2026, 10, 19), SUN)  # 이번 주: 2번, 지난주(10/12~18): 0번
        check(env, water, SUN)
        block = habit_week_block(env.parts.habits, SUN)
        empty = habit_week_block(env.parts.habits, date(2026, 10, 25))
        none = habit_week_block(BeEnv_no_habits(env), SUN)

    assert block.startswith("## 이번 주 습관\n")
    assert "- 운동 (주 3회): 이번 주 2번 · 지난 4주 3·2·3·0번" in block
    assert "- 물 마시기 (매일): 이번 주 1번 · 지난 4주 0·0·0·0번" in block
    assert empty == block
    assert none == ""


class BeEnv_no_habits:
    def __init__(self, env):
        self._env = env

    def list(self, statuses=("active",)):
        return []


async def test_review_week_prompt_has_week_block(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_EVENING, script=[FakeTurn([], "한 주 수고했어요")]) as env:
        habit(env, "운동", kind="weekly", target=3)
        await env.tick()
        prompt = env.brain.prompts[0]

    assert "## 이번 주 습관\n- 운동 (주 3회): 이번 주 0번 · 지난 4주 0·0·0·0번" in prompt
    assert "## 오늘 습관" in prompt and BUTTONS_NOTE in prompt  # 합친 저녁 체크인


def test_habit_buttons_note_text():
    assert _habit_buttons_note(SAT) == BUTTONS_NOTE
    assert _habit_buttons_note(None) == ""


async def test_habit_buttons_note_only_when_rows(tmp_path):
    # 활성 습관이 없으면 저녁 체크인에도 메모가 없다(메시지에 습관 줄이 안 붙는다)
    async with BeEnv.start(tmp_path, start=SAT_EVENING, script=[FakeTurn([], "수고했어요")]) as env:
        habit(env, "쉬는 습관", status="paused")
        await env.tick()
        prompt = env.brain.prompts[0]
        (out,) = env.sender.sent

    assert out.habit_date is None
    assert "## 습관 버튼" not in prompt and "## 오늘 습관" not in prompt


# --- 후속: return 회차, 회차 대화의 답, 습관 버튼 날짜 ---


async def test_return_run_prompt_has_no_habits(tmp_path):
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0), script=[FakeTurn([], "돌아오셨네요")]) as env:
        habit(env, "물 마시기")
        run = env.parts.runs.ensure(LoopKey.return_, env.clock.now())
        env.parts.runs.mark_queued(run.id)
        env.parts.dispatcher.submit_run(env.parts.runs.get(run.id), [])
        await env.drain()
        prompt = env.brain.prompts[0]

    assert "## 지금" in prompt
    assert "## 오늘 습관" not in prompt and "## 습관 버튼" not in prompt


async def test_reply_in_run_conversation_has_today_habits(tmp_path):
    async with BeEnv.start(
        tmp_path, start=SAT_EVENING, script=[FakeTurn([], "수고했어요", session_id=None), FakeTurn([], "좋아요")]
    ) as env:
        habit(env, "물 마시기")
        await env.tick()
        await env.telegram("오늘 물 마셨어요")
        prompt = env.brain.prompts[1]

    assert "## 오늘 습관\n- 물 마시기 (매일)" in prompt


def test_today_habit_block_uses_habit_day(tmp_path):
    # 체크인 날짜(토)와 지금의 논리적 날짜(일)가 다르면 블록은 체크인 날짜 기준이다
    import asyncio

    async def go():
        async with BeEnv.start(tmp_path, start=kst(2026, 10, 25, 5, 0)) as env:
            water = habit(env, "물 마시기")
            check(env, water, SAT)
            return preamble(env, include_habits=True), preamble(env, include_habits=True, habit_day=SAT)

    now_day, sat_day = asyncio.run(go())
    assert "- 물 마시기 (매일)\n" in now_day + "\n" and "오늘 ✓" not in now_day
    assert "- 물 마시기 (매일): 오늘 ✓" in sat_day

"""텔레그램 어댑터: 컨디션 버튼과 누름 (스펙 5.4, 5.8). 네트워크 없이 Update.de_json으로 만든 가짜 업데이트."""

from datetime import date

import pytest
from test_dispatcher_messages import kst
from test_telegram_drafts import OWNER, DraftEnv, _rows, press

from my_planner.bot.telegram_io import TelegramSender
from my_planner.harness.dispatcher import Outbound
from my_planner.store.repos.conditions import ConditionsRepo

OCT23 = date(2026, 10, 23)
ROW_1_5 = [(str(n), f"c:2026-10-23:{n}") for n in range(1, 6)]


@pytest.fixture
def cenv(tmp_path, conn, state):
    env = DraftEnv(tmp_path, conn, state)
    env.conditions = ConditionsRepo(conn, env.clock)
    env.tools.conditions = env.conditions
    return env


async def test_condition_buttons_layout(cenv):
    sender = TelegramSender(cenv.bot, OWNER, tasks=cenv.repo)

    # 컨디션만: 1~5 한 줄
    await sender.send(Outbound(text="오늘 컨디션은 어땠어요?", ask_condition_for=OCT23))
    text, markup = cenv.bot.sent[0]
    assert text == "오늘 컨디션은 어땠어요?"
    assert _rows(markup) == [ROW_1_5]
    assert all(len(b.callback_data.encode()) <= 64 for row in markup.inline_keyboard for b in row)

    # 초안과 함께: 초안 줄이 먼저, 그다음 1~5 줄. 버튼은 마지막 조각에만
    (a,) = cenv.propose("산책")
    long_text = "\n\n".join(["가" * 3000, "나" * 3000])
    await sender.send(
        Outbound(text=long_text, draft_conversation_id=7, draft_task_ids=[a], ask_condition_for=OCT23)
    )
    assert [m is None for _, m in cenv.bot.sent[1:]] == [True, False]
    assert _rows(cenv.bot.sent[-1][1]) == [
        [("✓ 추가: 산책", f"d:c:{a}"), ("✗ 빼기", f"d:x:{a}")],
        [("전부 추가", "d:all:7")],
        ROW_1_5,
    ]


async def test_condition_button_records_original_date(cenv):
    assert cenv.clock.now() == kst(2026, 10, 24, 10, 30)
    # 10/23 저녁 체크인의 버튼을 10/24 아침에 눌러도 10/23에 기록한다
    assert await press(cenv, "c:2026-10-23:4", update_id=900) == "recorded"

    assert cenv.conditions.get(OCT23).score == 4
    assert cenv.conditions.get(date(2026, 10, 24)) is None
    assert cenv.bot.answers == [("cb900", "컨디션 4 기록했어요.")]
    day = (cenv.tmp / "data" / "transcripts" / "2026" / "10" / "2026-10-24.md").read_text(encoding="utf-8")
    assert "### 10:30 사용자 [-]\n\n[버튼] 컨디션 4\n" in day

    # 다시 누르면 덮어쓴다
    assert await press(cenv, "c:2026-10-23:2", update_id=901) == "recorded"
    assert cenv.conditions.get(OCT23).score == 2
    assert cenv.bot.answers[-1] == ("cb901", "컨디션 2 기록했어요.")

    # 다른 사람, 모르는 모양은 아무것도 바꾸지 않고 답만 한 번
    assert await press(cenv, "c:2026-10-23:5", uid=99, update_id=902) == "ignored"
    bad = (
        "c:2026-10-23:6", "c:2026-10-23:0", "c:2026-13-40:3", "c:yesterday:3",
        "c:20261023:3", "c:2026-W43-5:3", "c:2026-10-25:3",  # 느슨한 형식, 논리적 오늘(10/24)보다 뒤
    )
    for n, data in enumerate(bad):
        assert await press(cenv, data, update_id=910 + n) == "unknown"
    assert cenv.conditions.get(OCT23).score == 2
    assert cenv.conn.execute("SELECT count(*) FROM conditions").fetchone()[0] == 1
    assert len(cenv.bot.answers) == 2 + 1 + len(bad)


async def test_condition_button_transcript_before_answer_none_when_rejected(cenv):
    order = []
    real_append = cenv.transcripts.append
    real_answer = cenv.bot.answer_callback_query

    def spy_append(*a, **kw):
        order.append(("transcript", a[4]))
        return real_append(*a, **kw)

    async def spy_answer(callback_query_id, text=None, **kw):
        order.append(("answer", text))
        return await real_answer(callback_query_id, text, **kw)

    cenv.transcripts.append = spy_append
    cenv.bot.answer_callback_query = spy_answer

    # 사용자가 아니거나 형식이 틀리거나 미래 날짜면 원문 기록 없이 답만 한 번
    assert await press(cenv, "c:2026-10-23:3", uid=99, update_id=950) == "ignored"
    assert await press(cenv, "c:2026-10-23:9", update_id=951) == "unknown"
    assert await press(cenv, "c:2026-10-25:3", update_id=952) == "unknown"
    assert order == [("answer", None), ("answer", None), ("answer", None)]

    # 기록하면 원문 기록이 먼저, 답이 그다음
    order.clear()
    assert await press(cenv, "c:2026-10-23:3", update_id=953) == "recorded"
    assert order == [("transcript", "[버튼] 컨디션 3"), ("answer", "컨디션 3 기록했어요.")]

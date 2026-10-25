"""텔레그램 사건·챕터 초안 버튼 (SP3-4 스펙 10장, 11.3, 부록 A, 문구 C2·C3). 내용은 꾸며 낸 것이다."""

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.bot.telegram_io import (
    chapter_keyboard,
    message_keyboard,
    milestone_keyboard,
)
from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.harness.dispatcher import Outbound

SAT_1300 = kst(2026, 10, 24, 13, 0)


def _rows(markup):
    return [[(b.text, b.callback_data) for b in row] for row in markup]


def _ctx(conversation_id=None):
    return RunContext(conversation_id=conversation_id, run_id=None)


def _transcript(env):
    return env.parts.transcripts.read_range(SAT_1300.date(), SAT_1300.date())


def test_milestone_buttons_layout_and_64_bytes():
    big = 2**53
    rows = _rows(milestone_keyboard([7, big], big, {7: "제주 여행", big: "아주 긴 꾸민 사건 제목이 여기에 있어요"}))
    assert rows == [
        [("✓ 저장: 제주 여행", "m:c:7"), ("✗ 빼기", "m:x:7")],
        [("✓ 저장: 아주 긴 꾸민 사건 제목이…", f"m:c:{big}"), ("✗ 빼기", f"m:x:{big}")],
        [("전부 저장", f"m:all:{big}")],
    ]
    assert all(len(d.encode()) <= 64 for row in rows for _, d in row)
    assert milestone_keyboard([], 3, {}) == []

    # 한 메시지의 줄 순서: 할 일 초안 → 사건 → 챕터 → 확인 → 컨디션
    from datetime import date

    out = Outbound(text="꾸민 답", draft_conversation_id=5, draft_task_ids=[1], draft_milestone_ids=[7],
                   draft_chapter_ids=[3], confirms=[("ct_" + "a" * 22, "내려놓기: 꾸민 일")],
                   ask_condition_for=date(2026, 10, 24))
    datas = [[b.callback_data for b in row] for row in message_keyboard(out, {}).inline_keyboard]
    assert datas == [
        ["d:c:1", "d:x:1"], ["d:all:5"], ["m:c:7", "m:x:7"], ["m:all:5"], ["h:c:3", "h:x:3"],
        ["k:a:ct_" + "a" * 22, "k:x:ct_" + "a" * 22], [f"c:2026-10-24:{n}" for n in range(1, 6)],
    ]


async def test_reply_with_milestone_draft_gets_buttons(tmp_path):
    add = ("add_milestone", {"date": "2019", "kind": "high", "title": "제주 여행"})
    async with BeEnv.start(tmp_path, start=SAT_1300, script=[FakeTurn([add], "곡선에 고점으로 남길까요?")]) as env:
        await env.telegram("예전에 처음 혼자 제주 여행 갔을 때 정말 좋았어")
        out = env.sender.sent[-1]
        mid = env.conn.execute("SELECT id FROM curve_milestones").fetchone()[0]
        cid = env.conn.execute("SELECT conversation_id FROM curve_milestones").fetchone()[0]

    assert out.text == "곡선에 고점으로 남길까요?"  # 초안에는 확인 문구가 없다
    assert out.draft_milestone_ids == [mid] and out.draft_conversation_id == cid is not None
    assert env.sender.message_ids[-1] is not None  # 버튼이 붙은 메시지(답하면 거둘 수 있게 id가 남는다)


async def test_m_all_confirms_only_this_conversation_drafts(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        a = tools.add_milestone(_ctx(11), date="2019", kind="high", title="꾸민 하나")["id"]
        b = tools.add_milestone(_ctx(11), date="2020", kind="low", title="꾸민 둘")["id"]
        other = tools.add_milestone(_ctx(12), date="2021", kind="high", title="꾸민 남의 것")["id"]
        result = await env.press("m:all:11")
        status = {i: env.parts.curve.get_milestone(i).status for i in (a, b, other)}

    assert result == "confirmed"
    assert status == {a: "confirmed", b: "confirmed", other: "draft"}
    assert env.bot.answers[-1][1] == (
        "✓ 저장: 꾸민 하나 (2019, 높은 때)\n칭호: 「꾸민 하나」의 순간\n✓ 저장: 꾸민 둘 (2020, 힘든 때)"
    )
    assert "[버튼] 저장: 꾸민 하나\n[버튼] 저장: 꾸민 둘" in _transcript(env)


async def test_stale_milestone_button_reply(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        done = tools.add_milestone(_ctx(), date="2019", kind="high", title="꾸민 하나")["id"]
        tools.confirm_milestones(_ctx(), ids=[done])
        dropped = tools.add_milestone(_ctx(), date="2020", kind="low", title="꾸민 둘")["id"]
        tools.drop_curve_drafts(_ctx(), milestone_ids=[dropped])
        before = len(env.activity())
        results = [await env.press(d) for d in (f"m:c:{done}", f"m:x:{done}", f"m:c:{dropped}", f"m:x:{dropped}",
                                                "m:all:99")]
        after = len(env.activity())

    assert results == ["stale"] * 5
    assert [t for _, t in env.bot.answers] == ["이미 정리된 사건이에요."] * 5
    assert after == before


async def test_button_reply_copy(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        tools = env.parts.tools
        keep = tools.add_milestone(_ctx(), date="2019", kind="high", title="제주 여행")["id"]
        drop = tools.add_milestone(_ctx(), date="2019", kind="high", title="제주 여행")["id"]
        r1 = await env.press(f"m:c:{keep}")
        r2 = await env.press(f"m:x:{drop}")
        gone = env.parts.curve.get_milestone(drop)
        acts = [(r["kind"], r["actor"], r["channel"]) for r in env.activity()][-2:]

    assert (r1, r2) == ("confirmed", "dropped")
    assert [t for _, t in env.bot.answers] == [
        "✓ 저장: 제주 여행 (2019, 높은 때)\n칭호: 「제주 여행」의 순간",
        "✗ 뺐어요: 제주 여행",
    ]
    assert gone is None
    assert acts == [("milestones_confirmed", "user", "telegram"), ("milestone_dropped", "user", "telegram")]
    text = _transcript(env)
    assert "[버튼] 저장: 제주 여행" in text and "[버튼] 빼기: 제주 여행" in text


async def test_chapter_buttons(tmp_path):
    assert _rows(chapter_keyboard([3], {3: "꾸민 시절"})) == [[("✓ 저장: 꾸민 시절", "h:c:3"), ("✗ 빼기", "h:x:3")]]
    propose = ("propose_chapter", {"title": "꾸민 시절", "start": "2019-03"})
    script = [FakeTurn([propose], "이 시기를 챕터로 남길까요?")]
    async with BeEnv.start(tmp_path, start=SAT_1300, script=script) as env:
        await env.telegram("2019년 봄부터 꾸민 시절이었어")
        out = env.sender.sent[-1]
        tools = env.parts.tools
        other = tools.propose_chapter(_ctx(), title="꾸민 다른 시절", start="2015-01", end="2016-12")["id"]
        (cid,) = out.draft_chapter_ids
        results = [await env.press(f"h:c:{cid}"), await env.press(f"h:x:{other}"), await env.press(f"h:c:{cid}"),
                   await env.press(f"h:x:{other}")]
        saved = env.parts.curve.get_chapter(cid)

    assert out.draft_milestone_ids == [] and out.draft_chapter_ids == [cid]
    assert results == ["confirmed", "dropped", "stale", "stale"]
    assert [t for _, t in env.bot.answers] == [
        "✓ 저장: 꾸민 시절 (2019-03~지금)", "✗ 뺐어요: 꾸민 다른 시절", "이미 정리된 챕터예요.", "이미 정리된 챕터예요.",
    ]
    assert saved is not None and saved.status == "confirmed"
    text = _transcript(env)
    assert "[버튼] 저장: 꾸민 시절" in text and "[버튼] 빼기: 꾸민 다른 시절" in text


def test_system_prompt_has_principles_9_to_11():
    text = prompts.load("system.md")
    assert "사건과 챕터는 초안으로만 냅니다" in text  # 9
    assert "추측해서 만들지 않습니다" in text
    assert "사용자가 말한 숫자만 기록합니다" in text  # 10
    assert "회복 퀘스트 하나를 제안합니다" in text  # 11
    for word in ("add_milestone", "confirm_milestones", "drop_curve_drafts", "propose_chapter"):
        assert word in text


# --- SP8 8.1, 8.7: 새 종류 이름과 영역 꼬리 ---


def test_confirmed_line_with_area():
    from my_planner.tools.confirmations import milestone_confirmed_line

    assert milestone_confirmed_line("제주 여행", "2019", "high", "quality_of_life") == (
        "✓ 저장: 제주 여행 (2019, 높은 때, 삶의 질)")
    assert milestone_confirmed_line("꾸민 결심", "2021-03", "turning_point", "career") == (
        "✓ 저장: 꾸민 결심 (2021-03, 전환점, 커리어)")


def test_confirmed_line_without_area():
    from my_planner.tools.confirmations import milestone_confirmed_line

    assert milestone_confirmed_line("꾸민 감기", "2019", "low") == "✓ 저장: 꾸민 감기 (2019, 힘든 때)"
    assert milestone_confirmed_line("꾸민 감기", "2019", "low", None) == "✓ 저장: 꾸민 감기 (2019, 힘든 때)"


async def test_button_text_unchanged(tmp_path):
    add = ("add_milestone", {"date": "2019", "kind": "high", "title": "제주 여행", "area": "quality_of_life"})
    async with BeEnv.start(tmp_path, start=SAT_1300, script=[FakeTurn([add], "곡선에 높은 때로 남길까요?")]) as env:
        await env.telegram("예전에 처음 혼자 제주 여행 갔을 때 정말 좋았어")
        out = env.sender.sent[-1]
        (mid,) = out.draft_milestone_ids
        rows = _rows(milestone_keyboard([mid], out.draft_conversation_id, {mid: "제주 여행"}))
        result = await env.press(f"m:c:{mid}")

    assert rows[0][0] == ("✓ 저장: 제주 여행", f"m:c:{mid}")  # 버튼은 `✓ 저장: {제목}` 그대로
    assert result == "confirmed"
    assert env.bot.answers[-1][1] == "✓ 저장: 제주 여행 (2019, 높은 때, 삶의 질)\n칭호: 「제주 여행」의 순간"


def test_undo_summary_strips_new_tail():
    from my_planner.tools.confirmations import undo_summary

    assert undo_summary("✓ 저장: 제주 여행 (2019, 높은 때, 삶의 질)") == "↩ 되돌림: 제주 여행 저장"
    assert undo_summary("✓ 저장: 가 (2019, 힘든 때), 나 (2020-05-02, 전환점, 관계)") == "↩ 되돌림: 가, 나 저장"
    assert undo_summary("✓ 저장: 꾸민 (2019, 쉬운 때)") == "↩ 되돌림: 꾸민 (2019, 쉬운 때) 저장"  # 모르는 꼬리는 그대로

"""텔레그램 습관 버튼: 저녁 체크인 습관 줄, `hb:` 토글과 다시 그리기, `/habits` (SP7 스펙 5.7, 5.8, 부록 A).

가짜 두뇌 + 가짜 시계(`BeEnv`)와 가짜 텔레그램 봇. 날짜는 2026-10-24(토) 저녁 체크인 18:00(답장 창은 10/25 04:00까지).
내용은 모두 꾸며 낸 것이다.
"""

from datetime import date, timedelta

from be_env import BeEnv
from fakes import FakeTurn
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, NetworkError
from test_dispatcher_messages import kst
from test_telegram_drafts import OWNER, FakeBot
from ui_stream import parse_sse

from my_planner.bot.telegram_io import (
    TelegramSender,
    condition_keyboard,
    habit_keyboard,
    message_keyboard,
)
from my_planner.harness.dispatcher import Outbound
from my_planner.harness.review_steps import LADDER_STEP1
from my_planner.status.xp import XP_CHECKIN_REPLY

SAT = date(2026, 10, 24)
SAT_EVENING = kst(2026, 10, 24, 18, 0) + timedelta(seconds=30)
SUN_1129 = kst(2026, 11, 29, 18, 0) + timedelta(seconds=30)  # 11월 마지막 일요일: 월말 회고 + 저녁 체크인
RUN_TEXT = "꾸민 회차 본문"
PAUSED = "쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요."


def habit(env, title, *, kind="daily", target=None, status="active"):
    h = env.parts.habits.add(title, "health", kind, target, env.clock.now())
    if status != "active":
        h = env.parts.habits.set_status(h.id, status, env.clock.now())
    return h


def run_row(env, loop="evening_checkin"):
    return env.conn.execute("SELECT * FROM runs WHERE loop = ? ORDER BY id DESC", (loop,)).fetchone()


def _rows(markup):
    rows = markup.inline_keyboard if isinstance(markup, InlineKeyboardMarkup) else markup
    return [[(b.text, b.callback_data) for b in row] for row in rows]


def _habit_markup(env, day=SAT, *, condition=True):
    """그 메시지에 붙은 버튼: 지금 DB 상태의 습관 줄 + 컨디션 줄."""
    h = env.parts.habits
    rows = habit_keyboard(h.list(), h.checked_on(day), day)
    return InlineKeyboardMarkup([*rows, *(condition_keyboard(day) if condition else [])])


def _evening(tmp_path, script=(), at=SAT_EVENING):
    return BeEnv.start(tmp_path, start=at, script=[FakeTurn([], RUN_TEXT), *script])


async def _sent_evening(env):
    """저녁 체크인을 보낸다. (회차 행, 버튼이 붙은 메시지 id)."""
    await env.tick()
    run = run_row(env)
    return run, env.parts.deliveries.telegram_message_id(run["id"])


def _ledger(env):
    return [
        (r["source_kind"], r["amount"])
        for r in env.conn.execute("SELECT source_kind, amount FROM status_xp_ledger ORDER BY id").fetchall()
    ]


# --- 슬라이스 1: 회차 메시지의 습관 줄 ---


async def test_evening_checkin_has_habit_rows_before_condition(tmp_path):
    async with _evening(tmp_path) as env:
        water = habit(env, "물 마시기")
        run_h = habit(env, "운동", kind="weekly", target=3)
        env.parts.habits.check(run_h.id, SAT, env.clock.now())
        await env.tick()
        (out,) = env.sender.sent
        bot = FakeBot()
        sender = TelegramSender(bot, OWNER, tasks=env.parts.tasks, habits=env.parts.habits)
        await sender.send(out)
        # 확인 줄 다음, 컨디션 줄 앞(초안 줄은 맨 앞)
        await sender.send(Outbound(text="꾸민 답", draft_task_ids=[3], confirms=[("ct_" + "a" * 22, "내려놓기: 산책")],
                                   ask_condition_for=SAT, habit_date=SAT))

    assert out.habit_date == SAT and out.ask_condition_for == SAT
    habit_rows = [[("☐ 물 마시기", f"hb:{water.id}:2026-10-24"), ("✓ 운동", f"hb:{run_h.id}:2026-10-24")]]
    condition = [[(str(n), f"c:2026-10-24:{n}") for n in range(1, 6)]]
    assert _rows(bot.sent[0][1]) == habit_rows + condition
    rows = _rows(bot.sent[1][1])
    assert [r[0][1] for r in rows] == ["d:c:3", "k:a:ct_" + "a" * 22, f"hb:{water.id}:2026-10-24", "c:2026-10-24:1"]


async def test_month_end_review_merged_habit_rows_before_ladder(tmp_path):
    async with BeEnv.start(tmp_path, start=SUN_1129, script=[FakeTurn([], RUN_TEXT)]) as env:
        water = habit(env, "물 마시기")
        # 컨디션을 먼저 적었다: 회고 메시지에 컨디션 줄 대신 사다리 1단계(11.1-1 (c))
        await env.action("record_condition", {"score": 4, "date": "2026-11-29"})
        await env.tick()
        (out,) = env.sender.sent
        markup = message_keyboard(out, {}, habits=env.parts.habits.list(), checked=set())

    assert out.text == f"{RUN_TEXT}\n\n{LADDER_STEP1}"
    assert out.ask_condition_for is None and out.ladder == ("2026-11", "n")
    assert out.habit_date == date(2026, 11, 29)  # 사다리 때문에 컨디션 날짜를 지우기 전의 값
    datas = [d for row in _rows(markup) for _, d in row]
    assert datas[0] == f"hb:{water.id}:2026-11-29"
    assert datas[1:] == [f"l:2026-11:n:{n}" for n in range(11)]


async def test_no_habits_no_rows(tmp_path):
    async with _evening(tmp_path) as env:
        habit(env, "쉬는 습관", status="paused")
        habit(env, "그만둔 습관", status="archived")
        await env.tick()
        (out,) = env.sender.sent

    assert out.habit_date is None
    assert out.ask_condition_for == SAT
    # 날짜가 있어도 활성 습관이 없으면 줄이 없다
    assert message_keyboard(Outbound(text="꾸민 답", habit_date=SAT), {}, habits=[], checked=set()) is None


async def test_morning_brief_has_no_habit_rows(tmp_path):
    async with BeEnv.start(
        tmp_path, start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), script=[FakeTurn([], "좋은 아침이에요")]
    ) as env:
        habit(env, "물 마시기")
        await env.tick()
        (out,) = env.sender.sent

    assert out.ask_condition_for == date(2026, 10, 25)  # 어제 컨디션은 묻는다
    assert out.habit_date is None


async def test_resend_keeps_habit_rows(tmp_path):
    async with _evening(tmp_path) as env:
        habit(env, "물 마시기")
        # 바로 3회가 모두 안 되면 5분 뒤 전송만 한 번 더(SP1 5.4-2)
        real_send, fails = env.sender.send, [3]

        async def flaky(out):
            if fails[0] > 0:
                fails[0] -= 1
                raise ConnectionError("fake send failure")
            return await real_send(out)

        env.sender.send = flaky
        await env.tick()
        for _ in range(50):
            if env.sender.sent:
                break
            await env.drain()
        later = list(env.sender.sent)
        run_id = run_row(env)["id"]
        # 시작 때 복구(전송만 한 번 더)에도
        env.conn.execute("UPDATE runs SET status = 'failed', resent = 0 WHERE id = ?", (run_id,))
        env.conn.commit()
        env.parts.dispatcher.submit_resend(env.parts.runs.get(run_id))
        await env.drain()
        on_start = env.sender.sent[-1]

    assert [o.habit_date for o in later] == [SAT]
    assert on_start.habit_date == SAT and len(env.sender.sent) == 2


# --- 슬라이스 2: 버튼 모양 ---


def test_button_layout_two_per_row_and_64_bytes():
    from my_planner.store.repos.habits import Habit

    now = kst(2026, 10, 24, 18, 0)

    def h(i, title):
        return Habit(i, title, "health", "daily", None, "active", i, now, now)  # type: ignore[arg-type]

    habits = [h(1, "물 마시기"), h(2, "운동"), h(3, "스트레칭"), h(10**9, "명상")]
    rows = _rows(habit_keyboard(habits, {2, 10**9}, SAT))

    assert rows == [
        [("☐ 물 마시기", "hb:1:2026-10-24"), ("✓ 운동", "hb:2:2026-10-24")],
        [("☐ 스트레칭", "hb:3:2026-10-24"), ("✓ 명상", f"hb:{10**9}:2026-10-24")],
    ]
    assert all(len(d.encode()) <= 64 for row in rows for _, d in row)
    assert _rows(habit_keyboard(habits[:3], set(), SAT))[1] == [("☐ 스트레칭", "hb:3:2026-10-24")]
    assert habit_keyboard([], set(), SAT) == []


def test_button_label_truncates_by_codepoint():
    from my_planner.store.repos.habits import Habit

    now = kst(2026, 10, 24, 18, 0)

    def label(title):
        h = Habit(1, title, "health", "daily", None, "active", 1, now, now)  # type: ignore[arg-type]
        return habit_keyboard([h], set(), SAT)[0][0].text

    ten = "가나다라마바사아자차"
    assert label(ten) == f"☐ {ten}"  # 10자는 그대로
    assert label(ten + "카") == "☐ 가나다라마바사아자…"  # 넘으면 9자 + …
    # 이모지가 든 40자 제목도 코드포인트로 센다(UTF-16, 바이트가 아니다)
    emoji = "💧🏃🧘 물 마시기와 아침 달리기, 저녁 명상까지 하루에 다 챙기는 긴 습관 제목"
    assert label(emoji) == "☐ " + emoji[:9] + "…"
    assert len(label(emoji)) == 2 + 10


# --- 슬라이스 3: 누름, 토글, 다시 그리기, 답 ---


async def test_press_toggles_and_redraws_all_habit_buttons(tmp_path):
    async with _evening(tmp_path) as env:
        water, run_h, walk = habit(env, "물 마시기"), habit(env, "운동"), habit(env, "산책")
        env.parts.habits.check(run_h.id, SAT, env.clock.now())  # 다른 통로에서 먼저 체크한 습관
        stale = InlineKeyboardMarkup([*habit_keyboard(env.parts.habits.list(), set(), SAT), *condition_keyboard(SAT)])
        env.clock.set(kst(2026, 10, 24, 19, 0))
        r1 = await env.press(f"hb:{water.id}:2026-10-24", message_id=777, reply_markup=stale)
        checked1 = env.parts.habits.checked_on(SAT)
        r2 = await env.press(f"hb:{water.id}:2026-10-24", message_id=777, reply_markup=stale)
        checked2 = env.parts.habits.checked_on(SAT)

    assert (r1, r2) == ("recorded", "recorded")
    assert checked1 == {water.id, run_h.id} and checked2 == {run_h.id}
    assert [a for _, a in env.bot.answers] == ["✓ 습관: 물 마시기", "↩ 습관 체크 취소: 물 마시기"]
    (mid1, m1), (mid2, m2) = env.bot.edits
    assert mid1 == mid2 == 777
    condition = [[(str(n), f"c:2026-10-24:{n}") for n in range(1, 6)]]
    assert _rows(m1) == [
        [("✓ 물 마시기", f"hb:{water.id}:2026-10-24"), ("✓ 운동", f"hb:{run_h.id}:2026-10-24")],
        [("☐ 산책", f"hb:{walk.id}:2026-10-24")],
        *condition,  # 다른 버튼은 그대로
    ]
    assert _rows(m2)[0] == [("☐ 물 마시기", f"hb:{water.id}:2026-10-24"), ("✓ 운동", f"hb:{run_h.id}:2026-10-24")]


async def test_button_after_app_check_on_telegram_answered_run_unchecks_and_redraws_from_db(tmp_path):
    """Review Focus 2: 텔레그램으로 먼저 답한 저녁 체크인에서, 앱 체크 직후 같은 습관의 텔레그램 버튼은 취소가 된다."""
    async with _evening(tmp_path) as env:
        water, run_h = habit(env, "물 마시기"), habit(env, "운동")
        _, mid = await _sent_evening(env)
        shown = _habit_markup(env)  # 보낼 때의 버튼(둘 다 ☐)
        env.clock.set(kst(2026, 10, 24, 19, 0))
        await env.press(f"hb:{run_h.id}:2026-10-24", message_id=mid, reply_markup=shown)
        answered = run_row(env)
        status, _ = await env.action("check_habit", {"id": water.id})  # 앱에서 체크(회차는 이미 답했다)
        await env.drain()
        result = await env.press(f"hb:{water.id}:2026-10-24", message_id=mid, reply_markup=shown)
        checked = env.parts.habits.checked_on(SAT)

    assert answered["answered_via"] == "telegram" and status == 200
    assert env.sender.cleared == []  # 텔레그램으로 먼저 답했으니 버튼은 그대로
    assert result == "recorded"
    assert checked == {run_h.id}  # 누르기 전 DB 상태(체크됨)로 판단해 취소
    assert env.bot.answers[-1][1] == "↩ 습관 체크 취소: 물 마시기"
    assert _rows(env.bot.edits[-1][1])[0] == [
        ("☐ 물 마시기", f"hb:{water.id}:2026-10-24"), ("✓ 운동", f"hb:{run_h.id}:2026-10-24"),
    ]


async def test_habits_command_message_always_redraws(tmp_path):
    async with _evening(tmp_path) as env:
        water = habit(env, "물 마시기")
        await _sent_evening(env)
        env.clock.set(kst(2026, 10, 24, 19, 0))
        await env.action("record_condition", {"score": 4, "date": "2026-10-24"})  # 앱에서 먼저 답했다
        await env.drain()
        answered = run_row(env)
        # 회차 메시지가 아닌 `/habits` 답의 버튼
        assert await env.press(f"hb:{water.id}:2026-10-24", message_id=555, reply_markup=_habit_markup(env)) == (
            "recorded"
        )

    assert answered["answered_via"] == "app"
    assert [(m, _rows(k)[0]) for m, k in env.bot.edits] == [(555, [("✓ 물 마시기", f"hb:{water.id}:2026-10-24")])]


async def test_not_modified_ignored(tmp_path, caplog):
    async with _evening(tmp_path) as env:
        water = habit(env, "물 마시기")
        env.bot.edit_error = BadRequest("Message is not modified: specified new message content and reply markup "
                                        "are exactly the same")
        r1 = await env.press(f"hb:{water.id}:2026-10-24", message_id=555, reply_markup=_habit_markup(env))
        not_modified = [r for r in caplog.records if r.levelname == "WARNING"]
        env.bot.edit_error = NetworkError("꾸민 네트워크 오류")
        r2 = await env.press(f"hb:{water.id}:2026-10-24", message_id=555, reply_markup=_habit_markup(env))
        failed = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]

    assert (r1, r2) == ("recorded", "recorded")
    assert [a for _, a in env.bot.answers] == ["✓ 습관: 물 마시기", "↩ 습관 체크 취소: 물 마시기"]
    assert not_modified == []  # 같은 모양: 잡고 넘어간다
    assert failed == ["habit_redraw_failed"]  # 다른 오류는 종류만 남긴다(바꾼 것은 이미 커밋됐다)


async def test_no_redraw_after_app_answer(tmp_path):
    async with _evening(tmp_path) as env:
        water = habit(env, "물 마시기")
        _, mid = await _sent_evening(env)
        shown = _habit_markup(env)
        env.clock.set(kst(2026, 10, 24, 19, 0))
        await env.action("record_condition", {"score": 4, "date": "2026-10-24"})  # 앱에서 먼저 답: 버튼을 거둔다
        await env.drain()
        result = await env.press(f"hb:{water.id}:2026-10-24", message_id=mid, reply_markup=shown)
        checked = env.parts.habits.checked_on(SAT)
        after = run_row(env)

    assert env.sender.cleared == [mid]
    assert result == "recorded" and checked == {water.id}  # 누름은 지금 상태로 토글된다
    assert env.bot.answers[-1][1] == "✓ 습관: 물 마시기"
    assert env.bot.edits == []  # 거둔 버튼을 다시 그리지 않는다
    assert after["answered_via"] == "app"


async def test_press_marks_run_answered_and_xp_x3(tmp_path):
    async with _evening(tmp_path) as env:
        water, run_h = habit(env, "물 마시기"), habit(env, "운동")
        _, mid = await _sent_evening(env)
        env.clock.set(kst(2026, 10, 24, 19, 0))
        # `/habits` 답의 버튼은 답장 창 안 저녁 체크인 날짜여도 회차의 답이 아니다
        await env.press(f"hb:{water.id}:2026-10-24", message_id=555, reply_markup=_habit_markup(env))
        before = run_row(env)
        ledger_before = _ledger(env)
        await env.press(f"hb:{run_h.id}:2026-10-24", message_id=mid, reply_markup=_habit_markup(env))
        after = run_row(env)
        ledger_after = _ledger(env)

    assert before["answered_at"] is None
    assert ledger_before == [("habit_check", 3)]
    assert after["answered_via"] == "telegram"
    assert ledger_after == [("habit_check", 3), ("habit_check", 3), ("checkin_reply", XP_CHECKIN_REPLY)]  # X3
    assert env.sender.cleared == []


# --- 슬라이스 4: 지난 버튼, 다른 콜백 ---


async def test_paused_habit_old_button_reply(tmp_path):
    async with _evening(tmp_path) as env:
        h = habit(env, "물 마시기", status="paused")
        result = await env.press(f"hb:{h.id}:2026-10-24", message_id=555, reply_markup=_habit_markup(env))
        checks = env.conn.execute("SELECT COUNT(*) FROM habit_checks").fetchone()[0]

    assert result == "stale"
    assert env.bot.answers[-1][1] == PAUSED
    assert checks == 0 and env.bot.edits == []


async def test_deleted_habit_old_button_reply(tmp_path):
    async with _evening(tmp_path) as env:
        h = habit(env, "물 마시기")
        env.parts.habits.soft_delete(h.id, env.clock.now())
        result = await env.press(f"hb:{h.id}:2026-10-24", message_id=555)
        checks = env.conn.execute("SELECT COUNT(*) FROM habit_checks").fetchone()[0]

    assert result == "stale"
    assert env.bot.answers[-1][1] == "없는 습관이에요."
    assert checks == 0 and env.bot.edits == []


def test_h_chapter_callbacks_still_parse():
    from my_planner.bot.callbacks import _parse_curve, _parse_habit

    assert _parse_habit("h:c:3") is None
    assert _parse_curve("h:c:3") == ("h", "c", 3)
    assert _parse_habit("hb:3:2026-10-24") == (3, SAT)
    assert _parse_curve("hb:3:2026-10-24") is None
    for bad in ("hb:3", "hb:x:2026-10-24", "hb:3:20261024", "hb:3:2026-13-01", "hb:3:2026-W43-6",
                "hb::2026-10-24", "hb:3:2026-10-24:1", "hb:-3:2026-10-24", None, ""):
        assert _parse_habit(bad) is None, bad


def test_redraw_keeps_other_buttons():
    from my_planner.bot.callbacks import redraw_habit_buttons

    rows = InlineKeyboardMarkup([
        *condition_keyboard(SAT),
        *habit_keyboard([], set(), SAT),
    ])
    assert redraw_habit_buttons(rows, {1}).to_dict() == rows.to_dict()


# --- 슬라이스 5: /habits, 원문 기록 ---


async def test_habits_command_text_and_buttons(tmp_path):
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0)) as env:
        run_h = habit(env, "운동", kind="weekly", target=3)
        water = habit(env, "물 마시기")
        habit(env, "쉬는 습관", status="paused")
        for d in ("2026-10-20", "2026-10-22", "2026-10-18"):  # 10/18은 전 주
            env.parts.habits.check(run_h.id, date.fromisoformat(d), env.clock.now())
        env.parts.habits.check(water.id, SAT, env.clock.now())
        assert await env.telegram("/habits") == "command"
        text, markup = env.bot.sent[-1][1], env.bot.markups[-1]
        day = (env.settings.paths.data_dir / "transcripts" / "2026" / "10" / "2026-10-24.md").read_text("utf-8")

    assert text == "오늘 습관 (10/24 토)\n- 운동 · 이번 주 2번 / 목표 3번\n- 물 마시기"
    assert _rows(markup) == [[("☐ 운동", f"hb:{run_h.id}:2026-10-24"), ("✓ 물 마시기", f"hb:{water.id}:2026-10-24")]]
    assert env.brain.calls == []  # 두뇌를 거치지 않는다
    assert "/habits" in day and "오늘 습관 (10/24 토)" in day


async def test_habits_command_empty_copy(tmp_path):
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0)) as env:
        habit(env, "쉬는 습관", status="paused")
        await env.telegram("/habits")

    assert env.bot.sent[-1][1] == "아직 습관이 없어요. '매일 물 마시기 습관 추가해 줘'처럼 말하면 만들어 드려요."
    assert env.bot.markups[-1] is None


async def test_app_chat_habits_command_text_only(tmp_path):
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0)) as env:
        water = habit(env, "물 마시기")
        _, raw = await env.chat("/habits")

    chunks = parse_sse(raw)
    text = "".join(c["delta"] for c in chunks if c["type"] == "text-delta")
    assert text == "오늘 습관 (10/24 토)\n- 물 마시기"
    assert f"hb:{water.id}" not in raw.decode()
    assert not [c for c in chunks if c["type"].startswith("data-") and "habit" in str(c)]


async def test_transcript_button_lines(tmp_path):
    async with _evening(tmp_path) as env:
        water = habit(env, "물 마시기")
        env.clock.set(kst(2026, 10, 24, 19, 0))
        await env.press(f"hb:{water.id}:2026-10-24", message_id=555, reply_markup=_habit_markup(env))
        await env.press(f"hb:{water.id}:2026-10-24", message_id=555, reply_markup=_habit_markup(env))
        day = (env.settings.paths.data_dir / "transcripts" / "2026" / "10" / "2026-10-24.md").read_text("utf-8")

    assert "### 19:00 사용자 [-]\n\n[버튼] 습관 체크 물 마시기\n" in day
    assert "### 19:00 사용자 [-]\n\n[버튼] 습관 체크 취소 물 마시기\n" in day

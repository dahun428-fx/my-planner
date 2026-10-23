"""텔레그램 어댑터: 초안 버튼과 버튼 누름 (스펙 5.7). 네트워크 없이 Update.de_json으로 만든 가짜 업데이트."""

from datetime import time

import pytest
from test_dispatcher_messages import kst

from my_planner.bot.telegram_io import TelegramSender
from my_planner.clock import FakeClock
from my_planner.domain import RunContext
from my_planner.harness.dispatcher import Outbound
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools

OWNER = 42
TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
NOW = kst(2026, 10, 24, 10, 30)


class FakeBot:
    def __init__(self):
        self.sent = []  # (text, reply_markup)
        self.answers = []  # (callback_query_id, text)

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))

    async def answer_callback_query(self, callback_query_id, text=None, **kw):
        self.answers.append((callback_query_id, text))
        return True


class DraftEnv:
    def __init__(self, tmp_path, conn, state):
        self.clock = FakeClock(NOW)
        self.state = state
        self.conn = conn
        self.repo = TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY)
        self.transcripts = TranscriptStore(tmp_path / "data", TZ, BOUNDARY)
        self.tools = Tools(
            tasks=self.repo,
            transcripts=self.transcripts,
            export_path=tmp_path / "data" / "exports" / "tasks.md",
            clock=self.clock,
            tz=TZ,
            boundary=BOUNDARY,
        )
        self.bot = FakeBot()
        self.tmp = tmp_path

    def propose(self, *titles, conv=7):
        out = self.tools.propose_tasks(
            RunContext(conversation_id=conv, run_id=None), tasks=[{"title": t, "areas": ["career"]} for t in titles]
        )
        return [t["id"] for t in out["proposed"]]


@pytest.fixture
def denv(tmp_path, conn, state):
    return DraftEnv(tmp_path, conn, state)


def _rows(markup):
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


async def test_draft_buttons_layout(denv):
    a, b = denv.propose("보고서 목차 쓰기", "자료 모으기")
    sender = TelegramSender(denv.bot, OWNER, tasks=denv.repo)

    await sender.send(Outbound(text="이렇게 해 볼까요?", draft_conversation_id=7, draft_task_ids=[a, b]))

    assert len(denv.bot.sent) == 1
    text, markup = denv.bot.sent[0]
    assert text == "이렇게 해 볼까요?"
    assert _rows(markup) == [
        [("✓ 추가: 보고서 목차 쓰기", f"d:c:{a}"), ("✗ 빼기", f"d:x:{a}")],
        [("✓ 추가: 자료 모으기", f"d:c:{b}"), ("✗ 빼기", f"d:x:{b}")],
        [("전부 추가", "d:all:7")],
    ]
    # 초안이 없으면 버튼도 없다
    await sender.send(Outbound(text="안녕하세요."))
    assert denv.bot.sent[1] == ("안녕하세요.", None)


async def test_buttons_only_on_last_chunk(denv):
    (a,) = denv.propose("산책")
    sender = TelegramSender(denv.bot, OWNER, tasks=denv.repo)
    long_text = "\n\n".join(["가" * 3000, "나" * 3000, "다" * 3000])

    await sender.send(Outbound(text=long_text, draft_conversation_id=7, draft_task_ids=[a]))

    assert len(denv.bot.sent) == 3
    assert "".join(t for t, _ in denv.bot.sent) == long_text
    assert [m is None for _, m in denv.bot.sent] == [True, True, False]
    assert _rows(denv.bot.sent[-1][1])[0][0] == ("✓ 추가: 산책", f"d:c:{a}")


def _user(uid=OWNER):
    return {"id": uid, "is_bot": False, "first_name": "다훈"}


def _callback(bot, data, *, uid=OWNER, update_id=500):
    from telegram import Update

    return Update.de_json(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"cb{update_id}",
                "from": _user(uid),
                "chat_instance": "ci",
                "data": data,
                "message": {
                    "message_id": 9,
                    "date": 1792737000,
                    "chat": {"id": OWNER, "type": "private"},
                    "from": {"id": 1, "is_bot": True, "first_name": "비서"},
                    "text": "이렇게 해 볼까요?",
                },
            },
        },
        bot,
    )


async def press(denv, data, **kw):
    from my_planner.bot.callbacks import handle_callback

    upd = _callback(denv.bot, data, **kw)
    return await handle_callback(
        upd.callback_query, OWNER, denv.tools, transcripts=denv.transcripts, clock=denv.clock
    )


async def test_draft_all_callback_fits_64_bytes_and_confirms_conversation_drafts(denv):
    from my_planner.bot.telegram_io import draft_keyboard
    from my_planner.domain import TaskStatus

    big = 2**63 - 1  # SQLite INTEGER 최댓값
    markup = draft_keyboard([big], big, {big: "가" * 200})
    assert all(len(b.callback_data.encode()) <= 64 for row in markup.inline_keyboard for b in row)

    a, b, gone = denv.propose("목차 쓰기", "자료 모으기", "뺀 것", conv=7)
    (other,) = denv.propose("다른 대화의 초안", conv=8)
    denv.tools.drop_task(RunContext(None, None), id=gone)

    assert await press(denv, "d:all:7") == "confirmed"

    st = {i: denv.repo.get(i).status for i in (a, b, gone, other)}
    assert st == {a: TaskStatus.open, b: TaskStatus.open, gone: TaskStatus.dropped, other: TaskStatus.draft}
    assert len(denv.bot.answers) == 1
    # 다시 누르면 남은 초안이 없다
    assert await press(denv, "d:all:7", update_id=501) == "stale"
    assert denv.bot.answers[-1][1] == "이미 정리된 할 일이에요."


async def test_stale_draft_button(denv):
    from my_planner.domain import TaskStatus

    a, b = denv.propose("목차 쓰기", "자료 모으기")
    denv.tools.confirm_tasks(RunContext(None, None), ids=[a])  # 글로 이미 확정했다
    denv.repo.expire_drafts(denv.clock.now().replace(year=2027))  # b는 만료돼 빠졌다
    before = denv.conn.execute("SELECT count(*) FROM task_events").fetchone()[0]

    for n, data in enumerate((f"d:c:{a}", f"d:x:{a}", f"d:c:{b}", f"d:x:{b}", "d:c:999")):
        assert await press(denv, data, update_id=600 + n) == "stale"

    assert denv.bot.answers == [(f"cb{600 + n}", "이미 정리된 할 일이에요.") for n in range(5)]
    assert denv.repo.get(a).status is TaskStatus.open
    assert denv.repo.get(b).status is TaskStatus.dropped
    assert denv.conn.execute("SELECT count(*) FROM task_events").fetchone()[0] == before


async def test_callback_from_other_user_ignored(denv):
    from my_planner.domain import TaskStatus

    (a,) = denv.propose("목차 쓰기")
    for n, data in enumerate((f"d:c:{a}", f"d:x:{a}", "d:all:7")):
        assert await press(denv, data, uid=99, update_id=700 + n) == "ignored"

    assert denv.repo.get(a).status is TaskStatus.draft
    assert denv.bot.answers == [(f"cb{700 + n}", None) for n in range(3)]  # 조용히 답만 한다
    assert not (denv.tmp / "data" / "transcripts").exists()


async def test_button_logged_to_transcript(denv):
    from my_planner.domain import TaskStatus

    a, b, c = denv.propose("목차 쓰기", "자료 모으기", "산책")
    (d,) = denv.propose("물 마시기", conv=8)

    assert await press(denv, f"d:c:{a}", update_id=801) == "confirmed"
    assert await press(denv, f"d:x:{b}", update_id=802) == "dropped"
    assert await press(denv, "d:all:7", update_id=803) == "confirmed"
    assert await press(denv, f"d:c:{a}", update_id=804) == "stale"  # 바뀐 것이 없으니 기록도 없다

    assert [denv.repo.get(i).status for i in (a, b, c, d)] == [
        TaskStatus.open, TaskStatus.dropped, TaskStatus.open, TaskStatus.draft,
    ]
    assert [t for _, t in denv.bot.answers] == [
        "✓ 확정: 목차 쓰기", "✓ 내려놓음: 자료 모으기", "✓ 확정: 산책", "이미 정리된 할 일이에요.",
    ]
    day = (denv.tmp / "data" / "transcripts" / "2026" / "10" / "2026-10-24.md").read_text(encoding="utf-8")
    assert day == (
        "### 10:30 사용자 [-]\n\n[버튼] 확정: 목차 쓰기\n\n"
        "### 10:30 사용자 [-]\n\n[버튼] 빼기: 자료 모으기\n\n"
        "### 10:30 사용자 [-]\n\n[버튼] 확정: 산책\n\n"
    )


async def test_callback_update_routed_once_and_marked_done(denv):
    import functools

    from test_telegram_io import _NoDispatch

    from my_planner.bot.callbacks import handle_callback
    from my_planner.bot.telegram_io import handle_update
    from my_planner.domain import TaskStatus

    (a,) = denv.propose("목차 쓰기")
    callbacks = functools.partial(
        handle_callback, owner_id=OWNER, tools=denv.tools, transcripts=denv.transcripts, clock=denv.clock
    )
    dispatcher = _NoDispatch()

    async def deliver(upd):
        return await handle_update(
            upd, bot=denv.bot, owner_id=OWNER, state=denv.state, dispatcher=dispatcher,
            transcripts=denv.transcripts, clock=denv.clock, tools=denv.tools, callbacks=callbacks,
        )

    upd = _callback(denv.bot, f"d:c:{a}", update_id=900)
    assert await deliver(upd) == "callback"
    assert denv.state.is_seen_update(900)
    assert denv.repo.get(a).status is TaskStatus.open
    assert await deliver(upd) == "duplicate"  # 같은 update_id는 다시 처리하지 않는다
    assert len(denv.bot.answers) == 1 and dispatcher.got == []


async def test_today_hides_drafts(denv):
    from test_telegram_io import _NoDispatch, _update

    from my_planner.bot.telegram_io import handle_update

    denv.tools.add_task(RunContext(None, None), title="열린 일", areas=["career"], planned_for="2026-10-24")
    denv.tools.propose_tasks(
        RunContext(7, None),
        tasks=[{"title": "제안한 초안", "areas": ["career"], "planned_for": "2026-10-24"},
               {"title": "시각 있는 초안", "areas": ["career"], "scheduled_at": "2026-10-24T15:00"}],
    )

    await handle_update(
        _update(update_id=950, text="/today"), bot=denv.bot, owner_id=OWNER, state=denv.state,
        dispatcher=_NoDispatch(), transcripts=denv.transcripts, clock=denv.clock, tools=denv.tools,
    )
    text = denv.bot.sent[-1][0]
    assert "열린 일" in text
    assert "초안" not in text

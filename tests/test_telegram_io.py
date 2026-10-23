from telegram import Update

from my_planner.bot.telegram_io import accept_update

OWNER = 42
DATE = 1792737000  # 2026-10-23 06:30 UTC


def _user(uid=OWNER):
    return {"id": uid, "is_bot": False, "first_name": "다훈", "username": "dahun"}


def _message(*, uid=OWNER, chat_type="private", chat_id=None, **content):
    msg = {
        "message_id": 1,
        "date": DATE,
        "chat": {"id": chat_id if chat_id is not None else uid, "type": chat_type},
        "from": _user(uid),
    }
    msg.update(content)
    return msg


def _update(update_id=7, *, edited=False, bot=None, **kw):
    key = "edited_message" if edited else "message"
    msg = _message(**kw)
    if edited:
        msg["edit_date"] = DATE + 60
    return Update.de_json({"update_id": update_id, key: msg}, bot)


def test_accept_owner_private_text(state):
    assert accept_update(_update(text="안녕"), OWNER, state) == "accept"


def test_ignore_other_user(state):
    assert accept_update(_update(uid=99, text="안녕"), OWNER, state) == "ignore"


def test_ignore_group_chat_from_owner(state):
    assert accept_update(_update(chat_type="group", chat_id=-100123, text="안녕"), OWNER, state) == "ignore"
    assert (
        accept_update(_update(chat_type="supergroup", chat_id=-100124, text="안녕"), OWNER, state) == "ignore"
    )


def test_edited_message_ignored(state):
    assert accept_update(_update(edited=True, text="고친 글"), OWNER, state) == "ignore"


def _log_lines(state_dir):
    import json
    import logging

    for h in logging.getLogger().handlers:
        h.flush()
    path = state_dir / "logs" / "my-planner.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_ignored_update_logs_sender_id_only(state, tmp_path):
    from my_planner.logging_setup import setup_logging

    state_dir = tmp_path / "state"
    setup_logging(state_dir, 30)
    body = "남의 비밀 본문 문장"
    assert accept_update(_update(uid=99, text=body), OWNER, state) == "ignore"

    lines = [e for e in _log_lines(state_dir) if e.get("msg") == "update_ignored"]
    assert len(lines) == 1
    assert lines[0]["from_id"] == 99
    text = (state_dir / "logs" / "my-planner.jsonl").read_text(encoding="utf-8")
    assert body not in text
    assert "다훈" not in text and "dahun" not in text


def test_duplicate_update_id_ignored(state):
    upd = _update(update_id=7, text="안녕")
    assert accept_update(upd, OWNER, state) == "accept"
    state.mark_updates_done([7])
    assert accept_update(upd, OWNER, state) == "duplicate"
    assert accept_update(_update(update_id=8, text="안녕"), OWNER, state) == "accept"


PHOTO = [{"file_id": "p1", "file_unique_id": "u1", "width": 10, "height": 10}]


class _RecordingBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


class _NoDispatch:
    def __init__(self):
        self.got = []

    def submit_message(self, m):
        self.got.append(m)


async def test_non_text_message_gets_polite_reply(state, tmp_path):
    from datetime import UTC, datetime, time

    from my_planner.bot.telegram_io import NON_TEXT_REPLY, handle_update
    from my_planner.clock import FakeClock
    from my_planner.store.transcripts import TranscriptStore

    assert NON_TEXT_REPLY == "지금은 글로만 이야기할 수 있어요."
    bot, dispatcher = _RecordingBot(), _NoDispatch()
    transcripts = TranscriptStore(tmp_path / "data", "Asia/Seoul", time(4))
    clock = FakeClock(datetime(2026, 10, 23, 6, 30, tzinfo=UTC))  # KST 15:30

    updates = [
        _update(update_id=11, photo=PHOTO),
        _update(update_id=12, photo=PHOTO, caption="이거 봐 주세요"),
        _update(update_id=13, voice={"file_id": "v1", "file_unique_id": "v2", "duration": 3}),
    ]
    for upd in updates:
        assert accept_update(upd, OWNER, state) == "non_text"
        verdict = await handle_update(
            upd,
            bot=bot,
            owner_id=OWNER,
            state=state,
            dispatcher=dispatcher,
            transcripts=transcripts,
            clock=clock,
        )
        assert verdict == "non_text"
        assert state.is_seen_update(upd.update_id)

    assert bot.sent == [(OWNER, NON_TEXT_REPLY)] * 3
    assert dispatcher.got == []
    day = (tmp_path / "data" / "transcripts" / "2026" / "10" / "2026-10-23.md").read_text(encoding="utf-8")
    assert "### 15:30 비서 [-]" in day and NON_TEXT_REPLY in day
    assert "이거 봐 주세요" not in day

    # 다른 사람이 보낸 글: 답하지 않고 처리 완료로만 기록
    other = _update(update_id=14, uid=99, text="안녕")
    assert (
        await handle_update(
            other,
            bot=bot,
            owner_id=OWNER,
            state=state,
            dispatcher=dispatcher,
            transcripts=transcripts,
            clock=clock,
        )
        == "ignore"
    )
    assert len(bot.sent) == 3 and state.is_seen_update(14)


def test_split_long_reply():
    from my_planner.bot.telegram_io import split_message

    text = "가" * 9000
    parts = split_message(text)
    assert len(parts) == 3
    assert all(len(p) <= 4096 for p in parts)
    assert "".join(parts) == text

    # 문단 경계(빈 줄)가 먼저, 그다음 줄바꿈에서 자른다
    paragraphs = "\n\n".join(["나" * 3000, "다" * 3000, "라" * 2900])
    parts = split_message(paragraphs)
    assert "".join(parts) == paragraphs
    assert parts[0] == "나" * 3000 + "\n\n"
    assert all(len(p) <= 4096 for p in parts)

    lines = "\n".join(["마" * 1000] * 9)
    parts = split_message(lines)
    assert "".join(parts) == lines
    assert all(len(p) <= 4096 and (p.endswith("\n") or p is parts[-1]) for p in parts)

    assert split_message("짧은 답") == ["짧은 답"]

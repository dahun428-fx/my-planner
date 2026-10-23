from datetime import time

import pytest
from test_dispatcher_messages import kst
from test_telegram_io import OWNER, _NoDispatch, _RecordingBot, _update

from my_planner.bot.telegram_io import handle_update
from my_planner.clock import FakeClock
from my_planner.domain import Area, TaskStatus
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
NOW = kst(2026, 10, 24, 10, 30)  # 토요일, 논리적 날짜 10/24, 이번 주 W43 (10/19~10/25)


class CmdEnv:
    def __init__(self, tmp_path, conn, state):
        self.clock = FakeClock(NOW)
        self.state = state
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
        self.bot = _RecordingBot()
        self.dispatcher = _NoDispatch()
        self.tmp = tmp_path
        self._uid = 100

    def add(self, title, *, status=TaskStatus.open, planned_for=None, scheduled_at=None):
        from datetime import date

        pf = date.fromisoformat(planned_for) if planned_for else None
        return self.repo.create(title, [Area.career], status, pf, scheduled_at, None, "").id

    async def send(self, text, **kw):
        self._uid += 1
        return await handle_update(
            _update(update_id=self._uid, text=text, **kw),
            bot=self.bot,
            owner_id=OWNER,
            state=self.state,
            dispatcher=self.dispatcher,
            transcripts=self.transcripts,
            clock=self.clock,
            tools=self.tools,
        )

    @property
    def last(self):
        return self.bot.sent[-1][1]

    def day_file(self):
        path = self.tmp / "data" / "transcripts" / "2026" / "10" / "2026-10-24.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def cenv(tmp_path, conn, state):
    return CmdEnv(tmp_path, conn, state)


async def test_today_command_shows_priorities_schedule_open_no_drafts(cenv):
    a = cenv.add("보고서 쓰기", planned_for="2026-10-24")
    cenv.add("장보기", planned_for="2026-10-24")
    cenv.add("치과", planned_for="2026-10-24", scheduled_at=kst(2026, 10, 24, 14, 0))
    cenv.add("제안된 초안", status=TaskStatus.draft, planned_for="2026-10-24")
    cenv.add("내일 일", planned_for="2026-10-25")
    done = cenv.add("끝낸 일", planned_for="2026-10-24")
    cenv.repo.set_status(done, TaskStatus.done)
    cenv.repo.set_priorities("day", "2026-10-24", [a])
    cenv.repo.set_priorities("week", "2026-W43", [a])

    assert await cenv.send("/today") == "command"

    text = cenv.last
    assert cenv.bot.sent[0][0] == OWNER and len(cenv.bot.sent) == 1
    assert text.index("우선순위") < text.index("일정") < text.index("열린 할 일")
    assert "1. 보고서 쓰기" in text
    assert "14:00 치과" in text
    assert "장보기" in text
    assert "제안된 초안" not in text and "내일 일" not in text and "끝낸 일" not in text
    assert cenv.dispatcher.got == []


async def test_week_and_help_commands(cenv):
    from my_planner.bot.commands import HELP_TEXT

    a = cenv.add("보고서 쓰기", planned_for="2026-10-26")  # 다음 주 월요일: 이번 주에 안 나온다
    b = cenv.add("운동", planned_for="2026-10-22")
    cenv.add("치과", planned_for="2026-10-25", scheduled_at=kst(2026, 10, 25, 14, 0))
    cenv.add("제안된 초안", status=TaskStatus.draft, planned_for="2026-10-23")
    cenv.add("오늘 일", planned_for="2026-10-24")
    cenv.repo.set_priorities("week", "2026-W43", [b])
    cenv.repo.set_priorities("week", "2026-W44", [a])

    assert await cenv.send("/week") == "command"
    text = cenv.last
    assert text.startswith("이번 주 (10/19~10/25)")
    assert text.index("우선순위") < text.index("10/22")
    assert "1. 운동" in text
    assert "10/22 목\n- 운동" in text
    assert "10/24 토 (오늘)\n- 오늘 일" in text
    assert "10/25 일\n- 14:00 치과" in text
    assert "보고서 쓰기" not in text and "제안된 초안" not in text

    assert await cenv.send("/help") == "command"
    assert cenv.last == HELP_TEXT
    for cmd in ("/today", "/week", "/help"):
        assert cmd in HELP_TEXT
    assert cenv.dispatcher.got == []


async def test_command_logged_to_transcript(cenv):
    cenv.add("장보기", planned_for="2026-10-24")
    await cenv.send("/today")
    await cenv.send("/help@my_planner_bot")
    day = cenv.day_file()
    assert "### 10:30 사용자 [-]\n\n/today\n" in day
    assert "### 10:30 비서 [-]\n\n오늘 (10/24 토)" in day
    assert "### 10:30 사용자 [-]\n\n/help@my_planner_bot\n" in day
    assert day.index("/today") < day.index("오늘 (10/24 토)") < day.index("/help@my_planner_bot")
    assert "> 도구:" not in day
    assert cenv.state.is_seen_update(101) and cenv.state.is_seen_update(102)


async def test_command_from_other_user_ignored(cenv):
    cenv.add("장보기", planned_for="2026-10-24")
    assert await cenv.send("/today", uid=99) == "ignore"
    assert cenv.bot.sent == [] and cenv.day_file() == ""
    assert cenv.dispatcher.got == []
    # 소유자의 일반 글과 모르는 명령은 두뇌로 간다
    assert await cenv.send("안녕") == "accept"
    assert await cenv.send("/pause 2") == "accept"
    assert [m.text for m in cenv.dispatcher.got] == ["안녕", "/pause 2"]

from datetime import UTC, datetime, timedelta

from fakes import FakeBrain, FakeSender, FakeTurn, fake_sleep, make_settings

from my_planner.clock import FakeClock
from my_planner.harness.conversations import ConversationRouter
from my_planner.harness.dispatcher import Dispatcher, Inbound
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.core import Tools


class Env:
    def __init__(
        self, tmp_path, conn, state, *, script, start, sender=None, with_tools=False, with_conditions=False,
        keep_awake=None,
    ):
        self.settings = make_settings(tmp_path)
        self.clock = FakeClock(start)
        self.sender = sender or FakeSender()
        self.state = state
        self.convs = ConversationsRepo(conn, self.clock)
        self.runs = RunsRepo(conn, self.clock)
        self.transcripts = TranscriptStore(
            self.settings.paths.data_dir, self.settings.timezone, self.settings.day_boundary
        )
        self.tools = None
        self.conditions = None
        extra = {}
        if keep_awake is not None:
            extra["keep_awake"] = keep_awake
        if with_conditions:
            from my_planner.store.repos.conditions import ConditionsRepo

            self.conditions = ConditionsRepo(conn, self.clock)
            extra["conditions"] = self.conditions
        if with_tools:
            self.tools = Tools(
                tasks=TasksRepo(
                    conn, self.clock, tz=self.settings.timezone, boundary=self.settings.day_boundary
                ),
                transcripts=self.transcripts,
                export_path=self.settings.paths.data_dir / "exports" / "tasks.md",
                clock=self.clock,
                tz=self.settings.timezone,
                boundary=self.settings.day_boundary,
                conditions=self.conditions,
            )
        self.brain = FakeBrain(script, tools=self.tools, clock=self.clock)
        self.dispatcher = Dispatcher(
            brain=self.brain,
            sender=self.sender,
            convs=self.convs,
            state=state,
            transcripts=self.transcripts,
            clock=self.clock,
            settings=self.settings,
            router=ConversationRouter(self.convs, self.runs, clock=self.clock, settings=self.settings),
            tools=self.tools,
            runs=self.runs,
            data_dir=self.settings.paths.data_dir,
            sleep=fake_sleep(self.clock),
            **extra,
        )

    def inbound(self, text, update_id=1):
        now = self.clock.now()
        return Inbound(text=text, at=now, sent_at=now, update_ids=[update_id])

    async def process(self, *messages):
        self.dispatcher.start()
        for m in messages:
            self.dispatcher.submit_message(m)
        await self.dispatcher.stop(timeout=5)

    async def process_run(self, run, merged=()):
        self.dispatcher.start()
        self.dispatcher.submit_run(run, list(merged))
        await self.dispatcher.stop(timeout=5)

    def day_file(self, ymd):
        y, m, _ = ymd.split("-")
        return self.settings.paths.data_dir / "transcripts" / y / m / f"{ymd}.md"


def kst(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC) - timedelta(hours=9)


async def test_message_roundtrip_writes_transcript_both_sides(tmp_path, conn, state):
    env = Env(
        tmp_path, conn, state, script=[FakeTurn([], "안녕하세요, Dahun님.")], start=kst(2026, 10, 23, 1, 0)
    )
    await env.process(env.inbound("안녕"))

    assert [o.text for o in env.sender.sent] == ["안녕하세요, Dahun님."]
    assert "안녕" in env.brain.prompts[0]
    assert env.brain.session_ids == [None]

    # KST 01:00은 논리적 날짜로 전날(10-22)
    day = env.day_file("2026-10-22").read_text(encoding="utf-8")
    assert not env.day_file("2026-10-23").exists()
    assert "### 01:00 사용자 [1]\n\n안녕\n" in day
    assert "### 01:00 비서 [1]\n\n안녕하세요, Dahun님.\n" in day
    assert day.index("사용자") < day.index("비서")


async def test_logical_date_boundary_in_transcript(tmp_path, conn, state):
    env = Env(
        tmp_path,
        conn,
        state,
        script=[FakeTurn([], "첫 답"), FakeTurn([], "둘째 답")],
        start=kst(2026, 10, 23, 3, 59),
    )
    env.dispatcher.start()
    env.dispatcher.submit_message(env.inbound("새벽 세 시 오십구 분", update_id=1))
    await env.dispatcher.stop(timeout=5)

    env.clock.set(kst(2026, 10, 23, 4, 0))
    env.convs.close(1)  # 경계 확인을 위해 앞 대화를 닫아 새 대화로 시작한다
    env.dispatcher.start()
    env.dispatcher.submit_message(env.inbound("네 시 정각", update_id=2))
    await env.dispatcher.stop(timeout=5)

    before = env.day_file("2026-10-22").read_text(encoding="utf-8")
    after = env.day_file("2026-10-23").read_text(encoding="utf-8")
    assert "### 03:59 사용자 [1]" in before and "새벽 세 시 오십구 분" in before and "첫 답" in before
    assert "### 04:00 사용자 [2]" in after and "네 시 정각" in after and "둘째 답" in after
    assert "네 시 정각" not in before and "새벽" not in after


async def test_redacted_text_reaches_neither_transcript_nor_brain(tmp_path, conn, state):
    env = Env(
        tmp_path,
        conn,
        state,
        script=[FakeTurn([], "그 정보는 저장하지 않았어요.")],
        start=kst(2026, 10, 23, 15, 0),
    )
    await env.process(env.inbound("비번은 hunter2 이고 주민번호는 900101-1234567이야"))

    prompt = env.brain.prompts[0]
    assert "hunter2" not in prompt and "900101-1234567" not in prompt
    assert "비번은 [가림]" in prompt

    day = env.day_file("2026-10-23").read_text(encoding="utf-8")
    assert "hunter2" not in day and "1234567" not in day
    assert "비번은 [가림] 이고 주민번호는 [가림]이야" in day


async def test_update_ids_marked_after_send(tmp_path, conn, state):
    failing = Env(
        tmp_path,
        conn,
        state,
        script=[FakeTurn([], "답")],
        start=kst(2026, 10, 23, 15, 0),
        sender=FakeSender(fail=True),
    )
    await failing.process(failing.inbound("첫 메시지", update_id=7))
    assert not state.is_seen_update(7)

    ok = Env(tmp_path, conn, state, script=[FakeTurn([], "답")], start=kst(2026, 10, 23, 15, 1))
    await ok.process(ok.inbound("다시 보낸 메시지", update_id=7))
    assert [o.text for o in ok.sender.sent] == ["답"]
    assert state.is_seen_update(7)


async def test_typing_every_5_seconds_during_brain_call(tmp_path, conn, state):
    env = Env(
        tmp_path,
        conn,
        state,
        script=[FakeTurn([], "오래 생각한 답", delay=12)],
        start=kst(2026, 10, 23, 15, 0),
    )
    await env.process(env.inbound("어려운 질문"))
    assert env.sender.typing_count == 3  # 0초, 5초, 10초
    assert [o.text for o in env.sender.sent] == ["오래 생각한 답"]


async def test_logging_drops_message_bodies(tmp_path, conn, state):
    import json
    import logging

    from my_planner.logging_setup import setup_logging

    env = Env(
        tmp_path, conn, state, script=[FakeTurn([], "비서의 답장 본문 문장")], start=kst(2026, 10, 23, 15, 0)
    )
    log_path = setup_logging(env.settings.paths.state_dir, 30)
    await env.process(env.inbound("사용자의 고유한 본문 문장"))
    for h in logging.getLogger().handlers:
        h.flush()

    raw = log_path.read_text(encoding="utf-8")
    assert "사용자의 고유한 본문 문장" not in raw
    assert "비서의 답장 본문 문장" not in raw
    calls = [e for e in map(json.loads, raw.splitlines()) if e.get("msg") == "brain_call"]
    assert len(calls) == 1
    assert {"duration_ms", "turns", "status"} <= calls[0].keys()
    assert calls[0]["status"] == "ok" and calls[0]["turns"] == 1
    assert not ({"text", "args", "input"} & calls[0].keys())


def test_brain_timeout_defaults_to_300_seconds():
    import tomllib
    from pathlib import Path

    from my_planner.config import LimitsConfig

    assert LimitsConfig().brain_timeout_s == 300
    toml = tomllib.loads((Path(__file__).resolve().parents[1] / "config.toml").read_text(encoding="utf-8"))
    assert toml["limits"]["brain_timeout_s"] == 300


async def test_hung_brain_call_times_out_and_message_retries(tmp_path, conn, state):
    from fakes import make_settings

    from my_planner.config import LimitsConfig

    env = Env(
        tmp_path, conn, state,
        script=[FakeTurn([], "", hang=True), FakeTurn([], "다시 생각한 답")],
        start=kst(2026, 10, 23, 15, 0),
    )
    env.dispatcher.settings = make_settings(tmp_path, limits=LimitsConfig(brain_timeout_s=0.05))
    env.dispatcher._sleep = fake_sleep(env.clock, real=0.005)  # 기다리는 동안 가짜 시계가 내달리지 않게
    await env.process(env.inbound("안녕", update_id=5))

    # 시간 상한에 걸린 호출은 error(timeout): 메시지 규칙대로 백오프 뒤 다시 부른다
    assert len(env.brain.calls) == 2
    assert [o.text for o in env.sender.sent] == ["다시 생각한 답"]
    assert state.is_seen_update(5)

"""/plan, /done (스펙 5.6, 5.7): 텔레그램 어댑터 경계."""

import pytest
from fakes import make_settings
from test_telegram_commands import NOW, CmdEnv
from test_telegram_io import OWNER, _update

from my_planner.bot.telegram_io import handle_update
from my_planner.domain import ConversationKind
from my_planner.harness.conversations import ConversationRouter
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.runs import RunsRepo


class PlanEnv(CmdEnv):
    def __init__(self, tmp_path, conn, state):
        super().__init__(tmp_path, conn, state)
        self.convs = ConversationsRepo(conn, self.clock)
        self.router = ConversationRouter(
            self.convs, RunsRepo(conn, self.clock), clock=self.clock, settings=make_settings(tmp_path)
        )

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
            router=self.router,
        )


@pytest.fixture
def penv(tmp_path, conn, state):
    return PlanEnv(tmp_path, conn, state)


async def test_plan_command_opens_plan_conversation(penv):
    assert await penv.send("/plan 이번 주 운동") == "command"
    first = penv.convs.latest_open(ConversationKind.plan)
    assert first is not None and penv.router.plan_open()
    # 주제를 디스패처에 넘긴다. 답은 두뇌가 하고, 처리 완료 기록도 디스패처가 보낸 뒤에 한다
    [m] = penv.dispatcher.got
    assert m.text == "이번 주 운동" and m.update_ids == [penv._uid] and m.at == NOW
    assert penv.bot.sent == []
    assert not penv.state.is_seen_update(penv._uid)

    # 주제가 없으면 "계획 모드 시작". 열려 있던 계획 대화는 닫고 새로 연다
    assert await penv.send("/plan@my_planner_bot") == "command"
    assert penv.dispatcher.got[1].text == "계획 모드 시작"
    second = penv.convs.latest_open(ConversationKind.plan)
    assert second.id != first.id
    assert penv.convs.get(first.id).closed_at is not None


async def test_done_without_plan_says_nothing_open(penv):
    from my_planner.bot.commands import NO_PLAN_REPLY, PLAN_DONE_REPLY

    assert await penv.send("/done") == "command"
    assert penv.last == NO_PLAN_REPLY
    assert penv.state.is_seen_update(penv._uid)  # 보낸 뒤 처리 완료
    assert penv.dispatcher.got == []

    await penv.send("/plan")
    plan = penv.convs.latest_open(ConversationKind.plan)
    assert await penv.send("/done") == "command"
    assert penv.last == PLAN_DONE_REPLY
    assert penv.convs.get(plan.id).closed_at is not None and not penv.router.plan_open()
    assert len(penv.dispatcher.got) == 1  # /done은 두뇌를 거치지 않는다
    for word in ("놓쳤어요", "밀렸어요", "늦었지만", "실패"):
        assert word not in NO_PLAN_REPLY + PLAN_DONE_REPLY

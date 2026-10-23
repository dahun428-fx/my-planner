"""컨디션 도구 record_condition (스펙 5.5). MCP 핸들러를 두뇌처럼 직접 await한다."""

import json
import logging

import pytest
from test_dispatcher_messages import kst
from test_tools_tasks import ToolEnv

from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.tools.mcp_adapter import TOOL_NAMES, build_planner_tools


class CondEnv(ToolEnv):
    def __init__(self, tmp_path, conn, now=None):
        super().__init__(tmp_path, conn, now)
        self.conditions = ConditionsRepo(conn, self.clock)
        self.tools.conditions = self.conditions

    async def call(self, name, **args):
        handlers = {t.name: t.handler for t in build_planner_tools(self.tools, self.ctx())}
        out = await handlers[name](args)
        return json.loads(out["content"][0]["text"]), out["is_error"]


@pytest.fixture
def cenv(tmp_path, conn):
    return CondEnv(tmp_path, conn, now=kst(2026, 10, 24, 1, 30))


async def test_record_condition_defaults_to_logical_today(cenv, caplog):
    from datetime import date

    assert "record_condition" in TOOL_NAMES
    caplog.set_level(logging.DEBUG)
    out, is_error = await cenv.call("record_condition", score=4, note="조금 피곤하지만 괜찮아요")

    # KST 10/24 01:30은 논리적 날짜로 10/23
    assert is_error is False
    assert out == {"date": "2026-10-23", "score": 4, "note": "조금 피곤하지만 괜찮아요"}
    got = cenv.conditions.get(date(2026, 10, 23))
    assert (got.score, got.note) == (4, "조금 피곤하지만 괜찮아요")
    assert cenv.conditions.get(date(2026, 10, 24)) is None

    # 같은 날 다시 기록하면 덮어쓰고 최근 메모를 남긴다. 날짜를 주면 그 날에 기록한다
    await cenv.call("record_condition", score=2, note="저녁에 지쳤어요")
    await cenv.call("record_condition", score=5, date="2026-10-20")
    got = cenv.conditions.get(date(2026, 10, 23))
    assert (got.score, got.note) == (2, "저녁에 지쳤어요")
    # 메모 없이 점수만 다시 기록하면(버튼) 점수만 바뀌고 가장 최근 메모는 남는다
    await cenv.call("record_condition", score=3, date="2026-10-23")
    got = cenv.conditions.get(date(2026, 10, 23))
    assert (got.score, got.note) == (3, "저녁에 지쳤어요")
    assert cenv.conditions.get(date(2026, 10, 20)).score == 5
    # 로그에는 날짜와 점수만, 메모는 없다
    assert "지쳤어요" not in caplog.text and "피곤" not in caplog.text
    recs = [r for r in caplog.records if r.getMessage() == "condition_recorded"]
    assert [(r.date, r.score) for r in recs] == [
        ("2026-10-23", 4), ("2026-10-23", 2), ("2026-10-20", 5), ("2026-10-23", 3)
    ]


async def test_record_condition_out_of_range_error(cenv):
    from datetime import date

    for bad in (0, 6, -1, 3.5, "4", True, None):
        out, is_error = await cenv.call("record_condition", score=bad)
        assert is_error is True and "error" in out, bad
    out, is_error = await cenv.call("record_condition", score=3, date="10월 23일")
    assert is_error is True and "error" in out
    assert cenv.conditions.get(date(2026, 10, 23)) is None
    assert cenv.conn.execute("SELECT count(*) FROM conditions").fetchone()[0] == 0


async def test_record_condition_rejects_loose_and_future_dates(cenv):
    # 지금 KST 10/24 01:30 → 논리적 오늘은 10/23. 날짜는 YYYY-MM-DD만, 오늘보다 뒤는 안 된다
    for bad in ("20261023", "2026-W43-5", "2026-10-24", "2099-01-01"):
        out, is_error = await cenv.call("record_condition", score=3, date=bad)
        assert is_error is True and "error" in out, bad
    assert cenv.conn.execute("SELECT count(*) FROM conditions").fetchone()[0] == 0
    out, is_error = await cenv.call("record_condition", score=3, date="2026-10-23")
    assert is_error is False

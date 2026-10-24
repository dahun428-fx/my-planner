"""운영 앱 기준 응답(golden) (SP3-4 스펙 16장, 6.4.1).

`BeEnv`(가짜 두뇌 + 가짜 시계)로 같은 요청을 보내 `tests/fixtures/app_golden/<이름>.sse`, `headers.json`과
`messageId`만 바꿔 두고(`normalize_sse`) 바이트 단위로 비교한다. 모든 파일이 `parse_sse`를 통과해야 한다.
`python -m pytest tests/test_app_golden.py --update-app-golden`이 파일을 다시 쓴다. 꾸며 낸 내용만 쓴다.

`chat_propose_tasks.sse`(하네스 `ui_todo_draft` 조각 `h_draft_*`, 출력 `data.todos`)는 티켓 09가 더했다.
SP6 G-BE2가 두뇌의 새 화면 조각 여섯 파일을 더했다(SP6 스펙 10.6): `chat_date_choice`, `chat_result`,
`chat_period_list`, `chat_block`, `chat_ui_rejected`, `chat_gallery`(시험 전용, 상한 10.4를 풀어 두뇌 조각 일곱을 한 답에).
"""

import json
from pathlib import Path

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from ui_stream import normalize_sse, parse_sse, types

GOLDEN = Path(__file__).parent / "fixtures" / "app_golden"
START = kst(2026, 10, 24, 13, 0)
CASES = (
    "chat_add_task", "chat_daily_cap", "chat_replay", "chat_add_task_streamed", "chat_retry_streamed",
    "chat_propose_tasks",
    # SP6 G-BE2(10.6)
    "chat_date_choice", "chat_result", "chat_period_list", "chat_block", "chat_ui_rejected", "chat_gallery",
)
HEADER_NAMES = (
    "content-type", "cache-control", "x-accel-buffering", "x-vercel-ai-ui-message-stream", "x-conversation-id",
)

# 6.4.1의 예시 그대로(조각마다 빈 줄로 나눈다)
SPEC_EXAMPLE = "".join(f"{line}\n\n" for line in [
    ('data: {"type":"start","messageId":"m-41-7","messageMetadata":{"conversation_id":41,"channel":"app",'
    '"kind":"chat","checkin_id":null}}'),
    'data: {"type":"data-status","data":{"state":"queued"},"transient":true}',
    'data: {"type":"start-step"}',
    'data: {"type":"text-start","id":"t1"}',
    'data: {"type":"text-delta","id":"t1","delta":"내일 치과를 "}',
    'data: {"type":"text-delta","id":"t1","delta":"추가할게요."}',
    'data: {"type":"text-end","id":"t1"}',
    ('data: {"type":"tool-input-available","toolCallId":"tc_01","toolName":"add_task","input":{"title":"치과",'
    '"areas":["health"],"planned_for":"2026-10-25"}}'),
    'data: {"type":"tool-output-available","toolCallId":"tc_01","output":{"id":53,"status":"open"}}',
    'data: {"type":"finish-step"}',
    ('data: {"type":"data-activity","data":{"activity_ids":[912],"undo_ids":[912],'
    '"confirmation":"✓ 추가: 치과 → 내일"}}'),
    'data: {"type":"finish","messageMetadata":{"conversation_id":41,"channel":"app","kind":"chat"}}',
    "data: [DONE]",
]).encode("utf-8")

DENTIST = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-10-25"})
PROPOSE = ("propose_tasks", {"tasks": [{"title": "물 마시기", "areas": ["health"]},
                                       {"title": "스트레칭", "areas": ["health"]}]})


# --- SP6 G-BE2 (10.6): 두뇌의 새 화면 조각. 새 DB라 할 일 번호는 1부터다. 꾸며 낸 내용만 ---

DATE_CHOICE = ("ui_date_choice", {
    "task_id": 1, "question": "치과 예약은 언제 할까요?",
    "candidates": [{"date": "2026-10-27", "note": "오후가 비어요"}, {"date": "2026-10-28"}, {"date": "2026-10-30"}],
})
BLOCK = ("ui_block", {"title": "이번 주 운동", "children": [
    {"type": "group", "layout": "row", "children": [
        {"type": "stat", "label": "이번 주", "value": "3회", "delta": {"text": "1회", "trend": "up"}},
        {"type": "stat", "label": "지난주", "value": "2회"}]},
    {"type": "progress", "label": "이번 주 목표", "value": 3, "max": 4},
    {"type": "text", "md": "**목요일** 오후가 비어 있어요."},
    {"type": "todo_rows", "task_ids": [1]},
    {"type": "buttons", "items": [{"label": "운동 끝났어", "do": {"kind": "complete", "task_id": 1}}]},
]})
BLOCK_MISPLACED = ("ui_block", {"title": "이번 주 운동", "children": [  # B4: 버튼 줄이 맨 끝이 아니다
    {"type": "buttons", "items": [{"label": "운동 끝났어", "do": {"kind": "complete", "task_id": 1}}]},
    {"type": "todo_rows", "task_ids": [1]},
]})
# (미리 넣는 할 일, 두뇌 대본, 사용자 글)
SP6_CASES: dict[str, tuple[list[dict], list[FakeTurn], str]] = {
    "chat_date_choice": (
        [],
        [FakeTurn([("add_task", {"title": "치과 예약", "areas": ["health"]}), DATE_CHOICE], "날짜를 골라 주세요.")],
        "다음 주에 치과 예약 추가해 줘",
    ),
    "chat_result": (
        [{"title": "꾸민 장보기", "areas": ["quality_of_life"], "planned_for": "2026-10-25"}],
        [FakeTurn([("move_task", {"id": 1, "planned_for": "2026-10-27"}), ("ui_result", {"task_ids": [1]})],
                  "화요일로 옮겼어요.")],
        "장보기 화요일로 옮겨 줘",
    ),
    "chat_period_list": (
        [{"title": "꾸민 보고서 초안", "areas": ["career"], "planned_for": "2026-10-25"},
         {"title": "꾸민 독서 모임", "areas": ["learning"], "planned_for": "2026-10-26",
          "scheduled_at": "2026-10-26T19:30"},
         {"title": "꾸민 화분 분갈이", "areas": ["quality_of_life"], "planned_for": "2026-10-27"},
         {"title": "꾸민 산책", "areas": ["health"], "planned_for": "2026-10-28"}],
        [FakeTurn([("move_task", {"id": 1, "planned_for": "2026-10-29"}),
                   ("move_task", {"id": 3, "planned_for": "2026-10-30"}),
                   ("move_task", {"id": 4, "planned_for": "2026-11-03"}),
                   ("ui_period_list", {"week": "2026-W44", "highlight_task_ids": [1, 3, 4]})],
                  "다음 주로 나눠 옮겼어요.")],
        "다음 주 할 일 좀 나눠 줘",
    ),
    "chat_block": (
        [{"title": "꾸민 저녁 운동", "areas": ["health"], "planned_for": "2026-10-24"}],
        [FakeTurn([BLOCK], "이번 주 운동이에요.")],
        "이번 주 운동 어땠지",
    ),
    "chat_ui_rejected": (
        [{"title": "꾸민 저녁 운동", "areas": ["health"], "planned_for": "2026-10-24"}],
        [FakeTurn([BLOCK_MISPLACED, BLOCK], "이번 주 운동이에요.")],
        "이번 주 운동 어땠지",
    ),
    "chat_gallery": (
        [{"title": "꾸민 치과 예약", "areas": ["health"]},
         {"title": "꾸민 장보기", "areas": ["quality_of_life"], "planned_for": "2026-10-25"},
         {"title": "꾸민 독서 모임", "areas": ["learning"], "planned_for": "2026-10-27",
          "scheduled_at": "2026-10-27T19:30"}],
        [FakeTurn([
            ("move_task", {"id": 2, "planned_for": "2026-10-26"}),
            ("ui_todo_list", {"title": "꾸민 목록", "task_ids": [1, 2, 3]}),
            ("ui_choice", {"question": "어느 쪽이 좋아요?", "options": [{"id": "a", "label": "오전"},
                                                                      {"id": "b", "label": "오후"}]}),
            ("ui_summary_card", {"title": "꾸민 정리", "lines": ["한 줄 정리", "두 줄 정리"]}),
            ("ui_date_choice", {"task_id": 1, "question": "치과 예약은 언제 할까요?",
                                "candidates": [{"date": "2026-10-28", "note": "오전이 비어요"}, {"date": "2026-10-29"}]}),
            ("ui_result", {"task_ids": [2]}),
            ("ui_period_list", {"week": "2026-W44", "highlight_task_ids": [2]}),
            ("ui_block", {**BLOCK[1], "children": [
                *BLOCK[1]["children"][:4], {"type": "todo_rows", "task_ids": [3]},
                {"type": "buttons", "items": [{"label": "기록에서 보기", "do": {"kind": "open", "screen": "activity"}},
                                              {"label": "다음 주는?", "do": {"kind": "send"}}]}]}),
        ], "꾸민 갤러리예요.")],
        "꾸민 갤러리 보여 줘",
    ),
}


async def _record(tmp_path: Path, name: str) -> tuple[bytes, dict[str, str]]:
    if name in SP6_CASES:
        seed, script, text = SP6_CASES[name]
        async with BeEnv.start(tmp_path, start=START, script=script) as env:
            for task in seed:
                status, body = await env.action("add_task", task)
                assert status == 200, body
            resp, raw = await env.chat(text, client_msg_id="cm-golden")
        return normalize_sse(raw), {h: resp.headers[h] for h in HEADER_NAMES}
    script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.")]
    if name == "chat_daily_cap":
        script = []
    elif name == "chat_propose_tasks":  # 09: 하네스 초안 카드 `h_draft_1`(`ui_todo_draft`, 6.4.1)
        script = [FakeTurn([PROPOSE], "이번 주에 이 둘을 해 보면 어때요?")]
    elif name == "chat_add_task_streamed":  # 06b: 글이 도구 조각보다 먼저 조각으로 간다
        script = [FakeTurn([DENTIST], "내일 치과를 추가할게요.", deltas=["내일 치과를 ", "추가할게요."])]
    elif name == "chat_retry_streamed":  # 06b: 첫 시도가 글 일부를 보낸 뒤 오류, 재시도는 새 단계와 새 글 id
        script = [
            FakeTurn([], "", status="error", error="boom", deltas=["내일 치과를 "]),
            FakeTurn([], "내일 치과를 추가할게요.", deltas=["내일 치과를 ", "추가할게요."]),
        ]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        if name == "chat_daily_cap":
            env.conn.execute("INSERT INTO usage_state (date, brain_calls) VALUES ('2026-10-24', 60)")
            env.conn.commit()
        text = "이번 주 뭐 하면 좋을까" if name == "chat_propose_tasks" else "내일 치과 추가해 줘"
        resp, raw = await env.chat(text, client_msg_id="cm-golden")
        if name == "chat_replay":
            resp, raw = await env.chat("내일 치과 추가해 줘", client_msg_id="cm-golden")
    return normalize_sse(raw), {h: resp.headers[h] for h in HEADER_NAMES}


def test_parser_reads_spec_example():
    chunks = parse_sse(SPEC_EXAMPLE)
    assert types(chunks)[0] == "start" and types(chunks)[-1] == "finish"
    assert chunks[-2]["data"]["confirmation"] == "✓ 추가: 치과 → 내일"
    assert normalize_sse(SPEC_EXAMPLE).startswith(b'data: {"type":"start","messageId":"<id>"')


@pytest.mark.parametrize("bad", [
    b'data: {"type":"text-delta","id":"t1","delta":"x"}\n\ndata: [DONE]\n\n',  # start가 없다
    b'data: {"type":"start"}\n\ndata: {"type":"finish"}\n\n',  # [DONE]이 없다
    b'data: {"type":"start"}\n\ndata: {"type":"text-start","id":"t1"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n',
    (b'data: {"type":"start"}\n\ndata: {"type":"tool-output-available","toolCallId":"x","output":{}}\n\n'
    b'data: {"type":"finish"}\n\ndata: [DONE]\n\n'),
    b'data: {"type":"start"}\n\ndata: {"type":"text-chunk","id":"t1"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n',
    (b'data: {"type":"start"}\n\ndata: {"type":"start-step"}\n\n'
     b'data: {"type":"data-status","data":{"state":"thinking"},"transient":true}\n\n'
     b'data: {"type":"finish-step"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n'),  # 단계 뒤 data-status
    (b'data: {"type":"start"}\n\ndata: {"type":"data-status","data":{"state":"thinking"},"transient":true}\n\n'
     b'data: {"type":"data-status","data":{"state":"queued"},"transient":true}\n\n'
     b'data: {"type":"finish"}\n\ndata: [DONE]\n\n'),  # thinking 뒤 queued
])
def test_parser_rejects_broken_streams(bad):
    with pytest.raises(AssertionError):
        parse_sse(bad)


@pytest.mark.parametrize("name", CASES)
async def test_app_golden_matches_stream(tmp_path, name, update_app_golden, monkeypatch):
    if name == "chat_gallery":  # 시험 전용: 한 답 두 개 상한(10.4)을 푼다. `BeEnv`에는 설정을 더하지 않는다
        from my_planner.tools import mcp_adapter

        monkeypatch.setattr(mcp_adapter, "UI_PARTS_PER_REPLY", 10)
    body, headers = await _record(tmp_path, name)
    parse_sse(body)
    path = GOLDEN / f"{name}.sse"
    if update_app_golden:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        if name == "chat_add_task":
            (GOLDEN / "headers.json").write_text(
                json.dumps(headers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    assert body == path.read_bytes()
    if name == "chat_add_task":
        assert headers == json.loads((GOLDEN / "headers.json").read_text(encoding="utf-8"))


def test_app_golden_files_parse():
    files = sorted(p.name for p in GOLDEN.glob("*.sse"))
    assert set(files) >= {f"{n}.sse" for n in CASES}
    for name in files:
        parse_sse((GOLDEN / name).read_bytes())
    headers = json.loads((GOLDEN / "headers.json").read_text(encoding="utf-8"))
    assert set(headers) == set(HEADER_NAMES)
    assert headers["content-type"] == "text/event-stream"


def _golden(name: str) -> list[dict]:
    return parse_sse((GOLDEN / f"{name}.sse").read_bytes())


def _parts(chunks: list[dict]) -> list[tuple[str, dict]]:
    """두뇌 화면 조각 `(이름, 출력)`, 나온 순서."""
    names = {c["toolCallId"]: c["toolName"] for c in chunks if c["type"] == "tool-input-available"}
    return [(names[c["toolCallId"]], c["output"]) for c in chunks
            if c["type"] == "tool-output-available" and names[c["toolCallId"]].startswith("ui_")]


def test_sp6_golden_contents():
    """앱 대화 계약(G-A3)이 기대는 모양: 기준 SSE를 다시 만들 때 뜻이 바뀌지 않았는지 본다."""
    date_choice = _golden("chat_date_choice")
    assert [n for n, _ in _parts(date_choice)] == ["ui_date_choice"]  # 이 답에는 `ui_result`가 없다
    (activity,) = [c for c in date_choice if c["type"] == "data-activity"]
    assert len(activity["data"]["activity_ids"]) == 1  # 추가(확인 칸이 추가와 되돌리기를 맡는다)
    assert _parts(date_choice)[0][1]["data"]["todo"]["planned_for"] is None

    result = _golden("chat_result")
    ((_, out),) = _parts(result)
    (activity,) = [c for c in result if c["type"] == "data-activity"]
    (item,) = out["data"]["items"]
    assert item["activity_ids"] == activity["data"]["activity_ids"] and item["undo_id"] == item["activity_ids"][0]

    ((_, period),) = _parts(_golden("chat_period_list"))
    assert len(period["data"]["days"]) == 7 and [o["reason"] for o in period["data"]["outside"]] == ["moved"]

    ((_, block),) = _parts(_golden("chat_block"))
    assert [t["id"] for t in block["data"]["todos"]] == [1]

    rejected = _golden("chat_ui_rejected")
    assert [n for n, _ in _parts(rejected)] == ["ui_block"]  # 거절된 첫 호출은 조각이 없다
    assert not [c for c in rejected if c["type"] == "tool-output-error"]

    assert [n for n, _ in _parts(_golden("chat_gallery"))] == [
        "ui_todo_list", "ui_choice", "ui_summary_card", "ui_date_choice", "ui_result", "ui_period_list", "ui_block",
    ]

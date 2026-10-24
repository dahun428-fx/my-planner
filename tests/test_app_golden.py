"""운영 앱 기준 응답(golden) (SP3-4 스펙 16장, 6.4.1).

`BeEnv`(가짜 두뇌 + 가짜 시계)로 같은 요청을 보내 `tests/fixtures/app_golden/<이름>.sse`, `headers.json`과
`messageId`만 바꿔 두고(`normalize_sse`) 바이트 단위로 비교한다. 모든 파일이 `parse_sse`를 통과해야 한다.
`python -m pytest tests/test_app_golden.py --update-app-golden`이 파일을 다시 쓴다. 꾸며 낸 내용만 쓴다.

`chat_propose_tasks.sse`(하네스 `ui_todo_draft` 조각 `h_draft_*`, 출력 `data.todos`)는 티켓 09가 더했다.
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


async def _record(tmp_path: Path, name: str) -> tuple[bytes, dict[str, str]]:
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
async def test_app_golden_matches_stream(tmp_path, name, update_app_golden):
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

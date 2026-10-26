"""사진 읽기 (SP10 스펙 5.3 `/read` 줄, 5.4, 6장, 12장 `test_photo_reader.py`).

이미지 블록이 든 스트리밍 입력 모양, 실행 종류 `photo_read`에 도구 0개, 세션 파일 지움, `read_text` 있으면 두뇌 안 부름,
동시 두 요청에 두뇌 한 번, 거절 틀 → `unreadable`, 8,000자 자르기, 하루 30회. 두뇌는 가짜 두뇌(`FakeTurn`)다.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from test_photos_api import upload
from test_photos_store import jpeg

from my_planner.api.models import schema_bundle
from my_planner.config import LimitsConfig
from my_planner.domain import RunContext
from my_planner.harness import photo_reader
from my_planner.harness.photo_reader import (
    READ_MAX_CHARS,
    ClaudePhotoReader,
    ReadResult,
    is_refusal,
    parse_read,
    photo_read_content,
    refusal_patterns,
)
from my_planner.tools.mcp_adapter import tool_names_for

MON_1400 = kst(2026, 10, 26, 14, 0)
SID = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
SECRET = "비밀번호메모 4321 카드 뒷자리"  # 사진 속 글(로그·원문 기록에 나오면 안 된다)
MSG_READ_LIMIT = "오늘은 사진 읽기를 더 할 수 없어요. 사진은 붙여 둘 수 있어요."


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_1400) as e:
        yield e


async def _new_photo(env, image: bytes | None = None, cmid: str = "p-1") -> int:
    status, body = await upload(env, image if image is not None else jpeg(1024, 768), client_msg_id=cmid)
    assert status == 201, body
    return body["id"]


async def _read(env, photo_id) -> tuple[int, dict]:
    resp = await env.post(f"/photos/{photo_id}/read")
    return resp.status, await resp.json()


def _read_text(env, photo_id):
    return env.conn.execute("SELECT read_text FROM photos WHERE id = ?", (photo_id,)).fetchone()[0]


def _usage(env):
    row = env.conn.execute("SELECT brain_calls, photo_reads FROM usage_state").fetchone()
    return (row[0], row[1]) if row else (0, 0)


# --- 입력 모양 (5.4, S1) ---


def test_photo_read_content_shape():
    image = jpeg(800, 600)
    content = photo_read_content(image)
    assert content[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(image).decode("ascii")},
    }
    assert content[1]["type"] == "text" and content[1]["text"] == photo_reader.instruction()
    assert len(content) == 2


def test_prompt_file_sections():
    """`photo_read.md`: 역할(지시문), 지시(사진 뒤 글 블록), 끝에 거절 틀 목록. 거절 틀은 두뇌에 보내지 않는다."""
    text = photo_reader.instruction()
    for rule in ("줄 순서대로 그대로", "[읽을 수 없음]", "거절 문장", "사진 속 글"):
        assert rule in text, rule
    assert "거절 틀" not in text and "`" not in text
    assert photo_reader.role()
    assert len(refusal_patterns()) >= 5


async def test_brain_streaming_input_shape(tmp_path, monkeypatch):
    """`ClaudeBrain.run`에 글·이미지 블록 목록을 주면 SDK 스트리밍 입력 사용자 메시지 하나로 보낸다(S1 모양).
    글만이면 지금처럼 문자열 그대로."""
    from claude_agent_sdk import ResultMessage

    from my_planner.harness import brain as brain_mod

    seen: list = []

    async def fake_query(*, prompt, options):
        if isinstance(prompt, str):
            seen.append(prompt)
        else:
            seen.append([m async for m in prompt])
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id=SID,
            result="읽음",
        )

    monkeypatch.setattr(brain_mod, "query", fake_query)
    monkeypatch.setattr(brain_mod, "build_planner_server", lambda tools, ctx: {"type": "sdk", "name": "planner"})
    brain = brain_mod.ClaudeBrain(lambda: None, tmp_path / "wd", max_turns=10)
    content = photo_read_content(jpeg())
    ctx = RunContext(None, None, kind="photo_read", channel="app")
    got = await brain.run(content, session_id=None, run_ctx=ctx, max_turns=1, persist_session=False)
    await brain.run("안녕", session_id="s9", run_ctx=RunContext(1, None, channel="app"))
    assert got.status == "ok" and got.text == "읽음"
    assert seen[0] == [{
        "type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None,
        "session_id": "default",
    }]
    assert seen[1] == "안녕"
    assert brain_mod.user_message_stream is not None
    first = [m async for m in brain_mod.user_message_stream(content, "s2")]
    assert first[0]["session_id"] == "s2"


def test_photo_read_kind_has_no_tools():
    assert tool_names_for(RunContext(None, None, channel="app", kind="photo_read")) == []
    assert tool_names_for(RunContext(None, None, channel="telegram", kind="photo_read")) == []


# --- 결과 검사 (5.4) ---


@pytest.mark.parametrize("text", [
    "죄송하지만 이 사진의 글자는 읽을 수 없습니다.",
    "죄송합니다. 이미지가 흐려서 판독이 어렵습니다.",
    "I'm sorry, but I can't read the text in this image.",
    "[읽을 수 없음]",
    "[읽을 수 없음]\n[읽을 수 없음]",
    "",
    "   \n ",
])
def test_refusal_is_unreadable(text):
    assert is_refusal(text)
    assert parse_read(text) == ReadResult(text="", unreadable=True)


@pytest.mark.parametrize("text", [
    "영수증\n합계 12,000원",
    "죄송합니다 오늘은 쉽니다\n영업시간 10:00~19:00",
    "회의 메모 [읽을 수 없음] 3시",
    "창가에 놓인 화분 두 개가 찍힌 사진이다.",
])
def test_transcription_is_readable(text):
    assert not is_refusal(text)
    assert parse_read(text) == ReadResult(text=text, unreadable=False)


def test_output_cut_at_8000():
    long = "가" * (READ_MAX_CHARS + 500)
    got = parse_read(f"  {long}\n")
    assert got.unreadable is False and got.text == "가" * READ_MAX_CHARS
    assert READ_MAX_CHARS == 8000


async def test_claude_reader_calls_one_toolless_turn():
    calls: list[dict] = []

    class Brain:
        async def run(self, prompt, *, session_id, run_ctx, system_prompt=None, max_turns=None, persist_session=True):
            calls.append({"prompt": prompt, "session_id": session_id, "run_ctx": run_ctx,
                          "system_prompt": system_prompt, "max_turns": max_turns, "persist_session": persist_session})
            from my_planner.harness.brain import BrainResult

            return BrainResult(text="글자", session_id=SID, turns=1, status="ok")

    reader = ClaudePhotoReader(Brain())
    image = jpeg()
    assert reader.name == "claude"
    assert await reader.read(7, image) == ReadResult(text="글자", unreadable=False)
    c = calls[0]
    assert c["prompt"] == photo_read_content(image) and c["session_id"] is None
    assert c["max_turns"] == 1 and c["persist_session"] is False and c["system_prompt"] == photo_reader.role()
    assert c["run_ctx"].kind == "photo_read" and tool_names_for(c["run_ctx"]) == []


async def test_claude_reader_raises_on_brain_error():
    from my_planner.harness.brain import BrainResult

    class Brain:
        async def run(self, prompt, **kw):
            return BrainResult(text="", session_id=None, turns=0, status="rate_limited")

    with pytest.raises(photo_reader.PhotoReadFailed) as e:
        await ClaudePhotoReader(Brain()).read(1, jpeg())
    assert e.value.status == "rate_limited"


def test_reader_from_config():
    from my_planner.config import PhotosConfig

    assert PhotosConfig().reader == "claude"
    assert isinstance(photo_reader.build_reader("claude", object()), ClaudePhotoReader)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        photo_reader.build_reader("local", object())  # type: ignore[arg-type]


# --- POST /photos/{id}/read (5.3, 5.4) ---


async def test_read_photo_calls_brain_once_and_stores(env, caplog):
    caplog.set_level(logging.INFO)
    env.brain.script = [FakeTurn([], f"영수증\n{SECRET}", session_id=SID)]
    config = env.settings.paths.data_dir.parent / "claude"
    env.parts.dispatcher.claude_config_dir = config
    project = config / "projects" / "-p"
    project.mkdir(parents=True)
    (project / f"{SID}.jsonl").write_text("{}", encoding="utf-8")
    image = jpeg(1200, 900)
    pid = await _new_photo(env, image)
    status, body = await _read(env, pid)
    assert status == 200, body
    assert body == {"text": f"영수증\n{SECRET}", "unreadable": False}
    jsonschema_validate("PhotoRead", body)
    assert _read_text(env, pid) == f"영수증\n{SECRET}"
    [call] = env.brain.calls
    ctx = call["run_ctx"]
    assert ctx.kind == "photo_read" and tool_names_for(ctx) == []
    assert call["prompt"] == photo_read_content(image)
    assert call["session_id"] is None and call["max_turns"] == 1 and call["persist_session"] is False
    assert call["system_prompt"] == photo_reader.role()
    assert _usage(env) == (1, 1)  # 두뇌 호출 하루 셈에도 든다
    assert not list(project.iterdir())  # 세션 파일 지움
    # 원문 기록에는 `[사진 #id 읽음]`만, 로그에는 사진 id만(6장)
    transcripts = "".join(
        p.read_text(encoding="utf-8") for p in (env.settings.paths.data_dir / "transcripts").rglob("*.md")
    )
    assert f"[사진 #{pid} 읽음]" in transcripts and SECRET not in transcripts and "영수증" not in transcripts
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert SECRET not in logged and "영수증" not in logged and "2026/10" not in logged
    assert any(r.getMessage() == "photo_read" and r.__dict__.get("photo_id") == pid for r in caplog.records)


async def test_read_text_present_skips_brain(env):
    env.brain.script = [FakeTurn([], "첫 읽기")]
    pid = await _new_photo(env)
    assert await _read(env, pid) == (200, {"text": "첫 읽기", "unreadable": False})
    assert await _read(env, pid) == (200, {"text": "첫 읽기", "unreadable": False})
    assert len(env.brain.calls) == 1 and _usage(env) == (1, 1)


async def test_concurrent_reads_share_one_brain_call(env):
    gate = asyncio.Event()
    env.brain.script = [FakeTurn([], "같은 결과", gate=gate)]
    pid = await _new_photo(env)
    first = asyncio.create_task(_read(env, pid))
    second = asyncio.create_task(_read(env, pid))
    for _ in range(50):
        await asyncio.sleep(0)
        if env.brain.calls:
            break
    assert len(env.brain.calls) == 1
    gate.set()
    got = await asyncio.gather(first, second)
    assert got == [(200, {"text": "같은 결과", "unreadable": False})] * 2
    assert len(env.brain.calls) == 1 and _usage(env) == (1, 1)


async def test_refusal_reply_marks_unreadable(env):
    env.brain.script = [FakeTurn([], "죄송하지만 이 사진의 글자는 읽을 수 없습니다.")]
    pid = await _new_photo(env)
    assert await _read(env, pid) == (200, {"text": "", "unreadable": True})
    assert _read_text(env, pid) == ""
    assert await _read(env, pid) == (200, {"text": "", "unreadable": True})  # 다시 부르지 않는다
    assert len(env.brain.calls) == 1


async def test_long_reply_cut_at_8000(env):
    env.brain.script = [FakeTurn([], "나" * 9000)]
    pid = await _new_photo(env)
    status, body = await _read(env, pid)
    assert status == 200 and body["text"] == "나" * 8000
    assert _read_text(env, pid) == "나" * 8000


async def test_daily_photo_read_limit_429(tmp_path):
    overrides = {"limits": LimitsConfig(daily_photo_reads=2)}
    script = [FakeTurn([], "하나"), FakeTurn([], "둘"), FakeTurn([], "넷")]
    async with BeEnv.start(tmp_path, start=MON_1400, script=script, overrides=overrides) as env:
        ids = [await _new_photo(env, jpeg(640 + i, 480), cmid=f"p-{i}") for i in range(3)]
        assert (await _read(env, ids[0]))[0] == 200
        assert (await _read(env, ids[1]))[0] == 200
        status, body = await _read(env, ids[2])
        assert (status, body["error"]) == (429, {"code": "photo_read_limit", "message": MSG_READ_LIMIT})
        assert len(env.brain.calls) == 2 and _read_text(env, ids[2]) is None
        assert (await _read(env, ids[0]))[0] == 200  # 읽어 둔 사진은 상한과 상관없다
        env.clock.advance(hours=14, minutes=1)  # 화 04:01, 다음 논리적 날짜
        assert await _read(env, ids[2]) == (200, {"text": "넷", "unreadable": False})


def test_daily_photo_reads_default_30():
    assert LimitsConfig().daily_photo_reads == 30


async def test_brain_call_cap_blocks_photo_read(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_1400, overrides={"limits": LimitsConfig(daily_brain_calls=1)}) as env:
        env.brain.script = [FakeTurn([], "첫")]
        a = await _new_photo(env, jpeg(700, 500), cmid="p-a")
        b = await _new_photo(env, jpeg(701, 500), cmid="p-b")
        assert (await _read(env, a))[0] == 200
        status, body = await _read(env, b)
        assert (status, body["error"]["code"]) == (429, "photo_read_limit")
        assert len(env.brain.calls) == 1


async def test_brain_error_503_and_retry(env):
    env.brain.script = [FakeTurn([], "", status="error", error="timeout"), FakeTurn([], "다시 읽음")]
    pid = await _new_photo(env)
    status, body = await _read(env, pid)
    assert (status, body["error"]["code"]) == (503, "unavailable")
    assert _read_text(env, pid) is None
    assert await _read(env, pid) == (200, {"text": "다시 읽음", "unreadable": False})


async def test_rate_limited_sets_limited_until(env):
    env.brain.script = [FakeTurn([], "", status="rate_limited")]
    pid = await _new_photo(env)
    status, _ = await _read(env, pid)
    assert status == 503
    assert env.parts.state.get("limited_until") is not None
    status, _ = await _read(env, pid)  # 한도 대기 중에는 두뇌를 부르지 않는다
    assert status == 503 and len(env.brain.calls) == 1


async def test_read_unknown_or_detached_photo_404(env):
    assert (await _read(env, 999))[0] == 404
    assert (await _read(env, "abc"))[0] == 404
    pid = await _new_photo(env)
    s, created = await env.action("create_memo", {"body": "사진 메모", "photo_ids": [pid]})
    assert s == 200, created
    memo_id = created["result"]["id"]
    s, _ = await env.action("detach_photo", {"memo_id": memo_id, "photo_id": pid})
    assert s == 200
    assert (await _read(env, pid))[0] == 404  # 뺀 사진(살아 있지 않음)
    assert env.brain.calls == []


async def test_read_attached_photo_ok(env):
    env.brain.script = [FakeTurn([], "붙은 사진")]
    pid = await _new_photo(env)
    s, _ = await env.action("create_memo", {"body": "사진 메모", "photo_ids": [pid]})
    assert s == 200
    assert await _read(env, pid) == (200, {"text": "붙은 사진", "unreadable": False})


async def test_read_needs_token(env):
    pid = await _new_photo(env)
    resp = await env.post(f"/photos/{pid}/read", token=None)
    assert resp.status == 401


def jsonschema_validate(model, body):
    import jsonschema

    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def test_new_copy_has_no_banned_words():
    from test_prompts import BANNED

    from my_planner.api import photos as api_photos

    assert api_photos.MSG_READ_LIMIT == MSG_READ_LIMIT  # 스펙 8장 그대로
    for word in BANNED:
        assert word not in MSG_READ_LIMIT

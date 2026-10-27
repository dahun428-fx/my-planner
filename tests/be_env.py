"""BE 끝에서 끝까지 시험 이음매 `BeEnv` (SP3-4 티켓 01, 모든 수용 시험이 쓴다).

실제 조립 함수 `app.build_be`에 가짜 두뇌(`FakeBrain`), 가짜 전송(`FakeSender`), 가짜 시계와 sleep을 끼우고,
API는 aiohttp `TestClient`로, 텔레그램 입력은 SP1 `handle_update` 경로로 넣는다.

    async with BeEnv.start(tmp_path, script=[FakeTurn([], "좋은 아침이에요")], start=kst(...)) as env:
        await env.tick()
        resp = await env.get("/health")

시작 시각 1분 전에 설치하고 tick한 것으로 둔다(`installed_at`, `last_seen_at`): 1분 tick이 이미 돌고 있던 BE처럼
`start` 직전의 예정 회차를 다음 `tick()`이 만든다.
"""

from __future__ import annotations

import asyncio
import itertools
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import ClientResponse
from aiohttp.test_utils import TestClient, TestServer
from fakes import (
    FAKE_AUTH,
    FAKE_P256DH,
    FAKE_VAPID,
    FakeBrain,
    FakeSender,
    FakeTurn,
    fake_sleep,
    make_settings,
)
from telegram import Update

from my_planner.api.health import ErrorCounter
from my_planner.api.server import API_PREFIX, ApiDeps, build_app
from my_planner.app import BeParts, _body_token, build_be
from my_planner.bot.telegram_io import handle_update
from my_planner.clock import FakeClock, to_iso
from my_planner.harness.moments import MOMENTS_PAUSED_KEY
from my_planner.store.db import migrate, open_db, open_ro

# 쓰기 경로 감시(SP3-4 16장, `tests/test_write_paths.py`): 주면 쓰기 연결의 데이터 쓰기마다 그 SQL로 부른다
ON_WRITE: Any = None
TEST_TOKEN = "test-token-" + "x" * 40  # 꾸며 낸 값(51자). 로그 검사 시험이 이 문자열을 찾는다
OWNER = 42
DRAIN_STEPS = 10_000
DISK_FREE = 50 * 1024**3  # 남은 공간(SP10 5.6 4번)을 시험 기계의 디스크와 떼어 둔다. 시험이 `env.deps.disk_free`를 바꾼다


class RecordingBot:
    """명령 답(`bot.send_message`)과 버튼 답(`answer_callback_query`)을 적는 가짜 텔레그램 봇."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.markups: list[Any] = []  # `sent`과 같은 순서의 `reply_markup`
        self.answers: list[tuple[str, str | None]] = []
        self.edits: list[tuple[int, Any]] = []  # (message_id, reply_markup): `editMessageReplyMarkup`
        self.edit_error: Exception | None = None  # 주면 버튼 다시 그리기가 이 예외를 올린다

    async def send_message(self, chat_id: int, text: str, reply_markup: Any = None, **kw: Any) -> None:
        self.sent.append((chat_id, text))
        self.markups.append(reply_markup)

    async def edit_message_reply_markup(
        self, chat_id: int | None = None, message_id: int | None = None, reply_markup: Any = None, **kw: Any
    ) -> bool:
        if self.edit_error is not None:
            raise self.edit_error
        assert message_id is not None
        self.edits.append((message_id, reply_markup))
        return True

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None, **kw: Any) -> bool:
        self.answers.append((callback_query_id, text))
        return True


async def inline_to_thread(fn: Any, /, *args: Any, **kw: Any) -> Any:
    """`asyncio.to_thread` 대신: 같은 스레드에서 바로 부른다(가짜 푸시 전송용)."""
    return fn(*args, **kw)


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


class BeEnv:
    def __init__(
        self, *, parts: BeParts, client: TestClient, clock: FakeClock, brain: FakeBrain, sender: FakeSender,
        conn: sqlite3.Connection, db_path: Path, deps: ApiDeps,
    ) -> None:
        self.parts = parts
        self.client = client
        self.clock = clock
        self.brain = brain
        self.sender = sender
        self.conn = conn
        self.db_path = db_path
        self.deps = deps
        self.push = parts.delivery.push
        parts.delivery.to_thread = inline_to_thread  # 가짜 전송은 바로 돈다(drain이 실제 스레드를 기다리지 않게)
        self.settings = deps.settings
        self.bot = RecordingBot()
        self._ids = itertools.count(1000)

    @classmethod
    @asynccontextmanager
    async def start(
        cls,
        tmp_path: Path,
        *,
        script: list[FakeTurn] | tuple[FakeTurn, ...] = (),
        start: datetime,
        overrides: dict[str, Any] | None = None,
        api_sleep: Any = None,
        push: Any = None,
        moments: bool = False,
        body_token: str | None = None,
    ) -> AsyncIterator[BeEnv]:
        """`push`: 가짜 푸시 전송(`FakePushSender`). 주면 꾸며 낸 VAPID 값으로 푸시를 켠다.

        `moments`: 하루 끝 이룬 순간 작업(SP8 6.2)을 켠다. 기본은 끔(`moments_paused = "1"`): 하루 tick이 두뇌
        시나리오를 쓰지 않게. 순간 시험만 켠다.

        `body_token`: `.env`의 `BODY_TOKEN` 자리(꾸며 낸 값). 주면 `app._body_token`의 규칙(43자 이상, `API_TOKEN`과
        다름)대로 `POST /body`를 연다. 기본은 None(경로 없음, 경고 없음)."""
        base: dict[str, Any] = {"api_token": TEST_TOKEN}
        if body_token is not None:
            base["body_token"] = body_token
        if push is not None:
            base["vapid"] = FAKE_VAPID
        settings = make_settings(tmp_path, **{**base, **(overrides or {})})
        db_path = settings.paths.state_dir / "planner.db"
        conn = open_db(db_path, on_write=ON_WRITE)
        migrate(conn)
        clock = FakeClock(start)
        brains: list[FakeBrain] = []
        senders: list[FakeSender] = []

        def brain_factory(tools: Any) -> FakeBrain:
            brains.append(FakeBrain(list(script), tools, clock=clock))
            return brains[0]

        def sender_factory(_tasks: Any) -> FakeSender:
            senders.append(FakeSender())
            return senders[0]

        parts = build_be(settings, conn, clock, brain_factory=brain_factory, sender_factory=sender_factory,
                         sleep=fake_sleep(clock), push_sender=push)
        before = to_iso(start - timedelta(minutes=1))
        parts.state.set("installed_at", before)
        parts.state.set("last_seen_at", before)
        if not moments:
            parts.state.set(MOMENTS_PAUSED_KEY, "1")
        deps = ApiDeps(
            settings=settings, clock=clock, token=TEST_TOKEN, read_conn=lambda: open_ro(db_path),
            dispatcher=parts.dispatcher, errors=ErrorCounter(clock),
            polling_state=lambda: "down" if parts.runner.polling_down else "running",
            started_at=start, transcripts=parts.transcripts,
            body_token=_body_token(settings, TEST_TOKEN) if body_token is not None else None,
            disk_free=lambda _path: DISK_FREE,
            **({"sleep": api_sleep} if api_sleep is not None else {}),
        )
        client = TestClient(TestServer(build_app(deps)))
        await client.start_server()
        parts.dispatcher.start()
        env = cls(parts=parts, client=client, clock=clock, brain=brains[0], sender=senders[0], conn=conn,
                  db_path=db_path, deps=deps)
        try:
            yield env
        finally:
            await parts.dispatcher.stop(timeout=5)
            await client.close()
            conn.close()

    # --- API ---

    async def request(self, method: str, path: str, *, token: str | None = TEST_TOKEN, **kw: Any) -> ClientResponse:
        """`path`가 `/api/`로 시작하지 않으면 `/api/v1`을 붙인다. `token=None`이면 인증 헤더 없이."""
        headers = dict(kw.pop("headers", {}) or {})
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        url = path if path.startswith("/api/") else API_PREFIX + path
        return await self.client.request(method, url, headers=headers, **kw)

    async def get(self, path: str, **kw: Any) -> ClientResponse:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> ClientResponse:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw: Any) -> ClientResponse:
        return await self.request("PUT", path, **kw)

    async def delete(self, path: str, **kw: Any) -> ClientResponse:
        return await self.request("DELETE", path, **kw)

    async def action(
        self, action: str, args: dict[str, Any] | None = None, *, client_msg_id: str | None = None,
        confirm_token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """`POST /actions`(즉시 갈래). `client_msg_id`를 주지 않으면 새로 만든다. (HTTP 상태, 본문)."""
        body = {
            "action": action, "args": args or {}, "client_msg_id": client_msg_id or f"cm-{next(self._ids)}",
            "confirm_token": confirm_token,
        }
        resp = await self.post("/actions", json=body)
        return resp.status, await resp.json()

    def chat_body(
        self, text: str | None = None, *, client_msg_id: str | None = None, conversation_id: int | None = None,
        checkin_id: int | None = None, parts: list[dict[str, Any]] | None = None, message_id: str = "msg-1",
        resume_conversation_id: int | None = None, chip: str | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = (
            {"resume_conversation_id": resume_conversation_id} if resume_conversation_id is not None else {}
        )
        if chip is not None:  # 퀵 칩(SP9c 4.1). 없으면 칸을 싣지 않는다
            extra["chip"] = chip
        return {
            **extra,
            "client_msg_id": client_msg_id or f"cm-{next(self._ids)}",
            "conversation_id": conversation_id,
            "checkin_id": checkin_id,
            "message": {
                "id": message_id, "role": "user",
                "parts": parts if parts is not None else [{"type": "text", "text": text or ""}],
            },
        }

    async def chat(self, text: str | None = None, **kw: Any) -> tuple[ClientResponse, bytes]:
        """`POST /chat`을 보내고 스트림을 끝까지 읽는다. 그다음 디스패처 큐가 빌 때까지 기다린다."""
        resp = await self.post("/chat", json=self.chat_body(text, **kw))
        raw = await resp.read()
        await self.drain()
        return resp, raw

    async def subscribe(self, endpoint: str, *, label: str | None = "폰") -> int:
        """`POST /push/subscriptions`(꾸며 낸 키). 구독 id."""
        body = {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": FAKE_P256DH, "auth": FAKE_AUTH},
                "label": label}
        resp = await self.post("/push/subscriptions", json=body)
        assert resp.status == 201, resp.status
        return (await resp.json())["id"]

    def activity(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM activity ORDER BY id").fetchall()

    # --- 텔레그램과 루프 ---

    async def telegram(self, text: str, *, sent_at: datetime | None = None) -> str:
        """사용자가 텔레그램에 글을 보낸다(SP1 `handle_update` 경로). 디스패처 큐가 빌 때까지 기다린다."""
        uid = next(self._ids)
        update = Update.de_json(
            {
                "update_id": uid,
                "message": {
                    "message_id": uid,
                    "date": _unix(sent_at or self.clock.now()),
                    "chat": {"id": OWNER, "type": "private"},
                    "from": {"id": OWNER, "is_bot": False, "first_name": "사용자"},
                    "text": text,
                },
            },
            self.bot,  # type: ignore[arg-type]
        )
        p = self.parts
        verdict = await handle_update(
            update, bot=self.bot, owner_id=self.settings.owner_telegram_id, state=p.state, dispatcher=p.dispatcher,
            transcripts=p.transcripts, clock=self.clock, tools=p.tools, callbacks=p.callbacks, router=p.router,
            sleep=fake_sleep(self.clock), apply=p.dispatcher.apply_action,
        )
        await self.drain()
        return verdict

    async def press(self, data: str, *, message_id: int | None = None, reply_markup: Any = None) -> str:
        """버튼을 누른다(가짜 `CallbackQuery` → `parts.callbacks`, 즉시 갈래 `apply_action`). 처리 결과 이름을 돌려준다.

        `reply_markup`: 누른 메시지에 붙어 있던 버튼(`InlineKeyboardMarkup`). 버튼 다시 그리기 시험이 준다."""
        uid = next(self._ids)
        markup = {"reply_markup": reply_markup.to_dict()} if reply_markup is not None else {}
        update = Update.de_json(
            {
                "update_id": uid,
                "callback_query": {
                    "id": f"cb{uid}",
                    "from": {"id": OWNER, "is_bot": False, "first_name": "사용자"},
                    "chat_instance": "ci",
                    "data": data,
                    "message": {
                        "message_id": message_id if message_id is not None else uid,
                        "date": _unix(self.clock.now()),
                        "chat": {"id": OWNER, "type": "private"},
                        "from": {"id": 1, "is_bot": True, "first_name": "비서"},
                        "text": "꾸민 회차 본문",
                        **markup,
                    },
                },
            },
            self.bot,  # type: ignore[arg-type]
        )
        assert update.callback_query is not None
        result = await self.parts.callbacks(update.callback_query)
        await self.drain()
        return result

    async def tick(self) -> None:
        self.parts.runner.tick()
        await self.drain()

    async def drain(self) -> None:
        """디스패처 큐가 비고 처리 중인 일이 없을 때까지 양보한다."""
        for _ in range(DRAIN_STEPS):
            await asyncio.sleep(0)
            if self.parts.dispatcher.idle:
                return
        raise AssertionError("BeEnv.drain: 디스패처가 끝내 쉬지 않았다")

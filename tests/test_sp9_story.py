"""SP9 수용 이야기 (스펙 1장 완료 조건 2·3·6·7·8·9·13의 BE 쪽). 가짜 두뇌·가짜 시계·가짜 푸시, 꾸며 낸 내용.

월요일(2026-10-26) 아침 메모·일정·대화(닫힘, 요약, 잇기, 지우기)를 거쳐 낮에 알림을 받고, 체크인 시간을 바꾸고(다음 날 09:30
브리핑), `.ics`를 본다.
"""

from __future__ import annotations

import json
from datetime import timedelta

from be_env import BeEnv
from fakes import FakePushSender, FakeTurn
from test_delivery import tick_at
from test_dispatcher_messages import kst

from my_planner.clock import to_iso
from my_planner.store.transcripts import ERASED_LINE

START = kst(2026, 10, 26, 8, 0)  # 월
UNIQUE = "청록색-하마-4417"  # 대화 A에만 있는 문자열
ENDPOINT = "https://push.example.invalid/sub/sp9-story"


def reminders(push: FakePushSender) -> list[tuple[str, str]]:
    return [(c.payload["title"], c.payload["body"]) for c in push.sent if c.payload["type"] == "reminder"]


def day_text(env, ymd: str) -> str:
    y, m, _ = ymd.split("-")
    return (env.settings.paths.data_dir / "transcripts" / y / m / f"{ymd}.md").read_text(encoding="utf-8")


async def test_sp9_story(tmp_path):
    push = FakePushSender()
    script = [
        FakeTurn([("create_memo", {"body": "장보기\n- 우유"})], f"알겠어요, {UNIQUE} 기억할게요.", session_id="sess-a"),
        FakeTurn([], "그것도요.", session_id="sess-a"),
        FakeTurn([], json.dumps({"title": "장보기 메모", "summary": "우유 사는 메모를 남겼어요. 다음에 할 일은 없어요."}, ensure_ascii=False)),
        FakeTurn([], "새 대화 답", session_id="sess-b"),
        FakeTurn([], "A를 이어요.", session_id="sess-a2"),
        FakeTurn([], "좋은 아침이에요"),  # 화 09:30 아침 브리핑
    ]
    async with BeEnv.start(tmp_path, start=START, script=script, push=push) as env:
        await env.subscribe(ENDPOINT)

        # --- 조건 6: 메모 만들기와 찾기 (월 08:00) ---
        status, made = await env.action("create_memo", {"body": "읽을 책\n- [ ] 사피엔스"})
        assert status == 200, made
        found = await (await env.get("/memos?q=사피")).json()
        assert [m["title"] for m in found["items"]] == ["읽을 책"]

        # --- 조건 2: 14:00 치과(30분 전), 16:00 미용실(30분 전) ---
        for title, at in (("치과", "14:00"), ("미용실", "16:00")):
            status, ev = await env.action("create_event", {"title": title, "date": "2026-10-26", "time": at, "remind_min": 30})
            assert status == 200, ev
        listed = await (await env.get("/events?start=2026-10-26&end=2026-10-26")).json()
        assert [e["title"] for e in listed["items"]] == ["치과", "미용실"]

        # --- 조건 7·8: 대화 A. 두뇌가 메모를 만들고 확인 줄이 붙는다 ---
        env.clock.set(kst(2026, 10, 26, 8, 10))
        resp, raw = await env.chat(f"이거 메모해줘 {UNIQUE}")
        a = int(resp.headers["x-conversation-id"])
        assert "✓ 메모를 만들었어요: 장보기" in raw.decode("utf-8")
        titles = [m["title"] for m in (await (await env.get("/memos")).json())["items"]]
        assert "장보기" in titles
        env.clock.advance(timedelta(minutes=2))
        resp, _ = await env.chat(f"{UNIQUE} 다시 한 번")
        assert int(resp.headers["x-conversation-id"]) == a

        # 30분 넘게 조용하면 닫히고, 비서가 제목과 요약을 붙인다 → 목록에 보인다
        env.clock.advance(timedelta(minutes=31))
        await env.tick()
        conv = env.parts.convs.get(a)
        assert conv.closed_at is not None and conv.title == "장보기 메모"
        items = (await (await env.get("/conversations?channel=app")).json())["items"]
        assert [i["id"] for i in items] == [a] and items[0]["title"] == "장보기 메모"

        # --- 조건 9: 새 대화 B의 첫 두뇌 입력에 A의 원문이 없다 ---
        n = len(env.brain.calls)
        resp, _ = await env.chat("완전히 새 얘기")
        b = int(resp.headers["x-conversation-id"])
        assert b != a and len(env.brain.calls) == n + 1
        first = env.brain.prompts[n]
        assert env.brain.session_ids[n] is None and "## 지금 상황" in first
        assert UNIQUE not in first and "장보기 메모" not in first and "우유 사는" not in first

        # --- 조건 8: 목록에서 A를 이어 말하면 같은 대화가 이어진다 ---
        resp, _ = await env.chat("A 이어서 얘기해요", resume_conversation_id=a)
        assert int(resp.headers["x-conversation-id"]) == a
        assert env.parts.convs.get(a).closed_at is None

        # --- 지우기: 원문 줄이 지워지고 목록에서 사라진다 ---
        assert UNIQUE in day_text(env, "2026-10-26")
        resp = await env.delete(f"/conversations/{a}")
        assert resp.status == 204
        text = day_text(env, "2026-10-26")
        assert UNIQUE not in text and "A 이어서" not in text and ERASED_LINE in text
        assert "완전히 새 얘기" in text  # 다른 대화는 남는다
        after = (await (await env.get("/conversations?channel=app")).json())["items"]
        assert a not in [i["id"] for i in after]
        assert (await env.get(f"/conversations/{a}/messages")).status == 404

        # 13:30 tick: 앱 푸시 "치과 · 14:00 (30분 뒤)"가 한 번
        await tick_at(env, kst(2026, 10, 26, 13, 30) + timedelta(seconds=30))
        await env.parts.runner.drain_reminders()
        assert reminders(push) == [("치과", "14:00 (30분 뒤)")]
        assert [c.payload["url"] for c in push.sent if c.payload["type"] == "reminder"] == ["/schedule/?date=2026-10-26"]
        await tick_at(env, kst(2026, 10, 26, 13, 31) + timedelta(seconds=30))
        await env.parts.runner.drain_reminders()
        assert len(reminders(push)) == 1  # 같은 알림은 다시 가지 않는다

        # --- 조건 3: 노트북이 15:20~15:45 꺼져 있었다 → 켜진 직후 "미용실 · 16:00 (15분 남았어요)" 한 번 ---
        env.parts.state.set("last_seen_at", to_iso(kst(2026, 10, 26, 15, 20)))
        env.clock.set(kst(2026, 10, 26, 15, 45))
        await env.tick()
        await env.parts.runner.drain_reminders()
        assert reminders(push) == [("치과", "14:00 (30분 뒤)"), ("미용실", "16:00 (15분 남았어요)")]
        outcomes = [tuple(r) for r in env.conn.execute("SELECT outcome FROM event_reminders ORDER BY event_id")]
        assert outcomes == [("sent",), ("late_sent",)]

        # --- 조건 13: 평일 아침을 09:30으로 바꾼다 (월 15:50 → 내일부터) ---
        env.clock.set(kst(2026, 10, 26, 15, 50))
        resp = await env.put("/settings/checkin-times", json={"loop": "morning_brief", "day_type": "weekday", "time": "09:30"})
        body = await resp.json()
        assert resp.status == 200, body
        assert body["applies"] == "tomorrow"
        assert body["items"][0]["time"] == "09:30" and body["items"][0]["from"] == "2026-10-27"
        calls_before = len(env.brain.calls)
        await tick_at(env, kst(2026, 10, 27, 9, 0) + timedelta(seconds=30))
        assert len(env.brain.calls) == calls_before  # 옛 시각 09:00에는 브리핑이 없다
        await tick_at(env, kst(2026, 10, 27, 9, 30) + timedelta(seconds=30))  # 재시작 없이 09:30에
        assert len(env.brain.calls) == calls_before + 1
        health = await (await env.get("/health")).json()
        (brief,) = [r for r in health["runs_today"] if r["loop"] == "morning_brief"]
        assert brief["scheduled_for"] == "2026-10-27T00:30:00Z"  # KST 09:30

        # --- 조건 5: 구독 주소의 .ics에 일정이 있다(메모는 없다) ---
        resp = await env.post("/settings/calendar", json={"rotate": False})
        key = (await resp.json())["url"].split("key=")[1]
        resp = await env.get(f"/api/v1/calendar.ics?key={key}", token=None)
        ics = await resp.text()
        assert resp.status == 200
        assert "SUMMARY:치과" in ics and "SUMMARY:미용실" in ics
        assert "사피엔스" not in ics and UNIQUE not in ics

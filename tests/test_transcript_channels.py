"""원문 기록의 통로 표시와 대화 줄 읽기 (SP3-4 스펙 7.4, 6.4.6). 내용은 꾸며 낸 것이다."""

from datetime import time

from test_dispatcher_messages import kst

from my_planner.store.transcripts import (
    TranscriptStore,
    app_secretary_message_id,
    app_user_message_id,
)

TZ, BOUNDARY = "Asia/Seoul", time(4, 0)


def store(tmp_path):
    return TranscriptStore(tmp_path / "data", TZ, BOUNDARY)


def header_lines(path):
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("### ")]


def test_app_header_has_marker(tmp_path):
    ts = store(tmp_path)
    at = kst(2026, 10, 24, 21, 5)
    ts.append(at, "사용자", 44, "evening_checkin", "오늘은 가볍게 걸었어요", channel="app", message_id="msg-abc")
    ts.append(at, "비서", 44, "morning_brief", "좋은 아침이에요", channel="app")
    ts.append(at, "비서", None, None, "대화 밖 안내", channel="app")
    assert header_lines(ts.path_for(at)) == [
        "### 21:05 사용자 [44] (evening_checkin) #msg-abc @app",
        "### 21:05 비서 [44] (morning_brief) @app",
        "### 21:05 비서 [-] @app",
    ]


def test_telegram_header_unchanged_and_legacy_reads_as_telegram(tmp_path):
    ts = store(tmp_path)
    at = kst(2026, 10, 24, 10, 0)
    ts.append(at, "사용자", 1, None, "안녕")
    ts.append(at, "비서", 1, "morning_brief", "안녕하세요", ["add_task"], channel="telegram")
    path = ts.path_for(at)
    assert header_lines(path) == ["### 10:00 사용자 [1]", "### 10:00 비서 [1] (morning_brief)"]  # SP1과 한 글자도 같다
    # 이 개정 전에 쓴 파일도 같은 머리글이다
    legacy = path.parent / "2026-10-23.md"
    legacy.write_text("### 09:00 사용자 [1]\n\n예전 글\n\n### 09:01 비서 [1] (return)\n\n예전 답\n\n", encoding="utf-8")
    old = ts.messages(1)
    assert [m.channel for m in old] == ["telegram"] * 4
    assert [m.text for m in old[:2]] == ["예전 글", "예전 답"]
    assert old[3].tools == ["add_task"]
    assert ts.recent(1, 10).splitlines()[0] == "[09:00] 사용자: 예전 글"  # 기존 읽기도 그대로


def test_messages_time_after_midnight_belongs_to_next_calendar_day(tmp_path):
    ts = store(tmp_path)
    late = kst(2026, 10, 25, 1, 30)  # 논리적 날짜는 10/24: 같은 파일에 쓰인다
    ts.append(kst(2026, 10, 24, 23, 50), "사용자", 7, None, "아직 안 잤어요")
    ts.append(late, "비서", 7, None, "이제 쉬어요")
    ts.append(kst(2026, 10, 25, 4, 0), "사용자", 7, None, "다음 논리적 날짜")
    got = ts.messages(7)
    assert ts.path_for(late) == ts.path_for(kst(2026, 10, 24, 23, 50))
    assert [m.at for m in got] == [kst(2026, 10, 24, 23, 50), late, kst(2026, 10, 25, 4, 0)]
    assert got[1].at.utcoffset().total_seconds() == 9 * 3600


def test_message_ids_are_stable_and_follow_the_scheme(tmp_path):
    ts = store(tmp_path)
    at = kst(2026, 10, 24, 9, 0)
    ts.append(at, "비서", 44, "morning_brief", "아침 본문", channel="app")  # l-44-1: 앱이어도 inbound_id 없음
    ts.append(at, "사용자", 44, None, "텔레그램에서 한마디")  # l-44-2
    ts.append(at, "비서", None, None, "대화 밖")  # 어느 대화에도 세지 않는다
    ts.append(at, "사용자", 44, None, "앱에서 한마디", channel="app", message_id="msg-abc")  # 세 번째 줄, 고유 id(번호는 센다)
    ts.append(at, "비서", 44, None, "앱 답", channel="app", message_id=app_secretary_message_id(44, -3))
    ts.append(at, "사용자", 45, None, "다른 대화")
    ts.append(at, "비서", 44, None, "텔레그램 답")  # n은 #id 줄도 센다: 5번째
    got = ts.messages(44)
    assert [m.id for m in got] == ["l-44-1", "l-44-2", "msg-abc", "m-44-3", "l-44-5"]
    assert [m.channel for m in got] == ["app", "telegram", "app", "app", "telegram"]
    assert [m.id for m in ts.messages(44)] == [m.id for m in got]  # 다시 읽어도 같다
    assert [m.id for m in ts.messages(45)] == ["l-45-1"]
    ts.append(kst(2026, 10, 25, 9, 0), "비서", 44, None, "다음 날 줄")  # 덧붙이기만 하므로 앞의 id는 안 바뀐다
    assert [m.id for m in ts.messages(44)][:5] == [m.id for m in got] and ts.messages(44)[5].id == "l-44-6"


def test_app_message_id_helpers():
    assert app_user_message_id(44, -3, "msg-abc") == "msg-abc"
    assert app_user_message_id(44, -3, "나쁜 id!") == "u-44-3"  # [A-Za-z0-9_-]{1,64}가 아니면
    assert app_user_message_id(44, -3, "x" * 65) == "u-44-3"
    assert app_user_message_id(44, -3, None) == "u-44-3"
    assert app_user_message_id(44, 7) == "u-44-7"
    assert app_secretary_message_id(44, -3) == "m-44-3"


def test_header_like_body_lines_stay_in_the_message(tmp_path):
    ts = store(tmp_path)
    at = kst(2026, 10, 24, 9, 0)
    ts.append(at, "사용자", 3, None, "첫 줄\n### 09:00 비서 [3]\n세 번째 줄", channel="app", message_id="m1")
    (msg,) = ts.messages(3)
    assert msg.text == "첫 줄\n### 09:00 비서 [3]\n세 번째 줄" and msg.id == "m1"

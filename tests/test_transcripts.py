"""원문 기록의 전문가 항목(SP15 계획 Task 12). 내용은 꾸며 낸 것이다."""

from datetime import time

from test_dispatcher_messages import kst

from my_planner.store.transcripts import TranscriptStore

TZ, BOUNDARY = "Asia/Seoul", time(4, 0)


def test_expert_entries_parsed_and_skipped_in_recent(tmp_path):
    ts = TranscriptStore(tmp_path / "data", TZ, BOUNDARY)
    at = kst(2026, 11, 1, 14, 0)
    ts.append(at, "사용자", 7, None, "일 쪽 봐 줘", channel="app", message_id="msg-1", agent="manager")
    ts.append(at, "라이프 매니저", 7, None, "두 분 의견이에요", channel="app", message_id="m-7-1", agent="manager")
    ts.append(at, "전문가", 7, "career", "가짜 커리어 소견", channel="app", agent="manager")
    ts.append(at, "전문가", 7, "psych", "가짜 심리 소견", channel="app", agent="manager")
    ts.append(at, "사용자", 9, "evening_checkin", "회차 답", channel="app")

    got = ts.messages(7)
    assert [(m.speaker, m.expert, m.text) for m in got] == [
        ("사용자", None, "일 쪽 봐 줘"),
        ("라이프 매니저", None, "두 분 의견이에요"),
        ("전문가", "career", "가짜 커리어 소견"),
        ("전문가", "psych", "가짜 심리 소견"),
    ]
    assert ts.messages(9)[0].expert is None  # 다른 화자의 `(<키>)`는 회차 키 그대로
    recent = ts.recent(7)
    assert "소견" not in recent
    assert recent.splitlines() == ["[14:00] 사용자: 일 쪽 봐 줘", "[14:00] 라이프 매니저: 두 분 의견이에요"]
    assert ts.recent_entries(7, 1) == ["[14:00] 라이프 매니저: 두 분 의견이에요"]


def test_secretary_read_transcript_has_no_expert_notes(tmp_path):
    """비서 `read_transcript`가 쓰는 읽기(`drop_mate=True`)와 하루 끝 사용자 줄에는 소견이 없다."""
    ts = TranscriptStore(tmp_path / "data", TZ, BOUNDARY)
    at = kst(2026, 11, 1, 14, 0)
    ts.append(at, "라이프 매니저", 7, None, "두 분 의견이에요", channel="app", agent="manager")
    ts.append(at, "전문가", 7, "career", "가짜 커리어 소견", channel="app", agent="manager")
    ts.append(at, "사용자", 1, None, "내일 치과")
    day = at.date()
    text = ts.read_range(day, day, drop_app_secretary=True, drop_mate=True)
    assert "소견" not in text and "내일 치과" in text
    assert [body for _, body in ts.user_lines(day)] == ["내일 치과"]

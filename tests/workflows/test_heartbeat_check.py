"""watch.yml의 하트비트 확인 (스펙 3.5)과 PAT 만료 알림 (스펙 4.2). watch는 2시간 cron이다."""

from __future__ import annotations

from datetime import UTC, datetime

import gh
import heartbeat_check
from medic.fakes import FakeGitHub, FakeHttp

NOTICE = "노트북 응답이 없어요. 꺼짐·잠자기·고장 중 하나예요. 지나간 회차는 켜지면 따라잡아요."


def _env(body: str):
    server = FakeGitHub()
    http = FakeHttp(route=server.route)
    n = server.add_issue("heartbeat", ["heartbeat"], body=body)
    return server, gh.Api("tok", "o/r", http=http), n


def _body(last_seen: str, next_run: str) -> str:
    # medic watcher._heartbeat가 쓰는 틀 그대로
    return f"last_seen: {last_seen}, sha: abc1234, next_run: {next_run}"


def _at(h: int, m: int, day: int = 26) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=UTC)


def test_heartbeat_alert_only_after_next_run_passed():
    # 2026-10-26(월) 저녁 체크인 17:30 KST = 08:30 UTC. 마지막 하트비트 14:00 KST
    server, api, n = _env(_body("2026-10-26T05:00:00Z", "2026-10-26T08:30:00Z"))
    # 08:07 UTC 실행: 3시간 넘게 조용하지만 회차가 아직 안 지났다(잠자기, P1)
    assert heartbeat_check.check(api, now=_at(8, 7), pat_expires=None) == []
    # 다음 실행(2시간 뒤 10:07 UTC): 회차가 지났다 → 알림
    assert heartbeat_check.check(api, now=_at(10, 7), pat_expires=None) == [NOTICE]
    assert "stale-2026-10-26" in server.labels(n)


def test_heartbeat_fresh_last_seen_no_alert_even_if_run_passed():
    # 회차가 지났어도 하트비트가 45분 안이면 노트북은 살아 있다(회차 지연은 medic이 본다)
    _server, api, _ = _env(_body("2026-10-26T09:40:00Z", "2026-10-26T08:30:00Z"))
    assert heartbeat_check.check(api, now=_at(10, 7), pat_expires=None) == []


def test_heartbeat_stale_threshold_is_45_minutes():
    _server, api, _ = _env(_body("2026-10-26T09:22:00Z", "2026-10-26T08:30:00Z"))
    assert heartbeat_check.check(api, now=_at(10, 7), pat_expires=None) == []  # 45분
    assert heartbeat_check.check(api, now=_at(10, 8), pat_expires=None) == [NOTICE]  # 46분


def test_heartbeat_once_per_day():
    server, api, n = _env(_body("2026-10-26T05:00:00Z", "2026-10-26T08:30:00Z"))
    assert heartbeat_check.check(api, now=_at(10, 7), pat_expires=None) == [NOTICE]
    assert heartbeat_check.check(api, now=_at(12, 7), pat_expires=None) == []
    # 서울 날짜가 바뀌면(15:00 UTC = 다음날 00:00 KST) 다시 한 번
    assert heartbeat_check.check(api, now=_at(16, 7), pat_expires=None) == [NOTICE]
    assert "stale-2026-10-27" in server.labels(n)


def test_heartbeat_unreadable_body_or_no_issue_is_silent():
    _server, api, _ = _env("이상한 본문")
    assert heartbeat_check.check(api, now=_at(10, 7), pat_expires=None) == []
    empty = gh.Api("tok", "o/r", http=FakeHttp(route=FakeGitHub().route))
    assert heartbeat_check.check(empty, now=_at(10, 7), pat_expires="2026-11-01") == []


def test_pat_expiry_reminder_30_days():
    body = _body("2026-10-26T09:50:00Z", "2026-12-31T00:00:00Z")  # 회차가 안 지나 응답 없음 알림은 없다
    # 만료 31일 전: 아직
    server, api, _ = _env(body)
    assert heartbeat_check.check(api, now=_at(10, 7), pat_expires="2026-11-26") == []
    # 만료 30일 전: 하루 한 번
    server, api, n = _env(body)
    assert heartbeat_check.check(api, now=_at(10, 7), pat_expires="2026-11-25") == ["GitHub 토큰이 2026-11-25에 만료돼요"]
    assert heartbeat_check.check(api, now=_at(12, 7), pat_expires="2026-11-25") == []
    # 다음 날(서울): 다시, 어제 표시는 지운다
    assert heartbeat_check.check(api, now=_at(16, 7), pat_expires="2026-11-25") == ["GitHub 토큰이 2026-11-25에 만료돼요"]
    assert [x for x in server.labels(n) if x.startswith("pat-")] == ["pat-reminded-2026-10-27"]


def test_pat_expiry_other_tokens_and_bad_dates():
    body = _body("2026-10-26T09:50:00Z", "2026-12-31T00:00:00Z")
    _server, api, _ = _env(body)
    msgs = heartbeat_check.check(
        api, now=_at(10, 7), pat_expires="nope",
        more_pats={"RELEASE_PAT": "2026-11-01", "DEV_PAT": None, "X": ""},
    )
    assert msgs == ["GitHub 토큰(RELEASE_PAT)이 2026-11-01에 만료돼요"]


# --- 고침 1회차 (리뷰 M4, M6) ----------------------------------------------------------


def test_notice_survives_failure_in_pat_block():
    _server, api, n = _env(_body("2026-10-26T05:00:00Z", "2026-10-26T08:30:00Z"))
    http = api._http
    route = http.route

    def failing(m, url, json):
        if m == "POST" and url.endswith(f"/issues/{n}/labels") and "pat-reminded" in str(json):
            return 502, None, {}
        return route(m, url, json)

    http.route = failing
    msgs = heartbeat_check.check(api, now=_at(10, 7), pat_expires="2026-11-01")
    assert msgs == [NOTICE]  # PAT 쪽이 실패해도 응답 없음 알림은 간다


def test_past_date_labels_are_deleted_from_repo():
    server, api, n = _env(_body("2026-10-26T05:00:00Z", "2026-10-26T08:30:00Z"))
    server.issues[n]["labels"] += [{"name": "stale-2026-10-24"}, {"name": "pat-reminded-2026-10-25"}]
    heartbeat_check.check(api, now=_at(10, 7), pat_expires="2026-11-01")
    assert sorted(server.deleted_labels) == ["pat-reminded-2026-10-25", "stale-2026-10-24"]

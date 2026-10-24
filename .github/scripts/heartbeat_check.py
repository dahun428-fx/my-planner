"""watch.yml의 하트비트 확인 (스펙 3.5)과 PAT 만료 알림 (스펙 4.2). 보낼 텔레그램 글을 돌려준다.

medic은 30분마다 고정 이슈 "heartbeat"의 본문을 `last_seen: <UTC>, sha: <커밋>, next_run: <UTC>`로 바꾼다.
- `last_seen`이 45분보다 오래되었고 **`next_run`이 이미 지났으면** "노트북 응답 없음". 회차가 아직이면 잠자기로 보고
  보내지 않는다(P1). 확인 간격(2시간 cron)과 상관없이 같은 조건이라, 회차 시각을 지난 뒤 첫 실행이 보낸다.
- 서울 하루에 한 번: 이슈의 `stale-YYYY-MM-DD` 라벨(medic이 지난 날 것을 지운다).
- PAT 만료 30일 전부터 하루 한 번: 이슈의 `pat-reminded-YYYY-MM-DD` 라벨.
- 지난 날의 날짜 라벨(`stale-*`, `pat-reminded-*`)은 저장소 라벨째 지운다(라벨 목록이 날마다 늘지 않게).
  지우기와 PAT 쪽 API가 실패해도 이미 정한 응답 없음 알림은 돌려준다.
heartbeat 이슈가 없으면(medic이 아직 안 돌았다) 아무것도 보내지 않는다.

라벨을 먼저 달고 글을 돌려준다: 보내기가 실패하면 그날은 놓친다(두 번 보내느니 한 번 놓친다).
"""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import gh
import notify_telegram

STALE_AFTER = timedelta(minutes=45)
PAT_WARN = timedelta(days=30)
NOTICE = "노트북 응답이 없어요. 꺼짐·잠자기·고장 중 하나예요. 지나간 회차는 켜지면 따라잡아요."
PAT_TEXT = "GitHub 토큰이 {date}에 만료돼요"
PAT_TEXT_NAMED = "GitHub 토큰({name})이 {date}에 만료돼요"
PAT_MARK = "pat-reminded-"
_PAT_RE = re.compile(r"^pat-reminded-(\d{4}-\d{2}-\d{2})$")
_BODY = re.compile(r"last_seen: (\S+), sha: \S*, next_run: (\S+)")


def _utc(raw: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def parse_body(body: str) -> tuple[datetime, datetime] | None:
    """(last_seen, next_run). 틀이 다르면 None."""
    m = _BODY.search(body or "")
    if m is None:
        return None
    last, nxt = _utc(m[1]), _utc(m[2])
    return (last, nxt) if last is not None and nxt is not None else None


def _expiry(raw: str | None) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def check(
    api: gh.Api, *, now: datetime, pat_expires: str | None, more_pats: dict[str, str | None] | None = None,
) -> list[str]:
    found = api.issues(gh.HEARTBEAT)
    if not found:
        return []
    issue = min(found, key=lambda i: int(i["number"]))  # medic과 같은 이슈
    n = int(issue["number"])
    labels = gh.label_names(issue)
    today = now.astimezone(ZoneInfo(gh.TZ)).date()
    out: list[str] = []

    seen = parse_body(str(issue.get("body") or ""))
    stale_mark = f"stale-{today.isoformat()}"
    if seen is not None and stale_mark not in labels:
        last_seen, next_run = seen
        if now - last_seen > STALE_AFTER and now >= next_run:
            api.add_labels(n, [stale_mark])
            out.append(NOTICE)

    try:
        _drop_past_labels(api, labels, today)
        out += _pat_notices(api, n, labels, today, pat_expires, more_pats)
    except gh.ApiError as exc:
        print(f"heartbeat: label work failed ({exc.status})")
    return out


def _drop_past_labels(api: gh.Api, labels: list[str], today: date) -> None:
    for label in labels:
        m = gh.STALE_RE.match(label) or _PAT_RE.match(label)
        if m is None:
            continue
        day = _expiry(m[1])
        if day is not None and day < today:
            api.call("DELETE", f"/labels/{quote(label, safe='')}", ok_missing=True)


def _pat_notices(
    api: gh.Api, n: int, labels: list[str], today: date, pat_expires: str | None,
    more_pats: dict[str, str | None] | None,
) -> list[str]:
    out: list[str] = []
    pats = [(None, pat_expires), *sorted((more_pats or {}).items())]
    due = [
        (name, exp) for name, raw in pats
        if (exp := _expiry(raw)) is not None and today >= exp - PAT_WARN
    ]
    pat_mark = f"{PAT_MARK}{today.isoformat()}"
    if due and pat_mark not in labels:
        api.add_labels(n, [pat_mark])
        for name, exp in due:
            text = PAT_TEXT if name is None else PAT_TEXT_NAMED.format(name=name, date="{date}")
            out.append(text.format(date=exp.isoformat()))
    return out


def main() -> int:
    api = gh.from_env()
    msgs = check(
        api, now=datetime.now(UTC), pat_expires=os.environ.get("PAT_EXPIRES"),
        more_pats={
            "RELEASE_PAT": os.environ.get("RELEASE_PAT_EXPIRES"),
            "DEV_PAT": os.environ.get("DEV_PAT_EXPIRES"),
        },
    )
    results = [notify_telegram.send(m) for m in msgs]  # 하나가 실패해도 나머지는 보낸다
    ok = all(results)
    print(f"heartbeat: {len(msgs)} notice(s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

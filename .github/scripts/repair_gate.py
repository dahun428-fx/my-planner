"""repair.yml 시작 전 검사 (스펙 4.3). Claude 없이 이 셸 단계가 한다.

- `AUTO_REPAIR`가 `off`면 멈춤(`stop_off`).
- 열린 `incident` 이슈가 아니거나, 이미 `needs-dahun`·`merged`이면 할 일 없음(`skip`). `full`에서 이미
  `repairing`이면(다른 시도 중) `skip`, `merge_only`(sweep이 죽은 시도의 머지만 다시)에서는 `repairing`이 있어야 한다.
- 실패 수(`failed-N`의 가장 큰 N)가 한도 이상이거나 오늘(서울) 머지된 `auto-repair` PR이 한도 이상이면
  `needs-dahun`을 달고 "못 고쳤어요"를 텔레그램으로 한 번 보낸다(`gave_up`).
- 통과하면 `full`은 `repairing`을 단다(`go`), `merge_only`는 그대로(`merge_only`).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import gh
import notify_telegram

Decision = Literal["go", "merge_only", "stop_off", "gave_up", "skip"]
Mode = Literal["full", "merge_only"]


def merges_today(api: gh.Api, now: datetime) -> int:
    """`auto-repair` 라벨 PR 중 `merged_at`이 서울 달력으로 오늘인 것."""
    tz = ZoneInfo(gh.TZ)
    today = now.astimezone(tz).date()
    n = 0
    for pr in api.pulls("closed"):
        at = pr.get("merged_at")
        if not at or gh.AUTO_REPAIR_LABEL not in gh.label_names(pr):
            continue
        merged = datetime.fromisoformat(str(at))
        if merged.astimezone(tz).date() == today:
            n += 1
    return n


def attempt(labels: list[str]) -> int:
    """이번 시도 번호 = 실패 수 + 1 (브랜치 `auto-repair/<이슈>-<시도>`)."""
    return gh.failures(labels) + 1


def gate(
    api: gh.Api,
    issue: int,
    *,
    now: datetime,
    auto_repair: str,
    max_failures: int,
    max_merges: int,
    mode: Mode = "full",
    send: Callable[[str], object] = notify_telegram.send,
) -> Decision:
    if auto_repair.strip().lower() == "off":
        return "stop_off"
    item = api.issue(issue)
    labels = gh.label_names(item)
    if item.get("state") != "open" or gh.INCIDENT not in labels:
        return "skip"  # record 이슈, 닫힌 이슈, 하트비트 등
    if gh.NEEDS_DAHUN in labels or gh.MERGED in labels:
        return "skip"
    if (gh.REPAIRING in labels) != (mode == "merge_only"):
        return "skip"
    if gh.failures(labels) >= max_failures or merges_today(api, now) >= max_merges:
        # 라벨을 먼저 단다: 라벨이 실패하면 알림도 없고, 다음 실행이 다시 한다(알림은 한 번만)
        api.add_labels(issue, [gh.NEEDS_DAHUN])
        if gh.REPAIRING in labels:
            api.remove_label(issue, gh.REPAIRING)
        state = gh.ROLLED_BACK_TEXT if gh.ROLLED_BACK in labels else gh.AS_IS_TEXT
        send(gh.GAVE_UP_TEXT.format(fp=gh.fingerprint(item), state=state, url=api.issue_url(issue)))
        return "gave_up"
    if mode == "merge_only":
        return "merge_only"
    api.add_labels(issue, [gh.REPAIRING])
    return "go"


def outputs(decision: str, issue: int, labels: list[str]) -> dict[str, str]:
    """다음 작업에 넘길 값. 숫자와 정해진 낱말만(이슈 제목·본문은 넘기지 않는다)."""
    part = next((x for x in labels if x in gh.PART_LABELS), "")
    retry = gh.ROLLED_BACK in labels or gh.RECURRED in labels
    return {
        "decision": decision, "issue": str(issue), "attempt": str(attempt(labels)),
        "retry": "true" if retry else "false", "part": part,
    }


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() else default


def main() -> int:
    issue = int(os.environ["ISSUE"])  # 숫자가 아니면 여기서 멈춘다
    mode: Mode = "merge_only" if os.environ.get("MODE") == "merge_only" else "full"
    api = gh.from_env()
    sent: list[bool] = []

    def send(text: str) -> None:
        sent.append(notify_telegram.send(text))

    decision = gate(
        api, issue, now=datetime.now(UTC), auto_repair=os.environ.get("AUTO_REPAIR", "on"),
        max_failures=_int_env("REPAIR_MAX_FAILURES", 2), max_merges=_int_env("REPAIR_MAX_MERGES_PER_DAY", 3),
        mode=mode, send=send,
    )
    gh.set_output(**outputs(decision, issue, gh.label_names(api.issue(issue))))
    print(f"gate: {decision}")
    return 1 if sent and not all(sent) else 0  # 알림을 못 보냈으면 실행을 빨갛게 남긴다


if __name__ == "__main__":
    sys.exit(main())

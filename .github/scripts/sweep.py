"""watch.yml의 sweep (스펙 4.3 `repair-sweep` 규칙). 2시간마다.

열린 `incident` 이슈마다:
- `needs-dahun`·`merged`이면 건너뜀. 그 이슈의 repair.yml 실행이 대기·진행 중이어도 건너뜀.
- `repairing`이 아니면 `dispatch`(이벤트를 놓쳤거나 줄이 밀린 경우. 한도 검사는 게이트가 한다).
- `repairing`인데 실행이 없으면 죽은 시도다:
  - 이번 시도의 PR이 이미 머지됐으면(머지 뒤 라벨 일에서 죽음) `mark_merged`(`merged` 달고 `repairing` 떼기).
  - 열린 수리 PR의 CI가 초록이면 `merge_only`(같은 PR 재사용).
  - CI가 아직 돌면 다음 sweep까지 기다림. 단 PR이 6시간 넘게 그대로인데 끝난 `ci`가 없으면 `abandon`.
  - 아니면 `abandon`(PR 닫기, 브랜치 지우기, `failed-<시도>`, `repairing` 떼기).
- 그 이슈의 실행이 방금(10분 안) 끝났으면 건너뛴다(라벨 정리가 막 끝나는 중일 수 있다).

실행과 이슈는 repair.yml의 `run-name: repair #<이슈>`(실행의 `display_title`)로 잇는다.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Literal

import gh
import repair_merge

Action = tuple[Literal["dispatch", "merge_only", "abandon", "mark_merged"], int]
SETTLE = timedelta(minutes=10)
STUCK = timedelta(hours=6)  # 이만큼 CI 결과가 안 나오면 멈춘 PR로 본다
_RUN_TITLE = re.compile(r"^repair #(\d+)$")


def _age(item: dict, now: datetime) -> timedelta | None:
    raw = item.get("updated_at")
    return now - datetime.fromisoformat(str(raw)) if raw else None


def _ended_recently(run: dict, now: datetime) -> bool:
    age = _age(run, now)
    return age is not None and age < SETTLE


def live_issues(api: gh.Api, now: datetime) -> set[int]:
    """대기·진행 중이거나 방금 끝난 repair.yml 실행의 이슈 번호."""
    body = api.call("GET", f"/actions/workflows/{gh.REPAIR_WORKFLOW}/runs", query={"per_page": 100})
    runs = body.get("workflow_runs") if isinstance(body, dict) else None
    out: set[int] = set()
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        if run.get("status") == "completed" and not _ended_recently(run, now):
            continue
        m = _RUN_TITLE.match(str(run.get("display_title", "")))
        if m:
            out.add(int(m[1]))
    return out


def sweep(api: gh.Api, *, now: datetime) -> list[Action]:
    live = live_issues(api, now)
    actions: list[Action] = []
    for issue in api.issues(gh.INCIDENT):
        n = int(issue["number"])
        labels = gh.label_names(issue)
        if gh.NEEDS_DAHUN in labels or gh.MERGED in labels or n in live:
            continue
        if gh.REPAIRING not in labels:
            actions.append(("dispatch", n))
            continue
        if repair_merge.merged_this_attempt(api, n):
            actions.append(("mark_merged", n))
            continue
        pr = repair_merge.find_pr(api, n)
        state = "failure"
        if pr is not None:
            state = repair_merge.ci_state(api, str(pr["head"]["sha"]), str(pr["head"]["ref"]))
            age = _age(pr, now)
            if state == "pending" and age is not None and age > STUCK:
                state = "failure"
        if state == "success":
            actions.append(("merge_only", n))
        elif state == "failure":
            actions.append(("abandon", n))
    return actions


def apply(api: gh.Api, actions: list[Action], *, auto_repair: str) -> None:
    """`AUTO_REPAIR=off`면 정리(`abandon`)만 하고 수리를 부르지 않는다."""
    off = auto_repair.strip().lower() == "off"
    for kind, n in actions:
        if kind == "abandon":
            repair_merge.abandon(api, n)
        elif kind == "mark_merged":
            pr = repair_merge.merged_this_attempt(api, n)
            repair_merge.mark_merged(api, n, pr if isinstance(pr, dict) else None)
        elif not off:
            mode = "merge_only" if kind == "merge_only" else "full"
            api.call("POST", f"/actions/workflows/{gh.REPAIR_WORKFLOW}/dispatches", json={
                "ref": gh.BASE, "inputs": {"issue": str(n), "mode": mode},
            })
        skipped = off and kind in ("dispatch", "merge_only")
        print(f"sweep: {kind} #{n}{' (off)' if skipped else ''}")


def main() -> int:
    if gh.no_token():
        return 0
    api = gh.from_env()
    apply(api, sweep(api, now=datetime.now(UTC)), auto_repair=os.environ.get("AUTO_REPAIR", "on"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

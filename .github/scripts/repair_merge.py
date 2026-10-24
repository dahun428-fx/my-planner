"""repair.yml 머지 단계와 정리 (스펙 4.3). Claude 없이 이 셸 단계가 한다.

- `merge`: PR 머리 커밋의 `ci.yml` 실행(`pull_request` 이벤트, 그 PR 브랜치)이 끝날 때까지 기다려
  `GET /actions/runs?head_sha=`로 결과를 직접 본다(필수 검사 설정에 기대지 않는다, 10장 S6). 성공이면 squash 머지,
  커밋 본문 `Repairs #<이슈>`. 머지가 되면 **라벨 일보다 먼저** 결과(`merged`)를 남기고, 그다음 이슈에 `merged`,
  `repairing` 떼기, 브랜치 지우기 순서로 한다.
- `settle`: 이번 시도가 머지·시간 초과·취소가 아니면(CI 두 번 실패, PR 없음, 단계 실패) 먼저 이번 시도의 PR이
  이미 머지됐는지 본다(머지 뒤 라벨 일에서 죽은 경우). 머지됐으면 `merged`로 끝내고, 아니면 PR을 닫고 브랜치를
  지우고 `failed-<시도>`를 달고 `repairing`을 뗀다. 다음 시도는 watch.yml의 sweep이 집는다.
  시간 초과·취소(동시성 밀림)는 `repairing`을 둔다: sweep이 PR의 실제 CI를 보고 머지만 다시 하거나 정리한다.

"이번 시도"는 이슈에 `repairing`이 마지막으로 달린 뒤 머지된 `auto-repair/<이슈>-*` PR이다(이슈 이벤트로 본다).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

import gh

Result = Literal["merged", "ci_failed", "timeout"]
CiState = Literal["success", "failure", "pending"]
CI_PATH = ".github/workflows/ci.yml"
_PENDING_CONCLUSIONS = ("cancelled", "skipped", "stale", "neutral", None)  # 끝난 판정이 아니다: 다시 본다


def ci_state(api: gh.Api, sha: str, branch: str | None = None) -> CiState:
    """그 SHA의 `ci.yml` PR 실행(브랜치를 주면 그 브랜치) 중 가장 새 것. 없거나 안 끝났으면 `pending`."""
    runs = [
        r for r in api.ci_runs(sha, "pull_request")
        if str(r.get("path", "")).split("@")[0] == CI_PATH
        and (branch is None or r.get("head_branch") == branch)
    ]
    if not runs:
        return "pending"
    run = max(runs, key=lambda r: (str(r.get("created_at", "")), int(r.get("id") or 0)))
    if run.get("status") != "completed" or run.get("conclusion") in _PENDING_CONCLUSIONS:
        return "pending"
    return "success" if run.get("conclusion") == "success" else "failure"


def _ours(api: gh.Api, pr: dict[str, Any], issue: int) -> bool:
    head = pr.get("head") or {}
    repo = (head.get("repo") or {}).get("full_name")
    return str(head.get("ref", "")).startswith(f"{gh.BRANCH_PREFIX}{issue}-") and repo == api.repo  # 포크 제외


def find_pr(api: gh.Api, issue: int, state: str = "open") -> dict[str, Any] | None:
    """`main` 대상, 이 저장소의 브랜치 `auto-repair/<이슈>-*`인 PR 중 가장 새 것."""
    found = [p for p in api.pulls(state) if _ours(api, p, issue)]
    return max(found, key=lambda p: int(p["number"])) if found else None


def _repairing_since(api: gh.Api, issue: int) -> datetime | None:
    """이슈에 `repairing`이 마지막으로 달린 시각(이슈 이벤트 최근 100개)."""
    body = api.call("GET", f"/issues/{issue}/events", query={"per_page": 100})
    times = [
        datetime.fromisoformat(str(e["created_at"]))
        for e in (body if isinstance(body, list) else [])
        if isinstance(e, dict) and e.get("event") == "labeled" and e.get("created_at")
        and (e.get("label") or {}).get("name") == gh.REPAIRING
    ]
    return max(times) if times else None


def merged_this_attempt(api: gh.Api, issue: int) -> dict[str, Any] | bool:
    """이번 시도(마지막 `repairing` 뒤)에 머지된 수리 PR. 없으면 False."""
    since = _repairing_since(api, issue)
    if since is None:
        return False
    for pr in sorted(api.pulls("closed"), key=lambda p: -int(p["number"])):
        at = pr.get("merged_at")
        if at and _ours(api, pr, issue) and datetime.fromisoformat(str(at)) >= since:
            return pr
    return False


def mark_merged(api: gh.Api, issue: int, pr: dict[str, Any] | None = None) -> None:
    """머지 뒤 기록. `merged`를 먼저 달아, 도중에 죽어도 sweep·settle이 실패로 세지 않게."""
    api.add_labels(issue, [gh.MERGED])
    api.remove_label(issue, gh.REPAIRING)
    if pr is not None:  # 다음 시도가 같은 브랜치 이름을 다시 쓸 수 있게
        api.call("DELETE", f"/git/refs/heads/{pr['head']['ref']}", ok_missing=True)


def merge(
    api: gh.Api,
    pr: int,
    issue: int,
    *,
    wait_s: float = 1800,
    poll_s: float = 30,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    on_merged: Callable[[], None] = lambda: None,
) -> Result:
    pull = api.call("GET", f"/pulls/{pr}")
    head = (pull.get("head") or {}) if isinstance(pull, dict) else {}
    sha, branch = str(head.get("sha", "")), str(head.get("ref", ""))
    if not sha:
        raise gh.ApiError(200)
    start = clock()
    while True:
        state = ci_state(api, sha, branch)
        if state == "failure":
            return "ci_failed"
        if state == "success":
            break
        if clock() - start >= wait_s:
            return "timeout"
        sleep(poll_s)
    api.add_labels(pr, [gh.AUTO_REPAIR_LABEL])  # 하루 머지 수를 세는 라벨(없으면 단다)
    # sha를 넘겨 확인한 커밋 그대로만 머지한다(그 사이 푸시가 있으면 409)
    api.call("PUT", f"/pulls/{pr}/merge", json={
        "merge_method": "squash", "commit_message": f"Repairs #{issue}", "sha": sha,
    })
    on_merged()
    mark_merged(api, issue, pull)
    return "merged"


def abandon(api: gh.Api, issue: int, attempt: int | None = None) -> None:
    """실패한 시도 정리: 열린 수리 PR 닫기, 브랜치 지우기, `failed-<시도>`, `repairing` 떼기.

    시도 번호(인자, 없으면 PR 브랜치 끝, 그것도 없으면 실패 수 + 1)로 라벨을 달아, 도중에 죽고 다시 해도
    실패를 두 번 세지 않는다."""
    pr = find_pr(api, issue)
    if pr is not None:
        api.call("PATCH", f"/pulls/{pr['number']}", json={"state": "closed"})
        api.call("DELETE", f"/git/refs/heads/{pr['head']['ref']}", ok_missing=True)
    if attempt is None and pr is not None:  # 브랜치 `auto-repair/<이슈>-<시도>`의 시도
        tail = str(pr["head"]["ref"]).rpartition("-")[2]
        attempt = int(tail) if tail.isdigit() else None
    if attempt is None:
        attempt = gh.failures(gh.label_names(api.issue(issue))) + 1
    api.add_labels(issue, [f"failed-{attempt}"])
    api.remove_label(issue, gh.REPAIRING)


def settle(
    api: gh.Api, issue: int, result: str, attempt: int | None = None,
) -> Literal["kept", "merged", "abandoned"]:
    if result in ("merged", "timeout", "cancelled"):
        return "kept"
    labels = gh.label_names(api.issue(issue))
    if gh.MERGED in labels or gh.REPAIRING not in labels:
        return "kept"  # 이미 정리됐다(다시 돈 실행)
    pr = merged_this_attempt(api, issue)
    if pr:
        mark_merged(api, issue, pr if isinstance(pr, dict) else None)
        return "merged"
    abandon(api, issue, attempt)
    return "abandoned"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["merge", "settle"])
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--attempt", default="")
    p.add_argument("--result", default="")
    args = p.parse_args(argv)
    if gh.no_token():
        return 0
    api = gh.from_env()
    if args.action == "settle":
        attempt = int(args.attempt) if args.attempt.isdigit() else None
        print(f"settle: {settle(api, args.issue, args.result, attempt)}")
        return 0
    pr = find_pr(api, args.issue)
    if pr is None:
        gh.set_output(result="no_pr", pr="", branch="")
        print("merge: no_pr")
        return 0
    number, branch = int(pr["number"]), str(pr["head"]["ref"])
    gh.set_output(pr=str(number), branch=branch if gh.BRANCH_RE.match(branch) else "")
    result = merge(api, number, args.issue, on_merged=lambda: gh.set_output(result="merged"))
    if result != "merged":
        gh.set_output(result=result)
    print(f"merge: {result} (PR #{number})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

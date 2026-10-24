"""repair.yml 머지 단계와 정리 (스펙 4.3). Claude 없이 이 셸 단계가 한다.

- `merge`: PR 머리 커밋의 `ci` 실행(`pull_request` 이벤트)이 끝날 때까지 기다려 `GET /actions/runs?head_sha=`로
  결과를 직접 본다(필수 검사 설정에 기대지 않는다, 10장 S6). 성공이면 squash 머지, 커밋 본문 `Repairs #<이슈>`,
  이슈 `repairing` → `merged`.
- `settle`: 이번 시도가 머지도 시간 초과도 아니면(CI 두 번 실패, PR 없음, 단계 실패) PR을 닫고 브랜치를 지우고
  `failed-N`을 하나 올리고 `repairing`을 뗀다. 다음 시도는 watch.yml의 sweep이 집는다.
  시간 초과는 `repairing`을 둔다: sweep이 CI 초록을 보면 머지만 다시 한다.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any, Literal

import gh

Result = Literal["merged", "ci_failed", "timeout"]
CiState = Literal["success", "failure", "pending"]


def ci_state(api: gh.Api, sha: str) -> CiState:
    """그 SHA의 `ci` PR 실행 중 가장 새 것. 없거나 안 끝났으면 `pending`."""
    runs = api.ci_runs(sha, "pull_request")
    if not runs:
        return "pending"
    run = max(runs, key=lambda r: (str(r.get("created_at", "")), int(r.get("id") or 0)))
    if run.get("status") != "completed":
        return "pending"
    return "success" if run.get("conclusion") == "success" else "failure"


def find_pr(api: gh.Api, issue: int, state: str = "open") -> dict[str, Any] | None:
    """`main` 대상, 브랜치 `auto-repair/<이슈>-*`인 PR 중 가장 새 것."""
    prefix = f"{gh.BRANCH_PREFIX}{issue}-"
    found = [p for p in api.pulls(state) if str((p.get("head") or {}).get("ref", "")).startswith(prefix)]
    return max(found, key=lambda p: int(p["number"])) if found else None


def merge(
    api: gh.Api,
    pr: int,
    issue: int,
    *,
    wait_s: float = 1800,
    poll_s: float = 30,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Result:
    pull = api.call("GET", f"/pulls/{pr}")
    sha = str(((pull or {}).get("head") or {}).get("sha", "")) if isinstance(pull, dict) else ""
    if not sha:
        raise gh.ApiError(200)
    start = clock()
    while True:
        state = ci_state(api, sha)
        if state == "failure":
            return "ci_failed"
        if state == "success":
            break
        if clock() - start >= wait_s:
            return "timeout"
        sleep(poll_s)
    api.add_labels(pr, [gh.AUTO_REPAIR_LABEL])  # Claude가 빠뜨려도 하루 머지 수에 든다
    # sha를 넘겨 확인한 커밋 그대로만 머지한다(그 사이 푸시가 있으면 409)
    api.call("PUT", f"/pulls/{pr}/merge", json={
        "merge_method": "squash", "commit_message": f"Repairs #{issue}", "sha": sha,
    })
    api.add_labels(issue, [gh.MERGED])
    api.remove_label(issue, gh.REPAIRING)
    return "merged"


def abandon(api: gh.Api, issue: int) -> None:
    """죽은·실패한 시도 정리: 열린 수리 PR 닫기, 브랜치 지우기, `failed-N` +1, `repairing` 떼기."""
    pr = find_pr(api, issue)
    if pr is not None:
        api.call("PATCH", f"/pulls/{pr['number']}", json={"state": "closed"})
        ref = str(pr["head"]["ref"])
        api.call("DELETE", f"/git/refs/heads/{ref}", ok_missing=True)
    labels = gh.label_names(api.issue(issue))
    api.add_labels(issue, [f"failed-{gh.failures(labels) + 1}"])
    api.remove_label(issue, gh.REPAIRING)


def settle(api: gh.Api, issue: int, result: str) -> Literal["kept", "abandoned"]:
    if result in ("merged", "timeout"):
        return "kept"
    labels = gh.label_names(api.issue(issue))
    if gh.MERGED in labels or gh.REPAIRING not in labels:
        return "kept"  # 이미 정리됐다(다시 돈 실행)
    abandon(api, issue)
    return "abandoned"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["merge", "settle"])
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--result", default="")
    args = p.parse_args(argv)
    api = gh.from_env()
    if args.action == "settle":
        print(f"settle: {settle(api, args.issue, args.result)}")
        return 0
    pr = find_pr(api, args.issue)
    if pr is None:
        gh.set_output(result="no_pr", pr="")
        print("merge: no_pr")
        return 0
    result = merge(api, int(pr["number"]), args.issue)
    gh.set_output(result=result, pr=str(int(pr["number"])))
    print(f"merge: {result} (PR #{int(pr['number'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

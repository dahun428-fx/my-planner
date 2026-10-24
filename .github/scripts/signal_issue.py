"""signal.yml: 노트북을 거치지 않는 두 신호를 장애 이슈로 (스펙 3.1, 3.5).

- `status`: 컨텍스트가 `Vercel`로 시작하고 `failure`이며 그 커밋의 `branches`에 `main`이 든 것만.
  Vercel은 `develop` 미리보기도 빌드하므로 `develop`에만 있는 커밋은 장애가 아니다. 지문 `vercel:<컨텍스트>`.
- `workflow_run`: `main` 푸시의 `ci`가 `failure`로 끝난 것만. 지문 `ci:main`. develop에서 이미 통과한 SHA라
  작업을 건너뛴(`already_green`) main 실행은 `success`로 끝나므로 오지 않는다.

같은 지문의 열린 `incident` 이슈가 있으면 댓글만 단다. 없으면 `incident` 라벨로 연다(라벨이 repair.yml을 깨운다).
본문은 허용 목록(7장)만: 지문, 시각, 커밋, 실행 id. 이벤트 글(컨텍스트)은 API 본문으로만 쓰고 셸에 넣지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import gh

VERCEL_PREFIX = "Vercel"
_MAX_CONTEXT = 100


def _z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_status(event: dict[str, Any]) -> str | None:
    context = str(event.get("context") or "")
    if event.get("state") != "failure" or not context.startswith(VERCEL_PREFIX):
        return None
    branches = [b.get("name") for b in event.get("branches") or [] if isinstance(b, dict)]
    if gh.BASE not in branches:
        return None
    return f"vercel:{context[:_MAX_CONTEXT]}"


def from_workflow_run(event: dict[str, Any]) -> str | None:
    run = event.get("workflow_run") or {}
    if (
        run.get("name") == gh.CI_NAME
        and run.get("conclusion") == "failure"
        and run.get("head_branch") == gh.BASE
        and run.get("event") == "push"
    ):
        return gh.CI_MAIN
    return None


def ensure_issue(
    api: gh.Api, fp: str, part: str, *, now: datetime, sha: str = "", run_id: int | None = None,
) -> int:
    title = gh.incident_title(fp)
    found = [i for i in api.issues(gh.INCIDENT) if i.get("title") == title]
    commit = sha[:12] or "?"
    if found:
        n = int(min(found, key=lambda i: int(i["number"]))["number"])
        extra = f", 실행 {run_id}" if run_id else ""
        api.comment(n, f"다시 실패: 커밋 `{commit}`, {_z(now)}{extra}")
        return n
    lines = [
        f"- 지문: `{fp}`",
        f"- 처음: {_z(now)}",
        f"- 커밋: `{commit}`",
    ]
    if run_id:
        lines.append(f"- `ci` 실행 id: {run_id}")
    labels = [gh.INCIDENT, *([part] if part in gh.PART_LABELS else [])]
    body = api.call("POST", "/issues", json={"title": title, "body": "\n".join(lines) + "\n", "labels": labels})
    if not isinstance(body, dict) or not isinstance(body.get("number"), int):
        raise gh.ApiError(201)
    return body["number"]


def main() -> int:
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    now = datetime.now(UTC)
    if name == "status":
        fp = from_status(event)
        if fp is None:
            print("signal: ignored")
            return 0
        n = ensure_issue(gh.from_env(), fp, "vercel", now=now, sha=str(event.get("sha") or ""))
    elif name == "workflow_run":
        fp = from_workflow_run(event)
        if fp is None:
            print("signal: ignored")
            return 0
        run = event["workflow_run"]
        n = ensure_issue(gh.from_env(), fp, "ci", now=now, sha=str(run.get("head_sha") or ""),
                         run_id=int(run["id"]) if isinstance(run.get("id"), int) else None)
    else:
        print("signal: ignored")
        return 0
    print(f"signal: issue #{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

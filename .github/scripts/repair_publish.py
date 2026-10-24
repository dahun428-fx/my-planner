"""repair.yml의 publish 단계 (스펙 4.2·4.3, 리뷰 I1). Claude는 쓰기 토큰 없이 커밋만 하고, 이 셸 단계가 PR을 연다.

- 푸시는 워크플로의 셸이 한다(새 체크아웃에 Claude 작업의 git bundle을 가져와 `REPAIR_PAT`으로 푸시).
  `.github/workflows/`를 바꾼 커밋은 PAT에 Workflows 권한이 없어 푸시가 거부되고, 그 시도는 보통의 실패 길
  (PR 없음 → settle이 `failed-N`)로 간다. 금지 경로 검사는 두지 않는다(Dahun 결정: 금지선 없음).
- 이 스크립트: 푸시가 됐으면 열린 PR이 없을 때 `main` 대상 PR을 연다. 본문 첫 줄은 `Repairs #<이슈>`, 라벨
  `auto-repair`. 커밋이 없으면(재현 못 함) Claude가 남긴 진단을 이슈 댓글로 단다.
Claude가 쓴 파일(`pr-title.txt`, `pr-body.md`, `issue-comment.md`)은 글로만 쓰고 셸에 넣지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

import gh

TITLE_MAX = 200
BODY_MAX = 60000
_REPAIRS_LINE = "Repairs #"


def pr_body(issue: int, raw: str) -> str:
    """첫 줄을 `Repairs #<이슈>`로 맞춘다(Claude가 빠뜨리거나 다른 번호를 써도)."""
    lines = raw.strip().splitlines()
    if lines and lines[0].strip().startswith(_REPAIRS_LINE):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    rest = "\n".join(lines)
    return (f"Repairs #{issue}\n\n{rest}".rstrip() + "\n")[:BODY_MAX]


def publish(
    api: gh.Api, issue: int, branch: str, *, pushed: bool, title: str, body: str, comment: str,
) -> Literal["opened", "exists", "commented", "nothing"]:
    if not gh.BRANCH_RE.match(branch) or not branch.startswith(f"{gh.BRANCH_PREFIX}{issue}-"):
        raise ValueError("unexpected branch")
    if not pushed:
        if comment.strip():
            api.comment(issue, comment.strip()[:BODY_MAX])
            return "commented"
        return "nothing"
    for pr in api.pulls("open"):
        if (pr.get("head") or {}).get("ref") == branch:
            return "exists"  # refix 뒤 다시 돈 실행 등
    title = " ".join(title.split())[:TITLE_MAX] or f"fix: incident #{issue}"
    created = api.call("POST", "/pulls", json={
        "title": title, "head": branch, "base": gh.BASE, "body": pr_body(issue, body),
    })
    if not isinstance(created, dict) or not isinstance(created.get("number"), int):
        raise gh.ApiError(201)
    api.add_labels(created["number"], [gh.AUTO_REPAIR_LABEL])
    return "opened"


def _read(out: Path, name: str) -> str:
    try:
        return (out / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--pushed", choices=["true", "false"], required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    out = Path(args.out)
    got = publish(
        gh.from_env(), args.issue, args.branch, pushed=args.pushed == "true",
        title=_read(out, "pr-title.txt"), body=_read(out, "pr-body.md"), comment=_read(out, "issue-comment.md"),
    )
    print(f"publish: {got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

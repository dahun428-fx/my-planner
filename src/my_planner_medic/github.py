"""GitHub REST 이음매 (스펙 3.5, 4.1, 4.4). 토큰·본문은 로그에 남기지 않는다."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import quote, urlencode

from .http import Body, Http

API = "https://api.github.com"
INCIDENT = "incident"
RECORD = "record"
HEARTBEAT = "heartbeat"
PART_LABELS = ("be", "app", "dashboard")  # 스펙 4.1 조각 라벨
TITLE_PREFIX = "[incident] "
_REPAIRS_RE = re.compile(r"\bRepairs #(\d+)\b")

Kind = Literal["network", "rate_limit", "auth", "server"]
CiConclusion = Literal["success", "failure", "pending", "unknown"]


class GitHubUnavailable(Exception):
    def __init__(self, kind: Kind, status: int = 0) -> None:
        super().__init__(f"github unavailable: {kind} ({status})")
        self.kind = kind
        self.status = status


def incident_title(fp: str) -> str:
    return TITLE_PREFIX + fp


def _kind(status: int, headers: dict[str, str]) -> Kind:
    if status == 0:
        return "network"
    if status == 429:
        return "rate_limit"
    if status == 403:
        remaining = {k.lower(): v for k, v in headers.items()}.get("x-ratelimit-remaining")
        return "rate_limit" if remaining == "0" else "auth"
    if status == 401:
        return "auth"
    return "server"  # 5xx, 그리고 예상 밖의 4xx(404·422 등)도 "이번 회차엔 못 한다"로 다룬다


def _labels(issue: dict[str, Any]) -> list[str]:
    return [x["name"] if isinstance(x, dict) else str(x) for x in issue.get("labels") or []]


class GitHub:
    def __init__(self, http: Http, token: str | None, repo: str) -> None:
        self._http = http
        self._token = token
        self.repo = repo

    def __repr__(self) -> str:
        return f"GitHub(repo={self.repo!r})"

    # --- 바탕 --------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json: Any = None,
        ok_missing: bool = False,
    ) -> Body:
        url = f"{API}/repos/{self.repo}{path}"
        if query:
            url += "?" + urlencode(query)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        status, body, resp_headers = self._http.request(method, url, headers=headers, json=json, timeout=10)
        if 200 <= status < 300 or (ok_missing and status == 404):
            return body
        raise GitHubUnavailable(_kind(status, resp_headers), status)

    def _list(self, path: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        body = self._call("GET", path, query=query)
        return [x for x in body if isinstance(x, dict)] if isinstance(body, list) else []

    def _issues(self, label: str, state: str) -> list[dict[str, Any]]:
        items = self._list("/issues", {"labels": label, "state": state, "per_page": 100})
        return [i for i in items if "pull_request" not in i]  # issues API는 PR도 준다

    # --- 이슈 --------------------------------------------------------------

    def find_incident(self, fp: str) -> dict[str, Any] | None:
        """제목 `[incident] <fp>`인 이슈 중 가장 새 것. 검색 API(색인 지연)가 아니라 목록을 본다.

        목록은 라벨별 최근 100개(생성 역순)만 본다.
        """
        title = incident_title(fp)
        found = [i for label in (INCIDENT, RECORD) for i in self._issues(label, "all") if i.get("title") == title]
        return max(found, key=lambda i: int(i["number"])) if found else None

    def open_incidents(self) -> list[dict[str, Any]]:
        """열린 `incident` 이슈(Actions가 연 것 포함)."""
        return self._issues(INCIDENT, "open")

    def open_incident(self, fp: str, part: str, body: str) -> int:
        labels = [RECORD] if part == RECORD else [INCIDENT, *([part] if part in PART_LABELS else [])]
        issue = self._call("POST", "/issues", json={"title": incident_title(fp), "body": body, "labels": labels})
        if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
            raise GitHubUnavailable("server", 201)
        return issue["number"]

    def update_body(self, n: int, body: str) -> None:
        self._call("PATCH", f"/issues/{n}", json={"body": body})

    def reopen(self, n: int, labels: list[str]) -> None:
        self._call("PATCH", f"/issues/{n}", json={"state": "open"})
        if labels:
            self.add_labels(n, labels)

    def add_labels(self, n: int, labels: list[str]) -> None:
        self._call("POST", f"/issues/{n}/labels", json={"labels": list(labels)})

    def remove_label(self, n: int, label: str) -> None:
        self._call("DELETE", f"/issues/{n}/labels/{quote(label, safe='')}", ok_missing=True)

    def close(self, n: int) -> None:
        self._call("PATCH", f"/issues/{n}", json={"state": "closed", "state_reason": "completed"})

    def comment(self, n: int, body: str) -> None:
        self._call("POST", f"/issues/{n}/comments", json={"body": body})

    def heartbeat(self, body: str) -> tuple[int, list[str]]:
        """열린 `heartbeat` 이슈의 본문을 바꾼다(없으면 만든다). (이슈 번호, 그 이슈의 라벨)."""
        found = self._issues(HEARTBEAT, "open")
        if found:
            issue = min(found, key=lambda i: int(i["number"]))
            self.update_body(issue["number"], body)
            return issue["number"], _labels(issue)
        created = self._call("POST", "/issues", json={"title": HEARTBEAT, "body": body, "labels": [HEARTBEAT]})
        if not isinstance(created, dict) or not isinstance(created.get("number"), int):
            raise GitHubUnavailable("server", 201)
        return created["number"], _labels(created) or [HEARTBEAT]

    def pr_for_issue(self, n: int) -> tuple[str, str] | None:
        """본문에 `Repairs #n`이 있는 머지된 PR의 (제목, URL). 최근 닫힌 PR 100개를 본다."""
        for pr in self._list("/pulls", {"state": "closed", "per_page": 100}):
            body = pr.get("body") or ""
            if pr.get("merged_at") and str(n) in {m for m in _REPAIRS_RE.findall(body)}:
                return str(pr.get("title", "")), str(pr.get("html_url", ""))
        return None

    # --- 커밋·CI ------------------------------------------------------------

    def head_sha(self, branch: str = "main") -> str:
        body = self._call("GET", f"/branches/{quote(branch, safe='')}")
        sha = body.get("commit", {}).get("sha") if isinstance(body, dict) else None
        if not isinstance(sha, str):
            raise GitHubUnavailable("server", 200)
        return sha

    def ci_conclusion(self, sha: str) -> CiConclusion:
        """`main` 푸시의 `ci` 실행 결과. `"unknown"`은 그런 실행이 없다는 뜻뿐이고, 조회 실패는 예외다."""
        body = self._call("GET", "/actions/runs", query={"head_sha": sha, "event": "push", "per_page": 100})
        runs = body.get("workflow_runs") if isinstance(body, dict) else None
        ci = [r for r in runs or [] if isinstance(r, dict) and r.get("name") == "ci"]
        if not ci:
            return "unknown"
        run = max(ci, key=lambda r: (str(r.get("created_at", "")), int(r.get("id") or 0)))
        if run.get("status") != "completed":
            return "pending"
        return "success" if run.get("conclusion") == "success" else "failure"

    def commit_state(self, sha: str, context_prefix: str) -> str:
        """커밋 상태 중 컨텍스트가 `context_prefix`로 시작하는 것의 `state`. 없으면 `"unknown"`."""
        body = self._call("GET", f"/commits/{sha}/status")
        statuses = body.get("statuses") if isinstance(body, dict) else None
        for st in statuses or []:
            if isinstance(st, dict) and str(st.get("context", "")).startswith(context_prefix):
                return str(st.get("state", "unknown"))
        return "unknown"

    def repairs_in_range(self, base: str, head: str) -> list[int]:
        """`base...head` 커밋 메시지의 `Repairs #N`(처음 나온 순서, 중복 없이)."""
        body = self._call("GET", f"/compare/{base}...{head}")
        out: list[int] = []
        for c in body.get("commits", []) if isinstance(body, dict) else []:
            msg = (c.get("commit") or {}).get("message", "") if isinstance(c, dict) else ""
            for num in _REPAIRS_RE.findall(str(msg)):
                if int(num) not in out:
                    out.append(int(num))
        return out

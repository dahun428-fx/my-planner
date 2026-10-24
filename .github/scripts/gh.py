"""GitHub REST 이음매 (스펙 4.2). 표준 라이브러리만 쓰고 `src/`를 가져오지 않는다.

모양은 medic의 `Http`·`GitHub`(티켓 06)와 같다. 라벨·제목 틀은 medic과 같아야 해서 여기에 다시 적고,
`tests/workflows/test_scripts_contract.py`가 medic 상수와 맞는지 본다.
토큰·URL·응답 본문은 찍지 않는다. 실패는 상태 코드만 담은 `ApiError`다.
"""

from __future__ import annotations

import http.client
import json as _json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol
from urllib.parse import quote, urlencode

API = "https://api.github.com"

# --- medic(티켓 06)과 같은 틀 -------------------------------------------------
INCIDENT = "incident"
RECORD = "record"
HEARTBEAT = "heartbeat"
PART_LABELS = ("be", "app", "dashboard")  # 스펙 4.1 조각 라벨
TITLE_PREFIX = "[incident] "
CI_MAIN = "ci:main"
REPAIRING = "repairing"
MERGED = "merged"
ROLLED_BACK = "rolled-back"
RECURRED = "recurred"
NEEDS_DAHUN = "needs-dahun"
FAILED_RE = re.compile(r"^failed-(\d+)$")
STALE_RE = re.compile(r"^stale-(\d{4}-\d{2}-\d{2})$")
GAVE_UP_TEXT = "⚠️ 자동으로 못 고쳤어요: {fp}. 지금은 {state}. {url}"
ROLLED_BACK_TEXT = "이전 버전으로 돌려 둠"
AS_IS_TEXT = "그대로"
TZ = "Asia/Seoul"  # Actions의 "오늘"(머지 한도, 하트비트 알림)은 서울 달력 날짜

# --- Actions 쪽만 -------------------------------------------------------------
AUTO_REPAIR_LABEL = "auto-repair"  # 수리 PR 라벨(하루 머지 수를 센다)
BRANCH_PREFIX = "auto-repair/"
BRANCH_RE = re.compile(r"^auto-repair/\d+-\d+$")  # 다음 작업에 넘겨도 되는 브랜치 이름
BASE = "main"  # 수리는 핫픽스: main에서 따서 main으로 (배포 흐름 스펙 7장)
REPAIR_WORKFLOW = "repair.yml"
CI_NAME = "ci"

Body = dict[str, Any] | list[Any] | None


class Http(Protocol):
    def request(
        self, method: str, url: str, *, headers: dict[str, str] | None = None, json: Any = None, timeout: float = 10,
    ) -> tuple[int, Body, dict[str, str]]:
        """(상태, JSON 본문, 소문자 키 응답 헤더). 연결 실패·시간 초과는 `(0, None, {})`. 예외를 올리지 않는다."""
        ...


def _decode(raw: bytes) -> Body:
    try:
        value = _json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict | list) else None


class UrllibHttp:
    """URL(텔레그램은 경로에 봇 토큰)과 예외 글은 어디에도 남기지 않는다."""

    def request(
        self, method: str, url: str, *, headers: dict[str, str] | None = None, json: Any = None, timeout: float = 10,
    ) -> tuple[int, Body, dict[str, str]]:
        hdrs = dict(headers or {})
        data = None
        if json is not None:
            data = _json.dumps(json, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, _decode(resp.read()), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except (OSError, http.client.HTTPException):
                raw = b""
            return exc.code, _decode(raw), {k.lower(): v for k, v in (exc.headers or {}).items()}
        except (OSError, http.client.HTTPException, ValueError):
            return 0, None, {}


class ApiError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"github api error ({status})")
        self.status = status


def incident_title(fp: str) -> str:
    return TITLE_PREFIX + fp


def label_names(item: dict[str, Any]) -> list[str]:
    return [x["name"] if isinstance(x, dict) else str(x) for x in item.get("labels") or []]


def failures(labels: list[str]) -> int:
    """실패 수 = `failed-N` 라벨의 가장 큰 N."""
    return max((int(m[1]) for x in labels if (m := FAILED_RE.match(x))), default=0)


def fingerprint(issue: dict[str, Any]) -> str:
    title = str(issue.get("title", ""))
    return title.removeprefix(TITLE_PREFIX)


class Api:
    def __init__(self, token: str | None, repo: str, http: Http | None = None) -> None:
        self._token = token
        self.repo = repo
        self._http = http or UrllibHttp()

    def __repr__(self) -> str:
        return f"Api(repo={self.repo!r})"

    def call(
        self, method: str, path: str, *, query: dict[str, Any] | None = None, json: Any = None,
        ok_missing: bool = False,
    ) -> Body:
        """`/repos/{repo}` 아래 경로. 2xx가 아니면 `ApiError`(`ok_missing`이면 404·422는 None)."""
        url = f"{API}/repos/{self.repo}{path}"
        if query:
            url += "?" + urlencode(query)
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        status, body, _ = self._http.request(method, url, headers=headers, json=json, timeout=20)
        if 200 <= status < 300:
            return body
        if ok_missing and status in (404, 422):
            return None
        raise ApiError(status)

    # --- 이슈 --------------------------------------------------------------

    def issue(self, n: int) -> dict[str, Any]:
        body = self.call("GET", f"/issues/{n}")
        if not isinstance(body, dict):
            raise ApiError(200)
        return body

    def issues(self, label: str, state: str = "open") -> list[dict[str, Any]]:
        """라벨별 최근 100개. issues API가 주는 PR은 뺀다."""
        body = self.call("GET", "/issues", query={"labels": label, "state": state, "per_page": 100})
        items = body if isinstance(body, list) else []
        return [i for i in items if isinstance(i, dict) and "pull_request" not in i]

    def add_labels(self, n: int, labels: list[str]) -> None:
        self.call("POST", f"/issues/{n}/labels", json={"labels": list(labels)})

    def remove_label(self, n: int, label: str) -> None:
        self.call("DELETE", f"/issues/{n}/labels/{quote(label, safe='')}", ok_missing=True)

    def comment(self, n: int, body: str) -> None:
        self.call("POST", f"/issues/{n}/comments", json={"body": body})

    def issue_url(self, n: int) -> str:
        return f"https://github.com/{self.repo}/issues/{n}"

    # --- PR·실행 -------------------------------------------------------------

    def pulls(self, state: str = "open") -> list[dict[str, Any]]:
        """`main` 대상 PR 최근 100개."""
        body = self.call("GET", "/pulls", query={"state": state, "base": BASE, "per_page": 100})
        return [p for p in body if isinstance(p, dict)] if isinstance(body, list) else []

    def ci_runs(self, sha: str, event: str) -> list[dict[str, Any]]:
        body = self.call("GET", "/actions/runs", query={"head_sha": sha, "event": event, "per_page": 100})
        runs = body.get("workflow_runs") if isinstance(body, dict) else None
        return [r for r in runs or [] if isinstance(r, dict) and r.get("name") == CI_NAME]


NO_TOKEN_TEXT = "REPAIR_PAT not set; auto-repair not set up yet"


def no_token() -> bool:
    """`REPAIR_PAT`이 비었으면(시크릿을 넣기 전) 한 줄을 찍고 True. 진입점은 아무것도 안 하고 0으로 끝난다."""
    if os.environ.get("REPAIR_PAT", ""):
        return False
    print(NO_TOKEN_TEXT)
    return True


def from_env() -> Api:
    """워크플로 단계에서: `REPAIR_PAT`(쓰기 신원, 스펙 4.2)와 `GITHUB_REPOSITORY`."""
    token = os.environ.get("REPAIR_PAT", "")
    if not token:
        raise SystemExit("REPAIR_PAT is not set")
    return Api(token, os.environ["GITHUB_REPOSITORY"])


def set_output(**values: str) -> None:
    """`$GITHUB_OUTPUT`에 한 줄씩. 값은 숫자·정해진 낱말만 넘긴다(이슈 글은 넘기지 않는다)."""
    path = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in values.items())
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(lines)
    else:
        print(lines, end="")

"""medic 시험용 가짜. 파일시스템은 tmp_path를 쓴다."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, minutes: float = 0, seconds: float = 0, hours: float = 0) -> None:
        self._now += timedelta(hours=hours, minutes=minutes, seconds=seconds)


@dataclass
class FakeResponse:
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FakeRequest:
    method: str
    url: str
    json: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 10

    @property
    def path(self) -> str:
        return urlsplit(self.url).path

    @property
    def query(self) -> dict[str, str]:
        return dict(parse_qsl(urlsplit(self.url).query))


Route = Callable[[str, str, Any], tuple[int, Any, dict[str, str]]]


class FakeHttp:
    """`Http` 프로토콜의 가짜(`my_planner_medic.http`). 받은 요청을 `requests`에 남긴다.

    응답 고르는 순서:
    1. `outage`(상태 코드, 0이면 연결 실패)가 있으면 모든 요청이 그것.
    2. (메서드, 경로) 큐에 응답이 있으면 하나 꺼낸다. 큐가 비면 마지막 응답을 되풀이한다.
    3. `lose_next(메서드, 경로)`면 `route`가 처리는 하고 응답은 `(0, None, {})`(응답이 끊김).
    4. `route`(예: `FakeGitHub.route`)가 있으면 그것, 없으면 404.
    """

    def __init__(self, route: Route | None = None) -> None:
        self._queues: dict[tuple[str, str], deque[FakeResponse | Exception]] = defaultdict(deque)
        self._last: dict[tuple[str, str], FakeResponse | Exception] = {}
        self._lose: list[tuple[str, str]] = []
        self.route = route
        self.outage: int | None = None
        self.requests: list[FakeRequest] = []

    def queue(self, method: str, path: str, *responses: FakeResponse | Exception) -> None:
        self._queues[(method.upper(), path)].extend(responses)

    def clear(self, method: str, path: str) -> None:
        """그 (메서드, 경로)의 큐와 되풀이 응답을 지워 다시 `route`로 보낸다."""
        key = (method.upper(), path)
        self._queues.pop(key, None)
        self._last.pop(key, None)

    def lose_next(self, method: str, path: str) -> None:
        self._lose.append((method.upper(), path))

    def calls(self, method: str, path: str) -> list[FakeRequest]:
        return [r for r in self.requests if r.method == method.upper() and r.path == path]

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        timeout: float = 10,
    ) -> tuple[int, Any, dict[str, str]]:
        req = FakeRequest(method.upper(), url, json, dict(headers or {}), timeout)
        self.requests.append(req)
        key = (req.method, req.path)
        if self.outage is not None:
            return self.outage, None, {}
        q = self._queues.get(key)
        if q or key in self._last:
            item = q.popleft() if q else self._last[key]
            self._last[key] = item
            if isinstance(item, Exception):
                raise item
            return item.status, item.body, dict(item.headers)
        if self.route is None:
            return 404, None, {}
        result = self.route(req.method, url, json)
        if key in self._lose:
            self._lose.remove(key)
            return 0, None, {}
        return result


class FakeGitHub:
    """api.github.com의 이 저장소 부분만 흉내 내는 상태 있는 가짜. `FakeHttp(route=gh.route)`로 쓴다."""

    def __init__(self, repo: str = "o/r", clock: FakeClock | None = None) -> None:
        self.repo = repo
        self.clock = clock
        self.issues: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[str]] = defaultdict(list)
        self.runs: list[dict[str, Any]] = []
        self.statuses: dict[str, list[dict[str, Any]]] = {}
        self.posted_statuses: list[tuple[str, dict[str, Any]]] = []  # POST /statuses/{sha}로 올라온 것
        # (base, head) -> 커밋 메시지들(오래된 것부터). `(sha, 메시지)` 짝도 된다(sha가 없으면 `<head>~<뒤에서 몇째>`)
        self.compares: dict[tuple[str, str], list[Any]] = {}
        self.path_commits: dict[str, list[str]] = {}  # 경로 -> 그 경로를 바꾼 main 커밋(새 것부터)
        self.pulls: list[dict[str, Any]] = []
        self.branches: dict[str, str] = {}
        self.workflow_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)  # 워크플로 파일 -> 실행
        self.dispatches: list[tuple[str, dict[str, Any]]] = []
        self.deleted_refs: list[str] = []
        self.merges: list[tuple[int, dict[str, Any]]] = []
        self.events: dict[int, list[dict[str, Any]]] = defaultdict(list)  # 이슈 -> labeled 이벤트(오래된 것부터)
        self.created_pulls: list[dict[str, Any]] = []
        self.deleted_labels: list[str] = []
        self._next = 1

    # --- 시험 준비 ---
    def add_issue(
        self, title: str, labels: list[str], *, state: str = "open", body: str = "",
        created_at: str = "2026-01-01T00:00:00Z",
    ) -> int:
        n = self._next
        self._next += 1
        self.issues[n] = {
            "number": n, "title": title, "body": body, "state": state,
            "labels": [{"name": x} for x in labels], "created_at": created_at,
            "html_url": f"https://github.com/{self.repo}/issues/{n}",
        }
        return n

    def add_pull(
        self, head_ref: str, *, base: str = "main", state: str = "open", head_sha: str = "h1",
        labels: list[str] | None = None, merged_at: str | None = None, body: str = "", title: str = "fix",
    ) -> int:
        """PR 하나(번호는 이슈와 같은 칸을 쓴다)."""
        n = self._next
        self._next += 1
        self.pulls.append({
            "number": n, "title": title, "body": body, "state": state, "merged_at": merged_at,
            "head": {"ref": head_ref, "sha": head_sha, "repo": {"full_name": self.repo}}, "base": {"ref": base},
            "labels": [{"name": x} for x in labels or []],
            "html_url": f"https://github.com/{self.repo}/pull/{n}",
        })
        return n

    def pull(self, n: int) -> dict[str, Any]:
        return next(p for p in self.pulls if p.get("number") == n)

    def labels(self, n: int) -> list[str]:
        return [x["name"] for x in self.issues[n]["labels"]]

    def titled(self, title: str) -> list[dict[str, Any]]:
        return [i for i in self.issues.values() if i["title"] == title]

    def _now(self) -> str:
        if self.clock is None:
            return "2026-01-01T00:00:00Z"
        return self.clock.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- 라우터 ---
    def route(self, method: str, url: str, json: Any) -> tuple[int, Any, dict[str, str]]:
        parts = urlsplit(url)
        q = dict(parse_qsl(parts.query))
        prefix = f"/repos/{self.repo}"
        if parts.netloc != "api.github.com" or not parts.path.startswith(prefix):
            return 404, {"message": "Not Found"}, {}
        segs = [unquote(s) for s in parts.path[len(prefix):].split("/")[1:]]
        ok: dict[str, str] = {}
        match method, segs:
            case "GET", ["issues"]:
                state = q.get("state", "open")
                want = [x for x in q.get("labels", "").split(",") if x]
                out = [
                    i for i in sorted(self.issues.values(), key=lambda i: -i["number"])
                    if (state == "all" or i["state"] == state)
                    and all(w in [x["name"] for x in i["labels"]] for w in want)
                ]
                return 200, out[: int(q.get("per_page", 30))], ok
            case "POST", ["issues"]:
                n = self.add_issue(json["title"], list(json.get("labels", [])), body=json.get("body", ""),
                                   created_at=self._now())
                return 201, self.issues[n], ok
            case "GET", ["issues", num] if num.isdigit() and int(num) in self.issues:
                return 200, self.issues[int(num)], ok
            case "PATCH", ["issues", num] if int(num) in self.issues:
                issue = self.issues[int(num)]
                for k in ("title", "body", "state"):
                    if k in json:
                        issue[k] = json[k]
                return 200, issue, ok
            case "POST", ["issues", num, "labels"] if any(p.get("number") == int(num) for p in self.pulls):
                pr = self.pull(int(num))  # PR도 이슈 API로 라벨을 단다
                pr["labels"] += [{"name": x} for x in json["labels"] if x not in [y["name"] for y in pr["labels"]]]
                return 200, pr["labels"], ok
            case "POST", ["issues", num, "labels"] if int(num) in self.issues:
                have = self.labels(int(num))
                for name in json["labels"]:
                    if name not in have:
                        self.issues[int(num)]["labels"].append({"name": name})
                        self.events[int(num)].append(
                            {"event": "labeled", "label": {"name": name}, "created_at": self._now()}
                        )
                return 200, self.issues[int(num)]["labels"], ok
            case "DELETE", ["issues", num, "labels", name] if int(num) in self.issues:
                if name not in self.labels(int(num)):
                    return 404, {"message": "Label does not exist"}, ok
                self.issues[int(num)]["labels"] = [x for x in self.issues[int(num)]["labels"] if x["name"] != name]
                return 200, self.issues[int(num)]["labels"], ok
            case "POST", ["issues", num, "comments"] if int(num) in self.issues:
                self.comments[int(num)].append(json["body"])
                return 201, {"id": len(self.comments[int(num)])}, ok
            case "GET", ["actions", "runs"]:
                runs = [
                    r for r in self.runs
                    if all(r.get(k) == q[k] for k in ("head_sha", "event", "branch") if k in q)
                ]
                return 200, {"total_count": len(runs), "workflow_runs": runs}, ok
            case "GET", ["commits", sha, "status"]:
                return 200, {"sha": sha, "statuses": self.statuses.get(sha, [])}, ok
            case "GET", ["commits", sha, "statuses"]:  # 목록 API: 새 것부터(나중에 넣은 것이 새 것)
                return 200, list(reversed(self.statuses.get(sha, [])))[: int(q.get("per_page", 30))], ok
            case "GET", ["commits"]:
                shas = self.path_commits.get(q.get("path", ""), [])
                return 200, [{"sha": x} for x in shas][: int(q.get("per_page", 30))], ok
            case "POST", ["statuses", sha]:
                self.posted_statuses.append((sha, dict(json)))
                self.statuses.setdefault(sha, []).append(dict(json))
                return 201, {"id": len(self.posted_statuses)}, ok
            case "GET", ["compare", rng]:
                base, _, head = rng.partition("...")
                msgs = self.compares.get((base, head))
                if msgs is None:
                    return 404, {"message": "Not Found"}, ok
                items = [m if isinstance(m, tuple) else (f"{head}~{len(msgs) - 1 - i}", m) for i, m in enumerate(msgs)]
                return 200, {"commits": [{"sha": c, "commit": {"message": m}} for c, m in items]}, ok
            case "GET", ["issues", num, "events"] if int(num) in self.issues:
                return 200, self.events[int(num)][: int(q.get("per_page", 30))], ok
            case "POST", ["pulls"]:
                n = self.add_pull(json["head"], base=json["base"], title=json["title"], body=json.get("body", ""))
                self.created_pulls.append(self.pull(n))
                return 201, self.pull(n), ok
            case "DELETE", ["labels", name]:
                self.deleted_labels.append(name)
                for issue in self.issues.values():  # 저장소 라벨을 지우면 이슈에서도 빠진다
                    issue["labels"] = [x for x in issue["labels"] if x["name"] != name]
                return 204, None, ok
            case "GET", ["pulls"]:
                out = [
                    p for p in sorted(self.pulls, key=lambda p: -int(p.get("number") or 0))
                    if q.get("state", "open") in ("all", p["state"])
                    and ("base" not in q or (p.get("base") or {}).get("ref") == q["base"])
                ]
                return 200, out[: int(q.get("per_page", 30))], ok
            case "GET", ["pulls", num] if num.isdigit() and any(p.get("number") == int(num) for p in self.pulls):
                return 200, self.pull(int(num)), ok
            case "PATCH", ["pulls", num] if num.isdigit() and any(p.get("number") == int(num) for p in self.pulls):
                pr = self.pull(int(num))
                for k in ("state", "title", "body"):
                    if k in json:
                        pr[k] = json[k]
                return 200, pr, ok
            case "PUT", ["pulls", num, "merge"] if any(p.get("number") == int(num) for p in self.pulls):
                pr = self.pull(int(num))
                if pr["state"] != "open" or ("sha" in json and json["sha"] != pr["head"]["sha"]):
                    return 409, {"message": "Head branch was modified"}, ok
                pr.update(state="closed", merged_at=self._now())
                self.merges.append((int(num), dict(json)))
                return 200, {"merged": True}, ok
            case "DELETE", ["git", "refs", "heads", *ref]:
                self.deleted_refs.append("/".join(ref))
                return 204, None, ok
            case "POST", ["actions", "workflows", wf, "dispatches"]:
                self.dispatches.append((wf, dict(json)))
                return 204, None, ok
            case "GET", ["actions", "workflows", wf, "runs"]:
                runs = self.workflow_runs.get(wf, [])
                return 200, {"total_count": len(runs), "workflow_runs": runs}, ok
            case "GET", ["branches", name] if name in self.branches:
                return 200, {"name": name, "commit": {"sha": self.branches[name]}}, ok
        return 404, {"message": "Not Found"}, ok


@dataclass
class ShellCall:
    args: list[str]
    cwd: Path
    timeout: int
    env: dict[str, str] | None


class FakeShell:
    """명령(앞부분 일치) -> (returncode, stdout) 규칙. 규칙 없으면 (0, "").

    규칙에 결과 목록을 주면 호출마다 하나씩 꺼내고 마지막 값을 되풀이한다.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[tuple[str, ...], list[tuple[int, str]]]] = []
        self.calls: list[ShellCall] = []

    @property
    def commands(self) -> list[list[str]]:
        return [c.args for c in self.calls]

    def on(
        self,
        *prefix: str,
        returns: tuple[int, str] | list[tuple[int, str]] = (0, ""),
    ) -> None:
        results = returns if isinstance(returns, list) else [returns]
        self.rules.append((prefix, list(results)))

    def missing(self, exe: str) -> None:
        """실행 파일이 없는 것처럼 127을 돌려준다."""
        self.on(exe, returns=(127, f"{exe} not found"))

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        self.calls.append(ShellCall(list(args), cwd, timeout, env))
        for prefix, results in reversed(self.rules):
            if tuple(args[: len(prefix)]) == prefix:
                return results.pop(0) if len(results) > 1 else results[0]
        return 0, ""


class FakeNotifier:
    """`NotifierLike`의 가짜. 호출을 기록만 한다."""

    def __init__(self) -> None:
        self.fixed_calls: list[tuple[str, str]] = []
        self.gave_up_calls: list[tuple[str, bool, str, bool]] = []
        self.daily_calls: list[tuple[str, str]] = []
        self.flushes = 0

    def fixed(self, pr_title: str, pr_url: str) -> None:
        self.fixed_calls.append((pr_title, pr_url))

    def gave_up(self, fingerprint: str, rolled_back: bool, issue_url: str, *, direct: bool = False) -> None:
        self.gave_up_calls.append((fingerprint, rolled_back, issue_url, direct))

    def daily(self, text: str, key: str) -> None:
        self.daily_calls.append((text, key))

    def flush_spill(self) -> None:
        self.flushes += 1


SCHEDULE = {
    "morning_brief": {"weekday": "09:00", "weekend": "10:00"},
    "evening_checkin": {"weekday": "17:30", "weekend": "18:00"},
    "review": {"week": {"day": "sun", "time": "18:00"}},
}


def make_config(root: Path | None = None, **overrides: Any) -> Any:
    """config.toml의 실제 [schedule] 모양을 가진 MedicConfig."""
    from datetime import time

    from my_planner_medic.config import MedicConfig

    values: dict[str, Any] = {
        "root": root or Path("/repo"),
        "enabled": True,
        "api_base": "http://127.0.0.1:8787/api/v1",
        "api_enabled": True,
        "api_token": None,
        "github_token": None,
        "telegram_token": None,
        "owner_telegram_id": None,
        "timezone": "Asia/Seoul",
        "day_boundary": time(4, 0),
        "schedule": SCHEDULE,
    }
    values.update(overrides)
    return MedicConfig(**values)

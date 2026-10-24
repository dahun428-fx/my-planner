"""가리기와 이슈 본문 (스펙 3.1 경로 가리기, 4.1, 7장). 허용 목록으로만 만든다.

키를 고르는 것에 더해 값도 틀에 맞는 것만 남긴다: 이벤트 이름·수준·시각 같은 값은 공백 없는 ASCII
토큰이므로, 틀에 안 맞는 값(사용자 글이 섞였을 수 있다)은 `?`로 바꾼다.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import Incident

OUTSIDE = "<외부>"
LOG_KEYS = ("ts", "level", "logger", "msg", "exc_type", "exc_where")
_DETAIL_SCALARS = ("exc_type", "event", "app", "version", "route", "error_name")
_MAX_FRAMES = 5
_MAX_LIST = 10

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:+\-/\[\]]{1,160}$")
_REL_RE = re.compile(r"^[A-Za-z0-9_.\-/]+$")
_FUNC_RE = re.compile(r"^[<>\w.]{1,120}$")
_WIN_RE = re.compile(r"^[A-Za-z]:[\\/]|\\")
UNKNOWN = "?"


def safe_token(value: Any) -> str:
    """공백 없는 ASCII 토큰(이벤트 이름, 수준, 시각, 커밋 등)만 통과시킨다."""
    if isinstance(value, bool):
        return UNKNOWN
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and _TOKEN_RE.match(value):
        return value
    return UNKNOWN


def _scalar(value: Any) -> Any:
    """None·정수는 그대로, 나머지는 토큰으로."""
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    return safe_token(value)


def _pure(path: str) -> PurePath:
    return PureWindowsPath(path) if _WIN_RE.search(path) else PurePosixPath(path)


def _fold(parts: tuple[str, ...]) -> list[str]:
    return [p.replace("\\", "/").casefold() for p in parts]


def relpath(frame: str, root: PurePath | str | None) -> str:
    """`/abs/path/x.py:12 fn` 한 프레임을 가린다(스펙 3.1).

    저장소 안 → 저장소 기준 상대 경로, `site-packages` 안 → 그 뒤만, 그 밖 → `<외부>`.
    Windows 경로는 `PureWindowsPath`로 나누고 대소문자를 무시해 비교한다. `root`가 없으면(이미 가린
    줄을 다시 거를 때) 상대 경로만 그대로 둔다.
    """
    loc, _, func = str(frame).rpartition(" ")
    path, _, line = loc.rpartition(":")
    if not path or not line.isdigit() or not _FUNC_RE.match(func):
        return OUTSIDE
    tail = f":{line} {func}"
    p = _pure(path)
    parts = p.parts
    if not p.is_absolute() and not p.anchor:
        rel = "/".join(parts)
        ok = ".." not in parts and _REL_RE.match(rel)  # 이미 가린 경로(`src/...`)만 남는다
        return (rel if ok else OUTSIDE) + tail
    folded = _fold(parts)
    # site-packages를 먼저 본다: 저장소 안의 .venv 라이브러리도 `site-packages/...`로 남긴다
    if "site-packages" in folded:
        i = len(folded) - 1 - folded[::-1].index("site-packages")
        rest = "/".join(parts[i + 1:])
        return (f"site-packages/{rest}" if rest and _REL_RE.match(rest) else OUTSIDE) + tail
    if root is not None:
        root_parts = _fold(_pure(str(root)).parts)
        if len(folded) > len(root_parts) and folded[: len(root_parts)] == root_parts:
            rest = "/".join(parts[len(root_parts):])
            return (rest if _REL_RE.match(rest) else OUTSIDE) + tail
    return OUTSIDE + tail


def _frames(value: Any, root: PurePath | str | None) -> list[str]:
    if not isinstance(value, list):
        return []
    return [relpath(f, root) if isinstance(f, str) else OUTSIDE for f in value[-_MAX_FRAMES:]]


def allowed_log_row(rec: dict[str, Any], root: PurePath | str | None) -> dict[str, Any]:
    """로그 레코드에서 `ts, level, logger, msg, exc_type, exc_where`만 남긴다(`exc_where`는 가린다)."""
    out: dict[str, Any] = {}
    for key in LOG_KEYS:
        if key not in rec:
            continue
        out[key] = _frames(rec[key], root) if key == "exc_where" else safe_token(rec[key])
    return out


def allowed_health(h: dict[str, Any]) -> dict[str, Any]:
    """`/health`에서 4.1 목록만: status, polling, brain.auth, runs_today[].loop/status/scheduled_for,
    errors.by_event, version."""
    out: dict[str, Any] = {}
    if not isinstance(h, dict):
        return out
    for key in ("status", "polling"):
        if key in h:
            out[key] = safe_token(h[key])
    version = h.get("version")
    if isinstance(version, dict):
        out["version"] = {
            k: _scalar(version[k])
            for k in ("app", "api", "schema", "ui_catalog") if k in version
        }
    elif version is not None:
        out["version"] = safe_token(version)
    brain = h.get("brain")
    if isinstance(brain, dict) and "auth" in brain:
        out["brain"] = {"auth": safe_token(brain["auth"])}
    runs = h.get("runs_today")
    if isinstance(runs, list):
        out["runs_today"] = [
            {k: safe_token(r[k]) for k in ("loop", "status", "scheduled_for") if k in r}
            for r in runs if isinstance(r, dict)
        ]
    errors = h.get("errors")
    if isinstance(errors, dict) and isinstance(errors.get("by_event"), dict):
        out["errors"] = {
            "by_event": {
                safe_token(k): v if isinstance(v, int) and not isinstance(v, bool) else 0
                for k, v in errors["by_event"].items()
            }
        }
    return out


def _allowed_detail(detail: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _DETAIL_SCALARS:
        if key in detail:
            out[key] = safe_token(detail[key])
    if "exc_where" in detail:
        out["exc_where"] = _frames(detail["exc_where"], None)
    if isinstance(detail.get("frames"), list):  # client_error의 번들 청크 프레임
        out["frames"] = [safe_token(f) for f in detail["frames"][:_MAX_LIST]]
    return out


def _code(value: str) -> str:
    return "`" + value.replace("`", "") + "`"


def issue_body(incident: Incident, rows: list[dict[str, Any]], health: dict[str, Any] | None, sha: str) -> str:
    """4.1 틀의 이슈 본문(마크다운). 넘겨 받은 줄·헬스·detail도 다시 허용 목록으로 거른다."""
    safe_rows = [allowed_log_row(r, None) for r in rows]
    detail = _allowed_detail(incident.detail or {})
    lines = [
        "<!-- medic:incident -->",
        f"## {_code(incident.fingerprint)}",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 지문 | {_code(incident.fingerprint)} |",
        f"| 처음 | {safe_token(incident.first_seen)} |",
        f"| 마지막 | {safe_token(incident.last_seen)} |",
        f"| 발생 수 | {int(incident.count)} |",
        f"| 배포된 커밋 | {_code(safe_token(sha))} |",
    ]
    exc_type = detail.get("exc_type")
    exc_where = detail.get("exc_where")
    if exc_type is None:
        last = next((r for r in reversed(safe_rows) if "exc_type" in r), None)
        if last is not None:
            exc_type, exc_where = last["exc_type"], last.get("exc_where", [])
    if exc_type is not None:
        lines += ["", "### 예외", f"- 종류: {_code(exc_type)}", "- 호출 스택(가림):"]
        lines += [f"  - {_code(f)}" for f in exc_where or []]
    client = {k: detail[k] for k in ("app", "version", "route", "error_name", "frames") if k in detail}
    if client:
        lines += ["", "### 브라우저 에러"]
        for k, v in client.items():
            shown = ", ".join(_code(x) for x in v) if isinstance(v, list) else _code(v)
            lines.append(f"- {k}: {shown}")
    lines += ["", "### 직전 30분 로그", ""]
    if safe_rows:
        lines += ["| " + " | ".join(LOG_KEYS) + " |", "|" + "---|" * len(LOG_KEYS)]
        for r in safe_rows:
            cells = [
                "<br>".join(_code(f) for f in r.get(k, [])) if k == "exc_where" else r.get(k, "")
                for k in LOG_KEYS
            ]
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("(없음)")
    lines += ["", "### /health", ""]
    if health is None:
        lines.append("(응답 없음)")
    else:
        lines += ["```json", json.dumps(allowed_health(health), ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines) + "\n"

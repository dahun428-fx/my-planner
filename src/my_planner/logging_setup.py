"""JSON 줄 로그 `state/logs/my-planner.jsonl`, 하루 단위 회전 (스펙 7).

메시지 본문과 도구 인자는 남기지 않는다. 그래서:
- `my_planner.*` 밖의 로거는 메시지와 extra를 버리고 로거 이름, 수준, 예외 종류만 남긴다.
- 로그 메시지는 `%` 서식을 적용하지 않고 이름(`msg`) 그대로 쓴다. 값은 `extra=`로 넘긴다.
- `text`, `args`, `input` 키는 지운다.
- 예외는 종류와 호출 위치만 남기고, 예외 메시지(입력값이 들어 있을 수 있다)는 남기지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import traceback
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "my-planner.jsonl"
# TimedRotatingFileHandler(when="midnight")가 회전한 파일: my-planner.jsonl.YYYY-MM-DD
_ROTATED_RE = re.compile(r"^" + re.escape(LOG_FILE_NAME) + r"\.\d{4}-\d{2}-\d{2}$")
DROPPED_KEYS = frozenset({"text", "args", "input"})

_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}
_MARK = "_my_planner_handler"

# httpx는 INFO에서 요청 URL을 남긴다. 텔레그램 URL에는 봇 토큰이 들어 있다.
_QUIET_LOGGERS = ("httpx", "httpcore", "telegram", "apscheduler")


THIRD_PARTY_MSG = "third_party_log"
_OWN_PREFIX = "my_planner"

# PTB Updater는 폴링 중 네트워크가 잠깐 끊기면 ERROR로 남기고 스스로 재시도한다. 이것이 장애 신호가 되어
# 배포 확인이 롤백되지 않도록 INFO로 낮춘다(지속되면 polling down·무응답 신호가 잡는다).
_POLL_LOGGER = "telegram.ext.Updater"
_TRANSIENT_POLL_EXC = frozenset({"NetworkError", "TimedOut", "RetryAfter"})


class _TransientPollFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[0] if record.exc_info else None
        if record.levelno >= logging.ERROR and exc is not None and exc.__name__ in _TRANSIENT_POLL_EXC:
            record.levelno, record.levelname = logging.INFO, "INFO"
        return True


def _is_own(name: str) -> bool:
    return name == _OWN_PREFIX or name.startswith(_OWN_PREFIX + ".")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
        }
        if _is_own(record.name):
            entry["msg"] = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
            for key, value in record.__dict__.items():
                if key in _STANDARD_ATTRS or key in DROPPED_KEYS or key.startswith("_"):
                    continue
                entry[key] = value
        else:
            # 외부 라이브러리는 f-string으로 본문을 메시지에 넣기도 한다(예: SDK의 JSON 해석 오류는
            # CLI 출력 앞 100자를 담는다). 메시지와 extra를 버리고 고정 이름만 남긴다.
            entry["msg"] = THIRD_PARTY_MSG
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _, tb = record.exc_info
            entry["exc_type"] = exc_type.__name__
            entry["exc_where"] = [
                f"{f.filename}:{f.lineno} {f.name}" for f in traceback.extract_tb(tb)[-5:]
            ]
        for key in DROPPED_KEYS:
            entry.pop(key, None)
        return json.dumps(entry, ensure_ascii=False, default=str)


def _ensure_std_streams() -> bool:
    """pythonw에서는 sys.stdout/stderr가 None이다. devnull로 바꿔 둔다. 콘솔이 있었는지 돌려준다."""
    had_console = sys.stderr is not None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    return had_console


def setup_logging(state_dir: Path, keep_days: int) -> Path:
    """로그를 설정하고 로그 파일 경로를 돌려준다. 여러 번 불러도 된다."""
    had_console = _ensure_std_streams()
    log_dir = Path(state_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = (log_dir / LOG_FILE_NAME).resolve()

    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _MARK, False):
            root.removeHandler(h)
            h.close()

    formatter = JsonFormatter()
    file_handler = TimedRotatingFileHandler(
        path, when="midnight", backupCount=keep_days, encoding="utf-8", utc=False
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MARK, True)
    root.addHandler(file_handler)

    if had_console:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        setattr(console, _MARK, True)
        root.addHandler(console)

    root.setLevel(logging.INFO)
    poll_logger = logging.getLogger(_POLL_LOGGER)
    if not any(isinstance(f, _TransientPollFilter) for f in poll_logger.filters):
        poll_logger.addFilter(_TransientPollFilter())
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return path


def cleanup_logs(log_dir: Path, keep: int) -> int:
    """회전된 날짜별 로그 파일을 날짜순으로 가장 최근 `keep`개만 남기고, 지운 개수를 돌려준다.

    회전 자체는 표준 핸들러가 맡는다. 핸들러는 회전할 때만 오래된 파일을 지우므로(재시작이 잦으면 놓친다)
    하루 한 번 따로 정리한다. 지금 쓰는 파일과 다른 파일은 건드리지 않는다.
    """
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return 0
    rotated = sorted(p for p in log_dir.iterdir() if _ROTATED_RE.match(p.name))
    old = rotated[: max(len(rotated) - keep, 0)]
    for p in old:
        p.unlink()
    return len(old)

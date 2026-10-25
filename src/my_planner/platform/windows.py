"""Windows 전용 장치 (스펙 5.1). Windows가 아니면 아무것도 하지 않는다.

- SingleInstanceLock: `msvcrt.locking` 비차단 잠금. 크래시하면 OS가 푼다.
- keep_awake: 두뇌 호출과 전송 동안 절전 방지(참조 카운트).
- hide_console: pythonw에서 창 없는 콘솔을 하나 만든다(S1).
- refresh_wake_task: 체크인 시간을 바꾼 뒤 깨우기 작업 `my-planner-wake`만 다시 등록한다(SP9 8장).
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Literal, Self

IS_WINDOWS = sys.platform == "win32"

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ALLOC_CONSOLE_MODE_NO_WINDOW = 2

ConsoleResult = Literal["created", "has_console", "unavailable", "not_windows"]


class AlreadyRunning(RuntimeError):
    """다른 프로세스가 이미 잠금을 쥐고 있다."""


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file: IO[bytes] | None = None

    def acquire(self) -> None:
        if not IS_WINDOWS:
            return
        import msvcrt

        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")  # noqa: SIM115
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as e:
            f.close()
            raise AlreadyRunning(str(self.path)) from e
        self._file = f

    def release(self) -> None:
        f, self._file = self._file, None
        if f is None:
            return
        import msvcrt

        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            f.close()

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


_KERNEL32: Any = None


def _kernel32() -> Any:
    """kernel32를 한 번만 불러오고, 쓰는 함수의 인자·반환 형식을 정해 둔다(64비트 핸들 잘림 방지)."""
    global _KERNEL32
    if _KERNEL32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        k.GetConsoleWindow.argtypes = []
        k.GetConsoleWindow.restype = ctypes.c_void_p  # HWND
        k.SetThreadExecutionState.argtypes = [ctypes.c_uint]  # EXECUTION_STATE (DWORD)
        k.SetThreadExecutionState.restype = ctypes.c_uint
        _KERNEL32 = k
    return _KERNEL32


_awake_refs = 0


def _set_execution_state(flags: int) -> None:
    _kernel32().SetThreadExecutionState(flags)


@contextmanager
def keep_awake() -> Iterator[None]:
    """0→1에서 ES_CONTINUOUS|ES_SYSTEM_REQUIRED, 1→0에서 ES_CONTINUOUS.

    SetThreadExecutionState는 스레드별이다. 모든 호출이 이벤트 루프 스레드 하나에서 일어난다.
    """
    global _awake_refs
    if not IS_WINDOWS:
        yield
        return
    _awake_refs += 1
    if _awake_refs == 1:
        _set_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        _awake_refs -= 1
        if _awake_refs == 0:
            _set_execution_state(ES_CONTINUOUS)


class _AllocConsoleOptions(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("useShowWindow", ctypes.c_int),
        ("showWindow", ctypes.c_ushort),
    ]


def hide_console() -> ConsoleResult:
    """콘솔이 없을 때만(`GetConsoleWindow()==0`) 창 없는 콘솔을 한 번 만든다.

    이게 없으면 pythonw가 SDK의 claude.exe를 띄울 때마다 터미널 창이 뜬다(S1).
    """
    if not IS_WINDOWS:
        return "not_windows"
    kernel32 = _kernel32()
    if kernel32.GetConsoleWindow():  # HWND, c_void_p: 콘솔이 없으면 None
        return "has_console"
    alloc = getattr(kernel32, "AllocConsoleWithOptions", None)
    if alloc is None:  # 이 함수가 없는 Windows 버전
        return "unavailable"
    alloc.argtypes = [ctypes.POINTER(_AllocConsoleOptions), ctypes.POINTER(ctypes.c_int)]
    alloc.restype = ctypes.c_long  # HRESULT
    options = _AllocConsoleOptions(ALLOC_CONSOLE_MODE_NO_WINDOW, 0, 0)
    result = ctypes.c_int(0)  # ALLOC_CONSOLE_RESULT
    hr = alloc(ctypes.byref(options), ctypes.byref(result))
    return "created" if hr == 0 else "unavailable"


# --- 깨우기 작업 다시 등록 (SP9 8장) ---

WAKE_SCRIPT = Path("scripts") / "update_wake_task.ps1"
WAKE_REFRESH_TIMEOUT_S = 20
CREATE_NO_WINDOW = 0x08000000
_WAIT_MARGIN_S = 1.0  # 스크립트 자신의 시간 제한(`subprocess.run(timeout=)`)이 먼저 걸리게 조금 더 기다린다
# 한 번에 하나만 돈다. 스크립트는 그때의 DB 값으로 트리거를 다시 만들므로 겹쳐 바꿔도 마지막 값이 이긴다
_WAKE_LOCK = asyncio.Lock()


def _run_wake_script(root: Path, timeout_s: float) -> bool:
    """`powershell -File scripts/update_wake_task.ps1 -Root <root>`. 종료 코드 0이면 True. 출력은 남기지 않는다."""
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(root / WAKE_SCRIPT), "-Root", str(root),
    ]
    try:
        done = subprocess.run(
            cmd, cwd=root, capture_output=True, timeout=timeout_s, check=False,
            creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )
    except subprocess.TimeoutExpired:
        log.warning("wake_task_refresh_timeout", extra={"timeout_s": timeout_s})
        return False
    except OSError as e:
        log.warning("wake_task_refresh_error", extra={"error_type": type(e).__name__})
        return False
    if done.returncode != 0:
        log.warning("wake_task_refresh_failed", extra={"exit_code": done.returncode})
        return False
    log.info("wake_task_refreshed")
    return True


async def refresh_wake_task(timeout_s: float = WAKE_REFRESH_TIMEOUT_S, *, root: Path | None = None) -> bool:
    """깨우기 작업만 다시 등록하고 끝나기를 최대 `timeout_s`초 기다린다. Windows가 아니면 할 일이 없어 True.

    스크립트는 `asyncio.to_thread`로 돌린다(이벤트 루프를 막지 않는다). 시간이 지나면 False(작업은 그대로일 수 있다).
    """
    if not IS_WINDOWS:
        return True
    if root is None:
        from my_planner.config import resolve_root

        root = resolve_root()
    async with _WAKE_LOCK:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_run_wake_script, root, timeout_s), timeout_s + _WAIT_MARGIN_S
            )
        except TimeoutError:
            log.warning("wake_task_refresh_timeout", extra={"timeout_s": timeout_s})
            return False

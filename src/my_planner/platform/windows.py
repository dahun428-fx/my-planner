"""Windows 전용 장치 (스펙 5.1). Windows가 아니면 아무것도 하지 않는다.

- SingleInstanceLock: `msvcrt.locking` 비차단 잠금. 크래시하면 OS가 푼다.
- keep_awake: 두뇌 호출과 전송 동안 절전 방지(참조 카운트).
- hide_console: pythonw에서 창 없는 콘솔을 하나 만든다(S1).
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Literal

IS_WINDOWS = sys.platform == "win32"

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

    def __enter__(self) -> SingleInstanceLock:
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

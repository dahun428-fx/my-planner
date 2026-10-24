"""BE 작업 스케줄러 작업 끄기·켜기 (스펙 5장 5·7단계, 스파이크 S3·S5).

PowerShell·taskkill 문자열은 모두 이 파일의 상수다. 노트북 스파이크(S3: 일반 권한 pythonw에서
Disable/Stop/Enable/Start, S5: 멈춘 뒤 파일 잠금 없음) 결과가 다르면 이 파일만 고친다.

명령 문자열에는 큰따옴표를 쓰지 않는다(Windows 명령줄 따옴표 처리와 PowerShell 5.1 파싱이 엇갈리지 않게).
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from .shell import Shell

log = logging.getLogger(__name__)

POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
# 첫 오류에서 멈춰 종료 코드 1(끄기가 실패하면 켜진 작업이 BE를 다시 띄운다)
DISABLE_STOP = (
    "$ErrorActionPreference='Stop'; "
    "Disable-ScheduledTask -TaskName {name} | Out-Null; Stop-ScheduledTask -TaskName {name}"
)
ENABLE_START = (
    "$ErrorActionPreference='Stop'; "
    "Enable-ScheduledTask -TaskName {name} | Out-Null; Start-ScheduledTask -TaskName {name}"
)
# 이미 켜진 작업을 "켜 둔 채" 둘 때: Start는 하지 않는다(돌고 있는 BE 옆에 둘째 인스턴스를 띄우지 않게)
ENABLE_ONLY = "$ErrorActionPreference='Stop'; Enable-ScheduledTask -TaskName {name} | Out-Null"
TASK_STATE = "$ErrorActionPreference='Stop'; (Get-ScheduledTask -TaskName {name}).State"
TASK_ENABLED = "$ErrorActionPreference='Stop'; (Get-ScheduledTask -TaskName {name}).Settings.Enabled"
# BE 프로세스: 명령줄에 저장소 루트가 있고 `-m my_planner`로 끝나는 python/pythonw.
# `my_planner_medic`·`my_planner.wake_times`는 맞지 않는다. medic 자신(PID)은 늘 뺀다.
# venv의 pythonw.exe는 기본 인터프리터를 자식으로 띄우는 실행기라, 자식은 /T로 함께 죽는다.
FIND_BE_PIDS = (
    "$ErrorActionPreference='Stop'; $r = '{root}'.ToLowerInvariant(); "
    "Get-CimInstance Win32_Process | Where-Object {{ "
    "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.ProcessId -ne {own_pid} "
    "-and $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($r) "
    "-and $_.CommandLine -match '(^|\\s)-m\\s+my_planner(\\s|$)' }} | "
    "ForEach-Object {{ $_.ProcessId }}"
)
TASKKILL = ["taskkill", "/T", "/F", "/PID"]
RUNNING = "Running"
STOP_WAIT_S = 30
POLL_S = 2
_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


class TaskControlError(Exception):
    pass


def _ps(command: str) -> list[str]:
    return [*POWERSHELL, command]


class TaskControl:
    def __init__(
        self,
        shell: Shell,
        root: Path,
        *,
        name: str = "my-planner",
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        own_pid: int | None = None,
    ) -> None:
        self._shell = shell
        self._root = root
        self.name = self._name(name)  # 잘못된 이름은 만들 때 실패한다(끄기·켜기 도중이 아니라)
        self._sleep = sleep
        self._monotonic = monotonic
        self._own_pid = os.getpid() if own_pid is None else own_pid

    def _name(self, name: str | None) -> str:
        n = self.name if name is None else name
        if not _NAME_RE.match(n):
            raise ValueError("bad task name")
        return n

    def _run(self, command: str, timeout: int = 60) -> tuple[int, str]:
        return self._shell.run(_ps(command), cwd=self._root, timeout=timeout)

    def is_enabled(self, name: str | None = None) -> bool | None:
        """켜짐 True, 꺼짐 False, 조회 실패·알 수 없는 답 None."""
        rc, out = self._run(TASK_ENABLED.format(name=self._name(name)))
        value = out.strip().lower()
        if rc != 0 or value not in ("true", "false"):
            return None
        return value == "true"

    def state(self, name: str | None = None) -> str | None:
        """`Ready`·`Running`·`Disabled` 등. 조회 실패는 None."""
        return self._state(self._name(name))

    def enable_only(self, name: str | None = None) -> bool:
        rc, _ = self._run(ENABLE_ONLY.format(name=self._name(name)))
        if rc != 0:
            log.warning("enable_failed rc=%d", rc)
        return rc == 0

    def _state(self, name: str) -> str | None:
        rc, out = self._run(TASK_STATE.format(name=name))
        return out.strip() if rc == 0 else None

    def be_pids(self) -> list[int]:
        root = str(self._root).replace("'", "''")
        rc, out = self._run(FIND_BE_PIDS.format(root=root, own_pid=self._own_pid))
        if rc != 0:
            raise TaskControlError(f"process query failed ({rc})")
        return [int(x) for x in out.split() if x.isdigit() and int(x) != self._own_pid]

    def disable_stop(self, name: str | None = None) -> None:
        """끄기 → 멈춤 → `Running`이 아닐 때까지 30초 → BE 프로세스 트리 `taskkill /T /F`.

        BE가 확실히 멈췄다고 볼 수 없으면 `TaskControlError`(호출자는 배포하지 않고 다시 켠다).
        """
        n = self._name(name)
        rc, _ = self._run(DISABLE_STOP.format(name=n))
        if self.is_enabled(n) is not False:  # 꺼졌다고 확인될 때만 이어 간다(켜진 채면 작업이 BE를 다시 띄운다)
            raise TaskControlError(f"disable not confirmed ({rc})")
        deadline = self._monotonic() + STOP_WAIT_S
        while self._state(n) == RUNNING and self._monotonic() < deadline:
            self._sleep(POLL_S)
        for pid in self.be_pids():
            krc, _ = self._shell.run([*TASKKILL, str(pid)], cwd=self._root, timeout=60)
            log.info("taskkill pid=%d rc=%d", pid, krc)
        if self.be_pids():
            raise TaskControlError("be still running")

    def enable_start(self, name: str | None = None) -> bool:
        rc, _ = self._run(ENABLE_START.format(name=self._name(name)))
        if rc != 0:
            log.warning("enable_start_failed rc=%d", rc)
        return rc == 0

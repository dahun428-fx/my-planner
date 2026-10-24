from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol


class Shell(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]: ...


class SubprocessShell:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
        try:
            proc = subprocess.run(
                args,
                check=False,
                cwd=cwd,
                env=env,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            return 124, out or "timeout"
        except FileNotFoundError:
            return 127, f"{args[0]} not found"
        except OSError as exc:
            return 126, str(exc)
        return proc.returncode, proc.stdout or ""

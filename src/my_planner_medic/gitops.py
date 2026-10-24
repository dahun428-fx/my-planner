"""git 이음매 (스펙 5장 1·3·5·7단계).

인증은 argv가 아니라 환경 변수(`GIT_CONFIG_*`)로만 넘긴다. 토큰·git 출력은 로그에 남기지 않는다(원격 URL에
자격 증명이 박혀 있을 수 있다). pythonw에는 콘솔이 없어 자격 증명 창이 뜨면 멈추므로 프롬프트를 끈다.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sys
from pathlib import Path

from .shell import Shell

log = logging.getLogger(__name__)

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.\-/]{1,100}$")
FETCH_TIMEOUT = 180


class GitError(Exception):
    pass


def venv_python(root: Path, *, windows: bool | None = None) -> Path:
    """BE venv의 python. medic 자신의 인터프리터가 아니다."""
    win = sys.platform == "win32" if windows is None else windows
    return root / ".venv" / ("Scripts/python.exe" if win else "bin/python")


def _check_sha(sha: str) -> str:
    if sha != "HEAD" and not _SHA_RE.match(sha):
        raise ValueError("bad sha")
    return sha


class GitOps:
    def __init__(self, shell: Shell, root: Path, token: str | None, *, branch: str = "main") -> None:
        if not _REF_RE.match(branch) or branch.startswith("-"):
            raise ValueError("bad branch")
        self._shell = shell
        self._root = root
        self._token = token
        self.branch = branch

    def __repr__(self) -> str:
        return f"GitOps(root={self._root!r}, branch={self.branch!r})"

    @property
    def remote_ref(self) -> str:
        return f"refs/remotes/origin/{self.branch}"

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
        if self._token:
            basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode("ascii")
            env.update({
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
            })
        return env

    def _git(self, *args: str, timeout: int = 120) -> tuple[int, str]:
        return self._shell.run(["git", *args], cwd=self._root, timeout=timeout, env=self._env())

    def _must(self, *args: str, timeout: int = 120) -> str:
        rc, out = self._git(*args, timeout=timeout)
        if rc != 0:
            raise GitError(f"git {args[0]} failed ({rc})")
        return out

    def fetch_main(self) -> str | None:
        """`origin/<branch>`를 받아 그 sha. 실패하면 None."""
        rc, _ = self._git(
            "fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/{self.branch}:{self.remote_ref}",
            timeout=FETCH_TIMEOUT,
        )
        if rc != 0:
            log.warning("git_fetch_failed rc=%d", rc)
            return None
        rc, out = self._git("rev-parse", "--verify", self.remote_ref)
        sha = out.strip()
        return sha if rc == 0 and _SHA_RE.match(sha) else None

    def head(self) -> str:
        sha = self._must("rev-parse", "HEAD").strip()
        if not _SHA_RE.match(sha):
            raise GitError("bad HEAD")
        return sha

    def is_ancestor(self, a: str, b: str) -> bool:
        rc, _ = self._git("merge-base", "--is-ancestor", _check_sha(a), _check_sha(b))
        if rc not in (0, 1):
            raise GitError(f"git merge-base failed ({rc})")
        return rc == 0

    def changed_paths(self, a: str, b: str) -> list[str]:
        out = self._must("diff", "--name-only", "-z", _check_sha(a), _check_sha(b))
        return [p for p in out.split("\0") if p.strip()]

    def is_clean(self, ignore: list[str]) -> bool:
        """추적 파일에 손으로 고친 것이 없는가(`ignore` 접두 경로는 뺀다). 추적 안 되는 파일은 보지 않는다."""
        out = self._must("status", "--porcelain=v1", "-z", "--untracked-files=no")
        items = out.split("\0")
        i = 0
        while i < len(items):
            entry = items[i]
            i += 1
            if len(entry) < 4:
                continue
            xy, path = entry[:2], entry[3:]
            paths = [path]
            if "R" in xy or "C" in xy:  # -z의 이름 바꿈은 다음 항목이 옛 경로
                if i < len(items):
                    paths.append(items[i])
                i += 1
            if any(not any(p.startswith(ig) for ig in ignore) for p in paths):
                return False
        return True

    def current_ref(self) -> str | None:
        """`HEAD`가 가리키는 브랜치 ref(`refs/heads/…`). 분리된 HEAD나 실패는 None."""
        rc, out = self._git("symbolic-ref", "-q", "HEAD")
        ref = out.strip()
        return ref if rc == 0 and ref else None

    def merge_ff(self, sha: str) -> bool:
        rc, _ = self._git("merge", "--ff-only", "--quiet", _check_sha(sha))
        if rc != 0:
            log.warning("git_merge_ff_failed rc=%d", rc)
        return rc == 0

    def reset_hard(self, sha: str) -> None:
        self._must("reset", "--hard", "--quiet", _check_sha(sha))

    def reset_keep(self, sha: str) -> bool:
        """손으로 고친 파일을 남기는 리셋. 그 파일이 두 커밋 사이에 바뀌었으면 git이 거부한다(False)."""
        rc, _ = self._git("reset", "--keep", _check_sha(sha))
        if rc != 0:
            log.warning("git_reset_keep_failed rc=%d", rc)
        return rc == 0

    def checkout_paths(self, sha: str, paths: list[str]) -> None:
        self._must("checkout", _check_sha(sha), "--", *paths)

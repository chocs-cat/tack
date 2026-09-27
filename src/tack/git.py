"""Git through subprocess: tack uses no Git library."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run(cwd: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    """`git [-C cwd] args...`, never raising; a missing git binary exits 127."""
    where = ["-C", str(cwd)] if cwd is not None else []
    try:
        return subprocess.run(
            ["git", *where, *args],
            capture_output=True,
            text=True,
            check=False,
            # Fail instead of waiting at a credentials prompt nobody will answer.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(["git", *args], 127, "", "git: not found")


def error(r: subprocess.CompletedProcess[str]) -> str:
    """The last thing git said on stderr, for a message."""
    lines = [line for line in r.stderr.strip().splitlines() if line.strip()]
    return lines[-1].removeprefix("fatal: ") if lines else f"git exited {r.returncode}"


def toplevel(path: Path) -> Path | None:
    """The root of the work tree containing `path`, or None outside one."""
    r = run(path, "rev-parse", "--show-toplevel")
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def tracked(repo: Path, *paths: str) -> set[str]:
    """Which of `paths` (relative to `repo`) are tracked in its index."""
    r = run(repo, "ls-files", "-z", "--", *paths)
    return set(r.stdout.split("\0")) - {""} if r.returncode == 0 else set()

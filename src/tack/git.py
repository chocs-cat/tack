"""Git through subprocess: tack uses no Git library."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`git -C cwd args...`, never raising; a missing git binary exits 127."""
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(["git", *args], 127, "", "git: not found")


def toplevel(path: Path) -> Path | None:
    """The root of the work tree containing `path`, or None outside one."""
    r = run(path, "rev-parse", "--show-toplevel")
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def tracked(repo: Path, *paths: str) -> set[str]:
    """Which of `paths` (relative to `repo`) are tracked in its index."""
    r = run(repo, "ls-files", "-z", "--", *paths)
    return set(r.stdout.split("\0")) - {""} if r.returncode == 0 else set()

"""Git through subprocess: tack uses no Git library."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

_KINDS = (b"blob", b"tree", b"commit", b"tag")


def run(cwd: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    """`git [-C cwd] args...`, never raising; a missing git binary exits 127."""
    where = ["-C", str(cwd)] if cwd is not None else []
    try:
        return subprocess.run(
            ["git", *where, *args],
            capture_output=True,
            text=True,
            check=False,
            env=_env(),
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(["git", *args], 127, "", "git: not found")


def _env() -> dict[str, str]:
    # Fail instead of waiting at a credentials prompt nobody will answer.
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def error(r: subprocess.CompletedProcess[str]) -> str:
    """The last thing git said on stderr (hints aside), for a message."""
    lines = [
        line for line in r.stderr.splitlines() if line.strip() and not line.startswith("hint:")
    ]
    if not lines:
        return f"git exited {r.returncode}"
    return lines[-1].strip().removeprefix("fatal: ").removeprefix("error: ")


def toplevel(path: Path) -> Path | None:
    """The root of the work tree containing `path`, or None outside one."""
    r = run(path, "rev-parse", "--show-toplevel")
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def log(repo: Path, fmt: str, *args: str) -> list[tuple[str, list[str]]]:
    """`git log --no-renames --name-only args...`: each commit's `fmt` line
    and the files it changes, none when git fails. Read NUL-separated, so a
    name holding a newline or a quote is itself; without rename detection, so
    a rename is its old path and its new one (design.md *Tracking upstream*).

    With `-z`, each commit is `\\0<fmt>\\0`, then, when it changes files, `\\n`
    and each name followed by `\\0`: the empty field a commit starts with is
    never a name."""
    r = run(repo, "log", "--no-renames", "-z", f"--format=%x00{fmt}", "--name-only", *args)
    commits: list[tuple[str, list[str]]] = []
    fields = iter(r.stdout.split("\0"))
    for field in fields:
        if field == "":
            head = next(fields, None)
            if head is None:
                break
            commits.append((head, []))
        elif commits:
            files = commits[-1][1]
            files.append(field if files else field.removeprefix("\n"))
    return commits


def tracked(repo: Path, *paths: str) -> set[str]:
    """Which of `paths` (relative to `repo`) are tracked in its index."""
    r = run(repo, "ls-files", "-z", "--", *paths)
    return set(r.stdout.split("\0")) - {""} if r.returncode == 0 else set()


@dataclass(frozen=True)
class Object:
    """What a path names at a commit: git's type for the object there (`blob`
    for a file, `tree` for a directory), or `missing` when there is nothing,
    `dangling` or `loop` for a symlink that leads nowhere, and `symlink` for
    one that leaves the repository."""

    kind: str
    data: bytes = b""  # a blob's contents


def cat(repo: Path, commit: str, path: str) -> Object:
    """The object at `path` (relative to the repository's root) in `commit`,
    following symlinks inside its tree as reading the checked-out file would
    (`git cat-file --batch --follow-symlinks`). A path through a file, a
    commit that isn't there and a repository git can't read are `missing`."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "--batch", "--follow-symlinks"],
            input=f"{commit}:{path}\n".encode(),
            capture_output=True,
            check=False,
            env=_env(),
        )
    except FileNotFoundError:
        return Object("missing")
    head, _, rest = r.stdout.partition(b"\n")
    parts = head.split(b" ")
    if r.returncode == 0 and len(parts) == 3 and parts[1] in _KINDS and parts[2].isdigit():
        return Object(parts[1].decode(), rest[: int(parts[2])])
    if r.returncode == 0 and len(parts) == 2 and parts[0] in (b"dangling", b"loop", b"symlink"):
        return Object(parts[0].decode())
    return Object("missing")  # also `notdir`: a path through a file

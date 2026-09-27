"""Finding the projects to audit: git repositories under the configured roots,
and which of them are clones of someone else's project."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from tack import git

PRUNE = frozenset({"node_modules"})

# scp-like remotes: `git@github.com:owner/repo.git`, `host:owner/repo`
_SCP = re.compile(r"(?:[^@/\s]+@)?[\w.-]+:(?!//)(?P<path>\S+)")


def url_owner(url: str) -> str | None:
    """The owner a remote URL names (`<host>/<owner>/<repo>`), or None for a
    local path or a URL without one."""
    if m := _SCP.fullmatch(url):
        path = m.group("path")
    else:
        parts = urlsplit(url)
        if parts.scheme in ("", "file") or not parts.netloc:
            return None
        path = parts.path
    segments = [s for s in path.split("/") if s]
    return segments[0] if len(segments) >= 2 else None


def is_clone(repo: Path, owners: Iterable[str]) -> bool:
    """Whether `repo`'s origin belongs to someone other than `owners`. With no
    owners configured, nothing is a clone."""
    mine = {o.lower() for o in owners}
    if not mine:
        return False
    r = git.run(repo, "remote", "get-url", "origin")
    owner = url_owner(r.stdout.strip()) if r.returncode == 0 else None
    return owner is not None and owner.lower() not in mine


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()  # a file in worktrees and submodules


def discover(starts: Iterable[Path], exclude: Iterable[Path] = ()) -> list[Path]:
    """Every repository at or below `starts`, not descending into a repository,
    a hidden directory, `node_modules`, or an excluded path."""
    excluded = [os.path.normpath(e) for e in exclude]
    found: list[Path] = []

    def skip(p: str) -> bool:
        return any(p == e or p.startswith(e.rstrip(os.sep) + os.sep) for e in excluded)

    def walk(d: Path) -> None:
        if is_repo(d):
            found.append(d)
            return
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            if e.name.startswith(".") or e.name in PRUNE:
                continue
            if e.is_dir(follow_symlinks=False) and not skip(os.path.normpath(e.path)):
                walk(Path(e.path))

    for start in starts:
        if start.is_dir():
            walk(Path(os.path.normpath(start)))
    return list(dict.fromkeys(found))

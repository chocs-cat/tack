"""Where each source's skills are, and bringing git sources to their pins.

A `path` source is its directory; a `git` source is tack's checkout of it
under the data directory, detached at the commit the lockfile pins. A skill
is a directory in the source's `subdir`, named by its directory name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from tack import git
from tack.config import LockEntry, Paths, Source
from tack.text import tilde


class SourceError(Exception):
    """A source sync can't bring up to date; its links are left alone."""


def root(source: Source, paths: Paths) -> Path:
    return source.path if source.path is not None else paths.sources_dir / source.name


def skills_dir(source: Source, paths: Paths) -> Path:
    return Path(os.path.normpath(root(source, paths) / source.subdir))


def offered(source: Source, paths: Paths) -> dict[str, Path] | None:
    """The source's skill directories by name; None if its skills dir isn't there."""
    d = skills_dir(source, paths)
    try:
        entries = sorted(os.scandir(d), key=lambda e: e.name)
    except OSError:
        return None
    return {e.name: Path(e.path) for e in entries if not e.name.startswith(".") and e.is_dir()}


# --- git sources ----------------------------------------------------------------


Step = Literal["pin", "clone", "checkout"]


@dataclass
class Checkout:
    entry: LockEntry  # the pin, new or as it was
    steps: list[tuple[Step, str]] = field(default_factory=list)  # (action, detail)


def remote_tip(url: str, ref: str | None) -> str:
    """The commit a remote's `ref` (a branch or tag; None for its default
    branch) points to now."""
    wanted = ["HEAD"] if ref is None else [f"refs/heads/{ref}", f"refs/tags/{ref}*"]
    r = git.run(None, "ls-remote", url, *wanted)
    if r.returncode != 0:
        raise SourceError(f"can't read {url}: {git.error(r)}")
    refs: dict[str, str] = {}
    for line in r.stdout.splitlines():
        commit, _, name = line.partition("\t")
        refs[name] = commit
    # A branch before a tag; an annotated tag by the commit it points to.
    order = ["HEAD"] if ref is None else [f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}"]
    order += [f"refs/tags/{ref}"] if ref is not None else []
    for name in order:
        if name in refs:
            return refs[name]
    raise SourceError(f"{url} has no branch or tag {ref!r}" if ref else f"{url} has no HEAD")


def head(checkout: Path) -> str | None:
    r = git.run(checkout, "rev-parse", "--verify", "--quiet", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def _has(checkout: Path, commit: str) -> bool:
    return git.run(checkout, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def local_changes(checkout: Path) -> bool:
    """Edits to tracked files (untracked ones, like a .DS_Store, don't count)."""
    r = git.run(checkout, "status", "--porcelain", "--untracked-files=no")
    return r.returncode != 0 or bool(r.stdout.strip())


def sync_git(
    source: Source,
    paths: Paths,
    entry: LockEntry | None,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> Checkout:
    """Bring tack's checkout of a git source to its pin, pinning it to the tip
    of its ref first when the lockfile has no entry for it."""
    assert source.git is not None
    if entry is not None and not entry.matches(source):
        raise SourceError(
            f"the manifest's git or ref for {source.name!r} changed since it was pinned; "
            f"`tack update {source.name}` re-pins it"
        )
    d = root(source, paths)
    exists = d.exists()
    if exists and not (d / ".git").exists():
        raise SourceError(f"{tilde(d)} is in the way and isn't a git checkout")
    if exists and local_changes(d):
        raise SourceError(f"tack's checkout at {tilde(d)} has local changes; discard or move them")

    out = Checkout(entry) if entry is not None else Checkout(_pin(source, now))
    if entry is None:
        out.steps.append(
            ("pin", f"{source.ref or 'the default branch'} at {out.entry.commit[:12]}")
        )
    commit = out.entry.commit

    if not exists:
        out.steps.append(("clone", source.git))
        if not dry_run:
            d.parent.mkdir(parents=True, exist_ok=True)
            r = git.run(None, "clone", "--quiet", "--no-checkout", source.git, str(d))
            if r.returncode != 0:
                raise SourceError(f"can't clone {source.git}: {git.error(r)}")
    elif not dry_run and git.run(d, "remote", "get-url", "origin").stdout.strip() != source.git:
        git.run(d, "remote", "set-url", "origin", source.git)

    if dry_run:
        if not exists or head(d) != commit:
            out.steps.append(("checkout", commit[:12]))
        return out
    if not _has(d, commit):
        r = git.run(d, "fetch", "--quiet", "--tags", "origin")
        if r.returncode != 0:
            raise SourceError(f"can't fetch {source.git}: {git.error(r)}")
        if not _has(d, commit):
            raise SourceError(f"pinned commit {commit[:12]} isn't in {source.git}")
    # A fresh --no-checkout clone has HEAD at the tip but no files: always check out.
    if not exists or head(d) != commit:
        r = git.run(d, "checkout", "--quiet", "--detach", commit)
        if r.returncode != 0:
            raise SourceError(f"can't check out {commit[:12]} in {tilde(d)}: {git.error(r)}")
        out.steps.append(("checkout", commit[:12]))
    return out


def _pin(source: Source, now: datetime | None) -> LockEntry:
    assert source.git is not None
    commit = remote_tip(source.git, source.ref)
    when = (now or datetime.now(UTC)).replace(microsecond=0)
    return LockEntry(source.git, source.ref, commit, when)


# --- pending edits in path sources ------------------------------------------------


def edits(source: Source, paths: Paths) -> tuple[list[str], list[str]]:
    """The skills a `path` source has uncommitted edits to, and those touched by
    commits not pushed to its upstream. Empty outside a git repository."""
    d = skills_dir(source, paths)
    top = git.toplevel(d) if d.is_dir() else None
    if top is None:
        return [], []
    rel = os.path.relpath(os.path.realpath(d), os.path.realpath(top))
    prefix = "" if rel == "." else rel + "/"

    def names(changed: list[str]) -> list[str]:
        found = {p[len(prefix) :].split("/", 1)[0] for p in changed if p.startswith(prefix)}
        return sorted(n for n in found if n and not n.startswith("."))

    status = git.run(top, "status", "--porcelain=v1", "-z", "--", rel)
    changed: list[str] = []
    fields = iter(status.stdout.split("\0"))
    for f in fields:
        if len(f) > 3:
            changed.append(f[3:])
            if "R" in f[:2] or "C" in f[:2]:
                changed.append(next(fields, ""))  # the source of a rename or copy

    log = git.run(top, "log", "--format=", "--name-only", "@{upstream}..HEAD", "--", rel)
    unpushed = names(log.stdout.splitlines()) if log.returncode == 0 else []
    return names(changed), unpushed

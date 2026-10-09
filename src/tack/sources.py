"""Where each source's skills are, and bringing git sources to their pins.

A `path` source is its directory; a `git` source is tack's checkout of it
under the data directory, detached at the commit the lockfile pins. A skill
is a directory in the source's `subdir`, named by its directory name.

*(P0001)* A plugin from another repository is a clone of that repository
under `<data>/plugins/<source>/<plugin>/`, kept at the commit its catalog
names by the same code that keeps a checkout at its pin (DEC-21).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from tack import catalog, git
from tack.config import Config, LockEntry, Paths, Source, UsageError
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


def present(source: Source, paths: Paths) -> bool:
    """Whether the source is present (design.md §5 *Source fields*).

    An empty skill selection needs only the root; every other selection
    needs a readable skills directory."""
    return (
        root(source, paths).is_dir() if source.skills == () else offered(source, paths) is not None
    )


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


def has_commit(checkout: Path, commit: str) -> bool:
    return git.run(checkout, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def fetch(checkout: Path, source: Source, commit: str) -> bool:
    """Fetch the source into tack's checkout of it, unless the checkout has
    `commit` already; whether it has it now."""
    assert source.git is not None
    return _fetch(checkout, source.git, commit)


def fetch_into_clone(clone: Path, url: str, commit: str) -> bool:
    """Fetch `commit` into a plugin's clone as `sync_clone` does when the
    clone lacks it: the remote's branches and tags, then the commit by its
    id (DEC-21). Moves nothing; whether the clone has the commit now. Raises
    SourceError when the fetch fails."""
    return _fetch(clone, url, commit, by_id=True)


def not_in(commit: str, url: str) -> str:
    """What tack says of a commit a fetch didn't bring."""
    return f"pinned commit {commit[:12]} isn't in {url}"


def in_the_way(d: Path) -> str:
    """What tack says of something at its checkout's path that isn't one."""
    return f"{tilde(d)} is in the way and isn't a git checkout"


def _fetch(checkout: Path, url: str, commit: str, *, by_id: bool = False) -> bool:
    """Fetch `url`'s branches and tags into the checkout, unless it has
    `commit` already, `origin` following `url`; then, `by_id`, the commit by
    its id if none of them reaches it. Whether it has the commit now."""
    if has_commit(checkout, commit):
        return True
    if git.run(checkout, "remote", "get-url", "origin").stdout.strip() != url:
        git.run(checkout, "remote", "set-url", "origin", url)
    r = git.run(checkout, "fetch", "--quiet", "--tags", "origin")
    if r.returncode != 0:
        raise SourceError(f"can't fetch {url}: {git.error(r)}")
    if by_id and not has_commit(checkout, commit):
        # A remote that doesn't have it refuses; the caller says so.
        git.run(checkout, "fetch", "--quiet", "origin", commit)
    return has_commit(checkout, commit)


def local_changes(checkout: Path) -> bool:
    """Edits to tracked files (untracked ones, like a .DS_Store, don't count)."""
    r = git.run(checkout, "status", "--porcelain", "--untracked-files=no")
    return r.returncode != 0 or bool(r.stdout.strip())


Blocked = Literal["in the way", "local changes"]


def _blocked(d: Path) -> Blocked | None:
    """What keeps tack from moving its checkout at `d`: something there that
    isn't a git checkout, or local changes; None when nothing does."""
    if not d.exists():
        return None
    if not (d / ".git").exists():
        return "in the way"
    return "local changes" if local_changes(d) else None


def _refuse(d: Path) -> bool:
    """Whether tack's checkout at `d` is there, refusing one it can't move
    (design.md *The lockfile*): the checkout is left as it is."""
    match _blocked(d):
        case "in the way":
            raise SourceError(in_the_way(d))
        case "local changes":
            raise SourceError(
                f"tack's checkout at {tilde(d)} has local changes; discard or move them"
            )
    return d.exists()


def _bring(
    d: Path, url: str, commit: str, *, there: bool, dry_run: bool, by_id: bool = False
) -> list[tuple[Step, str]]:
    """Bring tack's checkout at `d` (`there` or not, as `_refuse` found it)
    to `commit` from `url`: clone it when it isn't there, fetch only when it
    lacks the commit, and check the commit out detached. The steps it took,
    or, in a dry run, which clones and fetches nothing, would take.

    A clone this call made and then can't bring to `commit` is deleted
    again, so the path is `not cloned` rather than an empty index `git
    status` reads as local changes (DEC-22); one that was `there` stays."""
    steps: list[tuple[Step, str]] = []
    if not there:
        steps.append(("clone", url))
        if not dry_run:
            d.parent.mkdir(parents=True, exist_ok=True)
            r = git.run(None, "clone", "--quiet", "--no-checkout", url, str(d))
            if r.returncode != 0:
                raise SourceError(f"can't clone {url}: {git.error(r)}")

    if dry_run:
        if not there or head(d) != commit:
            steps.append(("checkout", commit[:12]))
        return steps
    try:
        if not _fetch(d, url, commit, by_id=by_id):
            raise SourceError(not_in(commit, url))
        # A fresh --no-checkout clone has HEAD at the tip but no files: always check out.
        if not there or head(d) != commit:
            r = git.run(d, "checkout", "--quiet", "--detach", commit)
            if r.returncode != 0:
                raise SourceError(f"can't check out {commit[:12]} in {tilde(d)}: {git.error(r)}")
            steps.append(("checkout", commit[:12]))
    except SourceError:
        if not there:
            shutil.rmtree(d, ignore_errors=True)
        raise
    return steps


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
    there = _refuse(d)
    out = Checkout(entry) if entry is not None else Checkout(pin(source, now))
    if entry is None:
        out.steps.append(("pin", pin_detail(out.entry)))
    out.steps += _bring(d, source.git, out.entry.commit, there=there, dry_run=dry_run)
    return out


def pin(source: Source, now: datetime | None = None) -> LockEntry:
    """A lock entry for the source at the tip of its ref."""
    assert source.git is not None
    commit = remote_tip(source.git, source.ref)
    when = (now or datetime.now(UTC)).replace(microsecond=0)
    return LockEntry(source.git, source.ref, commit, when)


def pin_detail(entry: LockEntry) -> str:
    return f"{entry.ref or 'the default branch'} at {entry.commit[:12]}"


def git_sources(cfg: Config, names: Sequence[str]) -> list[Source]:
    """The git sources `names` asks for (every one if it is empty), in
    manifest order."""
    by_name = {s.name: s for s in cfg.sources}
    for name in names:
        if name not in by_name:
            raise UsageError(f"no source named {name!r}")
        if by_name[name].git is None:
            raise UsageError(f"{name!r} is a path source; only git sources are pinned")
    return [s for s in cfg.sources if s.git is not None and (not names or s.name in names)]


# --- plugins' clones (design.md *Plugins from other repositories*) ---------------

# A clone's state, the first that applies (in DEC-21's terms, a checkout's):
#   in the way      something at its path isn't a git checkout
#   not cloned      nothing is there
#   local changes   its tracked files differ from its HEAD
#   off its commit  its HEAD isn't the catalog's commit
CloneState = Literal["in the way", "not cloned", "local changes", "off its commit", "ok"]


@dataclass(frozen=True)
class Clone:
    """A plugin's clone of another repository, kept as a source's checkout
    is (DEC-21)."""

    path: Path  # <data>/plugins/<source>/<plugin>
    where: catalog.InRepository

    @classmethod
    def of(cls, paths: Paths, source: str, plugin: str, where: catalog.InRepository) -> Clone:
        return cls(paths.clones_dir / source / plugin, where)

    @property
    def directory(self) -> Path:
        """The plugin's files: the clone, or the entry's `path` inside it."""
        return self.path if self.where.path is None else self.path / self.where.path

    def state(self) -> CloneState:
        if (blocked := _blocked(self.path)) is not None:
            return blocked
        if not self.path.exists():
            return "not cloned"
        return "ok" if head(self.path) == self.where.commit else "off its commit"


def sync_clone(clone: Clone, *, dry_run: bool = False) -> list[tuple[Step, str]]:
    """Bring a plugin's clone to its catalog's commit, as `sync_git` brings a
    checkout to its pin, fetching the commit by its id when no branch or tag
    reaches it (DEC-21). Raises SourceError as `sync_git` does in the same
    case, leaving a clone in the way or with local changes as it is."""
    there = _refuse(clone.path)
    w = clone.where
    return _bring(clone.path, w.url, w.commit, there=there, dry_run=dry_run, by_id=True)


# --- pending edits in path sources ------------------------------------------------


def skills_in(files: Iterable[str], rel: str) -> set[str]:
    """The skills that paths (relative to a work tree) are in, for a skills dir
    at `rel` ("." at the root): the directories directly in it. A loose file
    beside them is in no skill."""
    prefix = "" if rel == "." else rel + "/"
    out: set[str] = set()
    for f in files:
        if f.startswith(prefix):
            name, sep, _ = f[len(prefix) :].partition("/")
            if sep and name and not name.startswith("."):
                out.add(name)
    return out


def skills_at(repo: Path, commit: str, rel: str) -> set[str]:
    """The skills in `rel` ("." at the root) at `commit`: the directories
    there; none if the commit (or `rel` in it) doesn't exist."""
    tree = f"{commit}:" if rel == "." else f"{commit}:{rel}"
    r = git.run(repo, "ls-tree", "-d", "--name-only", "-z", tree)
    if r.returncode != 0:
        return set()
    return {n for n in r.stdout.split("\0") if n and not n.startswith(".")}


def work_tree(source: Source, paths: Paths) -> tuple[Path, str] | None:
    """The git work tree holding a source's skills dir, and that dir relative
    to it ("." at its root); None outside one."""
    d = skills_dir(source, paths)
    top = git.toplevel(d) if d.is_dir() else None
    if top is None:
        return None
    return top, os.path.relpath(os.path.realpath(d), os.path.realpath(top))


def uncommitted(top: Path, rel: str) -> set[str]:
    """The skills in `rel` with uncommitted edits, new files included."""
    r = git.run(
        top, "--literal-pathspecs", "status", "--porcelain=v1", "-z", "--untracked-files=all",
        "--", rel,
    )  # fmt: skip
    changed: list[str] = []
    fields = iter(r.stdout.split("\0"))
    for f in fields:
        if len(f) > 3:
            changed.append(f[3:])
            if "R" in f[:2] or "C" in f[:2]:
                changed.append(next(fields, ""))  # the source of a rename or copy
    return skills_in(changed, rel)


def unpushed(top: Path, rel: str) -> set[str]:
    """The skills in `rel` touched by commits not in the branch's upstream;
    none when it has no upstream. A file's name may hold any character, and a
    file moved from one skill to another touches both (design.md
    *Auto-commit*)."""
    r = git.run(
        top, "--literal-pathspecs", "log", "--no-renames", "-z", "--format=", "--name-only",
        "@{upstream}..HEAD", "--", rel,
    )  # fmt: skip
    return skills_in(r.stdout.split("\0"), rel) if r.returncode == 0 else set()


def edits(source: Source, paths: Paths) -> tuple[list[str], list[str]]:
    """The skills a `path` source has uncommitted edits to, and those touched by
    commits not pushed to its upstream. Empty outside a git repository."""
    where = work_tree(source, paths)
    if where is None:
        return [], []
    return sorted(uncommitted(*where)), sorted(unpushed(*where))

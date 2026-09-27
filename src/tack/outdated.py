"""`tack outdated`: how far each git source's pin is behind the tip of its ref.

It fetches into tack's checkouts but never moves one: the pin is compared with
the tip in git's object store. Reported are the commits between them, the ones
touching selected skills, and each selected skill that changed. For a source
taking every skill, a skill at either end is selected, so a new upstream skill
shows as added.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tack import config, git, sources
from tack.config import Config, LockEntry, Source
from tack.sources import SourceError

State = Literal["current", "behind", "not pinned", "manifest changed", "not checked out", "error"]
SkillChange = Literal["modified", "added", "removed"]


@dataclass(frozen=True)
class ChangedSkill:
    name: str
    change: SkillChange


@dataclass(frozen=True)
class Commit:
    commit: str
    subject: str
    skills: list[str]  # the selected skills it touches


@dataclass
class SourceReport:
    name: str
    git: str
    ref: str | None
    state: State
    message: str | None = None  # why it couldn't be compared
    pin: str | None = None
    tip: str | None = None
    behind: int = 0  # commits in the tip's history that aren't in the pin's
    rewritten: bool = False  # the tip's history doesn't contain the pin
    skills: list[ChangedSkill] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)  # newest first
    diff: str | None = None


@dataclass
class Report:
    sources: list[SourceReport]

    @property
    def failed(self) -> bool:
        """Any source behind, or not compared, fails the run."""
        return any(s.state != "current" for s in self.sources)


def outdated(cfg: Config, names: Sequence[str] = (), *, diff: bool = False) -> Report:
    """Compare the named git sources (every one if none are) with upstream."""
    lock = config.load_lock(cfg.paths)
    return Report(
        [
            _compare(src, cfg, lock.get(src.name), diff=diff)
            for src in sources.git_sources(cfg, names)
        ]
    )


def _compare(src: Source, cfg: Config, entry: LockEntry | None, *, diff: bool) -> SourceReport:
    assert src.git is not None
    r = SourceReport(src.name, src.git, src.ref, "current")
    if entry is None:
        r.state, r.message = "not pinned", "not pinned yet; `tack sync` pins it"
        return r
    r.pin = entry.commit
    if not entry.matches(src):
        r.state = "manifest changed"
        r.message = (
            f"the manifest's git or ref changed since it was pinned; "
            f"`tack update {src.name}` re-pins it"
        )
        return r
    d = sources.root(src, cfg.paths)
    if not (d / ".git").exists():
        r.state, r.message = "not checked out", "not checked out; `tack sync` fetches it"
        return r
    try:
        r.tip = sources.remote_tip(src.git, src.ref)
        if r.tip == r.pin:
            return r
        if not sources.fetch(d, src, r.tip):
            raise SourceError(f"fetching {src.git} didn't bring its tip {r.tip[:12]}")
    except SourceError as e:
        r.state, r.message = "error", str(e)
        return r

    pin, tip = r.pin, r.tip
    r.state = "behind"
    count = git.run(d, "rev-list", "--count", f"{pin}..{tip}")
    r.behind = int(count.stdout) if count.returncode == 0 else 0
    r.rewritten = git.run(d, "merge-base", "--is-ancestor", pin, tip).returncode != 0

    sub = os.path.normpath(src.subdir)
    prefix = "" if sub == "." else sub + "/"
    at_pin, at_tip = _skill_dirs(d, pin, sub), _skill_dirs(d, tip, sub)
    selected = at_pin | at_tip if src.skills is None else {s.name for s in src.skills}

    changed = git.run(d, "diff", "--name-only", "-z", pin, tip, "--", sub)
    touched = _skills_in(changed.stdout.split("\0"), prefix) & selected
    for name in sorted(touched):
        kind: SkillChange = (
            "added" if name not in at_pin else "removed" if name not in at_tip else "modified"
        )
        r.skills.append(ChangedSkill(name, kind))

    log = git.run(
        d, "-c", "core.quotePath=false", "log", "--format=%x1e%H%x1f%s", "--name-only",
        f"{pin}..{tip}", "--", sub,
    )  # fmt: skip
    for record in log.stdout.split("\x1e")[1:]:
        head, _, files = record.partition("\n")
        commit, _, subject = head.partition("\x1f")
        if names := sorted(_skills_in(files.splitlines(), prefix) & selected):
            r.commits.append(Commit(commit, subject, names))

    if diff and touched:
        paths = [prefix + name for name in sorted(touched)]
        out = git.run(d, "diff", "--no-color", "--no-ext-diff", pin, tip, "--", *paths)
        r.diff = out.stdout
    return r


def _skill_dirs(checkout: Path, commit: str, sub: str) -> set[str]:
    """The skill directories in `sub` at `commit`."""
    tree = f"{commit}:" if sub == "." else f"{commit}:{sub}"
    r = git.run(checkout, "ls-tree", "-d", "--name-only", "-z", tree)
    if r.returncode != 0:
        return set()
    return {n for n in r.stdout.split("\0") if n and not n.startswith(".")}


def _skills_in(files: list[str], prefix: str) -> set[str]:
    """The skills that paths (relative to the checkout) under `prefix` are in."""
    out: set[str] = set()
    for f in files:
        if f.startswith(prefix):
            name, sep, _ = f[len(prefix) :].partition("/")
            if sep and not name.startswith("."):
                out.add(name)
    return out

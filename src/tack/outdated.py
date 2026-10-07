"""`tack outdated`: how far each git source's pin is behind the tip of its ref.

It fetches into tack's checkouts but never moves one: the pin is compared with
the tip in git's object store. Reported are the commits between them, the ones
touching selected skills, and each selected skill that changed. For a source
taking every skill, a skill at either end is selected, so a new upstream skill
shows as added.

A source that selects plugins has them compared the same way, from its
catalog read from git at each end (design.md *Tracking plugins upstream*); a
catalog broken at either end leaves them uncompared (DEC-20).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

from tack import catalog, config, git, sources
from tack.config import Config, LockEntry, Source
from tack.sources import SourceError

State = Literal["current", "behind", "not pinned", "manifest changed", "not checked out", "error"]
SkillChange = Literal["modified", "added", "removed"]


@dataclass(frozen=True)
class ChangedSkill:
    name: str
    change: SkillChange


# A changed plugin's version at the pin and at the tip, either None.
Versions = TypedDict("Versions", {"from": str | None, "to": str | None})


@dataclass(frozen=True)
class ChangedPlugin:
    name: str
    change: SkillChange
    version: Versions


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
    plugins: list[ChangedPlugin] = field(default_factory=list)
    plugins_error: str | None = None  # why its plugins couldn't be compared (DEC-20)
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
    at_pin, at_tip = sources.skills_at(d, pin, sub), sources.skills_at(d, tip, sub)
    selected = at_pin | at_tip if src.skills is None else {s.name for s in src.skills}

    changed = git.run(d, "diff", "--name-only", "-z", pin, tip, "--", sub)
    touched = sources.skills_in(changed.stdout.split("\0"), sub) & selected
    for name in sorted(touched):
        kind: SkillChange = (
            "added" if name not in at_pin else "removed" if name not in at_tip else "modified"
        )
        r.skills.append(ChangedSkill(name, kind))
    if src.plugins != ():
        _plugins(r, src, d, pin, tip)

    log = git.run(
        d, "-c", "core.quotePath=false", "log", "--format=%x1e%H%x1f%s", "--name-only",
        f"{pin}..{tip}", "--", sub,
    )  # fmt: skip
    for record in log.stdout.split("\x1e")[1:]:
        head, _, files = record.partition("\n")
        commit, _, subject = head.partition("\x1f")
        if names := sorted(sources.skills_in(files.splitlines(), sub) & selected):
            r.commits.append(Commit(commit, subject, names))

    if diff and touched:
        paths = [prefix + name for name in sorted(touched)]
        out = git.run(d, "diff", "--no-color", "--no-ext-diff", pin, tip, "--", *paths)
        r.diff = out.stdout
    return r


# --- plugins --------------------------------------------------------------------------


@dataclass
class _End:
    """A source's catalog at the pin or the tip."""

    commit: str
    first: dict[str, catalog.Plugin]  # each name's first entry, as `plugins.plan` takes it
    entries: dict[str, list[Mapping[str, Any]]]  # each name's entries, in catalog order


def _end(repo: Path, commit: str) -> _End:
    found = catalog.read_at(repo, commit)
    end = _End(commit, {}, {})
    for p in found.plugins if found else ():
        end.first.setdefault(p.name, p)
        end.entries.setdefault(p.name, []).append(p.entry)
    return end


def _plugins(r: SourceReport, src: Source, repo: Path, pin: str, tip: str) -> None:
    """Each selected plugin that changed between the pin and the tip, with
    its versions; or, when the catalog is broken at either end, why they
    weren't compared (DEC-20)."""
    ends: list[_End] = []
    for which, commit in (("pin", pin), ("tip", tip)):
        try:
            ends.append(_end(repo, commit))
        except catalog.CatalogError as e:
            r.plugins_error = (
                f"plugins not compared: the catalog at the {which} ({commit[:12]}) is broken: {e}"
            )
            return
    before, after = ends
    names = set(before.first) | set(after.first)
    if src.plugins is not None:
        names &= {s.name for s in src.plugins}
    changed = git.run(repo, "diff", "--no-renames", "--name-only", "-z", pin, tip)
    files = [f for f in changed.stdout.split("\0") if f]
    for name in sorted(names):
        if name not in before.first:
            kind: SkillChange = "added"
        elif name not in after.first:
            kind = "removed"
        elif _json(before.entries[name]) != _json(after.entries[name]) or any(
            _under(f, d) for d in _directories(before, after, name) for f in files
        ):
            kind = "modified"
        else:
            continue
        version: Versions = {
            "from": _version(repo, before, name),
            "to": _version(repo, after, name),
        }
        r.plugins.append(ChangedPlugin(name, kind, version))


def _json(value: Any) -> str:
    """A JSON value's canonical text: entries compare as JSON, not as text."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _directories(before: _End, after: _End, name: str) -> list[str]:
    """A plugin's directory at each end where it is in the source: one from
    another repository, or one tack can't deploy, changes only with its entry."""
    return [
        p.where.path
        for p in (before.first.get(name), after.first.get(name))
        if p is not None and isinstance(p.where, catalog.InSource)
    ]


def _under(file: str, directory: str) -> bool:
    return directory == "." or file.startswith(directory + "/")


def _version(repo: Path, end: _End, name: str) -> str | None:
    """As `status` takes it (design.md *Catalogs*), from git at that end."""
    p = end.first.get(name)
    if p is None:
        return None
    if isinstance(p.where, catalog.InSource):
        return catalog.version(p.entry, catalog.files_at(repo, end.commit, p.where.path))
    return catalog.version(p.entry, lambda _: None)

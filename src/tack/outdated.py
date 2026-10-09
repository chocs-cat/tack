"""`tack outdated`: how far each git source's pin is behind the tip of its ref.

It fetches into tack's checkouts but never moves one: the pin is compared with
the tip in git's object store. Reported are the commits between them, the ones
touching selected skills, and each selected skill that changed. For a source
taking every skill, a skill at either end is selected, so a new upstream skill
shows as added.

A source that selects plugins has them compared the same way, from its
catalog read from git at each end (design.md *Tracking plugins upstream*):
the commits listed are those touching selected skills or plugins, and the
diff adds each changed plugin's. A catalog broken at either end leaves them
uncompared (DEC-20). For a plugin moved to another commit of its other
repository, the diff adds the two commits', fetched into its clone, which,
like a checkout, is never moved, and is never created (DEC-23).
"""

from __future__ import annotations

import difflib
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
    plugins: list[str] = field(default_factory=list)  # the selected plugins it touches


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

    changed = git.run(d, "diff", "--no-renames", "--name-only", "-z", pin, tip, "--", sub)
    touched = sources.skills_in(changed.stdout.split("\0"), sub) & selected
    for name in sorted(touched):
        kind: SkillChange = (
            "added" if name not in at_pin else "removed" if name not in at_tip else "modified"
        )
        r.skills.append(ChangedSkill(name, kind))
    tracked = _plugins(r, src, cfg.paths, d, pin, tip) if src.plugins != () else None

    for head, files in git.log(d, "%H%x1f%s", f"{pin}..{tip}", "--", sub):
        commit, _, subject = head.partition("\x1f")
        if names := sorted(sources.skills_in(files, sub) & selected):
            r.commits.append(Commit(commit, subject, names))
    if tracked is not None:
        r.commits = tracked.commits({c.commit: c.skills for c in r.commits})

    if diff and (touched or r.plugins):
        parts = []
        if touched:
            paths = [prefix + name for name in sorted(touched)]
            out = git.run(d, "diff", "--no-color", "--no-ext-diff", pin, tip, "--", *paths)
            parts.append(out.stdout)
        if tracked is not None:
            parts += [tracked.diff(p.name) for p in r.plugins]
        r.diff = "".join(parts)
    return r


# --- plugins --------------------------------------------------------------------------


@dataclass
class _End:
    """A source's catalog at a commit."""

    commit: str
    file: str | None  # the catalog file, relative to the source root
    first: dict[str, catalog.Plugin]  # each name's first entry, as `plugins.plan` takes it
    entries: dict[str, list[Mapping[str, Any]]]  # each name's entries, in catalog order


def _end(repo: Path, commit: str) -> _End:
    found = catalog.read_at(repo, commit)
    end = _End(commit, found.file if found else None, {}, {})
    for p in found.plugins if found else ():
        end.first.setdefault(p.name, p)
        end.entries.setdefault(p.name, []).append(p.entry)
    return end


def _plugins(
    r: SourceReport, src: Source, paths: config.Paths, repo: Path, pin: str, tip: str
) -> _Tracked | None:
    """Each selected plugin that changed between the pin and the tip, with
    its versions; or, when the catalog is broken at either end, why they
    weren't compared (DEC-20), and None."""
    ends: list[_End] = []
    for which, commit in (("pin", pin), ("tip", tip)):
        try:
            ends.append(_end(repo, commit))
        except catalog.CatalogError as e:
            r.plugins_error = (
                f"plugins not compared: the catalog at the {which} ({commit[:12]}) is broken: {e}"
            )
            return None
    before, after = ends
    names = set(before.first) | set(after.first)
    if src.plugins is not None:
        names &= {s.name for s in src.plugins}
    directories = {n: _directories(before, after, n) for n in names}
    tracked = _Tracked(repo, before, after, directories, paths.clones_dir / src.name)
    changed = git.run(repo, "diff", "--no-renames", "--name-only", "-z", pin, tip)
    files = [f for f in changed.stdout.split("\0") if f]
    for name in sorted(names):
        if name not in before.first:
            kind: SkillChange = "added"
        elif name not in after.first:
            kind = "removed"
        elif tracked.entry_changed(name) or tracked.under(name, files):
            kind = "modified"
        else:
            continue
        version: Versions = {
            "from": _version(repo, before, name),
            "to": _version(repo, after, name),
        }
        r.plugins.append(ChangedPlugin(name, kind, version))
    return tracked


@dataclass
class _Tracked:
    """A source's selected plugins, between its pin (`before`) and its tip."""

    repo: Path
    before: _End
    after: _End
    directories: dict[str, list[str]]  # each selected plugin's, by `_directories`
    clones: Path  # the source's plugins' clones: plugins/<source>/
    _entries: dict[str, dict[str, list[Mapping[str, Any]]]] = field(default_factory=dict)

    def entry_changed(self, name: str) -> bool:
        return _json(self.before.entries.get(name)) != _json(self.after.entries.get(name))

    def under(self, name: str, files: Sequence[str]) -> bool:
        """Whether any of `files` is under the plugin's directory at either end."""
        return any(_under(f, d) for d in self.directories[name] for f in files if f)

    def commits(self, skills: Mapping[str, list[str]]) -> list[Commit]:
        """The commits between the pin and the tip that touch selected skills
        (`skills`, by commit) or selected plugins, newest first (DEC-20)."""
        span = f"{self.before.commit}..{self.after.commit}"
        out: list[Commit] = []
        for head, files in git.log(self.repo, "%H%x1f%P%x1f%s", span):
            commit, parents, subject = head.split("\x1f", 2)
            plugins = self._touched(commit, parents.split(), files)
            names = skills.get(commit, [])
            if names or plugins:
                out.append(Commit(commit, subject, names, plugins))
        return out

    def _touched(self, commit: str, parents: list[str], files: list[str]) -> list[str]:
        """The selected plugins a commit touches: a file under one's directory
        at the pin or the tip, or a catalog file changed so that one's entries
        differ from the first parent's. A merge touches nothing."""
        if len(parents) > 1:
            return []
        out = {name for name in self.directories if self.under(name, files)}
        if any(f in catalog.CATALOGS for f in files):
            now = self._at(commit)
            was = self._at(parents[0]) if parents else {}
            out |= {n for n in self.directories if _json(now.get(n)) != _json(was.get(n))}
        return sorted(out)

    def _at(self, commit: str) -> dict[str, list[Mapping[str, Any]]]:
        """Each name's entries at a commit; none where the catalog can't be read."""
        if commit not in self._entries:
            try:
                self._entries[commit] = _end(self.repo, commit).entries
            except catalog.CatalogError:
                self._entries[commit] = {}
        return self._entries[commit]

    def diff(self, name: str) -> str:
        """A changed plugin's diff: its files under its directory at either
        end, then its entry's, as JSON, when that changed, then, for one from
        the same other repository at both ends, its commits' (DEC-23)."""
        out = ""
        if paths := sorted(set(self.directories[name])):
            r = git.run(
                self.repo, "--literal-pathspecs", "diff", "--no-color", "--no-ext-diff",
                self.before.commit, self.after.commit, "--", *paths,
            )  # fmt: skip
            out += r.stdout
        if self.entry_changed(name):
            was, now = self.before.entries.get(name), self.after.entries.get(name)
            out += "".join(
                difflib.unified_diff(
                    _entry_lines(was),
                    _entry_lines(now),
                    f"a/{self.before.file}#{name}" if was is not None else "/dev/null",
                    f"b/{self.after.file}#{name}" if now is not None else "/dev/null",
                )
            )
        return out + self._commits_diff(name)

    def _commits_diff(self, name: str) -> str:
        """For a plugin from another repository at both ends, with the same
        URL and a different commit, the diff between its two commits in its
        clone, limited to the entry's `path` at each end; or a line saying
        why there is none (design.md *Tracking plugins upstream*, DEC-23).
        Each commit the clone lacks is fetched as `sync` fetches it; the
        clone is never created, checked out or moved, so a missing one, or
        something in its place, reads no `git status` either."""
        was, now = self.before.first.get(name), self.after.first.get(name)
        if was is None or now is None:
            return ""
        a, b = was.where, now.where
        if not isinstance(a, catalog.InRepository) or not isinstance(b, catalog.InRepository):
            return ""
        if a.url != b.url or a.commit == b.commit:
            return ""
        clone = self.clones / name
        try:
            if not clone.exists():
                raise SourceError("it isn't cloned; `tack sync` clones it")
            if not (clone / ".git").exists():
                raise SourceError(sources.in_the_way(clone))
            for commit in (a.commit, b.commit):
                if not sources.fetch_into_clone(clone, a.url, commit):
                    raise SourceError(sources.not_in(commit, a.url))
        except SourceError as e:
            return f"plugin '{name}': no diff between its commits: {e}\n"
        paths = [] if a.path is None or b.path is None else sorted({a.path, b.path})
        r = git.run(
            clone, "--literal-pathspecs", "diff", "--no-color", "--no-ext-diff",
            f"--src-prefix=a/{name}@{a.commit[:12]}/", f"--dst-prefix=b/{name}@{b.commit[:12]}/",
            a.commit, b.commit, "--", *paths,
        )  # fmt: skip
        return r.stdout


def _entry_lines(entries: list[Mapping[str, Any]] | None) -> list[str]:
    """A plugin's entry as JSON lines, in the catalog's key order: its one
    entry, or the list of a name listed more than once."""
    if entries is None:
        return []
    value = entries[0] if len(entries) == 1 else entries
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").splitlines(keepends=True)


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

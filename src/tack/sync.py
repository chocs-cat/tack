"""`tack sync`: make every harness match the manifest and the lockfile.

Git sources are brought to their pins first (pinning any the lockfile doesn't
know yet), then each harness's links are created, repointed or removed. Only
tack's own links are ever replaced or removed; anything else in the way is a
conflict, which `adopt` takes over. A source that can't be brought up to date
is *held*: its links are left exactly as they are.

`update`, `add` and `remove` finish with a sync, handing it the pins they
want in place of the lockfile's; the lockfile is written once, if they differ.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from tack import config, deploy, sources
from tack.config import Config, Harness, LockEntry
from tack.deploy import Plan, Record, Selected
from tack.sources import SourceError
from tack.text import tilde

Action = Literal[
    "pin", "update", "clone", "checkout", "write", "link", "relink", "unlink", "adopt", "delete",
    "commit", "push", "move",
]  # fmt: skip
ProblemKind = Literal[
    "source", "conflict", "collision", "after-save", "commit", "push", "refused", "error"
]


@dataclass(frozen=True)
class Change:
    action: Action
    detail: str
    source: str | None = None
    harness: str | None = None
    path: Path | None = None
    diff: str | None = None  # a written file's unified diff, where tack shows one


@dataclass(frozen=True)
class Problem:
    kind: ProblemKind
    message: str
    source: str | None = None
    harness: str | None = None
    path: Path | None = None


@dataclass(frozen=True)
class Note:
    """Something worth knowing that isn't a problem, like a skipped auto-commit."""

    message: str
    source: str | None = None
    path: Path | None = None


@dataclass
class Result:
    dry_run: bool
    changes: list[Change] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    def extend(self, other: Result) -> Result:
        self.changes += other.changes
        self.problems += other.problems
        self.notes += other.notes
        return self


def sync(
    cfg: Config,
    *,
    dry_run: bool = False,
    adopt: bool = False,
    now: datetime | None = None,
    lock: dict[str, LockEntry] | None = None,
) -> Result:
    """Sync; `lock`, when given, stands in for the lockfile's pins."""
    now = now or datetime.now(UTC)
    result = Result(dry_run)
    held = _sources(cfg, result, dry_run=dry_run, now=now, lock=lock)
    plan = deploy.plan(cfg)
    for name, (harnesses, srcs) in plan.collisions.items():
        result.problems.append(
            Problem(
                "collision",
                f"skill {name!r} is selected from sources {', '.join(srcs)} for "
                f"{', '.join(harnesses)}; none of them is deployed -- deselect all but one",
                path=cfg.manifest,
            )
        )
    record = deploy.load_record(cfg.paths)
    before = dict(record.links)
    linker = _Linker(cfg, plan, record, held, result, dry_run=dry_run, adopt=adopt, now=now)
    for h in cfg.harnesses.values():
        linker.harness(h)
    _prune(record)
    if record.links != before and not dry_run:
        deploy.save_record(cfg.paths, record)
    return result


def _sources(
    cfg: Config,
    result: Result,
    *,
    dry_run: bool,
    now: datetime,
    lock: dict[str, LockEntry] | None,
) -> set[str]:
    """Bring git sources to their pins and write the lockfile; the names of the
    sources whose links must be left alone."""
    held: set[str] = set()
    on_disk = config.load_lock(cfg.paths)
    lock = on_disk if lock is None else lock
    pins: dict[str, LockEntry] = dict(lock)
    for src in cfg.sources:
        if src.git is None:
            if sources.offered(src, cfg.paths) is None:
                held.add(src.name)
                where = tilde(sources.skills_dir(src, cfg.paths))
                result.problems.append(
                    Problem("source", f"no skills directory at {where}", source=src.name)
                )
            continue
        try:
            checkout = sources.sync_git(
                src, cfg.paths, lock.get(src.name), dry_run=dry_run, now=now
            )
        except SourceError as e:
            held.add(src.name)
            result.problems.append(Problem("source", str(e), source=src.name))
            continue
        pins[src.name] = checkout.entry
        for action, detail in checkout.steps:
            result.changes.append(
                Change(action, detail, source=src.name, path=sources.root(src, cfg.paths))
            )
        if dry_run and src.skills is None and not sources.root(src, cfg.paths).exists():
            held.add(src.name)  # which skills it has is unknown until it is fetched

    if pins != on_disk:
        file = cfg.paths.lockfile
        result.changes.append(Change("write", tilde(file), path=file))
        written = not dry_run and config.save_lock(cfg.paths, pins)
        if written and (error := config.run_after_save(cfg, file)):
            result.problems.append(Problem("after-save", error, path=file))
    return held


@dataclass
class _Linker:
    cfg: Config
    plan: Plan
    record: Record
    held: set[str]
    result: Result
    dry_run: bool
    adopt: bool
    now: datetime

    def harness(self, h: Harness) -> None:
        want = self.plan.links[h.name]
        collided = {n for n, (hs, _) in self.plan.collisions.items() if h.name in hs}
        for name, sel in want.items():
            if sel.source.name not in self.held:
                self._want(h, h.skills_dir / name, sel)
        held_roots = [
            sources.root(s, self.cfg.paths) for s in self.cfg.sources if s.name in self.held
        ]
        try:
            entries = sorted(os.scandir(h.skills_dir), key=lambda e: e.name)
        except OSError:
            entries = []
        for e in entries:
            if h.ignores(e.name) or e.name in want or e.name in collided:
                continue
            entry = Path(e.path)
            if deploy.state(entry, None, self.cfg, self.record) != "owned":
                continue
            target = deploy.link_target(entry)
            if any(deploy.within(target, r) for r in held_roots):
                continue
            self._do(
                Change(
                    "unlink", f"{e.name} (a link to {tilde(target)})", harness=h.name, path=entry
                ),
                entry.unlink,
            )
            self.record.links.pop(str(entry), None)

    def _want(self, h: Harness, entry: Path, sel: Selected) -> None:
        name = entry.name
        if h.ignores(name):
            self._problem(
                "conflict",
                f"{name!r} is in {h.name}'s ignore list, so tack won't deploy it there",
                h,
                entry,
                sel,
            )
            return
        st = deploy.state(entry, sel, self.cfg, self.record)
        target = sel.path
        arrow = f"{name} -> {tilde(target)}"
        if st == "ok":
            self.record.links[str(entry)] = str(target)
            return
        if st == "absent":
            change = Change("link", arrow, sel.source.name, h.name, entry)
            if self._do(change, lambda: deploy.make_link(entry, target)):
                self.record.links[str(entry)] = str(target)
            return
        if st == "stale":
            was = tilde(deploy.link_target(entry))
            change = Change("relink", f"{arrow} (was {was})", sel.source.name, h.name, entry)
            if self._do(change, lambda: deploy.make_link(entry, target)):
                self.record.links[str(entry)] = str(target)
            return
        # A conflict: something tack doesn't own is where the skill goes.
        if entry.is_symlink():
            what = f"a link to {tilde(deploy.link_target(entry))}"
        else:
            what = f"a real {'directory' if entry.is_dir() else 'file'}"
        if not self.adopt:
            self._problem(
                "conflict",
                f"{what} is in the way; `tack sync --adopt` takes it over",
                h,
                entry,
                sel,
            )
            return
        stamp = self.now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = self.cfg.paths.state_dir / "adopted" / stamp / h.name / name
        symlink = entry.is_symlink()

        def take_over() -> None:
            if symlink:
                entry.unlink()
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(entry, dest)
            deploy.make_link(entry, target)

        detail = f"replaced {what}" if symlink else f"moved {what} to {tilde(dest)}"
        change = Change("adopt", f"{arrow} ({detail})", sel.source.name, h.name, entry)
        if self._do(change, take_over):
            self.record.links[str(entry)] = str(target)

    def _do(self, change: Change, step: Callable[[], object]) -> bool:
        """Record a change and, unless this is a dry run, make it."""
        if not self.dry_run:
            try:
                step()
            except OSError as e:
                self.result.problems.append(
                    Problem(
                        "error", f"{change.detail}: {e}", harness=change.harness, path=change.path
                    )
                )
                return False
        self.result.changes.append(change)
        return True

    def _problem(
        self, kind: ProblemKind, message: str, h: Harness, entry: Path, sel: Selected
    ) -> None:
        self.result.problems.append(
            Problem(kind, f"{entry.name}: {message}", sel.source.name, h.name, entry)
        )


def _prune(record: Record) -> None:
    """Forget links that are gone or were repointed by someone else."""
    for link, target in list(record.links.items()):
        p = Path(link)
        if not p.is_symlink() or not deploy.same_path(deploy.link_target(p), Path(target)):
            del record.links[link]

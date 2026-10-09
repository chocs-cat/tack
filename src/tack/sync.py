"""`tack sync`: make every harness match the manifest and the lockfile.

Git sources are brought to their pins first (pinning any the lockfile doesn't
know yet), then each harness's links are created, repointed or removed. Only
tack's own links are ever replaced or removed; anything else in the way is a
conflict, which `adopt` takes over. A source that can't be brought up to date
is *held*: its links are left exactly as they are.

Plugins come after the skills: tack's marketplace is brought up to date, then
each harness that takes plugins is made to match it through its agent's CLI
(design.md *Deploying*). A manifest without plugins runs no agent at all.

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

from tack import agents, catalog, config, deploy, plugins, sources
from tack.config import Config, Harness, LockEntry
from tack.deploy import Install, Plan, Record, Selected
from tack.sources import SourceError
from tack.text import tilde

Action = Literal[
    "pin", "update", "clone", "checkout", "write", "link", "relink", "unlink", "adopt", "delete",
    "commit", "push", "move",
    "copy", "register", "install", "reinstall", "uninstall", "unregister",
]  # fmt: skip
ProblemKind = Literal[
    "source", "conflict", "collision", "after-save", "commit", "push", "refused", "error", "agent"
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
    before = (dict(record.links), _installs(record))
    linker = _Linker(cfg, plan, record, held, result, dry_run=dry_run, adopt=adopt, now=now)
    for h in cfg.harnesses.values():
        linker.harness(h)
    _prune(record)
    _Plugins(cfg, record, result, held, dry_run=dry_run).run()
    if (record.links, _installs(record)) != before and not dry_run:
        deploy.save_record(cfg.paths, record)
    return result


def _installs(record: Record) -> dict[str, dict[str, Install]]:
    return {h: dict(by_name) for h, by_name in record.plugins.items() if by_name}


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
            if not sources.present(src, cfg.paths):
                held.add(src.name)
                directory = (
                    sources.root(src, cfg.paths)
                    if src.skills == ()
                    else sources.skills_dir(src, cfg.paths)
                )
                where = tilde(directory)
                what = "directory" if src.skills == () else "skills directory"
                result.problems.append(Problem("source", f"no {what} at {where}", source=src.name))
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


# What each agent command is, as a change.
_ACTIONS: dict[agents.Kind, Action] = {
    "register": "register",
    "install": "install",
    "uninstall": "uninstall",
    "unregister": "unregister",
}
# What failed, for the problem an agent command's failure is.
_FAILED = {
    "list": "listing its plugins",
    "marketplace-list": "listing its marketplaces",
    "register": "registering tack's marketplace",
    "install": "installing {}",
    "reinstall": "reinstalling {}",
    "uninstall": "uninstalling {}",
    "unregister": "unregistering tack's marketplace",
}


class _Plugins:
    """The plugin pass of one sync (design.md §9 *Deploying*, *Plugin
    ownership*): tack's marketplace brought up to date, then the five steps in
    each harness that takes plugins, run through its agent's CLI (agents.py)
    and recorded in `record.plugins`.

    *Wanted* plugins are the plan's plugins with files, one per name
    (DEC-11): in the source, or in a clone `ok` once it has been brought to
    its commit. *Kept* ones are left exactly as they are, copy, catalog
    entry, installs and record (DEC-12): a held source's plugins, a collided
    name, a plugin from another repository whose clone isn't `ok`, and a
    plugin whose copy failed. A dry run runs only the `list` commands, brings
    no clone, and lists every other step as if it had succeeded."""

    def __init__(
        self, cfg: Config, record: Record, result: Result, held: set[str], *, dry_run: bool
    ) -> None:
        self.cfg, self.paths, self.record, self.result = cfg, cfg.paths, record, result
        self.dry_run, self.held = dry_run, held
        self.plan = plugins.plan(cfg)
        self.selected = [sel for state in self.plan.sources for sel in state.selected]
        # The harnesses a selected plugin targets, deployable or not, collided or not.
        self.targeted = {h for sel in self.selected for h in sel.harnesses}
        self.failed_uninstalls: set[str] = set()

    def run(self) -> None:
        self._plan_problems()
        self._clones()
        exists = os.path.lexists(self.paths.marketplace_dir)
        involved = [
            h
            for h in config.PLUGIN_HARNESSES
            if h in self.targeted or self.record.plugins.get(h) or exists
        ]
        if not involved:
            return  # no CLI, no marketplace, no record change (DEC-3)

        kept = plugins.kept(self.plan, self.record, self.held)
        wanted: dict[str, plugins.Selected] = {}
        for by_name in self.plan.plugins.values():
            for name, sel in by_name.items():
                if sel.directory is not None:
                    wanted.setdefault(name, sel)
        hashes: dict[str, str] = {}
        if self.selected or exists:
            hashes = self._marketplace(wanted, kept)
        wanted = {name: sel for name, sel in wanted.items() if name not in kept}

        clear = True  # tack's marketplace is registered in no harness whose CLI is on PATH
        for h in involved:
            for_harness = {n: s for n, s in sorted(self.plan.plugins[h].items()) if n in wanted}
            clear = self._harness(h, for_harness, kept, hashes) and clear
        self._copies(wanted, kept, clear=clear)

    def _plan_problems(self) -> None:
        for name, (harnesses, srcs) in self.plan.collisions.items():
            self.result.problems.append(
                Problem(
                    "collision", plugins.collision(name, harnesses, srcs), path=self.cfg.manifest
                )
            )
        for state in self.plan.sources:
            src, file = state.source.name, catalog.find(state.root)
            if state.catalog_state == "broken":
                self.result.problems.append(Problem("source", str(state.error), src, path=file))
            for sel in state.selected:
                if why := plugins.undeployable(sel.plugin):
                    message = f"plugin {sel.name!r} {why}"
                    self.result.problems.append(Problem("source", message, src, path=file))

    def _clones(self) -> None:
        """Bring the clone of each plugin `sync` would copy (a selected name no
        other source selects, from a source it doesn't keep) to its commit, in
        name order, then read the plan again: a plugin's files are its clone's
        only while the clone is `ok` (design.md *Plugins from other
        repositories*). A dry run lists the steps and brings nothing."""
        moved = False
        for name, sel in plugins.brought(self.plan, self.held).items():
            assert sel.clone is not None
            src, path = sel.source.name, sel.clone.path
            steps, error = plugins.bring(sel, dry_run=self.dry_run)
            if error is not None:
                message = f"plugin {name!r}: {error}"
                self.result.problems.append(Problem("source", message, src, path=path))
                continue  # left as it was, or, freshly cloned, gone again (DEC-22)
            for action, detail in steps:
                self.result.changes.append(Change(action, detail, source=src, path=path))
            moved = moved or bool(steps)
        if moved and not self.dry_run:
            self.plan = plugins.plan(self.cfg)

    def _marketplace(self, wanted: dict[str, plugins.Selected], kept: set[str]) -> dict[str, str]:
        """Bring tack's marketplace up to date; each wanted plugin's hash. A
        plugin whose copy fails is kept from here on (DEC-12)."""
        up = plugins.update(
            self.paths,
            [
                plugins.Wanted(n, s.directory, s.plugin.entry)
                for n, s in wanted.items()
                if s.directory
            ],
            keep=kept,
            dry_run=self.dry_run,
        )
        for c in up.changes:
            src = wanted[c.plugin].source.name if c.plugin else None
            self.result.changes.append(Change(c.action, c.detail, source=src, path=c.path))
        for f in up.failures:
            src = wanted[f.plugin].source.name
            message = f"plugin {f.plugin!r}: {f.message}"
            self.result.problems.append(Problem("source", message, src, path=f.path))
            kept.add(f.plugin)
        return up.hashes

    def _harness(
        self, h: str, wanted: dict[str, plugins.Selected], kept: set[str], hashes: dict[str, str]
    ) -> bool:
        """Make one harness match tack's marketplace; whether tack's marketplace
        is unregistered there now (or its CLI isn't on PATH)."""
        targeted = h in self.targeted
        recorded = self.record.plugins.setdefault(h, {})
        inv = agents.inventory(h, self.paths)
        if isinstance(inv, agents.Outcome):
            # Its steps stop, and its record entries stay.
            if inv.missing:
                if targeted:
                    message = f"{inv.error}, so {h} gets no plugins"
                    self.result.problems.append(Problem("agent", message, harness=h))
                return True
            self._failed(inv)
            return False
        market = inv.marketplace(plugins.NAME)
        if market is not None and not agents.is_tack(h, market, self.paths):
            if targeted or recorded:
                where = tilde(market.location) if market.location else "elsewhere"
                self.result.problems.append(
                    Problem(
                        "conflict",
                        f"a marketplace named {plugins.NAME!r} from {where} isn't tack's; "
                        f"tack deploys no plugin to {h} until it is removed or renamed",
                        harness=h,
                    )
                )
            return True
        registered = market is not None
        installed = set(agents.tack_plugins(h, inv))

        # 1. Register; 2. install; 3. reinstall in Codex.
        if not targeted or registered or self._run(agents.register(h, self.paths.marketplace_dir)):
            if h == "codex" and targeted and not registered and recorded:
                # The first list hid these installs while unregistered (DEC-14).
                if self.dry_run:
                    installed.update(recorded)
                else:
                    refreshed = agents.inventory(h, self.paths)
                    if isinstance(refreshed, agents.Outcome):
                        self._failed(refreshed)
                        return False
                    installed = set(agents.tack_plugins(h, refreshed))
            for name, sel in wanted.items():
                now = Install(sel.source.name, hashes[name])
                if name not in installed:
                    if self._run(agents.install(h, name), name, sel.source.name):
                        recorded[name] = now
                elif h == "claude-code":
                    # It loads from tack's copy in place: nothing to run. The
                    # hash is the copy's when tack first recorded it.
                    was = recorded.get(name)
                    recorded[name] = now if was is None else Install(now.source, was.hash)
                elif name not in recorded or recorded[name].hash != now.hash:
                    # Codex's copy is stale, or of an age the record doesn't know.
                    if self._run(agents.install(h, name), name, sel.source.name, "reinstall"):
                        recorded[name] = now
                else:
                    recorded[name] = now

        # 4. Uninstall the rest of tack's plugins there, but kept ones.
        for name in sorted((installed | set(recorded)) - set(wanted) - kept):
            was = recorded.get(name)
            if h == "claude-code" and name not in installed:
                del recorded[name]  # its list shows every install: this one is gone
                continue
            # Codex's list hides a plugin whose catalog entry is gone, so every
            # recorded one is uninstalled; `codex plugin remove` of one that
            # isn't installed succeeds.
            if self._run(agents.uninstall(h, name), name, was.source if was else None):
                recorded.pop(name, None)
                installed.discard(name)
            else:
                self.failed_uninstalls.add(name)

        # 5. Unregister. Claude Code's `marketplace remove` uninstalls the
        # marketplace's plugins, so not while a kept one is installed there (DEC-13).
        if targeted:
            return False
        if not registered:
            return True
        if h == "claude-code" and installed & kept:
            return False
        return self._run(agents.unregister(h))

    def _copies(self, wanted: dict[str, plugins.Selected], kept: set[str], *, clear: bool) -> None:
        """Delete the copies no plugin needs, or tack's marketplace directory
        once nothing is selected, registered or recorded."""
        recorded = {name for by_name in self.record.plugins.values() for name in by_name}
        market = self.paths.marketplace_dir
        if not self.selected and clear and not recorded:
            if os.path.lexists(market):
                self._delete(market, lambda: plugins.remove(self.paths))
            return
        for name, copy in plugins.copies(self.paths).items():
            if name in wanted or name in kept or name in recorded:
                continue
            if name in self.failed_uninstalls:
                continue
            self._delete(copy, lambda name=name: plugins.drop(self.paths, name))

    def _delete(self, path: Path, step: Callable[[], object]) -> None:
        if not self.dry_run:
            try:
                step()
            except OSError as e:
                message = f"can't delete {tilde(path)}: {e.strerror or e}"
                self.result.problems.append(Problem("error", message, path=path))
                return
        self.result.changes.append(Change("delete", tilde(path), path=path))

    def _run(
        self,
        command: agents.Command,
        plugin: str | None = None,
        source: str | None = None,
        action: Action | None = None,
    ) -> bool:
        """List an agent command as a change and, unless this is a dry run,
        run it; whether it succeeded."""
        action = action or _ACTIONS[command.kind]
        if not self.dry_run:
            out = agents.run(command, self.paths)
            if not out.ok:
                self._failed(out, plugin, source, action)
                return False
        self.result.changes.append(Change(action, str(command), source, command.harness))
        return True

    def _failed(
        self,
        out: agents.Outcome,
        plugin: str | None = None,
        source: str | None = None,
        action: str | None = None,
    ) -> None:
        """An agent problem: what failed, and the agent's message."""
        what = _FAILED[action or out.command.kind].format(plugin)
        message = f"{what} failed: {out.error}"
        self.result.problems.append(Problem("agent", message, source, out.command.harness))


def _prune(record: Record) -> None:
    """Forget links that are gone or were repointed by someone else."""
    for link, target in list(record.links.items()):
        p = Path(link)
        if not p.is_symlink() or not deploy.same_path(deploy.link_target(p), Path(target)):
            del record.links[link]

"""`tack status`: what is deployed where, and the state of each source. Read-only.

Plugins are read from the agents through their own CLIs: each harness a
selected plugin targets is listed once, with its two `list` commands, and
nothing else is run (design.md §9 *Plugin states*)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from tack import agents, catalog, config, deploy, plugins, sources
from tack.config import Config

SourceState = Literal[
    "ok",  # a path source that is there, or a git checkout at its pin
    "missing",  # a path source whose skills dir isn't there
    "not pinned",  # a git source the lockfile doesn't know yet
    "manifest changed",  # its git or ref changed since it was pinned
    "not checked out",
    "local changes",
    "off its pin",  # checked out at another commit
]
LinkStatus = Literal["linked", "missing", "stale", "conflict", "collision"]
_LINK: dict[deploy.State, LinkStatus] = {"ok": "linked", "absent": "missing", "stale": "stale"}
# A plugin's state in a harness (design.md §9 *Plugin states*), in DEC-15's order.
PluginState = Literal[
    "collision", "unavailable", "conflict", "missing", "disabled", "stale", "installed"
]


@dataclass
class SourceStatus:
    name: str
    kind: Literal["path", "git"]
    location: str  # the path, or the clone URL
    ref: str | None
    root: Path
    state: SourceState
    commit: str | None = None  # the pin
    locked: datetime | None = None
    skills: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)  # the names it selects
    uncommitted: list[str] = field(default_factory=list)
    unpushed: list[str] = field(default_factory=list)


@dataclass
class SkillStatus:
    name: str
    source: str
    harnesses: dict[str, LinkStatus]  # only the harnesses it targets
    path: Path | None = None  # the skill directory the links point to


@dataclass
class PluginStatus:
    name: str
    source: str
    harnesses: dict[str, PluginState]  # only the harnesses it targets
    version: str | None = None
    path: Path | None = None  # its copy in tack's marketplace


@dataclass
class Status:
    sources: list[SourceStatus]
    skills: list[SkillStatus]
    plugins: list[PluginStatus] = field(default_factory=list)


def status(cfg: Config) -> Status:
    lock = config.load_lock(cfg.paths)
    plan = deploy.plan(cfg)
    record = deploy.load_record(cfg.paths)
    plugin_plan = plugins.plan(cfg)
    selects = {s.source.name: [sel.name for sel in s.selected] for s in plugin_plan.sources}

    out_sources: list[SourceStatus] = []
    for ss in plan.sources:
        src = ss.source
        s = SourceStatus(
            name=src.name,
            kind="path" if src.path is not None else "git",
            location=str(src.path) if src.path is not None else str(src.git),
            ref=src.ref,
            root=ss.root,
            state="ok",
            skills=[sel.name for sel in ss.selected],
            plugins=selects.get(src.name, []),
        )
        if src.path is not None:
            if not ss.present:
                s.state = "missing"
            else:
                s.uncommitted, s.unpushed = sources.edits(src, cfg.paths)
        else:
            entry = lock.get(src.name)
            if entry is not None:
                s.commit, s.locked = entry.commit, entry.locked
            s.state = _git_state(ss.root, entry, entry is not None and entry.matches(src))
        out_sources.append(s)

    skills: list[SkillStatus] = []
    for ss in plan.sources:
        for sel in ss.selected:
            links: dict[str, LinkStatus] = {}
            for h in sel.harnesses:
                if name_collides(plan, sel.name, h):
                    links[h] = "collision"
                    continue
                st = deploy.state(cfg.harnesses[h].skills_dir / sel.name, sel, cfg, record)
                links[h] = _LINK.get(st, "conflict")
            skills.append(SkillStatus(sel.name, ss.source.name, links, sel.path))
    skills.sort(key=lambda k: (k.name, k.source))
    return Status(out_sources, skills, _plugins(cfg, plugin_plan, record))


def name_collides(plan: deploy.Plan, name: str, harness: str) -> bool:
    return name in plan.collisions and harness in plan.collisions[name][0]


# --- plugins -------------------------------------------------------------------------


def plugin_state(
    *,
    collision: bool,
    unavailable: bool,
    conflict: bool,
    installed: bool,
    enabled: bool,
    stale: bool,
) -> PluginState:
    """The first state that applies, in DEC-15's order: a manifest error, then
    what stops tack reading the harness, then whether the plugin is
    installed, and only then how fresh it is."""
    if collision:
        return "collision"
    if unavailable:
        return "unavailable"
    if conflict:
        return "conflict"
    if not installed:
        return "missing"
    if not enabled:
        return "disabled"
    if stale:
        return "stale"
    return "installed"


# What `agents.inventory` gave for each harness read: its plugins and
# marketplaces, or the outcome of the `list` command that failed.
Inventories = Mapping[str, agents.Inventory | agents.Outcome]


@dataclass(frozen=True)
class _Harness:
    """What one harness that takes plugins has, as `sync` reads it."""

    unavailable: bool = False  # its CLI isn't on PATH, or a `list` failed (DEC-16)
    conflict: bool = False  # a `tack` marketplace that isn't tack's
    tack: dict[str, bool] = field(default_factory=dict)  # tack's plugins: name -> enabled


def _harness(h: str, inv: agents.Inventory | agents.Outcome, paths: config.Paths) -> _Harness:
    if isinstance(inv, agents.Outcome):
        return _Harness(unavailable=True)
    market = inv.marketplace(plugins.NAME)
    if market is not None and not agents.is_tack(h, market, paths):
        return _Harness(conflict=True)
    return _Harness(tack=agents.tack_plugins(h, inv))


def _plugins(cfg: Config, plan: plugins.Plan, record: deploy.Record) -> list[PluginStatus]:
    """Only a harness a selected plugin targets is listed, so a manifest
    without plugins runs no agent (DEC-3)."""
    targeted = {h for state in plan.sources for sel in state.selected for h in sel.harnesses}
    inventories = {
        h: agents.inventory(h, cfg.paths) for h in config.PLUGIN_HARNESSES if h in targeted
    }
    return plugin_states(cfg, plan, record, inventories)


def plugin_states(
    cfg: Config, plan: plugins.Plan, record: deploy.Record, inventories: Inventories
) -> list[PluginStatus]:
    """Each selected plugin's state in each harness it targets (design.md §9
    *Plugin states*), sorted by name and then source. `inventories` holds
    each targeted harness's inventory, read once by the caller: `status` reads
    the targeted harnesses, `doctor` every one (DEC-18). Runs nothing."""
    seen = {h: _harness(h, inv, cfg.paths) for h, inv in inventories.items()}
    out: list[PluginStatus] = []
    for sel in (sel for state in plan.sources for sel in state.selected):
        digest = plugin_digest(sel.directory)
        copy = cfg.paths.marketplace_dir / "plugins" / sel.name
        # What `sync` would copy: the copy is missing, or isn't the plugin's files.
        copy_stale = digest is not None and plugins.copy_hash(copy) != digest
        harnesses: dict[str, PluginState] = {}
        for h in sel.harnesses:
            has = seen[h].tack
            # In Codex, what `sync` would reinstall: an install whose files
            # the record doesn't know, or knows to be older (DEC-6).
            was = record.plugins.get(h, {}).get(sel.name)
            reinstall = h == "codex" and (was is None or was.hash != digest)
            harnesses[h] = plugin_state(
                collision=sel.name in plan.collisions,
                unavailable=seen[h].unavailable,
                conflict=seen[h].conflict,
                installed=sel.name in has,
                enabled=has.get(sel.name, False),
                stale=digest is not None and (copy_stale or reinstall),
            )
        read = catalog.files(sel.directory) if sel.directory else lambda _: None
        version = catalog.version(sel.plugin.entry, read)
        path = copy if copy.is_dir() else None
        out.append(PluginStatus(sel.name, sel.source.name, harnesses, version, path))
    out.sort(key=lambda p: (p.name, p.source))
    return out


def plugin_digest(directory: Path | None) -> str | None:
    """The hash of a plugin's files; None when it has no directory to compare,
    or one whose files can't be read (its copy would fail), so it is never
    `stale`."""
    if directory is None:
        return None
    digest = plugins.files_hash(directory)
    return digest if isinstance(digest, str) else None


def _git_state(root: Path, entry: config.LockEntry | None, matches: bool) -> SourceState:
    if entry is None:
        return "not pinned"
    if not matches:
        return "manifest changed"
    if not (root / ".git").exists():
        return "not checked out"
    if sources.local_changes(root):
        return "local changes"
    if sources.head(root) != entry.commit:
        return "off its pin"
    return "ok"

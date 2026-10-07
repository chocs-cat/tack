"""Global plugin checks (design.md *`doctor` checks*, the *(P0001)* paragraph):
what each agent has, read through its CLI, against the manifest's plugins.

Each built-in harness's inventory is read once per run, whether or not the
manifest selects plugins (DEC-18), and every check here shares it. A selected
plugin's state is `status.plugin_states`, the function `status` uses; the
leftovers are `sync`'s step 4 (design.md *Deploying*) seen from outside. Like
`status`, these read each source as it is now (DEC-17).
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence

from tack import agents, catalog, config, deploy, plugins, status
from tack.config import Config, Harness
from tack.doctor.findings import Finding
from tack.plugins import Plan, Selected
from tack.text import tilde

# What a plugin's state in a harness says, and what fixes it (DEC-5).
_STATES = {
    "missing": "isn't installed in {h}; `tack sync` installs it",
    "disabled": "is turned off in {h}; turn it on there, or limit its `harnesses` in the manifest",
    "stale": "is out of date in {h}: the copy it loads predates its files; `tack sync` "
    "refreshes it",
}


def check(cfg: Config) -> Iterator[Finding]:
    plan = plugins.plan(cfg)
    record = deploy.load_record(cfg.paths)
    inventories = {h: agents.inventory(h, cfg.paths) for h in config.PLUGIN_HARNESSES}
    yield from _collisions(cfg, plan)
    for state in plan.sources:
        yield from _source(state)
    cells = {
        (p.name, p.source): p.harnesses
        for p in status.plugin_states(cfg, plan, record, inventories)
    }
    selected = sorted(
        (sel for state in plan.sources for sel in state.selected),
        key=lambda sel: (sel.name, sel.source.name),
    )
    # The plugins whose state gets a finding of its own: one tack can't
    # deploy is its source's, a collided name `name-collision`'s.
    stated = [s for s in selected if s.directory is not None and s.name not in plan.collisions]
    kept = _kept(plan, record)
    for h, inv in inventories.items():
        here = [(sel, cells[sel.name, sel.source.name][h]) for sel in stated if h in sel.harnesses]
        if isinstance(inv, agents.Outcome):
            if stopped := [sel for sel, st in here if st == "unavailable"]:
                yield _unavailable(h, inv, stopped)
            continue
        market = inv.marketplace(plugins.NAME)
        foreign = market is not None and not agents.is_tack(h, market, cfg.paths)
        if foreign:
            assert market is not None
            if stopped := [sel for sel, st in here if st == "conflict"]:
                where = tilde(market.location) if market.location else "elsewhere"
                yield Finding(
                    "not-synced",
                    "warn",
                    f"a marketplace named {plugins.NAME!r} from {where} isn't tack's, so tack "
                    f"can't deploy {_names(stopped)} to {h}; remove or rename that marketplace",
                    harness=h,
                )
        else:
            for sel, st in here:
                if st in _STATES:
                    yield Finding(
                        "not-synced",
                        "warn",
                        f"plugin {sel.name!r} from {sel.source.name!r} " + _STATES[st].format(h=h),
                        path=sel.directory,
                        harness=h,
                    )
            if _involved(cfg, h, selected, record):
                yield from _leftovers(h, inv, plan, record, kept)
        yield from _others(cfg.harnesses[h], inv, plan, foreign=foreign)


def _collisions(cfg: Config, plan: Plan) -> Iterator[Finding]:
    for name, (harnesses, srcs) in sorted(plan.collisions.items()):
        yield Finding(
            "name-collision",
            "error",
            f"plugin {name!r} is selected from sources {', '.join(srcs)} for "
            f"{', '.join(harnesses)}; tack deploys none of them -- deselect all but one",
            path=cfg.manifest,
        )


def _source(state: plugins.SourceState) -> Iterator[Finding]:
    """A source's catalog: the names it lacks, the plugins tack can't deploy,
    or that it is broken; at the catalog file, or the root when there is none."""
    src = state.source.name
    where = catalog.find(state.root) or state.root
    if state.catalog_state == "broken":
        yield Finding(
            "not-synced",
            "warn",
            f"source {src!r} has a broken plugin catalog, so tack leaves its plugins as they "
            f"are: {state.error}",
            path=where,
        )
    if state.catalog_state == "no-catalog":
        lacks = "which has no plugin catalog"
    else:
        lacks = "whose catalog has no such plugin"
    for name in state.missing:
        message = f"the manifest selects plugin {name!r} from {src!r}, {lacks}"
        yield Finding("not-synced", "warn", message, path=where)
    for sel in state.selected:
        it = f"plugin {sel.name!r} from {src!r}"
        if isinstance(sel.plugin.where, catalog.Undeployable):
            message = f"{it} can't be deployed: {sel.plugin.where.reason}"
        elif isinstance(sel.plugin.where, catalog.InRepository):
            message = (
                f"{it} is in another repository ({sel.plugin.where.url}), "
                "and tack doesn't deploy those yet"
            )
        else:
            continue
        yield Finding("not-synced", "warn", message, path=where)


def _unavailable(h: str, inv: agents.Outcome, stopped: Sequence[Selected]) -> Finding:
    """A harness whose CLI isn't on PATH, or whose `list` fails (DEC-16)."""
    if inv.missing:
        message = f"{inv.error}, so tack can't deploy {_names(stopped)} to {h}; install it"
    else:
        message = (
            f"`{inv.command}` failed: {inv.error}; tack can't deploy {_names(stopped)} to {h} "
            "until it succeeds"
        )
    return Finding("not-synced", "warn", message, harness=h)


def _kept(plan: Plan, record: deploy.Record) -> set[str]:
    """The plugins `sync` keeps as they are wherever they are installed
    (DEC-12): a collided name, a plugin from another repository (D8), one whose
    copy would fail, and one whose recorded source's catalog can't be read."""
    unread = {s.source.name for s in plan.sources if s.catalog_state in ("no-root", "broken")}
    kept = set(plan.collisions)
    kept.update(
        name
        for by_name in record.plugins.values()
        for name, install in by_name.items()
        if install.source in unread
    )
    for by_name in plan.plugins.values():
        for name, sel in by_name.items():
            if status.plugin_digest(sel.directory) is None:
                kept.add(name)
    return kept


def _involved(cfg: Config, h: str, selected: Sequence[Selected], record: deploy.Record) -> bool:
    """Whether `sync` runs this harness's steps at all: a selected plugin
    targets it, the record lists one there, or tack's marketplace exists."""
    return (
        any(h in sel.harnesses for sel in selected)
        or bool(record.plugins.get(h))
        or os.path.lexists(cfg.paths.marketplace_dir)
    )


def _leftovers(
    h: str, inv: agents.Inventory, plan: Plan, record: deploy.Record, kept: set[str]
) -> Iterator[Finding]:
    """tack's plugins there that step 4 would uninstall. Claude Code lists
    every install; Codex hides one whose catalog entry is gone, so there the
    record's count too."""
    candidates = set(agents.tack_plugins(h, inv))
    if h == "codex":
        candidates.update(record.plugins.get(h, {}))
    for name in sorted(candidates - set(plan.plugins[h]) - kept):
        yield Finding(
            "not-synced",
            "warn",
            f"{name}@{plugins.NAME} is installed in {h}, but the manifest doesn't deploy "
            f"{name!r} there; `tack sync` uninstalls it",
            harness=h,
        )


def _others(
    harness: Harness, inv: agents.Inventory, plan: Plan, *, foreign: bool
) -> Iterator[Finding]:
    """The plugins a harness has from marketplaces that aren't tack's (a
    foreign `tack` among them), at user scope in Claude Code, as in `sync`:
    `duplicate-plugin` for one the manifest deploys there (none with a foreign
    `tack`, where nothing is tack's), whatever `ignore_marketplaces` says, by
    name; then `unmanaged-plugin` for each other one whose marketplace isn't
    ignored, by id."""
    h = harness.name
    theirs = sorted(
        (
            p
            for p in inv.plugins
            if (foreign or p.marketplace != plugins.NAME)
            and (h != "claude-code" or p.scope == "user")
        ),
        key=lambda p: p.id,
    )
    twins: dict[str, list[agents.Installed]] = {}
    if not foreign:
        for p in theirs:
            if p.name in plan.plugins[h]:
                twins.setdefault(p.name, []).append(p)
    for name, others in sorted(twins.items()):
        ids = " and ".join(p.id for p in others)
        yield Finding(
            "duplicate-plugin",
            "warn",
            f"the manifest deploys {name}@{plugins.NAME} to {h}, which also has {ids}: it loads "
            f"both; uninstall {'it' if len(others) == 1 else 'them'}, or stop deploying "
            f"{name!r} there",
            harness=h,
        )
    for p in theirs:
        if p.name in twins or p.marketplace in harness.ignore_marketplaces:
            continue
        yield Finding(
            "unmanaged-plugin",
            "info",
            f"{p.id} is installed in {h} outside tack; select it from its source in the "
            f"manifest, or add {p.marketplace!r} to [harness.{h}] ignore_marketplaces",
            harness=h,
        )


def _names(sels: Sequence[Selected]) -> str:
    names = [repr(sel.name) for sel in sels]
    if len(names) == 1:
        return f"plugin {names[0]}"
    return f"plugins {', '.join(names[:-1])} and {names[-1]}"

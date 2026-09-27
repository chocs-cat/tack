"""Which links the manifest asks for, and which links are tack's.

A deployment is a symlink `<harness skills_dir>/<skill> -> <skill directory>`.
The plan is what every harness should hold; `sync` makes it so and `doctor`
compares against it.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tack import sources
from tack.config import Config, Source


@dataclass(frozen=True)
class Selected:
    """One skill a source deploys, and to which harnesses."""

    source: Source
    name: str
    path: Path  # the skill directory the links point to
    harnesses: tuple[str, ...]


@dataclass
class SourceState:
    source: Source
    root: Path
    present: bool  # False: the skills dir isn't there (missing path, no checkout yet)
    selected: list[Selected]
    missing: list[str]  # listed in the manifest but not in the (present) source


@dataclass
class Plan:
    sources: list[SourceState]
    # harness -> skill -> the one skill it deploys; collided names left out
    links: dict[str, dict[str, Selected]]
    # skill -> (harnesses, sources) where two or more sources select it
    collisions: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)


def plan(cfg: Config) -> Plan:
    states: list[SourceState] = []
    for src in cfg.sources:
        offered = sources.offered(src, cfg.paths)
        skills_dir = sources.skills_dir(src, cfg.paths)
        default = src.harnesses or tuple(cfg.harnesses)
        selected: list[Selected] = []
        missing: list[str] = []
        if src.skills is None:
            for name, path in (offered or {}).items():
                selected.append(Selected(src, name, path, default))
        else:
            for spec in src.skills:
                if offered is not None and spec.name not in offered:
                    missing.append(spec.name)
                    continue
                path = offered[spec.name] if offered is not None else skills_dir / spec.name
                selected.append(Selected(src, spec.name, path, spec.harnesses or default))
        states.append(
            SourceState(src, sources.root(src, cfg.paths), offered is not None, selected, missing)
        )

    by_harness: dict[str, dict[str, list[Selected]]] = defaultdict(lambda: defaultdict(list))
    for state in states:
        for sel in state.selected:
            for h in sel.harnesses:
                by_harness[h][sel.name].append(sel)

    links: dict[str, dict[str, Selected]] = {h: {} for h in cfg.harnesses}
    collisions: dict[str, tuple[list[str], list[str]]] = {}
    for h, skills in by_harness.items():
        for name, sels in skills.items():
            if len(sels) == 1:
                links[h][name] = sels[0]
                continue
            hs, srcs = collisions.setdefault(name, ([], []))
            hs.append(h)
            srcs.extend(s.source.name for s in sels if s.source.name not in srcs)
    return Plan(states, links, collisions)


def link_target(link: Path) -> Path:
    """Where a symlink points, made absolute but not resolved further."""
    return Path(os.path.normpath(link.parent / link.readlink()))


def same_path(a: Path, b: Path) -> bool:
    return os.path.normpath(a) == os.path.normpath(b) or os.path.realpath(a) == os.path.realpath(b)


def within(path: Path, root: Path) -> bool:
    for p, r in (
        (os.path.normpath(path), os.path.normpath(root)),
        (os.path.realpath(path), os.path.realpath(root)),
    ):
        if p == r or p.startswith(r.rstrip(os.sep) + os.sep):
            return True
    return False


def is_owned(entry: Path, cfg: Config) -> bool:
    """Whether an entry in a harness skills dir is tack's: a symlink into tack's
    data directory or into a configured source."""
    if not entry.is_symlink():
        return False
    target = link_target(entry)
    roots = [cfg.paths.data_dir, *(sources.root(s, cfg.paths) for s in cfg.sources)]
    return any(within(target, r) for r in roots)

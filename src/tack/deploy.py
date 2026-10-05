"""Which links the manifest asks for, and which links are tack's.

A deployment is a symlink `<harness skills_dir>/<skill> -> <skill directory>`.
The plan is what every harness should hold; `sync` makes it so and `doctor`
compares against it.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tack import sources
from tack.config import Config, ConfigError, Paths, Source, write_atomic

RECORD = "state.json"
RECORD_VERSION = 1


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


# --- ownership -----------------------------------------------------------------


@dataclass(frozen=True)
class Install:
    """A plugin tack installed in a harness: the source it came from, and the
    hash of the files it was installed from (design.md *Plugin ownership*)."""

    source: str
    hash: str


@dataclass
class Record:
    """The links tack made (link path -> target), and the plugins it installed
    (harness -> plugin name -> Install; DEC-6)."""

    links: dict[str, str] = field(default_factory=dict)
    plugins: dict[str, dict[str, Install]] = field(default_factory=dict)


def load_record(paths: Paths) -> Record:
    file = paths.state_dir / RECORD
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Record()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ConfigError(f"{file}: {e}") from e
    links = data.get("links") if isinstance(data, dict) else None
    if not isinstance(links, dict) or data.get("version") != RECORD_VERSION:
        raise ConfigError(f"{file}: not a version {RECORD_VERSION} ownership record")
    try:
        installed = _plugins(data.get("plugins", {}))
    except TypeError as e:
        raise ConfigError(f"{file}: not a version {RECORD_VERSION} ownership record") from e
    return Record({str(k): str(v) for k, v in links.items()}, installed)


def _plugins(value: object) -> dict[str, dict[str, Install]]:
    """The record's `plugins`: harness -> name -> {"source": …, "hash": …}.
    Raises TypeError for anything else."""
    if not isinstance(value, dict):
        raise TypeError(value)
    out: dict[str, dict[str, Install]] = {}
    for harness, installed in value.items():
        if not isinstance(installed, dict):
            raise TypeError(installed)
        out[harness] = {}
        for name, entry in installed.items():
            source = entry.get("source") if isinstance(entry, dict) else None
            digest = entry.get("hash") if isinstance(entry, dict) else None
            if not isinstance(source, str) or not isinstance(digest, str):
                raise TypeError(entry)
            out[harness][name] = Install(source, digest)
    return out


def save_record(paths: Paths, record: Record) -> None:
    data: dict[str, object] = {
        "version": RECORD_VERSION,
        "links": dict(sorted(record.links.items())),
    }
    # Left out when it lists no plugin, so a record without plugins is the
    # one an older tack writes (DEC-6).
    installed = {
        h: {n: {"source": i.source, "hash": i.hash} for n, i in sorted(by_name.items())}
        for h, by_name in sorted(record.plugins.items())
        if by_name
    }
    if installed:
        data["plugins"] = installed
    write_atomic(paths.state_dir / RECORD, json.dumps(data, indent=2) + "\n")


def is_owned(entry: Path, cfg: Config, record: Record) -> bool:
    """Whether an entry in a harness skills dir is tack's: a symlink the record
    lists (still pointing where it did), or one into tack's data directory or a
    configured source."""
    if not entry.is_symlink():
        return False
    target = link_target(entry)
    recorded = record.links.get(str(entry))
    if recorded is not None and same_path(target, Path(recorded)):
        return True
    roots = [cfg.paths.data_dir, *(sources.root(s, cfg.paths) for s in cfg.sources)]
    return any(within(target, r) for r in roots)


# What is at a harness skills dir entry, against what the manifest wants there:
#   absent    nothing
#   ok        a link to the skill the manifest deploys
#   stale     a tack link pointing elsewhere          (sync relinks it)
#   conflict  anything else in the way                (sync --adopt takes it over)
#   owned     a tack link the manifest doesn't want   (sync removes it)
#   foreign   something else the manifest doesn't want (left alone)
State = Literal["absent", "ok", "stale", "conflict", "owned", "foreign"]


def state(entry: Path, sel: Selected | None, cfg: Config, record: Record) -> State:
    if not entry.is_symlink() and not entry.exists():
        return "absent"
    owned = is_owned(entry, cfg, record)
    if sel is None:
        return "owned" if owned else "foreign"
    if entry.is_symlink() and same_path(link_target(entry), sel.path):
        return "ok"
    return "stale" if owned else "conflict"


def make_link(entry: Path, target: Path) -> None:
    """Point `entry` at `target`, atomically replacing a symlink already there."""
    entry.parent.mkdir(parents=True, exist_ok=True)
    tmp = entry.with_name(f".{entry.name}.tack-tmp")  # a dot-entry: ignored meanwhile
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(target)
    tmp.replace(entry)

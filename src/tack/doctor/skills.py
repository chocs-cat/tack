"""Global skill checks: what is in each harness skills directory against the
manifest's plan, and the health of the sources the skills come from."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from tack import deploy, sources
from tack.config import Config, Harness
from tack.deploy import Plan, Record, Selected
from tack.doctor.findings import Finding
from tack.text import tilde


def check(cfg: Config) -> Iterator[Finding]:
    plan = deploy.plan(cfg)
    yield from _deployments(cfg, plan, deploy.load_record(cfg.paths))
    yield from _sources(cfg, plan)
    for name, (harnesses, srcs) in plan.collisions.items():
        yield Finding(
            "name-collision",
            "error",
            f"skill {name!r} is selected from sources {', '.join(srcs)} for "
            f"{', '.join(harnesses)}; tack deploys none of them -- deselect all but one",
            path=cfg.manifest,
        )
    for state in plan.sources:
        for sel in state.selected:
            if sel.path.is_dir() and (problem := skill_problem(sel.path)):
                yield Finding("bad-skill", "warn", problem, path=sel.path)
        if state.present and state.source.path is not None:
            uncommitted, unpushed = sources.edits(state.source, cfg.paths)
            parts = []
            if uncommitted:
                parts.append(f"uncommitted edits to {', '.join(uncommitted)}")
            if unpushed:
                parts.append(f"unpushed commits touching {', '.join(unpushed)}")
            if parts:
                yield Finding(
                    "dirty-source",
                    "info",
                    f"source {state.source.name!r} has {'; '.join(parts)}",
                    path=state.root,
                )


def _deployments(cfg: Config, plan: Plan, record: Record) -> Iterator[Finding]:
    for h in cfg.harnesses.values():
        want = plan.links[h.name]
        try:
            entries = sorted(os.scandir(h.skills_dir), key=lambda e: e.name)
        except OSError:
            entries = []
        names = [e.name for e in entries if not h.ignores(e.name)]
        for name in names:
            if found := _entry(cfg, h, h.skills_dir / name, want.get(name), record):
                yield found
        for name in sorted(set(want) - set(names)):
            sel = want[name]
            yield Finding(
                "not-synced",
                "warn",
                f"missing; the manifest deploys {name!r} from {sel.source.name} "
                f"({tilde(sel.path)})",
                path=h.skills_dir / name,
                harness=h.name,
            )


def _entry(
    cfg: Config, h: Harness, entry: Path, sel: Selected | None, record: Record
) -> Finding | None:
    """The finding, if any, for one entry in a harness skills dir; `sel` is what
    the manifest deploys under that name."""
    if entry.is_symlink() and not entry.exists():
        target = tilde(deploy.link_target(entry))
        return Finding("dangling-link", "error", f"links to {target}, which is gone", entry, h.name)
    st = deploy.state(entry, sel, cfg, record)
    if st == "ok":
        return None
    here = f"links to {tilde(deploy.link_target(entry))}" if entry.is_symlink() else ""
    if not here:
        here = f"a real {'directory' if entry.is_dir() else 'file'}"
    if st == "foreign":
        fid, msg = "unmanaged-skill", f"{here}, outside tack"
    elif st == "owned":
        fid = "not-synced"
        msg = (
            f"{here}, a tack link the manifest no longer deploys to {h.name}; "
            "`tack sync` removes it"
        )
    else:
        assert sel is not None
        fix = "`tack sync` fixes it" if st == "stale" else "`tack sync --adopt` replaces it"
        fid = "not-synced"
        msg = f"{here}; the manifest deploys it from {sel.source.name} ({tilde(sel.path)}); {fix}"
    return Finding(fid, "warn", msg, path=entry, harness=h.name)


def _sources(cfg: Config, plan: Plan) -> Iterator[Finding]:
    for state in plan.sources:
        src = state.source
        if not state.present:
            skills_dir = sources.skills_dir(src, cfg.paths)
            if src.git is not None and not state.root.exists():
                why = "is not checked out yet; `tack sync` fetches it"
            elif not state.root.exists():
                why = f"has no directory at {tilde(state.root)}"
            else:
                why = f"has no skills directory at {tilde(skills_dir)}"
            yield Finding("not-synced", "warn", f"source {src.name!r} {why}", path=state.root)
        for name in state.missing:
            yield Finding(
                "not-synced",
                "warn",
                f"the manifest selects {name!r} from {src.name!r}, which has no such skill",
                path=sources.skills_dir(src, cfg.paths) / name,
            )


# --- SKILL.md -------------------------------------------------------------------

_KEY = re.compile(r"([A-Za-z0-9_-]+)\s*:(.*)$")
_BLOCK = re.compile(r"[|>][+-]?\d*")


def skill_problem(skill: Path) -> str | None:
    """What is wrong with a skill directory's SKILL.md, if anything."""
    md = skill / "SKILL.md"
    try:
        text = md.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "no SKILL.md"
    except (OSError, UnicodeDecodeError) as e:
        return f"SKILL.md can't be read: {e}"
    meta = frontmatter(text)
    if meta is None:
        return "SKILL.md has no frontmatter"
    if not meta.get("description"):
        return "SKILL.md frontmatter has no description"
    name = meta.get("name")
    if name and name != skill.name:
        return f"SKILL.md names the skill {name!r}, but its directory is {skill.name!r}"
    return None


def frontmatter(text: str) -> dict[str, str] | None:
    """The top-level keys of a `---`-fenced YAML header, as strings.

    Only as much YAML as SKILL.md headers use: `key: value`, quoted values, and
    block scalars (`key: >`) whose indented lines follow.
    """
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    meta: dict[str, str] = {}
    key = None
    for line in lines[1:end]:
        m = _KEY.match(line)
        if m and not line[:1].isspace():
            key, value = m.group(1), m.group(2).strip()
            if _BLOCK.fullmatch(value):
                value = ""
            elif len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            meta[key] = value
        elif key and line[:1].isspace() and line.strip():
            meta[key] = f"{meta[key]} {line.strip()}".strip()
    return meta

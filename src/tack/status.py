"""`tack status`: what is deployed where, and the state of each source. Read-only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from tack import config, deploy, sources
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
    uncommitted: list[str] = field(default_factory=list)
    unpushed: list[str] = field(default_factory=list)


@dataclass
class SkillStatus:
    name: str
    source: str
    harnesses: dict[str, LinkStatus]  # only the harnesses it targets
    path: Path | None = None  # the skill directory the links point to


@dataclass
class Status:
    sources: list[SourceStatus]
    skills: list[SkillStatus]


def status(cfg: Config) -> Status:
    lock = config.load_lock(cfg.paths)
    plan = deploy.plan(cfg)
    record = deploy.load_record(cfg.paths)

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
    return Status(out_sources, skills)


def name_collides(plan: deploy.Plan, name: str, harness: str) -> bool:
    return name in plan.collisions and harness in plan.collisions[name][0]


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

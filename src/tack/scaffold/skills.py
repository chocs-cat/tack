"""The `skills-dir` fix: `.agents/skills` holds a project's skills, and
`.claude/skills` is a relative symlink to it.

Entries of `.claude/skills` and `.codex/skills` that `.agents/skills` lacks
move there; one it already has, as an identical copy or a link, is removed.
Nothing changes if an entry differs from its namesake, or a directory is a
link to somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

from tack.config import Config
from tack.doctor.project_skills import CODEX_UNREAD
from tack.scaffold.writer import Refusal, Writer
from tack.text import tilde


def fix(cfg: Config, w: Writer, source: str | None) -> None:
    claude = cfg.harnesses["claude-code"].project_skills_dir
    agents = cfg.harnesses["codex"].project_skills_dir
    agents_dir = w.project / agents
    target = os.path.relpath(agents_dir, (w.project / claude).parent)

    if agents_dir.is_symlink():
        raise Refusal(f"{agents} is a link to {tilde(agents_dir.readlink())}; fix it by hand")
    linked = _same_dir(w.project / claude, agents_dir)
    olds: list[str] = []  # the directories to empty into .agents/skills
    for rel in (claude, CODEX_UNREAD):
        d = w.project / rel
        if d.is_symlink():
            if not _same_dir(d, agents_dir):
                raise Refusal(f"{rel} is a link to {tilde(d.readlink())}; fix it by hand")
        elif d.is_dir():
            olds.append(rel)

    # What each name in .agents/skills will hold: the entry already there, or
    # the one moving in.
    there: dict[str, str] = {}
    if agents_dir.is_dir():
        there = {e.name: f"{agents}/{e.name}" for e in os.scandir(agents_dir)}
    moves: list[tuple[str, str]] = []
    removals: list[str] = []
    differ: list[str] = []
    for old in olds:
        for e in sorted(os.scandir(w.project / old), key=lambda e: e.name):
            rel = f"{old}/{e.name}"
            if w.ignored(rel):
                continue  # goes with its directory
            if e.name not in there:
                there[e.name] = rel
                moves.append((rel, f"{agents}/{e.name}"))
            elif _same(w, rel, there[e.name]):
                removals.append(rel)
            else:
                differ.append(f"{rel} (and {there[e.name]})")
    if differ:
        raise Refusal(
            f"these differ from their namesakes, so tack can't tell which to keep: "
            f"{', '.join(differ)}; reconcile them by hand"
        )

    for src, dst in moves:
        entry = w.project / src
        if entry.is_symlink():
            # Keep a link pointing where it did from its new directory.
            points = entry.readlink()
            dest = os.path.normpath(entry.parent / points)
            new = os.path.relpath(dest, (w.project / dst).parent)
            w.remove(src)
            w.link(dst, dest if points.is_absolute() else new)
        else:
            w.move(src, dst)
    for rel in removals:
        w.remove(rel)
    for old in olds:
        w.remove(old)
    if not linked and there:
        w.link(claude, target)


def _same_dir(a: Path, b: Path) -> bool:
    return a.is_dir() and b.is_dir() and a.resolve() == b.resolve()


def _same(w: Writer, a: str, b: str) -> bool:
    """Whether two entries hold the same thing: one links to the other, or
    their files (those git doesn't ignore) are identical."""
    pa, pb = w.project / a, w.project / b
    if pa.resolve() == pb.resolve():
        return True
    if pa.is_dir() != pb.is_dir():
        return False
    if not pa.is_dir():
        return _content(pa) == _content(pb)
    fa, fb = w.files(a), w.files(b)
    return fa == fb and all(_content(pa / f) == _content(pb / f) for f in fa or [])


def _content(p: Path) -> bytes | None:
    if p.is_symlink() and not p.exists():
        return b"link:" + str(p.readlink()).encode()
    try:
        return p.read_bytes()
    except OSError:
        return None

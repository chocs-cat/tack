"""Project skill-directory checks: every harness sees the project's skills, from
one copy.

The durable layout keeps skills in `.agents/skills` (which Codex reads) and
makes `.claude/skills` a symlink to it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from tack.config import Config
from tack.doctor.findings import Finding

CODEX_UNREAD = ".codex/skills"  # a plausible guess Codex doesn't read


def _skills(d: Path) -> dict[str, os.DirEntry[str]]:
    try:
        entries = list(os.scandir(d))
    except OSError:
        return {}
    return {e.name: e for e in entries if not e.name.startswith(".") and e.is_dir()}


def _same_dir(a: Path, b: Path) -> bool:
    return a.is_dir() and b.is_dir() and a.resolve() == b.resolve()


def check(cfg: Config, project: Path) -> Iterator[Finding]:
    claude_dir = project / cfg.harnesses["claude-code"].project_skills_dir
    agents_dir = project / cfg.harnesses["codex"].project_skills_dir
    codex_dir = project / CODEX_UNREAD
    claude_rel = cfg.harnesses["claude-code"].project_skills_dir
    agents_rel = cfg.harnesses["codex"].project_skills_dir

    def found(fid: str, message: str, path: Path, *, error: bool) -> Finding:
        severity = "error" if error else "warn"
        return Finding(fid, severity, message, path=path, project=project, fix="skills-dir")

    codex_skills = _skills(codex_dir)
    if codex_skills and not _same_dir(codex_dir, agents_dir):
        yield found(
            "codex-skills-dir",
            f"Codex doesn't read {CODEX_UNREAD}; skills there: {', '.join(sorted(codex_skills))}",
            codex_dir,
            error=True,
        )

    if _same_dir(claude_dir, agents_dir):
        return
    claude_skills, agents_skills = _skills(claude_dir), _skills(agents_dir)
    if only := sorted(set(claude_skills) - set(agents_skills)):
        yield found(
            "claude-only-skills",
            f"Codex can't see skills in {claude_rel} that aren't in {agents_rel}: "
            + ", ".join(only),
            claude_dir,
            error=True,
        )
    if only := sorted(set(agents_skills) - set(claude_skills)):
        yield found(
            "codex-only-skills",
            f"Claude Code can't see skills in {agents_rel} that aren't in {claude_rel}: "
            + ", ".join(only),
            agents_dir,
            error=True,
        )
    copies = sorted(
        n for n, e in claude_skills.items() if n in agents_skills and not e.is_symlink()
    )
    if copies and not claude_dir.is_symlink() and not agents_dir.is_symlink():
        yield found(
            "duplicate-skill-copies",
            f"{claude_rel} and {agents_rel} are separate directories with copies of "
            f"{', '.join(copies)}; make {claude_rel} a symlink to {agents_rel}",
            claude_dir,
            error=False,
        )

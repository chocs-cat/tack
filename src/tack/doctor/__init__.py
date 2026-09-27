"""`tack doctor`: a read-only audit of the harnesses and the projects.

Each check group is a module yielding Findings; `run` collects them.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tack.config import Config
from tack.doctor import hooks, instructions, project_skills, skills
from tack.doctor.findings import SEVERITIES, Finding, Severity
from tack.doctor.projects import discover, is_clone

__all__ = ["Finding", "Report", "check_project", "run"]


@dataclass
class Report:
    manifest: Path | None
    projects: list[Path]
    findings: list[Finding]
    clones: list[Path] = field(default_factory=list)  # found but skipped

    def count(self, severity: Severity) -> int:
        return sum(f.severity == severity for f in self.findings)

    @property
    def counts(self) -> dict[str, int]:
        return {s: self.count(s) for s in SEVERITIES}

    @property
    def failed(self) -> bool:
        """Errors and warnings fail the run; info alone doesn't."""
        return any(f.severity != "info" for f in self.findings)


def run(
    cfg: Config,
    paths: Sequence[Path] = (),
    *,
    global_checks: bool = True,
    project_checks: bool = True,
) -> Report:
    """Audit. `paths` replaces the configured project roots when given; a path
    naming a repository is audited even if it is a clone."""
    findings: list[Finding] = []
    if global_checks:
        findings += skills.check(cfg)
        findings += instructions.check_global(cfg)
        findings += hooks.check_global(cfg)
    projects: list[Path] = []
    clones: list[Path] = []
    if project_checks:
        named = {os.path.normpath(p) for p in paths}
        for repo in discover(paths or cfg.roots, cfg.exclude):
            if str(repo) not in named and is_clone(repo, cfg.owners):
                clones.append(repo)
            else:
                projects.append(repo)
        for project in projects:
            findings += check_project(cfg, project)
    return Report(cfg.manifest, projects, findings, clones)


def check_project(cfg: Config, project: Path) -> list[Finding]:
    """The per-project findings for one project."""
    return [
        *instructions.check_project(cfg, project),
        *project_skills.check(cfg, project),
        *hooks.check_project(cfg, project),
    ]

"""`tack scaffold`: apply one `doctor` fix to one project.

A fix writes, moves and removes files so that the project's findings with
that fix go away, and never commits. Each fix plans before it changes
anything: one it can't apply safely raises a Refusal, and the project is left
as it was. A dry run records the changes, with a diff for each file written,
and makes none.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tack import doctor
from tack.config import Config, UsageError
from tack.scaffold import hooks, instructions, skills
from tack.scaffold.writer import Failed, Refusal, Writer
from tack.sync import Problem, Result
from tack.text import tilde

FIXES: dict[str, Callable[[Config, Writer, str | None], None]] = {
    "agents-md": instructions.fix,
    "skills-dir": skills.fix,
    "hooks": hooks.fix,
}


def scaffold(
    cfg: Config,
    fix: str,
    project: Path,
    *,
    source: str | None = None,
    dry_run: bool = False,
) -> Result:
    """Apply `fix` to `project`; `source` is the harness whose hooks win a mismatch."""
    if fix not in FIXES:
        raise UsageError(f"no fix named {fix!r}; the fixes are {', '.join(FIXES)}")
    if source is not None and fix != "hooks":
        raise UsageError("--from applies to the hooks fix")
    if source is not None and source not in cfg.harnesses:
        raise UsageError(f"no harness named {source!r}")
    if not project.is_dir():
        raise UsageError(f"there is no directory at {tilde(project)}")

    result = Result(dry_run)
    if not any(f.fix == fix for f in doctor.check_project(cfg, project)):
        return result
    try:
        FIXES[fix](cfg, Writer.at(project, result), source)
    except Refusal as e:
        result.problems.append(Problem("refused", str(e), path=project))
    except Failed:
        pass  # reported where it happened
    return result

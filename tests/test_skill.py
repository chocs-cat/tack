"""The agent skill tack ships in `skills/tack`."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from tack.cli import build_parser
from tack.doctor.skills import frontmatter, skill_problem

SKILL = Path(__file__).parent.parent / "skills" / "tack"


def test_the_skill_is_valid() -> None:
    assert skill_problem(SKILL) is None
    meta = frontmatter((SKILL / "SKILL.md").read_text())
    assert meta is not None
    assert meta["name"] == "tack"


def _commands() -> list[str]:
    """Each `tack …` line in the skill's shell blocks."""
    blocks = re.findall(r"^```sh\n(.*?)^```", (SKILL / "SKILL.md").read_text(), re.M | re.S)
    return [line for block in blocks for line in block.splitlines() if line.startswith("tack ")]


@pytest.mark.parametrize("line", _commands())
def test_the_skill_runs_real_commands(line: str) -> None:
    """Every command the skill shows parses, so it can't drift from the CLI."""
    build_parser().parse_args(shlex.split(line, comments=True)[1:])

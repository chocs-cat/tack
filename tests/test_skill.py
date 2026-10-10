"""The agent skills tack ships in `skills/`."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from tack.cli import build_parser
from tack.doctor.skills import frontmatter, skill_problem

SKILLS = Path(__file__).parent.parent / "skills"
ALL = sorted(p for p in SKILLS.iterdir() if p.is_dir())


@pytest.mark.parametrize("skill", ALL, ids=lambda p: p.name)
def test_the_skill_is_valid(skill: Path) -> None:
    assert skill_problem(skill) is None
    meta = frontmatter((skill / "SKILL.md").read_text())
    assert meta is not None
    assert meta["name"] == skill.name


def _commands() -> list[tuple[str, str]]:
    """Each `tack …` line in each skill's shell blocks, with the skill's name."""
    out = []
    for skill in ALL:
        text = (skill / "SKILL.md").read_text()
        blocks = re.findall(r"^```sh\n(.*?)^```", text, re.M | re.S)
        out += [
            (skill.name, line)
            for block in blocks
            for line in block.splitlines()
            if line.startswith("tack ")
        ]
    return out


def test_the_listing_finds_both_skills_and_their_commands() -> None:
    """Guards the parametrization: a listing or a pattern that found nothing
    would leave the tests above with nothing to check."""
    assert {"tack", "instructions-setup"} <= {p.name for p in ALL}
    assert {"tack", "instructions-setup"} <= {name for name, _ in _commands()}


@pytest.mark.parametrize(("skill", "line"), _commands())
def test_the_skill_runs_real_commands(skill: str, line: str) -> None:
    """Every command a skill shows parses, so it can't drift from the CLI."""
    build_parser().parse_args(shlex.split(line, comments=True)[1:])

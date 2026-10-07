"""The manifest examples in `README.md` and the agent skill parse (#35)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tack.config import ConfigError
from tests.helpers import load

ROOT = Path(__file__).parent.parent
FILES = ("README.md", "skills/tack/SKILL.md")


def _blocks() -> list[tuple[str, int, str]]:
    """Each ```` ```toml ```` block in FILES: the file, its number in the file
    (from 1), and its text."""
    out = []
    for rel in FILES:
        found = re.findall(r"^```toml\n(.*?)^```", (ROOT / rel).read_text(), re.M | re.S)
        out += [(rel, n, block) for n, block in enumerate(found, 1)]
    return out


def test_each_file_has_a_manifest_example() -> None:
    assert {rel for rel, _, _ in _blocks()} == set(FILES)


@pytest.mark.parametrize(
    ("rel", "n", "block"), [pytest.param(*b, id=f"{b[0]}#{b[1]}") for b in _blocks()]
)
def test_the_manifest_examples_parse(home: Path, rel: str, n: int, block: str) -> None:
    """Every manifest the docs show loads through the real parser, so an
    example can't drift from the manifest's rules."""
    try:
        load(home, block)
    except ConfigError as e:
        pytest.fail(f"{rel}, toml block {n}: {e}")

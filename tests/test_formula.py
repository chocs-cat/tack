from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from packaging.requirements import Requirement

from tack import __version__

ROOT = Path(__file__).parent.parent
PYPROJECT_0_0_1 = '[project]\nname = "tack-agents"\nversion = "0.0.1"\n'


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("formula", ROOT / "scripts" / "formula.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["formula"] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


formula = _load()


def test_render() -> None:
    tack = formula.Sdist("tack-agents", "https://files/tack_agents-0.1.0.tar.gz", "a" * 64)
    text = formula.render(
        tack,
        [
            formula.Sdist("rich", "https://files/rich-15.0.0.tar.gz", "c" * 64),
            formula.Sdist("markdown-it-py", "https://files/markdown_it_py-4.2.0.tar.gz", "b" * 64),
        ],
    )
    assert text.startswith("class Tack < Formula\n  include Language::Python::Virtualenv\n")
    assert '  url "https://files/tack_agents-0.1.0.tar.gz"\n  sha256 "' + "a" * 64 in text
    assert '  depends_on "python@3.14"\n' in text
    assert text.index('resource "markdown-it-py"') < text.index('resource "rich"')
    assert '    url "https://files/rich-15.0.0.tar.gz"\n    sha256 "' + "c" * 64 in text
    assert 'assert_match "tack #{version}", shell_output("#{bin}/tack --version")' in text
    assert text.endswith("  end\nend\n")


def test_platform_markers() -> None:
    def needed(line: str) -> bool:
        return formula.needed(Requirement(line), "3.14")

    assert needed("rich==15.0.0")
    assert needed("appnope==0.1.4 ; sys_platform == 'darwin'")
    assert not needed("colorama==0.4.6 ; sys_platform == 'win32'")
    assert not needed("tomli==2.2.1 ; python_full_version < '3.11'")


def test_pins_are_the_locked_runtime_dependencies() -> None:
    pins = {r.name: str(r.specifier) for r in formula.pins()}
    assert pins["textual"].startswith("==")
    assert "pytest" not in pins  # dev dependencies stay out
    assert "tack-agents" not in pins


def test_checkout_version(tmp_path: Path) -> None:
    assert formula.checkout_version() == __version__
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_0_0_1)
    assert formula.checkout_version(tmp_path) == "0.0.1"


def test_refuses_another_versions_checkout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_0_0_1)
    with pytest.raises(SystemExit, match=r"is 0\.0\.1, not 0\.1\.0"):
        formula.main(["0.1.0", "--root", str(tmp_path)])

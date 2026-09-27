from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from packaging.requirements import Requirement


def _load() -> ModuleType:
    path = Path(__file__).parent.parent / "scripts" / "formula.py"
    spec = importlib.util.spec_from_file_location("formula", path)
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

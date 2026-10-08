from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests import standin

REAL_HOME = Path.home()

_ENV = (
    "TACK_CONFIG",
    "TACK_DATA",
    "TACK_STATE",
    "TACK_NO_COMMIT",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "GIT_DIR",
    "GIT_WORK_TREE",
)


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scratch home directory, and git configured only from a scratch file,
    so nothing in the suite reads or writes the real ones."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    for var in _ENV:
        monkeypatch.delenv(var, raising=False)
    gitconfig = tmp_path / "gitconfig"
    # No automatic maintenance: a commit or fetch would start it in the
    # background, changing a .git a test compares (review-checklist §3).
    gitconfig.write_text(
        "[user]\n\tname = Test\n\temail = test@example.com\n[init]\n\tdefaultBranch = master\n"
        "[maintenance]\n\tauto = false\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    assert Path.home() != REAL_HOME
    return h


@pytest.fixture(scope="session")
def _agentless_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    """PATH without the real agents, built once: see `standin.isolate`."""
    return standin.isolate(os.environ.get("PATH", ""), tmp_path_factory.mktemp("path"))


@pytest.fixture(autouse=True)
def standins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _agentless_path: str
) -> standin.Standins:
    """Stand-in `claude` and `codex` first on PATH, and no other `claude` or
    `codex` on it, so no test can start a real agent."""
    bin_dir = tmp_path / "bin"
    standin.write_bin(bin_dir)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), _agentless_path]))
    monkeypatch.setenv(standin.ENV, str(tmp_path / "agents"))
    return standin.Standins(tmp_path / "agents", bin_dir)

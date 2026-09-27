from __future__ import annotations

from pathlib import Path

import pytest

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
    gitconfig.write_text(
        "[user]\n\tname = Test\n\temail = test@example.com\n[init]\n\tdefaultBranch = master\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    assert Path.home() != REAL_HOME
    return h

"""Helpers for text meant for people."""

from __future__ import annotations

import os
from pathlib import Path


def tilde(path: Path | str) -> str:
    """`path` with the home directory shown as `~`."""
    p, home = str(path), str(Path.home())
    if home != "/" and (p == home or p.startswith(home + os.sep)):
        return "~" + p[len(home) :]
    return p

"""Where each source's skills are.

A `path` source is its directory; a `git` source is tack's checkout of it
under the data directory. A skill is a directory in the source's `subdir`,
named by its directory name.
"""

from __future__ import annotations

import os
from pathlib import Path

from tack.config import Paths, Source


def root(source: Source, paths: Paths) -> Path:
    return source.path if source.path is not None else paths.sources_dir / source.name


def skills_dir(source: Source, paths: Paths) -> Path:
    return Path(os.path.normpath(root(source, paths) / source.subdir))


def offered(source: Source, paths: Paths) -> dict[str, Path] | None:
    """The source's skill directories by name; None if its skills dir isn't there."""
    d = skills_dir(source, paths)
    try:
        entries = sorted(os.scandir(d), key=lambda e: e.name)
    except OSError:
        return None
    return {e.name: Path(e.path) for e in entries if not e.name.startswith(".") and e.is_dir()}

"""The skills a plugin carries (design.md *`doctor` checks*, *Global*, the
bullet *Skills a plugin carries*; DEC-27), read from its files as its source
has them now (DEC-17). Nothing here raises: a file or value that can't be
read adds nothing.
"""

from __future__ import annotations

import json
import os
import posixpath
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from tack import catalog
from tack.doctor.skills import frontmatter


def carried(directory: Path, plugin: catalog.Plugin) -> set[str]:
    """The names of the skills the plugin at `directory` carries: those under
    its `skills/`, and those each `skills` field of its three `plugin.json`
    files (as `version` reads them) and of its catalog entry names."""
    names = _directory_of_skills(directory / "skills")
    for value in _fields(directory, plugin.entry):
        for rel in value if isinstance(value, list) else [value]:
            if isinstance(rel, str):
                names |= _named(directory, rel, plugin.name)
    return names


def _fields(directory: Path, entry: Mapping[str, Any]) -> Iterator[Any]:
    """Each `skills` value: a `plugin.json` that is missing or isn't a JSON
    object has none."""
    read = catalog.files(directory)
    for rel in catalog.PLUGIN_JSONS:
        data = read(rel)
        if data is None:
            continue
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(doc, dict) and "skills" in doc:
            yield doc["skills"]
    if "skills" in entry:
        yield entry["skills"]


def _named(directory: Path, rel: str, plugin: str) -> set[str]:
    """What one path a `skills` field gives: the skill it is, else the skills
    of the directory it is. One that leaves the plugin, read as written (a
    symlink inside is followed, as the copy follows it, DEC-2), gives none."""
    norm = posixpath.normpath(rel)
    if posixpath.isabs(norm) or norm == ".." or norm.startswith("../"):
        return set()
    path = directory / norm
    try:
        if (path / "SKILL.md").is_file():
            return {_name(path, plugin if norm == "." else path.name)}
    except OSError:
        return set()
    return _directory_of_skills(path)


def _directory_of_skills(path: Path) -> set[str]:
    """The skills directly under `path`, as under a plugin's `skills/`."""
    try:
        with os.scandir(path) as entries:
            found = [(Path(e.path), e.name) for e in entries]
    except OSError:
        return set()
    names: set[str] = set()
    for skill, dirname in found:
        try:
            if skill.is_dir() and (skill / "SKILL.md").is_file():
                names.add(_name(skill, dirname))
        except OSError:
            continue
    return names


def _name(skill: Path, fallback: str) -> str:
    """A skill's frontmatter `name`, else `fallback`."""
    try:
        meta = frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return fallback
    return (meta or {}).get("name") or fallback

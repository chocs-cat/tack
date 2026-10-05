"""A source's plugin catalog: its marketplace file, in either agent's format.

A source offers plugins through `.claude-plugin/marketplace.json` (Claude
Code's format) or, failing that, `.agents/plugins/marketplace.json` (Codex's).
Each entry of its `plugins` array is a plugin, and its `source` says where the
plugin's files are: in the source, in another git repository at a commit, or
somewhere tack can't pin, which makes it not deployable (DEC-4).

`parse` is pure: it reads the decoded JSON only, never the filesystem, so the
same reading serves a catalog taken from git at any commit. Whether a plugin's
directory exists is found when tack copies it.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tack.config import valid_name

CATALOGS = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json")
# Where a plugin's own version is, in the order the agents prefer it.
PLUGIN_JSONS = (".claude-plugin/plugin.json", "plugin.json", ".codex-plugin/plugin.json")

_SHA = re.compile(r"[0-9a-f]{40}")
_SHORTHAND = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")  # owner/repo
_UNPINNABLE = ("npm", "archive", "command")


class CatalogError(Exception):
    """A catalog file can't be read, or isn't a catalog."""


@dataclass(frozen=True)
class InSource:
    """The plugin is a directory of the source."""

    path: str  # normalized POSIX path relative to the source root; "." for the root


@dataclass(frozen=True)
class InRepository:
    """The plugin is in another git repository, pinned to a commit."""

    url: str
    path: str | None  # its directory inside the repository; None for the whole of it
    commit: str


@dataclass(frozen=True)
class Undeployable:
    reason: str


Where = InSource | InRepository | Undeployable


@dataclass(frozen=True)
class Plugin:
    name: str
    where: Where
    entry: Mapping[str, Any]  # the upstream catalog entry, as it is


@dataclass(frozen=True)
class Ignored:
    """A `plugins` entry that names no plugin."""

    index: int  # its position in `plugins`, from 0
    reason: str


@dataclass(frozen=True)
class Catalog:
    file: str
    plugins: tuple[Plugin, ...]  # in catalog order; a name listed twice appears twice
    ignored: tuple[Ignored, ...] = ()


def find(root: Path) -> Path | None:
    """The catalog file of the source rooted at `root`, if it has one.

    Precedence is by existence: a broken `.claude-plugin/` catalog is not
    passed over for the `.agents/plugins/` one.
    """
    for rel in CATALOGS:
        file = root / rel
        if file.exists() or file.is_symlink():
            return file
    return None


def read(root: Path) -> Catalog | None:
    """The catalog of the source rooted at `root`; None when it has none."""
    file = find(root)
    if file is None:
        return None
    try:
        data = json.loads(file.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise CatalogError(f"{file}: {e}") from e
    return parse(data, str(file))


def parse(data: Any, file: str) -> Catalog:
    """Classify each entry of a decoded catalog; `file` labels messages."""
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise CatalogError(f"{file}: not a catalog: it needs a `plugins` list")
    metadata = data.get("metadata")
    root = metadata.get("pluginRoot") if isinstance(metadata, dict) else None
    plugin_root: str | Undeployable | None = None
    if root is not None:
        plugin_root = (isinstance(root, str) and _relative(root)) or Undeployable(
            f"`metadata.pluginRoot` {root!r} isn't a relative path inside the source"
        )

    plugins: list[Plugin] = []
    ignored: list[Ignored] = []
    for i, entry in enumerate(data["plugins"]):
        if not isinstance(entry, dict):
            ignored.append(Ignored(i, "not an object"))
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not valid_name(name):
            what = "no `name`" if name is None else f"{name!r} isn't a valid name"
            ignored.append(Ignored(i, what))
            continue
        plugins.append(Plugin(name, _where(entry, plugin_root), entry))

    twice = {name for name, n in Counter(p.name for p in plugins).items() if n > 1}
    plugins = [
        Plugin(p.name, Undeployable(f"{p.name!r} is listed more than once"), p.entry)
        if p.name in twice
        else p
        for p in plugins
    ]
    return Catalog(file, tuple(plugins), tuple(ignored))


def _where(entry: Mapping[str, Any], plugin_root: str | Undeployable | None) -> Where:
    if "source" not in entry:
        return Undeployable("no `source`")
    source = entry["source"]
    if isinstance(source, str):
        return _local(source, plugin_root, "`source`")
    if not isinstance(source, dict):
        return Undeployable("`source` is neither a path nor an object")
    kind = source.get("source")
    if not isinstance(kind, str):
        return Undeployable("the `source` object has no `source` type")

    def field(key: str) -> str | None:
        value = source.get(key)
        return value if isinstance(value, str) and value else None

    if kind == "local":
        path = field("path")
        if path is None:
            return Undeployable("a `local` source needs a `path`")
        return _local(path, plugin_root, "`path`")
    if kind in _UNPINNABLE:
        return Undeployable(f"`{kind}` sources can't be pinned")
    if kind not in ("url", "github", "git-subdir"):
        return Undeployable(f"unknown source type {kind!r}")

    if kind == "github":
        repo = field("repo")
        if repo is None:
            return Undeployable("a `github` source needs a `repo`")
        if not _SHORTHAND.fullmatch(repo):
            return Undeployable(f"a `github` source's `repo` is owner/repo, not {repo!r}")
        url: str | None = _github(repo)
    else:
        url = field("url")
        if url is None:
            return Undeployable(f"a `{kind}` source needs a `url`")
        if kind == "git-subdir" and _SHORTHAND.fullmatch(url):
            url = _github(url)

    subdir: str | None = None
    if kind == "git-subdir":
        raw = field("path")
        if raw is None:
            return Undeployable("a `git-subdir` source needs a `path`")
        if ".." in raw.split("/"):
            return Undeployable(f"`path` {raw!r} has a `..`")
        subdir = _relative(raw)
        if subdir is None:
            return Undeployable(f"`path` {raw!r} isn't a directory inside the repository")

    sha = source.get("sha")
    if sha is None:
        pinned = " is pinned only to a `ref`" if "ref" in source else " has no `sha`"
        return Undeployable(f"the `{kind}` source{pinned}; it needs a commit `sha`")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        return Undeployable(f"`sha` {sha!r} isn't a commit: 40 lowercase hexadecimal digits")
    assert url is not None
    return InRepository(url, subdir, sha)


def _local(path: str, plugin_root: str | Undeployable | None, what: str) -> Where:
    """A path in the source, by the agents' rules: ".", "./", a path starting
    with "./", or a bare name under `metadata.pluginRoot`."""
    if ".." in path.split("/"):
        return Undeployable(f"{what} {path!r} has a `..`")
    if path in (".", "./") or path.startswith("./"):
        return InSource(posixpath.normpath(path))
    if not path or "/" in path:
        return Undeployable(f"{what} {path!r} isn't a relative path starting with `./`")
    if plugin_root is None:
        return Undeployable(f"{what} {path!r} is a bare name, and there's no `metadata.pluginRoot`")
    if isinstance(plugin_root, Undeployable):
        return Undeployable(f"{what} {path!r} is a bare name, and {plugin_root.reason}")
    return InSource(posixpath.normpath(posixpath.join(plugin_root, path)))


def _relative(path: str) -> str | None:
    """`path` normalized, if it is a relative path with no `..`; else None."""
    if not path or path.startswith("/") or ".." in path.split("/"):
        return None
    return posixpath.normpath(path)


def _github(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def version(entry: Mapping[str, Any], read: Callable[[str], bytes | None]) -> str | None:
    """A plugin's version: the first string `version` among its `plugin.json`s,
    else its catalog entry's, else none.

    `read` gives a file of the plugin's by its path relative to the plugin's
    directory, or None if it can't; so the files can come from a directory
    (`files`) or from git at a commit. A file that can't be read, isn't JSON,
    or has no string `version` is passed over.
    """
    for rel in PLUGIN_JSONS:
        data = read(rel)
        if data is None:
            continue
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("version"), str):
            return doc["version"]
    v = entry.get("version")
    return v if isinstance(v, str) else None


def files(directory: Path) -> Callable[[str], bytes | None]:
    """A `read` for `version` over the plugin directory `directory`."""

    def read(rel: str) -> bytes | None:
        try:
            return (directory / rel).read_bytes()
        except OSError:
            return None

    return read

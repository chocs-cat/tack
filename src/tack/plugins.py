"""Which plugins the manifest selects (`plan`), and tack's marketplace: the
one marketplace tack registers with each agent (DEC-1).

The marketplace lives in `<data>/marketplace`, and only tack writes it:

- `plugins/<name>/` is a copy of each selected plugin: everything but `.git`
  (at any depth), with each symlink copied as the file or directory it points
  to (DEC-2). A copy is refreshed only when its hash differs from the
  plugin's, and is built beside the old one and swapped in, so an agent
  starting a session meanwhile never reads half a copy.
- `.claude-plugin/marketplace.json` is tack's catalog: an entry for each
  wanted plugin with a copy, its upstream entry with `source` pointing at the
  copy, and each kept plugin's entry as it was. Both agents read it.

Updating the marketplace never deletes a copy: `sync` drops a deselected
plugin's copy only after uninstalling it.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from tack import catalog, config, sources
from tack.config import Config, Paths, Source
from tack.text import tilde

NAME = "tack"
CATALOG = ".claude-plugin/marketplace.json"
_DROPPED = ("headers", "headersHelper")  # they apply only to sources tack doesn't deploy


class PluginError(Exception):
    """A plugin's directory can't be hashed or copied."""


@dataclass(frozen=True)
class Wanted:
    """A plugin the marketplace should hold."""

    name: str
    directory: Path  # the plugin's files: in a checkout, a `path` source or a clone
    entry: Mapping[str, Any]  # its upstream catalog entry


@dataclass(frozen=True)
class Change:
    action: Literal["copy", "write"]
    detail: str
    plugin: str | None  # None for tack's catalog
    path: Path


@dataclass(frozen=True)
class Failure:
    """A plugin that couldn't be copied; it keeps the copy it had, if any."""

    plugin: str
    message: str
    path: Path  # the plugin's directory


@dataclass
class Update:
    changes: list[Change] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    # Each wanted plugin's hash but a failed one's: its directory's, which its
    # copy has once copied (a dry run included). `sync` records it.
    hashes: dict[str, str] = field(default_factory=dict)


def update(
    paths: Paths,
    wanted: Iterable[Wanted],
    *,
    keep: Iterable[str] = (),
    dry_run: bool = False,
) -> Update:
    """Bring tack's marketplace up to date for the `wanted` plugins: copy each
    one whose copy is missing or stale, then write the catalog if it changes.

    The plugins named in `keep` stay exactly as they are: their copies are
    neither refreshed nor deleted, and their catalog entries are carried over
    from the catalog on disk (a kept name with no copy, or no entry there, has
    neither). A name both wanted and kept is kept (DEC-12).

    A dry run reports the same changes and writes nothing."""
    out = Update()
    kept = set(keep)
    plugins_dir = paths.marketplace_dir / "plugins"
    if not dry_run:
        _clear_leftovers(plugins_dir)
    listed: list[Wanted] = _kept(paths, kept)
    for w in sorted(wanted, key=lambda w: w.name):
        if w.name in kept:
            continue
        copy = plugins_dir / w.name
        digest = files_hash(w.directory)
        stale = False
        if isinstance(digest, Unreadable):
            out.failures.append(Failure(w.name, digest.reason, w.directory))
        else:
            try:
                stale = digest != copy_hash(copy)
                if stale and not dry_run:
                    _copy(w.directory, copy)
            except (PluginError, OSError) as e:
                out.failures.append(Failure(w.name, _failure(e), w.directory))
                stale = False
            else:
                out.hashes[w.name] = digest
        if stale:
            out.changes.append(Change("copy", f"{w.name} from {tilde(w.directory)}", w.name, copy))
        if stale or copy.is_dir():
            listed.append(w)

    file = paths.marketplace_dir / CATALOG
    text = catalog_text(listed)
    try:
        current = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        current = None
    if current != text:
        out.changes.append(Change("write", tilde(file), None, file))
        if not dry_run:
            config.write_atomic(file, text)
    return out


def _kept(paths: Paths, kept: set[str]) -> list[Wanted]:
    """The kept plugins with both a copy and an entry in tack's catalog on
    disk, each with that entry as it is."""
    if not kept:
        return []
    try:
        data = json.loads((paths.marketplace_dir / CATALOG).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    entries = data.get("plugins") if isinstance(data, dict) else None
    out: dict[str, Wanted] = {}
    for entry in entries if isinstance(entries, list) else []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or name not in kept or name in out:
            continue
        copy = paths.marketplace_dir / "plugins" / name
        if copy.is_dir():
            out[name] = Wanted(name, copy, entry)
    return list(out.values())


def catalog_text(plugins: Iterable[Wanted]) -> str:
    """tack's catalog for these plugins: each upstream entry, by name, with its
    `source` replaced by the copy and `headers` and `headersHelper` dropped."""
    entries: list[dict[str, Any]] = []
    for w in sorted(plugins, key=lambda w: w.name):
        entry = {k: v for k, v in w.entry.items() if k not in _DROPPED}
        entry["source"] = f"./plugins/{w.name}"
        entries.append(entry)
    doc = {"name": NAME, "owner": {"name": NAME}, "plugins": entries}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def copies(paths: Paths) -> dict[str, Path]:
    """The plugins with a copy in tack's marketplace, by name."""
    try:
        with os.scandir(paths.marketplace_dir / "plugins") as it:
            entries = sorted(it, key=lambda e: e.name)
    except (FileNotFoundError, NotADirectoryError):
        return {}
    return {
        e.name: Path(e.path)
        for e in entries
        if not e.name.startswith(".") and e.is_dir(follow_symlinks=False)
    }


def drop(paths: Paths, name: str) -> bool:
    """Delete one plugin's copy; whether there was one."""
    copy = paths.marketplace_dir / "plugins" / name
    if not os.path.lexists(copy):
        return False
    _remove(copy)
    return True


def remove(paths: Paths) -> bool:
    """Delete tack's marketplace; whether it was there."""
    if not os.path.lexists(paths.marketplace_dir):
        return False
    _remove(paths.marketplace_dir)
    return True


# --- the hash and the copy ------------------------------------------------------


def tree_hash(directory: Path) -> str:
    """A SHA-256 over the plugin's files, in order of their paths relative to
    `directory`: each file's path, whether it is executable, and its contents.
    Symlinks count as what they point to, `.git` is left out, and directories
    count only through their files, so a plugin and its copy hash the same.

    Raises PluginError for a missing directory, a symlink that points nowhere,
    or a loop; OSError for a file it can't read.
    """
    _, files = _walk(directory)
    h = hashlib.sha256()
    for rel, path in files:
        with path.open("rb") as f:
            executable = os.fstat(f.fileno()).st_mode & 0o111 != 0
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        h.update(os.fsencode(rel) + b"\0" + (b"x" if executable else b"-") + b"\0")
        h.update(digest.encode() + b"\0")
    return h.hexdigest()


@dataclass(frozen=True)
class Unreadable:
    """Why a plugin's files can't be read, so that its copy would fail."""

    reason: str


def files_hash(directory: Path) -> str | Unreadable:
    """The plugin's `tree_hash`, or why its files can't be read: the message
    `update` gives the plugin's failure, which `doctor` reports too."""
    try:
        return tree_hash(directory)
    except (PluginError, OSError) as e:
        return Unreadable(_failure(e))


def copy_hash(copy: Path) -> str | None:
    """The hash of a plugin's copy in tack's marketplace; None when there is
    no copy, or one that can't be read, which is stale either way."""
    if not copy.is_dir():
        return None
    try:
        return tree_hash(copy)
    except (PluginError, OSError):
        return None  # a damaged copy is stale


def _walk(directory: Path) -> tuple[list[str], list[tuple[str, Path]]]:
    """The directories and the files under `directory`, by POSIX path relative
    to it, following symlinks and leaving `.git` out; files sorted by path."""
    try:
        top = directory.stat()
    except OSError as e:
        raise PluginError(f"no plugin directory at {tilde(directory)}") from e
    if not stat.S_ISDIR(top.st_mode):
        raise PluginError(f"{tilde(directory)} isn't a directory")
    dirs: list[str] = []
    files: list[tuple[str, Path]] = []

    def walk(d: Path, prefix: str, ancestors: frozenset[tuple[int, int]]) -> None:
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            if e.name == ".git":
                continue
            rel, path = prefix + e.name, Path(e.path)
            try:
                st = path.stat()
            except FileNotFoundError as err:
                if path.is_symlink():
                    raise PluginError(f"{rel} is a link to nowhere ({path.readlink()})") from err
                raise
            except OSError as err:
                if err.errno == errno.ELOOP:
                    raise PluginError(f"{rel} is a symlink loop") from err
                raise
            if stat.S_ISDIR(st.st_mode):
                key = (st.st_dev, st.st_ino)
                if key in ancestors:
                    raise PluginError(f"{rel} is a link to a directory that contains it")
                dirs.append(rel)
                walk(path, rel + "/", ancestors | {key})
            elif stat.S_ISREG(st.st_mode):
                files.append((rel, path))
            # Anything else (a socket, a FIFO) has no contents to copy.

    walk(directory, "", frozenset({(top.st_dev, top.st_ino)}))
    files.sort()
    return dirs, files


def _copy(directory: Path, dest: Path) -> None:
    """Copy the plugin at `directory` to `dest`: built under a dot-named
    temporary directory beside it, then swapped in."""
    dirs, files = _walk(directory)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Plugin names can't start with a dot (config.valid_name), so the
    # temporary directories never collide with a copy.
    tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest.parent))
    try:
        tmp.chmod(0o755)
        for rel in dirs:
            (tmp / rel).mkdir()
        for rel, path in files:
            shutil.copy2(path, tmp / rel)  # follows a symlink: its target is copied
        if os.path.lexists(dest):
            old = tmp.with_name(tmp.name + ".old")
            dest.rename(old)
            try:
                tmp.rename(dest)
            except OSError:
                old.rename(dest)
                raise
            _remove(old)
        else:
            tmp.rename(dest)
    except BaseException:
        if tmp.exists():
            _remove(tmp)
        raise


def _clear_leftovers(plugins_dir: Path) -> None:
    """Remove temporary directories an interrupted copy left behind."""
    try:
        with os.scandir(plugins_dir) as it:
            leftovers = [Path(e.path) for e in it if e.name.startswith(".")]
    except (FileNotFoundError, NotADirectoryError):
        return
    for path in leftovers:
        _remove(path)


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _failure(e: PluginError | OSError) -> str:
    """What a plugin's failed hash or copy is reported as."""
    if isinstance(e, PluginError):
        return str(e)
    where = f"{tilde(e.filename)}: " if e.filename else ""
    return f"{where}{e.strerror or e}"


# --- the plan ------------------------------------------------------------------------

# What a source that selects plugins has for a catalog (design.md *Selecting
# plugins*):
#   found       its plugins can be selected
#   no-catalog  no catalog file: it selects nothing, and lacks every name it lists
#   no-root     its root isn't there (a missing `path`, a git source not cloned
#               yet): it selects and lacks nothing
#   broken      the catalog can't be read: it selects and lacks nothing
CatalogState = Literal["found", "no-catalog", "no-root", "broken"]


@dataclass(frozen=True)
class Selected:
    """One plugin a source selects, and the harnesses it targets."""

    source: Source
    plugin: catalog.Plugin
    harnesses: tuple[str, ...]  # only harnesses that take plugins (DEC-8)
    # An `InSource` plugin's files; None for any other (D8 gives an
    # `InRepository` plugin its clone).
    directory: Path | None

    @property
    def name(self) -> str:
        return self.plugin.name

    @property
    def deployable(self) -> bool:
        return not isinstance(self.plugin.where, catalog.Undeployable)


@dataclass
class SourceState:
    """A source that selects plugins, and what its catalog gives it."""

    source: Source
    root: Path
    catalog_state: CatalogState
    error: str | None  # a broken catalog's CatalogError message
    # One per name: under "*" in catalog order, else in the manifest's. A name
    # the catalog lists twice is its first entry, undeployable as every one is.
    selected: list[Selected]
    missing: list[str]  # listed in the manifest but not in the catalog
    ignored: tuple[catalog.Ignored, ...]  # catalog entries that name no plugin


@dataclass
class Plan:
    sources: list[SourceState]  # the sources that select plugins
    # harness -> plugin -> the one deployable plugin it gets, for each harness
    # that takes plugins; collided names and undeployable plugins left out
    plugins: dict[str, dict[str, Selected]]
    # plugin -> (harnesses, sources) where two or more sources select it,
    # deployable or not, whatever harnesses each targets (DEC-11): every
    # harness any of them targets, in config.PLUGIN_HARNESSES order
    collisions: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)


def plan(cfg: Config) -> Plan:
    """Which plugin each harness gets from which source (design.md *Selecting
    plugins*). It reads the catalogs of the sources that select plugins and
    nothing else: it copies nothing, runs no agent and writes nothing."""
    states = [_source_state(src, cfg) for src in cfg.sources if src.plugins != ()]

    by_name: dict[str, list[Selected]] = defaultdict(list)
    for state in states:
        for sel in state.selected:
            by_name[sel.name].append(sel)

    # A name two sources select collides whatever harnesses each targets:
    # tack's marketplace holds one plugin per name for every harness (DEC-11).
    wanted: dict[str, dict[str, Selected]] = {h: {} for h in config.PLUGIN_HARNESSES}
    collisions: dict[str, tuple[list[str], list[str]]] = {}
    for name, sels in by_name.items():
        if len(sels) > 1:  # a source selects each name once
            targeted = {h for s in sels for h in s.harnesses}
            hs = [h for h in config.PLUGIN_HARNESSES if h in targeted]
            collisions[name] = (hs, [s.source.name for s in sels])
            continue
        (sel,) = sels
        if sel.deployable:
            for h in sel.harnesses:
                wanted[h][name] = sel
    return Plan(states, wanted, collisions)


def undeployable(plugin: catalog.Plugin) -> str | None:
    """Why `sync` can't deploy a selected plugin, to follow its name: one tack
    can't deploy (design.md *Catalogs*), or one from another repository,
    until D8; None for one in the source. `sync`, `doctor` and `add` all say
    it this way, each with its own prefix."""
    where = plugin.where
    if isinstance(where, catalog.Undeployable):
        return f"can't be deployed: {where.reason}"
    if isinstance(where, catalog.InRepository):
        return f"is in another repository ({where.url}), and tack doesn't deploy those yet"
    return None


def collision(name: str, harnesses: Sequence[str], srcs: Sequence[str]) -> str:
    """A plugin name two sources select, as `sync` reports it (DEC-11)."""
    return (
        f"plugin {name!r} is selected from sources {', '.join(srcs)} for "
        f"{', '.join(harnesses)}; none of them is deployed -- deselect all but one"
    )


def problems(sel: Selected, plan: Plan) -> list[str]:
    """What `sync` reports about a selected plugin, each as `sync` words it:
    a name another source selects too, one tack can't deploy or from another
    repository, and one whose files can't be read, so that its copy would
    fail (a collided name is kept, not copied). It reads the plugin's files
    as they are now, as the states do (DEC-17)."""
    out: list[str] = []
    if sel.name in plan.collisions:
        out.append(collision(sel.name, *plan.collisions[sel.name]))
    if why := undeployable(sel.plugin):
        out.append(f"plugin {sel.name!r} {why}")
    elif sel.directory is not None and sel.name not in plan.collisions:
        digest = files_hash(sel.directory)
        if isinstance(digest, Unreadable):
            out.append(f"plugin {sel.name!r}: {digest.reason}")
    return out


def _source_state(src: Source, cfg: Config) -> SourceState:
    root = sources.root(src, cfg.paths)
    if not root.is_dir():
        return SourceState(src, root, "no-root", None, [], [], ())
    try:
        found = catalog.read(root)
    except catalog.CatalogError as e:
        return SourceState(src, root, "broken", str(e), [], [], ())
    listed = src.plugins or ()  # None ("*") lists no names
    if found is None:
        return SourceState(src, root, "no-catalog", None, [], [s.name for s in listed], ())

    first: dict[str, catalog.Plugin] = {}
    for p in found.plugins:
        first.setdefault(p.name, p)
    default = src.harnesses or tuple(cfg.harnesses)
    if src.plugins is None:
        chosen = [(p, default) for p in first.values()]
    else:
        chosen = [(first[s.name], s.harnesses or default) for s in listed if s.name in first]
    selected = [
        Selected(
            src,
            p,
            tuple(h for h in hs if h in config.PLUGIN_HARNESSES),  # DEC-8
            _directory(root, p.where),
        )
        for p, hs in chosen
    ]
    missing = [s.name for s in listed if s.name not in first]
    return SourceState(src, root, "found", None, selected, missing, found.ignored)


def _directory(root: Path, where: catalog.Where) -> Path | None:
    if not isinstance(where, catalog.InSource):
        return None
    return root if where.path == "." else root / where.path

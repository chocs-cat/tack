"""`tack add` and `tack remove`, the TUI's Settings, and the manifest edits
they make.

The manifest is edited as text so that its comments and layout survive: a new
`[[source]]` table goes after the last one, and a removed table is cut out
together with the comment lines directly above its header (the comments
directly above the next header are the next table's). Settings replaces a
key's lines, inserts a missing key after the last key of its table, and adds
a missing table before the first `[[source]]`. An edit is kept only if the new
text parses to the old manifest with exactly those changes.
"""

from __future__ import annotations

import copy
import difflib
import os
import re
import shutil
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tack import catalog, config, deploy, plugins, sources, sync
from tack.config import Config, LockEntry, Source, UsageError
from tack.sources import SourceError
from tack.sync import Change, Problem, Result
from tack.text import tilde


def add(
    cfg: Config,
    spec: str,
    *,
    name: str | None = None,
    skills: Sequence[str] = (),
    plugins: Sequence[str] = (),
    ref: str | None = None,
    subdir: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> Result:
    """Add a git URL or a local directory as a source, then sync. Nothing is
    written unless the source is reachable and deploys cleanly. Given
    `plugins` and no `skills`, it deploys only those plugins (`skills = []`)."""
    now = now or datetime.now(UTC)
    directory = None if is_url(spec) else Path(os.path.normpath(Path(spec).expanduser().absolute()))
    if directory is not None:
        if not directory.is_dir():
            raise UsageError(
                f"there is no directory at {spec} "
                "(a git URL has a scheme, like https://, or is host:path)"
            )
        if ref is not None:
            raise UsageError("--ref applies to git sources")
    name = name or (default_name(spec) if directory is None else directory.name)
    if not config.valid_name(name):
        raise UsageError(f"{name!r} can't name a source; pass --name")
    for s in cfg.sources:
        if s.name == name:
            raise UsageError(f"there is already a source named {name!r}; pass --name")
        if s.path is not None and directory is not None:
            same = deploy.same_path(s.path, directory)
        else:
            same = s.git == spec and s.ref == ref
        if same:
            raise UsageError(f"{spec} is already source {s.name!r}")

    fields: dict[str, Any] = {"name": name}
    fields.update({"git": spec} if directory is None else {"path": tilde(directory)})
    if ref is not None:
        fields["ref"] = ref
    if subdir is not None:
        fields["subdir"] = subdir
    if skills or plugins:
        fields["skills"] = list(dict.fromkeys(skills))
    if plugins:
        fields["plugins"] = list(dict.fromkeys(plugins))

    file = cfg.manifest or cfg.paths.manifest
    text = file.read_text(encoding="utf-8") if cfg.manifest else ""
    expected = copy.deepcopy(tomllib.loads(text))
    expected.setdefault("source", []).append(fields)
    new_text = _checked(append_source(text, _table(fields)), expected, file)
    new_cfg = config.parse(expected, file, cfg.paths)
    src = next(s for s in new_cfg.sources if s.name == name)

    result = Result(dry_run)
    pins = config.load_lock(cfg.paths)
    checkout = sources.root(src, cfg.paths)
    fresh = src.git is not None and not checkout.exists() and not dry_run
    if src.git is not None:
        try:
            if dry_run:
                entry = sources.pin(src, now)
                steps: list[tuple[sources.Step, str]] = [("pin", sources.pin_detail(entry))]
            else:
                out = sources.sync_git(src, cfg.paths, None, now=now)
                entry, steps = out.entry, out.steps
        except SourceError as e:
            if fresh:
                shutil.rmtree(checkout, ignore_errors=True)
            result.problems.append(Problem("source", str(e), source=name))
            return result
        pins[name] = entry
        result.changes += [Change(a, d, name, path=checkout) for a, d in steps]

    if refusals := _refusals(new_cfg, src, dry_run=dry_run):
        if fresh:
            shutil.rmtree(checkout, ignore_errors=True)
        raise UsageError(f"can't add {name}: " + "; ".join(refusals))
    _write(cfg, file, new_text, result)
    return result.extend(sync.sync(new_cfg, dry_run=dry_run, now=now, lock=pins))


def _refusals(cfg: Config, src: Source, *, dry_run: bool) -> list[str]:
    """What makes a new source unfit to add: its skills, unless it takes none
    (only plugins), then its plugins."""
    out = [] if src.skills == () else _skill_refusals(cfg, src, dry_run=dry_run)
    if src.plugins:  # `add` writes a list of names, never "*"
        out += _plugin_refusals(cfg, src)
    return out


def _skill_refusals(cfg: Config, src: Source, *, dry_run: bool) -> list[str]:
    plan = deploy.plan(cfg)
    state = next(s for s in plan.sources if s.source.name == src.name)
    where = tilde(sources.skills_dir(src, cfg.paths))
    if not state.present:
        if src.git is not None and dry_run:
            return []  # not fetched, so its skills are unknown
        return [f"there is no skills directory at {where}; --subdir says where they are"]
    out: list[str] = []
    if state.missing:
        out.append(f"{where} has no {_names('skill', state.missing)}")
    elif not state.selected:
        out.append(f"there are no skills in {where}")
    collided = sorted(n for n, (_, srcs) in plan.collisions.items() if src.name in srcs)
    if collided:
        others = sorted({s for n in collided for s in plan.collisions[n][1]} - {src.name})
        out.append(
            f"{_names('skill', collided)} already deployed by {', '.join(others)}; "
            "--skill takes only the skills you name"
        )
    return out


def _plugin_refusals(cfg: Config, src: Source) -> list[str]:
    """The plugins a new source selects that `sync` couldn't deploy, each with
    the reason `sync` gives (design.md *Adding and removing sources*). A
    source whose root isn't there (a git source a dry run hasn't cloned)
    selects and lacks nothing, so nothing is checked."""
    plan = plugins.plan(cfg)
    state = next(s for s in plan.sources if s.source.name == src.name)
    out: list[str] = []
    if state.catalog_state == "broken":
        out.append(str(state.error))
    elif state.catalog_state == "no-catalog":
        out.append(
            f"there is no plugin catalog in {tilde(state.root)} ({' or '.join(catalog.CATALOGS)})"
        )
    elif state.missing:
        file = catalog.find(state.root) or state.root
        out.append(f"{tilde(file)} has no {_names('plugin', state.missing)}")
    for sel in state.selected:
        if why := plugins.undeployable(sel.plugin):
            out.append(f"plugin {sel.name!r} {why}")
        elif sel.directory is not None:
            digest = plugins.files_hash(sel.directory)
            if isinstance(digest, plugins.Unreadable):
                out.append(f"plugin {sel.name!r}: {digest.reason}")  # as its copy fails in `sync`
    for sel in state.selected:
        if sel.name in plan.collisions:  # DEC-11
            others = [s for s in plan.collisions[sel.name][1] if s != src.name]
            out.append(f"plugin {sel.name!r} already selected by {', '.join(others)}")
    return out


def _names(word: str, names: Sequence[str]) -> str:
    quoted = ", ".join(map(repr, names))
    return f"{word} {quoted}" if len(names) == 1 else f"{word}s {quoted}"


def remove(cfg: Config, name: str, *, dry_run: bool = False, now: datetime | None = None) -> Result:
    """Remove a source: its table, its lock entry, its links (by syncing), and
    tack's checkout of it."""
    file = cfg.manifest or cfg.paths.manifest
    lock = config.load_lock(cfg.paths)
    index = next((i for i, s in enumerate(cfg.sources) if s.name == name), None)
    if index is None and name not in lock:
        raise UsageError(f"no source named {name!r} in {tilde(file)} or its lockfile")

    result = Result(dry_run)
    new_cfg = cfg
    if index is not None:
        text = file.read_text(encoding="utf-8")
        expected = copy.deepcopy(tomllib.loads(text))
        del expected["source"][index]
        if not expected["source"]:
            del expected["source"]
        new_text = _checked(cut_source(text, index), expected, file)
        new_cfg = config.parse(expected, file, cfg.paths)
        _write(cfg, file, new_text, result)
    pins: dict[str, LockEntry] = {k: v for k, v in lock.items() if k != name}
    result.extend(sync.sync(new_cfg, dry_run=dry_run, now=now, lock=pins))

    checkout = cfg.paths.sources_dir / name
    if checkout.exists():
        _delete(checkout, name, result)
    return result


def _delete(checkout: Path, name: str, result: Result) -> None:
    """Delete tack's checkout of a removed source, unless it holds work."""
    where = tilde(checkout)
    why = (
        "isn't a git checkout"
        if not (checkout / ".git").exists()
        else "has local changes"
        if sources.local_changes(checkout)
        else None
    )
    if why:
        message = f"{where} {why}, so it is left where it is"
        result.problems.append(Problem("source", message, name, path=checkout))
        return
    try:
        if not result.dry_run:
            shutil.rmtree(checkout)
    except OSError as e:
        result.problems.append(Problem("error", f"{where}: {e}", name, path=checkout))
    else:
        result.changes.append(Change("delete", where, name, path=checkout))


Key = tuple[str | int, ...]  # a value's place: ("after_save",), ("source", 0, "ref")


def settings(cfg: Config, changes: dict[Key, Any], *, dry_run: bool = False) -> Result:
    """Set values in the manifest, or remove them (a value of None): what the
    TUI's Settings saves. The change is shown as a diff; nothing is synced."""
    file = cfg.manifest or cfg.paths.manifest
    text = file.read_text(encoding="utf-8") if cfg.manifest else ""
    old = tomllib.loads(text)
    expected = copy.deepcopy(old)
    for key, value in changes.items():
        _put(expected, key, value)
    result = Result(dry_run)
    if expected == old:
        return result
    new_cfg = config.parse(expected, file, cfg.paths)
    new_text = _checked(set_values(text, changes), expected, file)
    diff = "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            f"a/{file.name}" if text else "/dev/null",
            f"b/{file.name}",
        )
    )
    _write(new_cfg, file, new_text, result, diff=diff)
    return result


def _put(data: dict[str, Any], key: Key, value: Any) -> None:
    *parents, last = key
    node: Any = data
    for part in parents:
        node = node[part] if isinstance(part, int) else node.setdefault(part, {})
    if value is None:
        node.pop(last, None)
    else:
        node[last] = value


def _write(cfg: Config, file: Path, text: str, result: Result, diff: str | None = None) -> None:
    result.changes.append(Change("write", tilde(file), path=file, diff=diff))
    if result.dry_run:
        return
    config.write_atomic(file, text)
    if error := config.run_after_save(cfg, file):
        result.problems.append(Problem("after-save", error, path=file))


# --- what an argument names -------------------------------------------------------

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def is_url(spec: str) -> bool:
    """Whether git would read `spec` as a URL rather than a path: it has a
    scheme, or is `[user@]host:path` with no slash before the colon."""
    if _SCHEME.match(spec):
        return True
    before, colon, _ = spec.partition(":")
    return bool(colon and before) and "/" not in before


def default_name(url: str) -> str:
    """The repository's name without `.git`, or its owner's for a repository
    named `skills`."""
    parts = [p for p in re.split(r"[/:]", url) if p]
    repo = parts[-1].removesuffix(".git") if parts else ""
    return parts[-2] if repo == "skills" and len(parts) > 1 else repo


# --- editing the manifest's text --------------------------------------------------

_HEADER = re.compile(r"[ \t]*\[")
_SOURCE_HEADER = re.compile(r"[ \t]*\[\[[ \t]*source[ \t]*\]\][ \t]*(#.*)?")


def _table(fields: dict[str, Any]) -> str:
    return "[[source]]\n" + "".join(line for k, v in fields.items() for line in _field(k, v))


def _field(key: str, value: Any) -> list[str]:
    """`key = value` as lines; a long list gets one item per line."""
    if not isinstance(value, list):
        return [f"{key} = {_toml(value)}\n"]
    items = [_toml(v) for v in value]
    one = f"{key} = [{', '.join(items)}]"
    return (
        [one + "\n"] if len(one) <= 100 else [f"{key} = [\n", *(f"  {i},\n" for i in items), "]\n"]
    )


def _toml(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return config.toml_str(value)


def append_source(text: str, table: str) -> str:
    """`text` with `table` after its last `[[source]]` table (or at the end),
    set off by blank lines."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    tables = _tables(lines)
    at = _span(lines, *tables[-1])[1] if tables else len(lines)
    new = table.splitlines(keepends=True)
    if at > 0 and not _blank(lines[at - 1]):
        new.insert(0, "\n")
    if at < len(lines) and not _blank(lines[at]):
        new.append("\n")
    return "".join(lines[:at] + new + lines[at:])


def cut_source(text: str, index: int) -> str | None:
    """`text` without its `index`th `[[source]]` table; None if it hasn't one."""
    lines = text.splitlines(keepends=True)
    tables = _tables(lines)
    if index >= len(tables):
        return None
    start, stop = _span(lines, *tables[index])
    # The blank lines after the table go too, unless nothing else separates
    # what came before it from what comes after.
    if start == 0 or _blank(lines[start - 1]):
        while stop < len(lines) and _blank(lines[stop]):
            stop += 1
    kept = lines[:start] + lines[stop:]
    if stop == len(lines):
        while kept and _blank(kept[-1]):
            kept.pop()
    return "".join(kept)


def set_values(text: str, changes: dict[Key, Any]) -> str | None:
    """`text` with each key set to its value, or removed for None; None if an
    array table isn't there. Keys set another way (a dotted key, an inline
    table) come out wrong, which the caller's parse check catches."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    for key, value in changes.items():
        edited = _set_value(lines, key, value)
        if edited is None:
            return None
        lines = edited
    return "".join(lines)


def _set_value(lines: list[str], key: Key, value: Any) -> list[str] | None:
    *path, name = key
    assert isinstance(name, str)
    table = tuple(path)
    region = _region(lines, table)
    if region is None:
        if value is None:
            return lines
        if any(isinstance(p, int) for p in table):
            return None  # an array table that isn't there
        return _add_table(lines, table, _field(name, value))
    start, end = region
    keys = _keys(lines, start, end)
    if keys is None:
        return None
    found = keys.get(name)
    if value is None:
        return lines if found is None else lines[: found[0]] + lines[found[1] :]
    new = _field(name, value)
    if found is not None:
        i, j = found
        indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
        new = [indent + line for line in new]
        if j == i + 1 and len(new) == 1 and (comment := _trailing_comment(lines[i])):
            new = [new[0].rstrip("\n") + comment + "\n"]
        return lines[:i] + new + lines[j:]
    if keys:
        at = max(j for _, j in keys.values())
    elif table:
        at = start  # right below the header
    else:  # the top level: above the first table and the comments that lead it
        headers = _headers(lines)
        at = _span(lines, headers[0][0], len(lines))[0] if headers else len(lines)
        if at < len(lines):
            new = [*new, "\n"]
    return lines[:at] + new + lines[at:]


def _headers(lines: list[str]) -> list[tuple[int, Key]]:
    """Each table header's line and the table it opens (array tables are
    numbered in order)."""
    out: list[tuple[int, Key]] = []
    counts: dict[Key, int] = {}
    for i, line in enumerate(lines):
        if not _HEADER.match(line):
            continue
        try:
            node: Any = tomllib.loads(line)
        except tomllib.TOMLDecodeError:
            continue  # a line of a multi-line array, say
        path: list[str | int] = []
        while isinstance(node, dict) and len(node) == 1:
            ((part, node),) = node.items()
            path.append(part)
            if isinstance(node, list):
                n = counts[tuple(path)] = counts.get(tuple(path), -1) + 1
                path.append(n)
                node = node[0]
            if not node:
                break
        out.append((i, tuple(path)))
    return out


def _region(lines: list[str], table: Key) -> tuple[int, int] | None:
    """The lines of `table`'s body: from below its header to the next header.
    The top level's is everything above the first header."""
    headers = _headers(lines)
    if not table:
        return 0, headers[0][0] if headers else len(lines)
    for n, (i, path) in enumerate(headers):
        if path == table:
            return i + 1, headers[n + 1][0] if n + 1 < len(headers) else len(lines)
    return None


def _keys(lines: list[str], start: int, end: int) -> dict[str, tuple[int, int]] | None:
    """Each key in lines[start:end] and the lines its value takes; None if
    one doesn't parse on its own."""
    out: dict[str, tuple[int, int]] = {}
    i = start
    while i < end:
        if _blank(lines[i]) or _comment(lines[i]):
            i += 1
            continue
        for j in range(i + 1, end + 1):
            try:
                parsed = tomllib.loads("".join(lines[i:j]))
            except tomllib.TOMLDecodeError:
                continue
            break
        else:
            return None
        (key,) = parsed
        out[key] = (i, j)
        i = j
    return out


def _trailing_comment(line: str) -> str | None:
    """The comment after a one-line key's value, with the space before it."""
    body = line.rstrip("\n")
    for at in (k for k, c in enumerate(body) if c == "#"):
        try:
            if tomllib.loads(body[:at]) == tomllib.loads(body):
                value = body[:at].rstrip()
                return body[len(value) :]
        except tomllib.TOMLDecodeError:
            continue
    return None


def _add_table(lines: list[str], table: Key, body: list[str]) -> list[str]:
    """`lines` with a new table, before the first `[[source]]` table and the
    comments above it (or at the end), set off by blank lines."""
    parts = [p if isinstance(p, str) and re.fullmatch(r"[A-Za-z0-9_-]+", p) else
             config.toml_str(str(p)) for p in table]  # fmt: skip
    new = [f"[{'.'.join(parts)}]\n", *body]
    sources = _tables(lines)
    at = _span(lines, *sources[0])[0] if sources else len(lines)
    if at > 0 and not _blank(lines[at - 1]):
        new.insert(0, "\n")
    if at < len(lines) and not _blank(lines[at]):
        new.append("\n")
    return lines[:at] + new + lines[at:]


def _checked(text: str | None, expected: dict[str, Any], file: Path) -> str:
    """`text`, if it parses to `expected`."""
    if text is not None:
        try:
            if tomllib.loads(text) == expected:
                return text
        except tomllib.TOMLDecodeError:
            pass
    raise UsageError(
        f"can't make this change to {tilde(file)} without disturbing the rest of it; "
        "edit it by hand"
    )


def _tables(lines: list[str]) -> list[tuple[int, int]]:
    """Each `[[source]]` table's header line, and the next header's (or the end)."""
    headers = [i for i, line in enumerate(lines) if _HEADER.match(line)]
    return [
        (h, headers[k + 1] if k + 1 < len(headers) else len(lines))
        for k, h in enumerate(headers)
        if _SOURCE_HEADER.fullmatch(lines[h].rstrip("\r\n"))
    ]


def _span(lines: list[str], header: int, end: int) -> tuple[int, int]:
    """The lines a table owns: the comments directly above its header, and the
    rest through its last key and any comments directly below that."""
    start = header
    while start > 0 and _comment(lines[start - 1]):
        start -= 1
    if end < len(lines):  # the comments directly above the next header are its
        while end - 1 > header and _comment(lines[end - 1]):
            end -= 1
    keys = [i for i in range(header + 1, end) if not _blank(lines[i]) and not _comment(lines[i])]
    stop = (keys[-1] if keys else header) + 1
    while stop < end and _comment(lines[stop]):
        stop += 1
    return start, stop


def _blank(line: str) -> bool:
    return not line.strip()


def _comment(line: str) -> bool:
    return line.lstrip().startswith("#")

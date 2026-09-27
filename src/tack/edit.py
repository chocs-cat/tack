"""`tack add` and `tack remove`, and the manifest edits they make.

The manifest is edited as text so that its comments and layout survive: a new
`[[source]]` table goes after the last one, and a removed table is cut out
together with the comment lines directly above its header (the comments
directly above the next header are the next table's). An edit is kept only if
the new text parses to the old manifest with exactly that source added or
removed.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tack import config, deploy, sources, sync
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
    ref: str | None = None,
    subdir: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> Result:
    """Add a git URL or a local directory as a source, then sync. Nothing is
    written unless the source is reachable and deploys cleanly."""
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
    if skills:
        fields["skills"] = list(dict.fromkeys(skills))

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
    """What makes a new source unfit to add."""
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


def _write(cfg: Config, file: Path, text: str, result: Result) -> None:
    result.changes.append(Change("write", tilde(file), path=file))
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
    lines = ["[[source]]"]
    for key, value in fields.items():
        if not isinstance(value, list):
            lines.append(f"{key} = {config.toml_str(value)}")
            continue
        items = [config.toml_str(v) for v in value]
        one = f"{key} = [{', '.join(items)}]"
        lines += [one] if len(one) <= 100 else [f"{key} = [", *(f"  {i}," for i in items), "]"]
    return "\n".join(lines) + "\n"


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

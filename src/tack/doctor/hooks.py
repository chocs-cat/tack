"""Hook checks: a hook registered for one harness should be registered, the
same way, for every harness.

Every hook file has the same shape once parsed -- Claude Code's
`settings.json` and Codex's `hooks.json` under a `hooks` key, Codex's
`config.toml` in `[[hooks.<Event>]]` tables:
`{event: [{matcher, hooks: [{type, command, ...}]}]}`.

Counterparts are found by *signature*: the command with every path reduced
to its file name, so the same script installed under each harness's own
directory still pairs up.
"""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from tack.config import Config
from tack.doctor.findings import Finding


class HookFileError(Exception):
    pass


@dataclass(frozen=True)
class Hook:
    event: str
    matcher: str
    command: str  # the command with its args, or a description of a non-command hook
    file: Path

    @property
    def signature(self) -> str:
        try:
            tokens = shlex.split(self.command)
        except ValueError:
            return self.command
        return " ".join(PurePosixPath(t).name if "/" in t else t for t in tokens)

    @property
    def alternatives(self) -> frozenset[str]:
        alts = {a.strip() for a in self.matcher.split("|")} - {""}
        return frozenset({"*"} if not alts or "*" in alts else alts)


def read(file: Path) -> list[Hook]:
    """The hooks registered in one file; none if it doesn't exist."""
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        raise HookFileError(str(e)) from e
    try:
        data = tomllib.loads(text) if file.suffix == ".toml" else json.loads(text)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError) as e:
        raise HookFileError(str(e)) from e
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return []
    out: list[Hook] = []
    for event, entries in hooks.items():
        if not isinstance(entries, list):  # e.g. Codex's [hooks.state]
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher", "")
            out.extend(
                Hook(event, str(matcher), _command(h), file)
                for h in entry.get("hooks", [])
                if isinstance(h, dict)
            )
    return out


def _command(h: dict[str, Any]) -> str:
    command, args = h.get("command"), h.get("args")
    if isinstance(command, str):
        if isinstance(args, list) and args:
            return shlex.join([command, *map(str, args)])
        return command
    rest = {k: v for k, v in h.items() if k not in ("timeout", "statusMessage")}
    return json.dumps(rest, sort_keys=True)


def _describe(hook: Hook) -> str:
    matcher = f" [{hook.matcher}]" if hook.matcher not in ("", "*") else ""
    return f"{hook.event}{matcher} `{hook.command}`"


def _read_all(
    files: dict[str, list[Path]], project: Path | None
) -> tuple[dict[str, list[Hook]], list[Finding]]:
    hooks: dict[str, list[Hook]] = {}
    errors: list[Finding] = []
    for name, paths in files.items():
        hooks[name] = []
        for f in paths:
            try:
                hooks[name].extend(read(f))
            except HookFileError as e:
                errors.append(
                    Finding(
                        "unreadable-file",
                        "error",
                        f"can't parse hook file: {e}",
                        path=f,
                        harness=name,
                        project=project,
                    )
                )
    return hooks, errors


def check_global(cfg: Config) -> Iterator[Finding]:
    files = {h.name: list(h.hooks) for h in cfg.harnesses.values()}
    hooks, errors = _read_all(files, None)
    yield from errors
    index: dict[tuple[str, str], dict[str, list[Hook]]] = defaultdict(lambda: defaultdict(list))
    for name, hs in hooks.items():
        for hook in hs:
            index[hook.event, hook.signature][name].append(hook)
    for by_harness in index.values():
        lacking = [n for n in cfg.harnesses if n not in by_harness]
        if not lacking:
            continue
        have = next(iter(by_harness))
        hook = by_harness[have][0]
        yield Finding(
            "hook-one-harness",
            "info",
            f"{_describe(hook)} is registered for {', '.join(by_harness)}, "
            f"not {', '.join(lacking)}",
            path=hook.file,
            harness=have,
        )


def check_project(cfg: Config, project: Path) -> Iterator[Finding]:
    files = {h.name: [project / f for f in h.project_hooks] for h in cfg.harnesses.values()}
    hooks, errors = _read_all(files, project)
    yield from errors

    # signature -> harness -> (event, command) -> matcher alternatives, merged
    index: dict[str, dict[str, dict[tuple[str, str], set[str]]]] = defaultdict(dict)
    first: dict[str, Hook] = {}
    for name, hs in hooks.items():
        for hook in hs:
            slot = index[hook.signature].setdefault(name, defaultdict(set))
            slot[hook.event, hook.command] |= hook.alternatives
            first.setdefault(hook.signature, hook)

    for sig, by_harness in index.items():
        hook = first[sig]
        lacking = [n for n in cfg.harnesses if n not in by_harness]
        if lacking:
            yield Finding(
                "hook-one-harness",
                "warn",
                f"{_describe(hook)} has no counterpart for {', '.join(lacking)}",
                path=hook.file,
                project=project,
                fix="hooks",
            )
            continue
        variants = {n: dict(v) for n, v in by_harness.items()}
        if len({_freeze(v) for v in variants.values()}) > 1:
            detail = "; ".join(f"{n}: {_summary(v)}" for n, v in variants.items())
            yield Finding(
                "hook-mismatch",
                "warn",
                f"counterpart hooks differ -- {detail}",
                path=hook.file,
                project=project,
                fix="hooks",
            )

    seen: set[tuple[Path, str]] = set()
    for hs in hooks.values():
        for hook in hs:
            if (hook.file, hook.command) not in seen and _hardcodes_home(hook.command):
                seen.add((hook.file, hook.command))
                yield Finding(
                    "hook-hardcoded-home",
                    "info",
                    f"{_describe(hook)} names a home directory; it breaks on another "
                    "machine or clone",
                    path=hook.file,
                    project=project,
                )


def _freeze(v: dict[tuple[str, str], set[str]]) -> frozenset:
    return frozenset((k, frozenset(alts)) for k, alts in v.items())


def _summary(v: dict[tuple[str, str], set[str]]) -> str:
    return ", ".join(
        f"{event} [{'|'.join(sorted(alts))}] `{command}`" for (event, command), alts in v.items()
    )


_HOME_PATH = re.compile(r"(?<![\w.$-])/(?:Users|home)/[^/\s'\"]+")


def _hardcodes_home(command: str) -> bool:
    home = str(Path.home())
    return (home != "/" and home in command) or bool(_HOME_PATH.search(command))

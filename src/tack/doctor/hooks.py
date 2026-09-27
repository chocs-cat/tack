"""Hook checks: a hook registered for one harness should be registered, the
same way, for every harness.

Every hook file has the same shape once parsed -- Claude Code's
`settings.json` and Codex's `hooks.json` under a `hooks` key, Codex's
`config.toml` in `[[hooks.<Event>]]` tables:
`{event: [{matcher, hooks: [{type, command, ...}]}]}`.

Counterparts are found by *signature*: the command with every path reduced
to its file name, so the same script installed under each harness's own
directory still pairs up. Counterparts then compare as `tack scaffold hooks`
writes them: `args` folded into the command, the project directory however
it is named, and `apply_patch` as the `Edit|Write` it stands for.
"""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from tack.config import Config
from tack.doctor.findings import Finding


class HookFileError(Exception):
    pass


# How each harness's hooks can name the project directory.
PROJECT_DIR = re.compile(r"\$\{CLAUDE_PROJECT_DIR\}|\$CLAUDE_PROJECT_DIR\b")
GIT_TOPLEVEL = "$(git rev-parse --show-toplevel)"
# Codex's edit tool, and the Claude Code tools its matcher aliases stand for.
APPLY_PATCH, EDIT_TOOLS = "apply_patch", ("Edit", "Write")


@dataclass(frozen=True)
class Hook:
    event: str
    matcher: str
    command: str  # the command with its args, or a description of a non-command hook
    file: Path
    spec: dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    @property
    def signature(self) -> str:
        try:
            tokens = shlex.split(self.command)
        except ValueError:
            return self.command
        return " ".join(PurePosixPath(t).name if "/" in t else t for t in tokens)

    @property
    def normalized(self) -> str:
        """The command as it compares with its counterparts."""
        try:
            tokens = shlex.split(self.command)
        except ValueError:
            return self.command
        project = [PROJECT_DIR.sub("$PROJECT", t).replace(GIT_TOPLEVEL, "$PROJECT") for t in tokens]
        return shlex.join(project)

    @property
    def alternatives(self) -> frozenset[str]:
        alts = {a.strip() for a in self.matcher.split("|")} - {""}
        if APPLY_PATCH in alts:
            alts = (alts - {APPLY_PATCH}) | set(EDIT_TOOLS)
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
                Hook(event, str(matcher), command_of(h), file, h)
                for h in entry.get("hooks", [])
                if isinstance(h, dict)
            )
    return out


def command_of(h: dict[str, Any]) -> str:
    """A hook's command with its args, or a description of a non-command hook."""
    command, args = h.get("command"), h.get("args")
    if isinstance(command, str):
        if isinstance(args, list) and args:
            return shlex.join([command, *map(str, args)])
        return command
    rest = {k: v for k, v in h.items() if k not in ("timeout", "statusMessage")}
    return json.dumps(rest, sort_keys=True)


def describe(hook: Hook) -> str:
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
            f"{describe(hook)} is registered for {', '.join(by_harness)}, not {', '.join(lacking)}",
            path=hook.file,
            harness=have,
        )


def check_project(cfg: Config, project: Path) -> Iterator[Finding]:
    files = {h.name: [project / f for f in h.project_hooks] for h in cfg.harnesses.values()}
    hooks, errors = _read_all(files, project)
    yield from errors

    # signature -> harness -> its hooks with that signature
    index: dict[str, dict[str, list[Hook]]] = defaultdict(dict)
    for name, hs in hooks.items():
        for hook in hs:
            index[hook.signature].setdefault(name, []).append(hook)

    for by_harness in index.values():
        hook = next(iter(by_harness.values()))[0]
        lacking = [n for n in cfg.harnesses if n not in by_harness]
        if lacking:
            yield Finding(
                "hook-one-harness",
                "warn",
                f"{describe(hook)} has no counterpart for {', '.join(lacking)}",
                path=hook.file,
                project=project,
                fix="hooks",
            )
            continue
        if len({variant(hs) for hs in by_harness.values()}) > 1:
            detail = "; ".join(f"{n}: {_summary(hs)}" for n, hs in by_harness.items())
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
                    f"{describe(hook)} names a home directory; it breaks on another "
                    "machine or clone",
                    path=hook.file,
                    project=project,
                )


def variant(hooks: list[Hook]) -> frozenset[tuple[str, str, frozenset[str]]]:
    """One harness's registrations of a hook, as they compare with another's:
    each event and command with its matchers' alternatives merged."""
    merged: dict[tuple[str, str], set[str]] = defaultdict(set)
    for h in hooks:
        merged[h.event, h.normalized] |= h.alternatives
    return frozenset((e, c, frozenset(alts)) for (e, c), alts in merged.items())


def _summary(hooks: list[Hook]) -> str:
    merged: dict[tuple[str, str], set[str]] = {}
    for h in hooks:
        merged.setdefault((h.event, h.command), set()).update(h.alternatives)
    return ", ".join(
        f"{event} [{'|'.join(sorted(alts))}] `{command}`"
        for (event, command), alts in merged.items()
    )


_HOME_PATH = re.compile(r"(?<![\w.$-])/(?:Users|home)/[^/\s'\"]+")


def _hardcodes_home(command: str) -> bool:
    home = str(Path.home())
    return (home != "/" and home in command) or bool(_HOME_PATH.search(command))

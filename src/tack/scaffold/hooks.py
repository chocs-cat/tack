"""The `hooks` fix: every harness registers each project hook, the same way.

A hook one harness has and another lacks is copied into the other's JSON hook
file. When both have it but differ, `--from` names the harness whose version
replaces the rest. A copy translates what has an exact equivalent -- `args`
folded into one command string for Codex, `$CLAUDE_PROJECT_DIR` (which Codex
doesn't set) as `$(git rev-parse --show-toplevel)`, Codex's `apply_patch`
matcher as `Edit|Write` -- and warns about what doesn't carry over.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

from tack.config import Config
from tack.doctor.hooks import (
    APPLY_PATCH,
    EDIT_TOOLS,
    GIT_TOPLEVEL,
    PROJECT_DIR,
    Hook,
    HookFileError,
    command_of,
    describe,
    read,
    variant,
)
from tack.scaffold.writer import Refusal, Writer

# What tack knows of each built-in harness's hooks.
TAKES_ARGS = {"claude-code"}  # a command hook can have `args`
SETS_PROJECT_DIR = {"claude-code"}  # hooks see $CLAUDE_PROJECT_DIR
CODEX_TOOLS = {"Bash", APPLY_PATCH, *EDIT_TOOLS}
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PermissionRequest"}
COPIED = ("type", "command", "timeout", "statusMessage")
_SEES_EDITS = {"", "*", APPLY_PATCH, "MultiEdit", *EDIT_TOOLS}
_READS_PAYLOAD = re.compile(r"tool_input|file_path")


def fix(cfg: Config, w: Writer, source: str | None) -> None:
    names = list(cfg.harnesses)
    found: dict[str, list[Hook]] = {}
    for h in cfg.harnesses.values():
        found[h.name] = []
        for f in h.project_hooks:
            try:
                found[h.name] += read(w.project / f)
            except HookFileError as e:
                raise Refusal(f"can't parse {f}: {e}") from e
    by_sig: dict[str, dict[str, list[Hook]]] = {}
    for name in names:
        for hook in found[name]:
            by_sig.setdefault(hook.signature, {}).setdefault(name, []).append(hook)

    # (the hooks to copy, from, to, whether they replace the target's own)
    plan: list[tuple[list[Hook], str, str, bool]] = []
    differ: list[str] = []
    for by in by_sig.values():
        present = [n for n in names if n in by]
        src = present[0]
        if len({variant(by[n]) for n in present}) > 1:
            if source not in by:
                differ.append("; ".join(f"{n}: {', '.join(map(describe, by[n]))}" for n in by))
                continue
            src = source
            for n in present:
                if n != src:
                    if toml := [h for h in by[n] if h.file.suffix != ".json"]:
                        raise Refusal(
                            f"{describe(toml[0])} would have to change in "
                            f"{toml[0].file.relative_to(w.project)}, which tack doesn't edit; "
                            "change it by hand"
                        )
                    plan.append((by[src], src, n, True))
        plan += [(by[src], src, n, False) for n in names if n not in by]
    if differ:
        raise Refusal(
            "counterpart hooks differ -- " + " | ".join(differ) + "; `--from HARNESS` says whose "
            "version to keep"
        )

    docs: dict[str, dict[str, Any]] = {}  # each hook file to write, parsed
    owners: dict[str, str] = {}  # and its harness
    for hooks, src, dst, replace in plan:
        target = next((f for f in cfg.harnesses[dst].project_hooks if f.endswith(".json")), None)
        if target is None:
            raise Refusal(f"{dst} has no JSON hook file for tack to write")
        doc = docs.get(target)
        if doc is None:
            doc, owners[target] = docs.setdefault(target, _load(w, target)), dst
        if replace:
            _drop(doc, hooks[0].signature, w.project / target)
        for hook in hooks:
            if (copied := _translate(hook, src, dst, w)) is not None:
                _add(doc, hook.event, *copied)

    for target, doc in docs.items():
        w.write(target, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        if owners[target] == "codex":
            w.note("Codex asks you to trust new or changed hooks: run /hooks in Codex here")


def _load(w: Writer, rel: str) -> dict[str, Any]:
    text = w.read(rel)
    doc = json.loads(text) if text and text.strip() else {}
    if not isinstance(doc, dict) or not isinstance(doc.setdefault("hooks", {}), dict):
        raise Refusal(f"{rel} isn't a JSON object with a `hooks` object")
    return doc


def _entries(doc: dict[str, Any], event: str) -> list[Any]:
    entries = doc["hooks"].setdefault(event, [])
    if not isinstance(entries, list):
        raise Refusal(f"hooks.{event} isn't a list")
    return entries


def _drop(doc: dict[str, Any], signature: str, file: Path) -> None:
    """Remove the registrations of a hook from a hook file's parsed JSON."""
    for event, entries in list(doc["hooks"].items()):
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
                matcher = str(entry.get("matcher", ""))
                entry["hooks"] = [
                    h
                    for h in entry["hooks"]
                    if not isinstance(h, dict)
                    or Hook(event, matcher, command_of(h), file).signature != signature
                ]
        entries[:] = [e for e in entries if not (isinstance(e, dict) and e.get("hooks") == [])]
        if not entries:
            del doc["hooks"][event]


def _add(doc: dict[str, Any], event: str, matcher: str, spec: dict[str, Any]) -> None:
    """Register a hook, beside others with the same matcher if there are some."""
    entries = _entries(doc, event)
    for entry in entries:
        if (
            isinstance(entry, dict)
            and str(entry.get("matcher", "")) == matcher
            and isinstance(entry.get("hooks"), list)
        ):
            entry["hooks"].append(spec)
            return
    entries.append({"matcher": matcher, "hooks": [spec]} if matcher else {"hooks": [spec]})


def _translate(hook: Hook, src: str, dst: str, w: Writer) -> tuple[str, dict[str, Any]] | None:
    """The matcher and hook to register for `dst`; None if it can't be copied."""
    spec = hook.spec
    where = f"{src}'s {describe(hook)}"
    command, args = spec.get("command"), spec.get("args")
    if spec.get("type", "command") != "command" or not isinstance(command, str):
        w.note(f"{where} isn't a command hook, so tack can't copy it to {dst}")
        return None
    if isinstance(args, list) and args and dst not in TAKES_ARGS:
        command, args = " ".join(_word(str(a), dst) for a in [command, *args]), None
    elif dst not in SETS_PROJECT_DIR:
        command = PROJECT_DIR.sub(GIT_TOPLEVEL, command)
    new: dict[str, Any] = {"type": "command", "command": command}
    if isinstance(args, list) and args:
        new["args"] = args
    new.update({k: spec[k] for k in COPIED[2:] if k in spec})
    if left := [k for k in spec if k not in (*COPIED, "args")]:
        w.note(f"{where}: its {', '.join(left)} isn't copied to {dst}")

    alts = [a.strip() for a in hook.matcher.split("|")]
    if dst == "claude-code" and APPLY_PATCH in alts:
        alts = list(
            dict.fromkeys(t for a in alts for t in (EDIT_TOOLS if a == APPLY_PATCH else [a]))
        )
    matcher = "|".join(alts) if hook.matcher.strip() else hook.matcher
    if hook.event in TOOL_EVENTS:
        if dst == "codex":
            lacking = [
                a for a in alts if a not in CODEX_TOOLS and a not in ("", "*")
                and not a.startswith("mcp__")
            ]  # fmt: skip
            if lacking:
                w.note(
                    f"{where}: Codex has no {', '.join(lacking)} tool, so that part of the "
                    "matcher never fires there"
                )
        if any(a in _SEES_EDITS for a in alts) and _reads_payload(command, w.project):
            w.note(
                f"{where} reads the tool payload, and the harnesses describe edits "
                "differently (Claude Code sends file_path, Codex a patch in tool_input.command); "
                f"check that it works for {dst}"
            )
    return matcher, new


def _word(arg: str, dst: str) -> str:
    """One `args` entry as a shell word, with the project directory as `dst` sees it."""
    if dst in SETS_PROJECT_DIR:
        return shlex.quote(arg)
    pieces = PROJECT_DIR.split(arg)
    return f'"{GIT_TOPLEVEL}"'.join(shlex.quote(p) if p else "" for p in pieces)


def _reads_payload(command: str, project: Path) -> bool:
    """Whether a command, or a script in the project it runs, mentions the payload."""
    if _READS_PAYLOAD.search(command):
        return True
    here = PROJECT_DIR.sub(str(project), command).replace(GIT_TOPLEVEL, str(project))
    try:
        tokens = shlex.split(here)
    except ValueError:
        return False
    for t in tokens:
        p = Path(t) if Path(t).is_absolute() else project / t
        try:
            inside = p.resolve().is_relative_to(project.resolve()) and p.is_file()
            if inside and _READS_PAYLOAD.search(p.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False

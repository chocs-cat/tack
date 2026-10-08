"""Helpers for text meant for people."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tack.outdated import ChangedPlugin, SourceReport
    from tack.sync import Result


def tilde(path: Path | str) -> str:
    """`path` with the home directory shown as `~`."""
    p, home = str(path), str(Path.home())
    if home != "/" and (p == home or p.startswith(home + os.sep)):
        return "~" + p[len(home) :]
    return p


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# What each change a command makes is called, before and after it happens.
VERBS = {
    "pin": ("pin", "pinned"),
    "update": ("update", "updated"),
    "clone": ("clone", "cloned"),
    "checkout": ("check out", "checked out"),
    "write": ("write", "wrote"),
    "link": ("link", "linked"),
    "relink": ("relink", "relinked"),
    "unlink": ("remove", "removed"),
    "adopt": ("adopt", "adopted"),
    "delete": ("delete", "deleted"),
    "commit": ("commit", "committed"),
    "push": ("push", "pushed"),
    "move": ("move", "moved"),
    "copy": ("copy", "copied"),
    # An agent's plugin command: its detail is the command line.
    "register": ("run", "ran"),
    "install": ("run", "ran"),
    "reinstall": ("run", "ran"),
    "uninstall": ("run", "ran"),
    "unregister": ("run", "ran"),
}


# What a source's state means, for people.
SOURCE_STATES = {
    "missing": "its skills directory isn't there",
    "not pinned": "not pinned yet; `tack sync` pins it",
    "manifest changed": "the manifest's git or ref changed since it was pinned; "
    "`tack update {name}` re-pins it",
    "not checked out": "not checked out; `tack sync` fetches it",
    "local changes": "tack's checkout has local changes",
    "off its pin": "checked out away from its pin; `tack sync` fixes it",
}


def upstream_changes(s: SourceReport, selects_plugins: bool) -> list[str]:
    """A source behind upstream: its changed skills and plugins, a line per
    kind of change, its `plugins_error`, or that nothing it selects changed,
    as `outdated`'s text gives them and the TUI's Sources detail too
    (design.md *Tracking plugins upstream*). `selects_plugins`: whether the
    source's `plugins` isn't `[]`."""
    changes = ("modified", "added", "removed")
    skills = {c: [k.name for k in s.skills if k.change == c] for c in changes}
    plugins = {c: [changed_plugin(p) for p in s.plugins if p.change == c] for c in changes}
    lines = [f"{c}: {', '.join(names)}" for c, names in skills.items() if names]
    lines += [f"plugins {c}: {', '.join(names)}" for c, names in plugins.items() if names]
    if s.plugins_error:
        lines.append(s.plugins_error)
    if not s.skills and not s.plugins:
        compared = selects_plugins and not s.plugins_error
        lines.append(f"no selected skill {'or plugin ' if compared else ''}changed")
    return lines


def changed_plugin(p: ChangedPlugin) -> str:
    """A changed plugin and its versions (design.md *Tracking plugins
    upstream*): both for a modified one, a single one when they are equal;
    the tip's for an added one, the pin's for a removed one."""
    was, now = p.version["from"], p.version["to"]
    if p.change == "modified" and (was or now):
        shown = was if was == now else f"{was or 'none'} -> {now or 'none'}"
    else:
        shown = now if p.change == "added" else was if p.change == "removed" else None
    return f"{p.name} ({shown})" if shown else p.name


def source_note(state: str, name: str, root: Path) -> str:
    """What a source's state means, for people. A `missing` source says
    whether its directory is gone or only its skills directory, as `doctor`
    does (#40)."""
    if state == "missing" and not root.is_dir():
        return "its directory isn't there"
    return SOURCE_STATES[state].format(name=name)


def result_text(result: Result, idle: str) -> str:
    """A changing command's result: each change (with its diff, in a dry run),
    note and problem, then a summary; `idle` when there were no changes."""
    rows = [(c.harness or c.source or "", c) for c in result.changes]
    width = max((len(label) for label, _ in rows), default=0)
    lines = []
    for label, c in rows:
        present, past = VERBS[c.action]
        verb = f"would {present}" if result.dry_run else past
        lines.append(f"{label:<{width}}  {verb} {c.detail}" if width else f"{verb} {c.detail}")
        if result.dry_run and c.diff:
            lines += c.diff.rstrip("\n").splitlines()
    lines += [f"note: {n.source + ': ' if n.source else ''}{n.message}" for n in result.notes]
    for p in result.problems:
        label = " ".join(x for x in (p.source, p.harness) if x)
        lines.append(f"{p.kind}: {label + ': ' if label else ''}{p.message}")
    n = len(result.changes)
    if not n:
        summary = idle
    else:
        summary = f"would make {plural(n, 'change')}" if result.dry_run else plural(n, "change")
    if result.problems:
        summary += f", {plural(len(result.problems), 'problem')}"
    return "\n".join([*lines, *([""] if lines else []), summary])

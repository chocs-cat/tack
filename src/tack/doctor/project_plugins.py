"""Project plugin settings: a plugin a project turns on or off should be
turned on or off, the same way, for every harness.

Claude Code reads `enabledPlugins` from the project's `.claude/settings.json`,
and Codex reads `enabled` from each `[plugins."<key>"]` table of its
`.codex/config.toml`. A plugin matches across the two by its name, the key up
to its first `@`, since the agents' names for one marketplace can differ
(DEC-26). design.md's *`doctor` checks* (*Per project*, **Plugins**) has the
rule; there is no `scaffold` fix (DEC-26).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from tack.config import Config
from tack.doctor import hooks
from tack.doctor.findings import Finding

# The files compared, whatever the harnesses' `project_hooks` say (DEC-8);
# `.claude/settings.local.json` is one machine's and isn't read.
CLAUDE_SETTINGS = ".claude/settings.json"
CODEX_CONFIG = ".codex/config.toml"
FILES = {"claude-code": CLAUDE_SETTINGS, "codex": CODEX_CONFIG}

Setting = Literal["on", "off", "unset"]
RANK: dict[Setting, int] = {"unset": 0, "off": 1, "on": 2}


@dataclass(frozen=True)
class Entry:
    """The entry a plugin's setting in one file was read from."""

    key: str
    value: bool

    @property
    def setting(self) -> Setting:
        return "on" if self.value else "off"


def entries(harness: str, data: Any) -> Iterator[tuple[str, bool]]:
    """Each `(key, value)` a parsed file sets, in file order; anything that
    isn't a boolean setting in the shape its agent reads sets nothing."""
    if not isinstance(data, dict):
        return
    if harness == "claude-code":
        enabled = data.get("enabledPlugins")
        if isinstance(enabled, dict):
            yield from ((k, v) for k, v in enabled.items() if isinstance(v, bool))
        return
    plugins = data.get("plugins")
    if isinstance(plugins, dict):
        for key, table in plugins.items():
            if isinstance(table, dict) and isinstance(v := table.get("enabled"), bool):
                yield key, v


def settings(harness: str, data: Any) -> dict[str, Entry]:
    """Each plugin name's deciding entry: the first `true` for it, else its
    first `false`. A name with neither is unset and absent here."""
    out: dict[str, Entry] = {}
    for key, value in entries(harness, data):
        name = key.partition("@")[0]
        if name not in out or (value and not out[name].value):
            out[name] = Entry(key, value)
    return out


def _hint(harness: str, name: str, value: bool) -> str:
    v = "true" if value else "false"
    if harness == "claude-code":
        return f'`"enabledPlugins": {{"{name}@<marketplace>": {v}}}`'
    return f'`[plugins."{name}@<marketplace>"] enabled = {v}`'


def check(cfg: Config, project: Path) -> Iterator[Finding]:
    listed = {project / f for h in cfg.harnesses.values() for f in h.project_hooks}
    parsed: dict[str, Any] = {}
    unreadable = False
    for harness, rel in FILES.items():
        path = project / rel
        try:
            parsed[harness] = hooks.parse(path)
        except hooks.HookFileError as e:
            unreadable = True
            if path not in listed:  # else the hooks check reports it
                yield Finding(
                    "unreadable-file",
                    "error",
                    f"can't parse plugin settings file: {e}",
                    path=path,
                    harness=harness,
                    project=project,
                )
    if unreadable:  # one side's settings are unknown
        return

    found = {h: settings(h, data) for h, data in parsed.items()}
    for name in sorted(found["claude-code"].keys() | found["codex"].keys()):
        by = {h: found[h].get(name) for h in FILES}
        rank = {h: RANK[e.setting] if e else 0 for h, e in by.items()}
        if rank["claude-code"] == rank["codex"]:
            continue
        h, other = sorted(FILES, key=lambda n: rank[n], reverse=True)
        entry, against = by[h], by[other]
        assert entry is not None  # it outranks the other side
        value = "true" if entry.value else "false"
        yield Finding(
            "plugin-one-harness",
            "warn",
            f"plugin {name!r} is {entry.setting} for {h} (`{entry.key} = {value}` in "
            f"{FILES[h]}) and {against.setting if against else 'unset'} for {other}; "
            f"add {_hint(other, name, entry.value)} to {FILES[other]}",
            path=project / FILES[h],
            harness=h,
            project=project,
        )

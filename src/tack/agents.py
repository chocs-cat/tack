"""The agents' plugin CLIs: `claude plugin …` and `codex plugin …`.

Only the built-in harnesses take plugins (DEC-8). tack never edits an
agent's files (principle 5): it reads what each agent has, and registers,
installs and uninstalls, only through that agent's own CLI, found on PATH,
with `--json` and stdin closed, run in tack's data directory (or an empty
temporary one when that doesn't exist yet) so that no project's plugin
settings apply. It never enables or disables a plugin (DEC-5).

design.md *Harness facts tack relies on* records what each command prints.
A command fails when it exits non-zero or doesn't print the JSON it should;
the agent's message is Claude Code's `message`, else the last line either
agent wrote to stderr (without Codex's `Error: ` prefix). A CLI that isn't on
PATH is an outcome of its own, which `sync` reports as an `agent` problem.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from tack import deploy, plugins
from tack.config import Paths

# The harnesses that take plugins, and their CLIs (DEC-8): config.PLUGIN_HARNESSES.
CLIS = {"claude-code": "claude", "codex": "codex"}
# How each agent says a marketplace is a local directory.
_LOCAL = {"claude-code": "directory", "codex": "local"}

Kind = Literal["list", "marketplace-list", "register", "install", "uninstall", "unregister"]


def available(harness: str) -> bool:
    """Whether the harness's CLI is on PATH."""
    return shutil.which(CLIS[harness]) is not None


# --- commands ---------------------------------------------------------------------


@dataclass(frozen=True)
class Command:
    harness: str
    kind: Kind
    args: tuple[str, ...]  # the whole command line, the CLI first

    def __str__(self) -> str:
        return shlex.join(self.args)


def _command(harness: str, kind: Kind, *args: str) -> Command:
    return Command(harness, kind, (CLIS[harness], "plugin", *args, "--json"))


def _user(harness: str) -> tuple[str, ...]:
    return ("--scope", "user") if harness == "claude-code" else ()


def list_plugins(harness: str) -> Command:
    return _command(harness, "list", "list")


def list_marketplaces(harness: str) -> Command:
    return _command(harness, "marketplace-list", "marketplace", "list")


def register(harness: str, directory: Path) -> Command:
    """Register tack's marketplace at `directory`; again is a no-op."""
    return _command(harness, "register", "marketplace", "add", str(directory), *_user(harness))


def install(harness: str, name: str) -> Command:
    """Install `<name>@tack`; in Codex, again reinstalls it."""
    verb = "install" if harness == "claude-code" else "add"
    return _command(harness, "install", verb, f"{name}@{plugins.NAME}", *_user(harness))


def uninstall(harness: str, name: str) -> Command:
    verb = "uninstall" if harness == "claude-code" else "remove"
    return _command(harness, "uninstall", verb, f"{name}@{plugins.NAME}", *_user(harness))


def unregister(harness: str) -> Command:
    """Remove tack's marketplace: Claude Code uninstalls its plugins too, Codex doesn't."""
    args = ("marketplace", "remove", plugins.NAME, *_user(harness))
    return _command(harness, "unregister", *args)


# --- running them -------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    command: Command
    output: Any = None  # the JSON it printed, decoded, when it succeeded
    error: str | None = None  # why it failed: the agent's message, or tack's
    missing: bool = False  # the CLI isn't on PATH

    @property
    def ok(self) -> bool:
        return self.error is None


def run(command: Command, paths: Paths) -> Outcome:
    cli = command.args[0]
    with _workdir(paths) as cwd:
        try:
            r = subprocess.run(
                command.args,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError:
            return Outcome(command, error=f"`{cli}` isn't on PATH", missing=True)
        except OSError as e:
            return Outcome(command, error=f"can't run `{cli}`: {e.strerror or e}")
    try:
        output = json.loads(r.stdout)
    except ValueError:
        output = None
    claude = command.harness == "claude-code"
    failed = claude and isinstance(output, dict) and output.get("outcome") == "failed"
    if r.returncode != 0 or failed:
        said = output.get("message") if claude and isinstance(output, dict) else None
        message = said if isinstance(said, str) and said else _stderr(command, r.stderr)
        return Outcome(command, error=message or f"`{command}` exited {r.returncode}")
    if command.kind in ("list", "marketplace-list"):
        well_formed = output is not None
    elif claude:
        well_formed = isinstance(output, dict) and output.get("outcome") == "ok"
    else:
        well_formed = isinstance(output, dict)
    if not well_formed:
        return Outcome(command, error=_garbled(command, r.stderr))
    return Outcome(command, output=output)


@contextmanager
def _workdir(paths: Paths) -> Iterator[Path]:
    """tack's data directory, or an empty temporary one; never created here."""
    if paths.data_dir.is_dir():
        yield paths.data_dir
        return
    with tempfile.TemporaryDirectory(prefix="tack-") as tmp:
        yield Path(tmp)


def _stderr(command: Command, stderr: str) -> str | None:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1]
    return last.removeprefix("Error: ") if command.harness == "codex" else last


def _garbled(command: Command, stderr: str) -> str:
    said = _stderr(command, stderr)
    return f"`{command}` didn't print the JSON tack reads" + (f": {said}" if said else "")


# --- what each agent has --------------------------------------------------------------


@dataclass(frozen=True)
class Installed:
    name: str
    marketplace: str
    enabled: bool
    scope: str  # Claude Code's `user`, `project`, `local` or `synced`; Codex's are `user`

    @property
    def id(self) -> str:
        return f"{self.name}@{self.marketplace}"


@dataclass(frozen=True)
class Marketplace:
    name: str
    kind: str  # Claude Code's `source` (`directory`, `github`, …), Codex's `sourceType`
    location: str | None  # its directory or URL, as the agent gives it


@dataclass(frozen=True)
class Inventory:
    plugins: tuple[Installed, ...]
    marketplaces: tuple[Marketplace, ...]

    def marketplace(self, name: str) -> Marketplace | None:
        return next((m for m in self.marketplaces if m.name == name), None)


def is_tack(harness: str, m: Marketplace, paths: Paths) -> bool:
    """Whether `m` is tack's marketplace: named `tack`, a local directory, and
    at tack's marketplace directory. Any other `tack` is a conflict."""
    return (
        m.name == plugins.NAME
        and m.kind == _LOCAL[harness]
        and m.location is not None
        and deploy.same_path(Path(m.location), paths.marketplace_dir)
    )


def tack_plugins(harness: str, inv: Inventory) -> dict[str, bool]:
    """The plugins the harness has from tack's marketplace, enabled or not
    (DEC-5): name -> enabled. Claude Code's only at user scope, where tack
    installs them. `sync`'s step 2 and `status` both read installs here."""
    return {
        p.name: p.enabled
        for p in inv.plugins
        if p.marketplace == plugins.NAME and (harness != "claude-code" or p.scope == "user")
    }


def inventory(harness: str, paths: Paths) -> Inventory | Outcome:
    """What the harness has installed and registered, from its `plugin list`
    and `plugin marketplace list`; or the outcome of the one that failed.

    Codex's list leaves out a plugin whose marketplace or catalog entry is
    gone, though it is still installed.
    """
    found: list[Any] = []
    for command, read in (
        (list_plugins(harness), _plugins),
        (list_marketplaces(harness), _marketplaces),
    ):
        out = run(command, paths)
        if not out.ok:
            return out
        try:
            found.append(read(harness, out.output))
        except (KeyError, TypeError, ValueError):
            return Outcome(command, error=_garbled(command, ""))
    return Inventory(*found)


def _plugins(harness: str, output: Any) -> tuple[Installed, ...]:
    out: list[Installed] = []
    if harness == "claude-code":
        for p in _list(output):
            name, at, market = _str(p["id"]).rpartition("@")
            if not at or not name:
                raise ValueError(p["id"])
            out.append(Installed(name, market, _bool(p["enabled"]), _str(p["scope"])))
    else:
        for p in _list(_dict(output)["installed"]):
            name, market = _str(p["name"]), _str(p["marketplaceName"])
            out.append(Installed(name, market, _bool(p["enabled"]), "user"))
    return tuple(out)


def _marketplaces(harness: str, output: Any) -> tuple[Marketplace, ...]:
    out: list[Marketplace] = []
    if harness == "claude-code":
        for m in _list(output):
            where = next((m[k] for k in ("path", "repo", "url") if isinstance(m.get(k), str)), None)
            out.append(Marketplace(_str(m["name"]), _str(m["source"]), where))
    else:
        for m in _list(_dict(output)["marketplaces"]):
            source = _dict(m["marketplaceSource"])
            where = source.get("source")
            out.append(
                Marketplace(
                    _str(m["name"]),
                    _str(source["sourceType"]),
                    where if isinstance(where, str) else None,
                )
            )
    return tuple(out)


def _list(v: Any) -> list[dict[str, Any]]:
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise TypeError(v)
    return v


def _dict(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise TypeError(v)
    return v


def _str(v: Any) -> str:
    if not isinstance(v, str) or not v:
        raise TypeError(v)
    return v


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise TypeError(v)
    return v

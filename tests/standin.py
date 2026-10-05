"""Stand-ins for the `claude` and `codex` CLIs, which no test may run.

`tests/conftest.py` writes two executables, `claude` and `codex`, first on
PATH; both run this script, which answers their `plugin … --json` commands
as design.md *Harness facts tack relies on* (the *(P0001)* parts) describes.
It keeps what each agent has registered and installed in `state.json`, and
appends every call to `calls.jsonl`, both in the directory the environment
variable STANDIN_AGENTS_DIR names. Only this script reads that variable:
tack doesn't know it is under test.

The quirks it copies, each pinned by a test in `tests/test_agents.py`:
Claude Code fails with a JSON object on stdout (and `✘ …` on stderr), Codex
with `Error: …` on stderr and nothing on stdout; registering a marketplace
again succeeds; installing an installed plugin succeeds; installing a plugin
the marketplace's catalog lacks fails; Claude Code's `uninstall` of a plugin
that isn't installed fails, `codex plugin remove` always succeeds; Claude
Code's `marketplace remove` uninstalls the marketplace's plugins, Codex's
doesn't; removing an unregistered marketplace fails in both; Codex's
`plugin list` hides a plugin whose marketplace isn't registered or whose
catalog lacks it, where Claude Code's lists it; and only Claude Code's
commands take `--scope`.

Outside pytest: `python tests/standin.py bin <dir>` writes the two
executables into `<dir>`; set STANDIN_AGENTS_DIR and put `<dir>` first on
PATH (or pass them to `tools/agent_facts.py` as `--claude` and `--codex`).

This file is also imported by the tests, for `Standins`, the helpers that
seed the state, script an answer, take a stand-in away and read the log.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV = "STANDIN_AGENTS_DIR"
CLIS = ("claude", "codex")
STATE = "state.json"
CALLS = "calls.jsonl"
VERSIONS = {"claude": "2.1.289 (Claude Code; stand-in)", "codex": "codex-cli 0.157.1 (stand-in)"}

# Where each agent looks for a directory marketplace's catalog, in order.
CATALOGS = {
    "claude": (".claude-plugin/marketplace.json",),
    "codex": (".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"),
}


# --- the executables and PATH ---------------------------------------------------


def write_bin(bin_dir: Path) -> None:
    """Write the `claude` and `codex` stand-ins into `bin_dir`, to put first on PATH."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    python, script = shlex.quote(sys.executable), shlex.quote(str(Path(__file__).resolve()))
    for cli in CLIS:
        exe = bin_dir / cli
        exe.write_text(f'#!/bin/sh\nexec {python} {script} {cli} "$@"\n')
        exe.chmod(0o755)


def isolate(path: str, root: Path) -> str:
    """`path` with every directory holding a `claude` or a `codex` replaced by
    a mirror of it under `root` without them: a link to each of its other
    entries. No real agent can be found, and everything else resolves as it
    did, in the same order: `git`, and what a version manager's shim looks
    for further down PATH (DEC-9). The stand-ins' directory goes first."""
    out: list[str] = []
    mirrors: dict[str, Path] = {}
    for d in path.split(os.pathsep) if path else []:
        where = Path(d or ".").absolute()
        if not any(os.path.lexists(where / c) for c in CLIS):
            out.append(d)
            continue
        mirror = mirrors.get(str(where))
        if mirror is None:
            mirror = mirrors[str(where)] = root / str(len(mirrors))
            mirror.mkdir(parents=True)
            with os.scandir(where) as it:
                for e in it:
                    if e.name not in CLIS:
                        (mirror / e.name).symlink_to(where / e.name)
        out.append(str(mirror))
    return os.pathsep.join(out)


# --- helpers for tests ------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    cli: str
    args: list[str]
    cwd: str
    stdin_devnull: bool


class Standins:
    """The stand-ins of one test: their state, their log, their executables."""

    def __init__(self, directory: Path, bin_dir: Path) -> None:
        self.directory, self.bin_dir = directory, bin_dir

    def state(self) -> dict[str, Any]:
        return _load(self.directory)

    def _change(self, cli: str, key: str, name: str, value: dict[str, Any]) -> None:
        state = _load(self.directory)
        state[cli][key][name] = value
        _save(self.directory, state)

    def marketplace(
        self,
        cli: str,
        name: str,
        location: Path | str,
        *,
        kind: str | None = None,
        plugins: list[str] | None = None,
    ) -> None:
        """Register a marketplace as if by hand: a local directory by default
        (whose catalog the stand-in reads), or `kind` ("github", "git", …)
        offering `plugins`."""
        local = "directory" if cli == "claude" else "local"
        value: dict[str, Any] = {"kind": kind or local, "location": str(location)}
        if plugins is not None:
            value["plugins"] = plugins
        self._change(cli, "marketplaces", name, value)

    def plugin(
        self, cli: str, plugin_id: str, *, enabled: bool = True, scope: str = "user"
    ) -> None:
        """Install a plugin as if by hand (Codex's are all `user`)."""
        self._change(cli, "plugins", plugin_id, {"enabled": enabled, "scope": scope})

    def answer(
        self, cli: str, args: list[str], *, stdout: str = "", stderr: str = "", code: int = 0
    ) -> None:
        """Answer every call whose arguments (`--json` aside) start with `args`
        with this output instead."""
        state = _load(self.directory)
        state["answers"].append(
            {"cli": cli, "args": args, "stdout": stdout, "stderr": stderr, "code": code}
        )
        _save(self.directory, state)

    def fail(self, cli: str, args: list[str], message: str) -> None:
        """Make the command `args` fail with `message`, as that agent fails."""
        if cli == "claude":
            out = {"outcome": "failed", "message": message, "failureCode": "scripted"}
            self.answer(cli, args, stdout=json.dumps(out), stderr=f"✘ {message}\n", code=1)
        else:
            self.answer(cli, args, stderr=f"Error: {message}\n", code=1)

    def remove(self, cli: str) -> None:
        """Take a stand-in away: it is no longer on PATH."""
        (self.bin_dir / cli).unlink()

    def calls(self, cli: str | None = None) -> list[Call]:
        try:
            lines = (self.directory / CALLS).read_text().splitlines()
        except FileNotFoundError:
            return []
        calls = [Call(**json.loads(line)) for line in lines]
        return [c for c in calls if cli is None or c.cli == cli]


def _load(directory: Path) -> dict[str, Any]:
    try:
        return json.loads((directory / STATE).read_text())
    except FileNotFoundError:
        return {cli: {"marketplaces": {}, "plugins": {}} for cli in CLIS} | {"answers": []}


def _save(directory: Path, state: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / STATE).write_text(json.dumps(state, indent=2) + "\n")


# --- the stand-in itself -----------------------------------------------------------


class Failed(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message, self.code = message, code


class Agent:
    """One run of a stand-in: `cli` with its state."""

    def __init__(self, cli: str, state: dict[str, Any]) -> None:
        self.cli = cli
        self.mine: dict[str, Any] = state[cli]
        self.marketplaces: dict[str, dict[str, Any]] = self.mine["marketplaces"]
        self.plugins: dict[str, dict[str, Any]] = self.mine["plugins"]

    def catalog(self, name: str) -> dict[str, dict[str, Any]] | None:
        """The plugins a registered marketplace's catalog lists now, by name."""
        m = self.marketplaces.get(name)
        if m is None:
            return None
        if "plugins" in m:
            return {p: {"name": p} for p in m["plugins"]}
        if m["kind"] not in ("directory", "local"):
            return {}
        data = _catalog(self.cli, Path(m["location"]))
        if data is None:
            return {}
        return {p["name"]: p for p in data["plugins"] if isinstance(p, dict) and "name" in p}

    def version(self, plugin_id: str) -> str:
        name, market = plugin_id.rsplit("@", 1)
        entry = (self.catalog(market) or {}).get(name, {})
        version = entry.get("version")
        return version if isinstance(version, str) else "unknown"


def _catalog(cli: str, root: Path) -> dict[str, Any] | None:
    for rel in CATALOGS[cli]:
        try:
            data = json.loads((root / rel).read_text())
        except (OSError, ValueError):
            continue
        ok = isinstance(data, dict) and isinstance(data.get("name"), str)
        if ok and isinstance(data.get("plugins"), list):
            return data
    return None


def _split(plugin_id: str) -> tuple[str, str]:
    name, at, market = plugin_id.rpartition("@")
    if not at or not name or not market:
        raise Failed(f'Invalid plugin id "{plugin_id}": expected <plugin>@<marketplace>')
    return name, market


def claude(agent: Agent, args: list[str], scope: str) -> Any:
    """`claude plugin <args>`: what it prints on success; Failed otherwise."""
    m, p = agent.marketplaces, agent.plugins
    match args:
        case ["marketplace", "list"]:
            out = []
            for name, v in m.items():
                entry = {"name": name, "source": v["kind"]}
                if v["kind"] == "directory":
                    entry["path"] = v["location"]
                    entry["installLocation"] = v["location"]
                else:
                    entry["repo" if v["kind"] == "github" else "url"] = v["location"]
                    entry["installLocation"] = f"~/.claude/plugins/marketplaces/{name}"
                out.append(entry)
            return out
        case ["marketplace", "add", directory]:
            root = Path(directory).absolute()
            data = _catalog("claude", root)
            if data is None:
                raise Failed(f"Marketplace file not found at {root}")
            # Adding a name already registered, from anywhere, points it here.
            m[data["name"]] = {"kind": "directory", "location": str(root)}
            message = f"Successfully added marketplace: {data['name']}"
            return {
                "command": "marketplace-add",
                "outcome": "ok",
                "marketplace": data["name"],
                "message": message,
            }
        case ["marketplace", "remove", name]:
            if name not in m:
                raise Failed(f"Marketplace '{name}' not found", "not_configured")
            del m[name]
            gone = [i for i in p if i.rpartition("@")[2] == name]
            for i in gone:
                del p[i]
            return {
                "command": "marketplace-remove",
                "outcome": "ok",
                "marketplace": name,
                "message": f"Successfully removed marketplace: {name}",
            }
        case ["install", plugin_id]:
            name, market = _split(plugin_id)
            if name not in (agent.catalog(market) or {}):
                raise Failed(f'Plugin "{name}" not found in marketplace "{market}"', "not_found")
            p.setdefault(plugin_id, {"enabled": True, "scope": scope})
            return {
                "command": "install",
                "outcome": "ok",
                "plugin": plugin_id,
                "pluginId": plugin_id,
                "scope": scope,
                "message": f"Successfully installed plugin: {plugin_id}",
            }
        case ["uninstall", plugin_id]:
            if plugin_id not in p:
                raise Failed(
                    f'Plugin "{plugin_id}" not found in installed plugins', "not_installed"
                )
            del p[plugin_id]
            return {
                "command": "uninstall",
                "outcome": "ok",
                "plugin": plugin_id,
                "message": f"Successfully uninstalled plugin: {plugin_id}",
            }
        case ["enable" | "disable" as verb, plugin_id]:
            if plugin_id not in p:
                raise Failed(
                    f'Plugin "{plugin_id}" not found in installed plugins', "not_installed"
                )
            p[plugin_id]["enabled"] = verb == "enable"
            return {
                "command": verb,
                "outcome": "ok",
                "plugin": plugin_id,
                "message": f"Successfully {verb}d plugin: {plugin_id}",
            }
        case ["list"]:
            out = []
            for plugin_id, v in p.items():
                name, market = plugin_id.rsplit("@", 1)
                entry = {
                    "id": plugin_id,
                    "version": agent.version(plugin_id),
                    "scope": v["scope"],
                    "enabled": v["enabled"],
                    "installPath": f"~/.claude/plugins/cache/{market}/{name}",
                }
                where = m.get(market)
                if where and where["kind"] == "directory":
                    entry["readFromFolder"] = str(Path(where["location"]) / "plugins" / name)
                out.append(entry)
            return out
    raise Unknown


def codex(agent: Agent, args: list[str]) -> Any:
    """`codex plugin <args>`: what it prints on success; Failed otherwise."""
    m, p = agent.marketplaces, agent.plugins
    match args:
        case ["marketplace", "list"]:
            return {
                "marketplaces": [
                    {
                        "name": name,
                        "root": v["location"],
                        "marketplaceSource": {"sourceType": v["kind"], "source": v["location"]},
                    }
                    for name, v in m.items()
                ]
            }
        case ["marketplace", "add", directory]:
            root = Path(directory).absolute()
            data = _catalog("codex", root)
            if data is None:
                raise Failed(f"no marketplace found at {root}")
            name = data["name"]
            already = m.get(name)
            if already is not None and already["location"] != str(root):
                raise Failed(
                    f"marketplace '{name}' is already added from a different source; "
                    "remove it before adding this source"
                )
            m[name] = {"kind": "local", "location": str(root)}
            return {
                "marketplaceName": name,
                "installedRoot": str(root),
                "alreadyAdded": already is not None,
            }
        case ["marketplace", "remove", name]:
            if name not in m:
                raise Failed(f"marketplace `{name}` is not configured or installed")
            del m[name]  # its plugins stay installed
            return {"marketplaceName": name, "installedRoot": None}
        case ["add", plugin_id]:
            name, market = _split(plugin_id)
            if name not in (agent.catalog(market) or {}):
                raise Failed(f"plugin `{name}` was not found in marketplace `{market}`")
            p.setdefault(plugin_id, {"enabled": True, "scope": "user"})
            version = agent.version(plugin_id)
            return {
                "pluginId": plugin_id,
                "name": name,
                "marketplaceName": market,
                "version": version,
                "installedPath": f"~/.codex/plugins/cache/{market}/{name}/{version}",
            }
        case ["remove", plugin_id]:
            name, market = _split(plugin_id)
            p.pop(plugin_id, None)  # succeeds whether or not it was installed
            return {"pluginId": plugin_id, "name": name, "marketplaceName": market}
        case ["list"]:
            installed = []
            for plugin_id, v in p.items():
                name, market = plugin_id.rsplit("@", 1)
                if name not in (agent.catalog(market) or {}):
                    continue  # still installed, but Codex doesn't list it
                installed.append(
                    {
                        "pluginId": plugin_id,
                        "name": name,
                        "marketplaceName": market,
                        "version": agent.version(plugin_id),
                        "installed": True,
                        "enabled": v["enabled"],
                    }
                )
            return {"installed": installed, "available": []}
    raise Unknown


class Unknown(Exception):
    """A command the stand-in doesn't know."""


def main(argv: list[str]) -> int:
    cli, args = argv[0], argv[1:]
    if cli == "bin":
        write_bin(Path(args[0]))
        return 0
    directory = os.environ.get(ENV)
    if not directory:
        print(f"stand-in {cli}: {ENV} isn't set", file=sys.stderr)
        return 2
    state_dir = Path(directory)
    try:
        devnull = os.path.samestat(os.fstat(0), Path(os.devnull).stat())
    except OSError:
        devnull = False
    state_dir.mkdir(parents=True, exist_ok=True)
    call = {"cli": cli, "args": args, "cwd": str(Path.cwd()), "stdin_devnull": devnull}
    with (state_dir / CALLS).open("a") as log:
        log.write(json.dumps(call) + "\n")

    if args == ["--version"]:
        print(VERSIONS[cli])
        return 0
    state = _load(state_dir)
    plain = [a for a in args if a != "--json"]
    for a in state["answers"]:
        if a["cli"] == cli and plain[: len(a["args"])] == a["args"]:
            sys.stdout.write(a["stdout"])
            sys.stderr.write(a["stderr"])
            return a["code"]
    if plain[:1] != ["plugin"] or "--json" not in args:
        print(f"stand-in {cli} only answers `plugin … --json`: {shlex.join(args)}", file=sys.stderr)
        return 2
    plain, scope = plain[1:], "user"
    # Only Claude Code's commands take `--scope`; Codex's take none, so a
    # Codex command carrying it is one the stand-in doesn't know.
    if cli == "claude" and "--scope" in plain:
        i = plain.index("--scope")
        scope = plain[i + 1]
        del plain[i : i + 2]

    agent = Agent(cli, state)
    try:
        out = claude(agent, plain, scope) if cli == "claude" else codex(agent, plain)
    except Unknown:
        print(f"stand-in {cli} doesn't know `plugin {shlex.join(plain)}`", file=sys.stderr)
        return 2
    except Failed as e:
        if cli == "claude":
            failure = {"outcome": "failed", "message": e.message}
            if e.code:
                failure["failureCode"] = e.code
            print(json.dumps(failure))
            print(f"✘ {e.message}", file=sys.stderr)
        else:
            print(f"Error: {e.message}", file=sys.stderr)
        return 1
    _save(state_dir, state)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

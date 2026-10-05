"""Check design.md's *Harness facts* about the agents' plugin CLIs against real ones.

What it verifies: the *(P0001)* plugin facts tack's `agents.py` and the test
suite's stand-in CLIs are built on. In a scratch HOME it builds a two-plugin
local marketplace named `tack`, then drives `claude plugin` and `codex plugin`
through the life cycle `sync` uses (register twice, install, reinstall,
uninstall, unregister, the failures in between) and checks each command's exit
code and the JSON fields tack reads: list shapes, `enabled`, `scope`, the
failure forms (Claude Code's JSON `message` and `failureCode`, Codex's
`Error:` line), Claude Code's `marketplace remove` uninstalling and Codex's
not, Codex's `plugin list` hiding a plugin whose catalog entry is gone, a
second directory under a registered name (Claude Code repoints the name,
Codex refuses), and Codex reading its own catalog before Claude Code's.

What it does not verify: anything about loading a plugin in a session, the
plugin caches' layout, project scope, git marketplaces, or fields tack doesn't
read (extra fields are fine; a missing one fails). It doesn't check the
stdin wait either (that takes a pipe held open); every command here runs with
stdin closed, as tack runs them.

How to run: `uv run python tools/agent_facts.py`, or with `--claude PATH`
and `--codex PATH` to check other executables. To check the test suite's
stand-ins, write them with `python tests/standin.py bin <dir>` and set
STANDIN_AGENTS_DIR to an empty directory for their state; they fail only the
checks that read Codex's `config.toml`, which a stand-in doesn't write (its
state file says the same, and `tests/test_agents.py` checks it there). It
never touches the real HOME: it sets HOME to a temporary directory and
removes it afterwards. Exit 0 when every fact holds, 1 when one doesn't, 2
when a CLI is missing.

Why it isn't in the gate: it runs the real agents, which CI doesn't have and
no test may start, and their behavior changes with their releases. Run it
when either agent updates, and when the stand-ins change.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

failures: list[str] = []


def check(label: str, ok: bool, detail: Any = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f": {detail}"))
    if not ok:
        failures.append(label)


class Agent:
    def __init__(self, exe: str, home: Path, cwd: Path) -> None:
        self.exe, self.home, self.cwd = exe, home, cwd

    def run(self, *args: str) -> tuple[int, str, str]:
        env = {**os.environ, "HOME": str(self.home)}
        for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            env.pop(var, None)
        r = subprocess.run(
            [self.exe, "plugin", *args, "--json"],
            cwd=self.cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        return r.returncode, r.stdout, r.stderr

    def json(self, label: str, *args: str, code: int = 0) -> Any:
        rc, out, err = self.run(*args)
        check(f"{label}: exits {code}", rc == code, f"exit {rc}, stderr {err.strip()!r}")
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            check(f"{label}: prints JSON", False, out[:200])
            return None

    def fails_with_error_line(self, label: str, *args: str) -> None:
        rc, out, err = self.run(*args)
        last = (err.strip().splitlines() or [""])[-1]
        check(
            f"{label}: exits 1, nothing on stdout, `Error: …` on stderr",
            rc == 1 and not out.strip() and last.startswith("Error: "),
            (rc, out[:100], last),
        )


def has(label: str, obj: Any, keys: dict[str, Callable[[Any], bool]]) -> None:
    if not isinstance(obj, dict):
        check(label, False, f"not an object: {obj!r}")
        return
    bad = [k for k, ok in keys.items() if k not in obj or not ok(obj[k])]
    check(label, not bad, f"missing or wrong: {bad} in {obj}")


def is_str(v: Any) -> bool:
    return isinstance(v, str)


def is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def marketplace(root: Path, names: list[str]) -> None:
    entries = [
        {"name": n, "source": f"./plugins/{n}", "description": f"The {n} plugin"} for n in names
    ]
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    catalog = {"name": "tack", "owner": {"name": "tack"}, "plugins": entries}
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(catalog, indent=2))
    for n in names:
        skill = root / "plugins" / n / "skills" / f"{n}-skill"
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(f"---\nname: {n}-skill\ndescription: Hi.\n---\nHi.\n")
    (root / "plugins" / "foo" / ".claude-plugin").mkdir(exist_ok=True)
    (root / "plugins" / "foo" / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "foo", "version": "1.3.0"})
    )


def claude_facts(a: Agent, mkt: Path) -> None:
    print("# claude")
    check(
        "marketplace list is [] at first", a.json("marketplace list", "marketplace", "list") == []
    )
    check("plugin list is [] at first", a.json("list", "list") == [])
    for label in ("marketplace add", "marketplace add again"):
        out = a.json(label, "marketplace", "add", str(mkt), "--scope", "user")
        has(f"{label}: outcome ok", out, {"outcome": lambda v: v == "ok", "message": is_str})
    listed = a.json("marketplace list", "marketplace", "list")
    ok = isinstance(listed, list) and len(listed) == 1
    check("marketplace list has one entry", ok, listed)
    if ok:
        has(
            "marketplace list entry",
            listed[0],
            {
                "name": lambda v: v == "tack",
                "source": lambda v: v == "directory",
                "path": lambda v: Path(v).resolve() == mkt.resolve(),
                "installLocation": is_str,
            },
        )
    # Another directory whose catalog is named `tack` takes the name over.
    other = mkt.parent / "other"
    marketplace(other, ["foo"])
    out = a.json("add another tack", "marketplace", "add", str(other), "--scope", "user")
    has("add another tack: outcome ok", out, {"outcome": lambda v: v == "ok"})
    listed = a.json("marketplace list", "marketplace", "list")
    paths = [Path(m.get("path", "")).resolve() for m in listed or [] if isinstance(m, dict)]
    check("tack now points at the other directory", paths == [other.resolve()], listed)
    a.json("marketplace add ours back", "marketplace", "add", str(mkt), "--scope", "user")
    for n in ("foo", "bar", "foo"):
        out = a.json(f"install {n}", "install", f"{n}@tack", "--scope", "user")
        has(f"install {n}: outcome ok", out, {"outcome": lambda v: v == "ok"})
    out = a.json("install a missing plugin", "install", "nope@tack", "--scope", "user", code=1)
    has(
        "install a missing plugin: failed, not_found",
        out,
        {"outcome": lambda v: v == "failed", "message": is_str,
         "failureCode": lambda v: v == "not_found"},
    )  # fmt: skip
    a.json("disable bar", "disable", "bar@tack", "--scope", "user")
    plugins = a.json("list", "list")
    by_id = {p.get("id"): p for p in plugins or [] if isinstance(p, dict)}
    check("list shows foo@tack and bar@tack", set(by_id) == {"foo@tack", "bar@tack"}, by_id)
    for pid, enabled in (("foo@tack", True), ("bar@tack", False)):
        has(
            f"list entry {pid}",
            by_id.get(pid),
            {"scope": lambda v: v == "user", "enabled": lambda v, e=enabled: v is e,
             "version": is_str, "installPath": is_str, "readFromFolder": is_str},
        )  # fmt: skip
    # Drop bar's entry and directory, then uninstall it: still listed, still removable.
    marketplace(mkt, ["foo"])
    shutil.rmtree(mkt / "plugins" / "bar")
    plugins = a.json("list after bar's entry is gone", "list")
    ids = {p.get("id") for p in plugins or [] if isinstance(p, dict)}
    check("list still shows bar@tack after its entry is gone", "bar@tack" in ids, ids)
    out = a.json("uninstall bar without its entry", "uninstall", "bar@tack", "--scope", "user")
    has("uninstall bar: outcome ok", out, {"outcome": lambda v: v == "ok"})
    out = a.json("uninstall again", "uninstall", "bar@tack", "--scope", "user", code=1)
    has("uninstall again: not_installed", out, {"failureCode": lambda v: v == "not_installed"})
    out = a.json("marketplace remove", "marketplace", "remove", "tack", "--scope", "user")
    has("marketplace remove: outcome ok", out, {"outcome": lambda v: v == "ok"})
    check("marketplace remove uninstalled foo", a.json("list", "list") == [])
    out = a.json(
        "marketplace remove again", "marketplace", "remove", "tack", "--scope", "user", code=1
    )
    has("marketplace remove again: not_configured", out,
        {"failureCode": lambda v: v == "not_configured"})  # fmt: skip


def codex_config(a: Agent) -> str:
    """Codex's config.toml; empty when there is none, as with the stand-in."""
    try:
        return (a.home / ".codex" / "config.toml").read_text()
    except FileNotFoundError:
        return ""


def codex_facts(a: Agent, mkt: Path) -> None:
    print("# codex")
    has("marketplace list is empty at first", a.json("marketplace list", "marketplace", "list"),
        {"marketplaces": lambda v: v == []})  # fmt: skip
    has("plugin list is empty at first", a.json("list", "list"),
        {"installed": lambda v: v == [], "available": lambda v: isinstance(v, list)})  # fmt: skip
    for label, again in (("marketplace add", False), ("marketplace add again", True)):
        out = a.json(label, "marketplace", "add", str(mkt))
        has(label, out, {"marketplaceName": lambda v: v == "tack", "installedRoot": is_str,
                         "alreadyAdded": lambda v, x=again: v is x})  # fmt: skip
    listed = a.json("marketplace list", "marketplace", "list")
    entries = listed.get("marketplaces") if isinstance(listed, dict) else None
    ok = isinstance(entries, list) and len(entries) == 1
    check("marketplace list has one entry", ok, listed)
    if ok:
        has(
            "marketplace list entry",
            entries[0],
            {
                "name": lambda v: v == "tack",
                "root": lambda v: Path(v).resolve() == mkt.resolve(),
                "marketplaceSource": lambda v: (
                    isinstance(v, dict) and v.get("sourceType") == "local"
                ),
            },
        )
    other = mkt.parent / "other"
    marketplace(other, ["foo"])
    a.fails_with_error_line("marketplace add another tack", "marketplace", "add", str(other))
    # With both catalogs, Codex reads its own.
    both = mkt.parent / "both"
    for rel, name in ((".claude-plugin", "claude-format"), (".agents/plugins", "codex-format")):
        (both / rel).mkdir(parents=True)
        (both / rel / "marketplace.json").write_text(json.dumps({"name": name, "plugins": []}))
    out = a.json("marketplace add with both catalogs", "marketplace", "add", str(both))
    has("marketplace add with both catalogs: its own", out,
        {"marketplaceName": lambda v: v == "codex-format"})  # fmt: skip
    a.json("marketplace remove it", "marketplace", "remove", "codex-format")
    for n in ("foo", "bar", "foo"):
        out = a.json(f"add {n}", "add", f"{n}@tack")
        has(f"add {n}", out, {"pluginId": lambda v, n=n: v == f"{n}@tack", "version": is_str,
                              "installedPath": is_str})  # fmt: skip
    a.fails_with_error_line("add a missing plugin", "add", "nope@tack")
    listed = a.json("list", "list")
    installed = listed.get("installed") if isinstance(listed, dict) else None
    by_id = {p.get("pluginId"): p for p in installed or [] if isinstance(p, dict)}
    check("list shows foo@tack and bar@tack", set(by_id) == {"foo@tack", "bar@tack"}, listed)
    for pid in by_id:
        has(f"list entry {pid}", by_id[pid],
            {"name": is_str, "marketplaceName": lambda v: v == "tack", "version": is_str,
             "installed": lambda v: v is True, "enabled": is_bool})  # fmt: skip
    # Drop bar's entry: Codex stops listing it, though it is still installed.
    marketplace(mkt, ["foo"])
    shutil.rmtree(mkt / "plugins" / "bar")
    listed = a.json("list after bar's entry is gone", "list")
    ids = {p.get("pluginId") for p in (listed or {}).get("installed", [])}
    check("list hides bar@tack once its entry is gone", ids == {"foo@tack"}, ids)
    config = codex_config(a)
    check("config.toml still has bar@tack", '[plugins."bar@tack"]' in config, config)
    for label, pid in (
        ("remove bar without its entry", "bar@tack"),
        ("remove a missing", "x@tack"),
    ):
        has(label, a.json(label, "remove", pid), {"pluginId": lambda v, p=pid: v == p})
    config = codex_config(a)
    check("remove took bar@tack out of config.toml", "bar@tack" not in config, config)
    has("marketplace remove", a.json("marketplace remove", "marketplace", "remove", "tack"),
        {"marketplaceName": lambda v: v == "tack"})  # fmt: skip
    config = codex_config(a)
    check("marketplace remove left foo@tack installed", '[plugins."foo@tack"]' in config, config)
    listed = a.json("list after marketplace remove", "list")
    check("list hides foo@tack once its marketplace is gone",
          isinstance(listed, dict) and listed.get("installed") == [], listed)  # fmt: skip
    a.fails_with_error_line("marketplace remove again", "marketplace", "remove", "tack")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", default=shutil.which("claude"))
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.claude or not args.codex:
        print("needs both `claude` and `codex` (on PATH, or --claude/--codex)", file=sys.stderr)
        return 2
    for exe in (args.claude, args.codex):
        print(subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip())
    with tempfile.TemporaryDirectory(prefix="tack-agent-facts-") as tmp:
        base = Path(tmp)
        for name, exe, facts in (("claude", args.claude, claude_facts),
                                 ("codex", args.codex, codex_facts)):  # fmt: skip
            home, cwd, mkt = base / name / "home", base / name / "data", base / name / "mkt"
            for d in (home, cwd):
                d.mkdir(parents=True)
            marketplace(mkt, ["foo", "bar"])
            facts(Agent(exe, home, cwd), mkt)
    print(f"\n{len(failures)} fact(s) failed" if failures else "\nevery fact holds")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

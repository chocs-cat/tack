from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tack import agents, plugins
from tack.agents import Installed, Inventory, Marketplace, Outcome
from tack.config import Paths
from tests import standin
from tests.helpers import write
from tests.standin import Standins

HARNESSES = ("claude-code", "codex")


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "config", tmp_path / "data", tmp_path / "state")


def marketplace(paths: Paths, *names: str) -> Path:
    """tack's marketplace holding a copy of each named plugin."""
    src = paths.data_dir.parent / "src"
    wanted = []
    for n in names:
        write(src / n / "skills" / n / "SKILL.md", f"The {n} skill.\n")
        wanted.append(plugins.Wanted(n, src / n, {"name": n, "source": f"./{n}"}))
    plugins.update(paths, wanted)
    return paths.marketplace_dir


def ok(out: Outcome) -> Any:
    assert out.ok, out.error
    return out.output


def inv(harness: str, paths: Paths) -> Inventory:
    found = agents.inventory(harness, paths)
    assert isinstance(found, Inventory), found
    return found


def ids(found: Inventory) -> list[str]:
    return sorted(p.id for p in found.plugins)


def raw(cli: str, *args: str) -> tuple[int, Any, str]:
    """Run a stand-in as tack would and decode what it printed."""
    r = subprocess.run(
        [cli, "plugin", *args, "--json"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr


# --- the fixture ----------------------------------------------------------------------


def test_the_stand_ins_are_the_agents_on_path(standins: Standins) -> None:
    for cli in standin.CLIS:
        assert shutil.which(cli) == str(standins.bin_dir / cli)
    for d in os.environ["PATH"].split(os.pathsep)[1:]:
        assert not any((Path(d or ".") / cli).exists() for cli in standin.CLIS)
    assert subprocess.run(["git", "--version"], capture_output=True, check=False).returncode == 0

    standins.remove("claude")
    assert shutil.which("claude") is None
    assert not agents.available("claude-code")
    assert agents.available("codex")


def _exe(path: Path) -> Path:
    write(path, "#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_isolate_mirrors_directories_holding_an_agent(tmp_path: Path) -> None:
    agent_dir, other_agent, git_dir, plain = (tmp_path / d for d in ("a", "b", "g", "p"))
    _exe(agent_dir / "claude")
    git = _exe(agent_dir / "git")
    asdf = _exe(agent_dir / "asdf")
    write(agent_dir / "notes.txt", "not a program\n")
    _exe(other_agent / "codex")
    _exe(git_dir / "git")
    plain.mkdir()

    root = tmp_path / "mirrors"
    dirs = (agent_dir, other_agent, git_dir, plain, agent_dir)
    path = standin.isolate(os.pathsep.join(map(str, dirs)), root)

    m0, m1 = root / "0", root / "1"
    assert path.split(os.pathsep) == [str(d) for d in (m0, m1, git_dir, plain, m0)]
    assert sorted(p.name for p in m0.iterdir()) == ["asdf", "git", "notes.txt"]
    assert list(m1.iterdir()) == []
    for cli in standin.CLIS:
        assert shutil.which(cli, path=path) is None
    # Everything else resolves as before, in the same order.
    found = shutil.which("git", path=path)
    assert found is not None
    assert Path(found).resolve() == git.resolve()
    found = shutil.which("asdf", path=path)
    assert found is not None
    assert Path(found).resolve() == asdf.resolve()


# --- commands -------------------------------------------------------------------------


def test_command_arguments(paths: Paths) -> None:
    d = paths.marketplace_dir
    claude = {
        agents.list_plugins: ["claude", "plugin", "list", "--json"],
        agents.list_marketplaces: ["claude", "plugin", "marketplace", "list", "--json"],
    }
    codex = {
        agents.list_plugins: ["codex", "plugin", "list", "--json"],
        agents.list_marketplaces: ["codex", "plugin", "marketplace", "list", "--json"],
    }
    for build, args in claude.items():
        assert list(build("claude-code").args) == args
    for build, args in codex.items():
        assert list(build("codex").args) == args
    expected = {
        "claude-code": [
            ["claude", "plugin", "marketplace", "add", str(d), "--scope", "user", "--json"],
            ["claude", "plugin", "install", "foo@tack", "--scope", "user", "--json"],
            ["claude", "plugin", "uninstall", "foo@tack", "--scope", "user", "--json"],
            ["claude", "plugin", "marketplace", "remove", "tack", "--scope", "user", "--json"],
        ],
        "codex": [
            ["codex", "plugin", "marketplace", "add", str(d), "--json"],
            ["codex", "plugin", "add", "foo@tack", "--json"],
            ["codex", "plugin", "remove", "foo@tack", "--json"],
            ["codex", "plugin", "marketplace", "remove", "tack", "--json"],
        ],
    }
    for h, lines in expected.items():
        commands = [
            agents.register(h, d),
            agents.install(h, "foo"),
            agents.uninstall(h, "foo"),
            agents.unregister(h),
        ]
        assert [list(c.args) for c in commands] == lines
        assert [c.kind for c in commands] == ["register", "install", "uninstall", "unregister"]
        assert all(c.harness == h for c in commands)
    spaced = agents.register("codex", Path("/a dir/marketplace"))
    assert str(spaced) == "codex plugin marketplace add '/a dir/marketplace' --json"


# --- running them -----------------------------------------------------------------------


@contextmanager
def stdin_pipe() -> Iterator[None]:
    """Our stdin an open pipe, as in a terminal, so a stand-in can tell
    whether tack closed it."""
    r, w = os.pipe()
    saved = os.dup(0)
    os.dup2(r, 0)
    try:
        yield
    finally:
        os.dup2(saved, 0)
        for fd in (saved, r, w):
            os.close(fd)


def test_commands_run_in_the_data_directory(paths: Paths, standins: Standins) -> None:
    paths.data_dir.mkdir(parents=True)
    with stdin_pipe():
        for h in HARNESSES:
            ok(agents.run(agents.list_plugins(h), paths))
    calls = standins.calls()
    assert [(c.cli, c.args) for c in calls] == [
        ("claude", ["plugin", "list", "--json"]),
        ("codex", ["plugin", "list", "--json"]),
    ]
    assert all(Path(c.cwd) == paths.data_dir.resolve() for c in calls)
    assert all(c.stdin_devnull for c in calls)


def test_commands_run_in_a_temporary_directory_without_one(
    paths: Paths, standins: Standins
) -> None:
    with stdin_pipe():
        for h in HARNESSES:
            ok(agents.run(agents.list_marketplaces(h), paths))
    calls = standins.calls()
    assert len(calls) == 2
    for c in calls:
        cwd = Path(c.cwd)
        assert cwd.name.startswith("tack-")
        assert not cwd.exists()  # removed afterwards
        assert c.stdin_devnull
    assert not paths.data_dir.exists()


def test_failure_messages(paths: Paths, standins: Standins) -> None:
    # Claude Code's message comes from its JSON, not its `✘` line.
    out = agents.run(agents.install("claude-code", "foo"), paths)
    assert not out.ok
    assert not out.missing
    assert out.error == 'Plugin "foo" not found in marketplace "tack"'
    # Codex's is its last stderr line, without `Error: `.
    out = agents.run(agents.install("codex", "foo"), paths)
    assert out.error == "plugin `foo` was not found in marketplace `tack`"

    standins.answer("claude", ["plugin", "uninstall"], stderr="warming up\nno JSON here\n", code=1)
    assert agents.run(agents.uninstall("claude-code", "x"), paths).error == "no JSON here"
    standins.answer("codex", ["plugin", "remove"], code=3)
    out = agents.run(agents.uninstall("codex", "x"), paths)
    assert out.error == "`codex plugin remove x@tack --json` exited 3"
    # Exiting 0 with `outcome: failed` is still a failure.
    failed = {"outcome": "failed", "message": "it went wrong"}
    standins.answer("claude", ["plugin", "marketplace", "remove"], stdout=json.dumps(failed))
    assert agents.run(agents.unregister("claude-code"), paths).error == "it went wrong"
    # So is exiting 0 without the JSON the command should print.
    standins.answer("codex", ["plugin", "marketplace", "remove"], stdout="done\n")
    out = agents.run(agents.unregister("codex"), paths)
    assert out.error is not None
    assert "didn't print the JSON" in out.error


@pytest.mark.parametrize("harness", HARNESSES)
@pytest.mark.parametrize(
    ("args", "stdout"),
    [
        (["plugin", "list"], "Installed plugins:\n  foo@tack\n"),
        (["plugin", "list"], '{"plugins": []}'),
        (["plugin", "list"], '[{"id": "foo@tack", "enabled": "yes", "scope": "user"}]'),
        (["plugin", "list"], '{"installed": [{"name": "foo"}]}'),
        (["plugin", "marketplace", "list"], ""),
        (["plugin", "marketplace", "list"], '[{"name": "tack"}]'),
        (["plugin", "marketplace", "list"], '{"marketplaces": [{"name": "tack"}]}'),
    ],
)
def test_a_list_without_its_json_is_a_failure(
    paths: Paths, standins: Standins, harness: str, args: list[str], stdout: str
) -> None:
    cli = agents.CLIS[harness]
    standins.answer(cli, args, stdout=stdout, stderr="something odd\n")
    found = agents.inventory(harness, paths)
    assert isinstance(found, Outcome)
    assert found.command.kind == (
        "list" if args[-1] == "list" and len(args) == 2 else "marketplace-list"
    )
    assert found.error is not None
    assert "didn't print the JSON" in found.error


@pytest.mark.parametrize("harness", HARNESSES)
def test_a_cli_that_is_not_there(paths: Paths, standins: Standins, harness: str) -> None:
    cli = agents.CLIS[harness]
    standins.remove(cli)
    assert not agents.available(harness)
    out = agents.run(agents.install(harness, "foo"), paths)
    assert out.missing
    assert out.error == f"`{cli}` isn't on PATH"
    found = agents.inventory(harness, paths)
    assert isinstance(found, Outcome)
    assert found.missing


# --- reading what each agent has ----------------------------------------------------------


def test_reading_claude_code(paths: Paths, standins: Standins) -> None:
    mkt = marketplace(paths, "foo")
    ok(agents.run(agents.register("claude-code", mkt), paths))
    ok(agents.run(agents.install("claude-code", "foo"), paths))
    standins.marketplace("claude", "elsewhere", "owner/elsewhere", kind="github", plugins=["x"])
    standins.plugin("claude", "hand@elsewhere")
    standins.plugin("claude", "off@elsewhere", enabled=False)
    standins.plugin("claude", "web@claude-ai", scope="synced")

    found = inv("claude-code", paths)

    assert found.plugins == (
        Installed("foo", "tack", True, "user"),
        Installed("hand", "elsewhere", True, "user"),
        Installed("off", "elsewhere", False, "user"),
        Installed("web", "claude-ai", True, "synced"),
    )
    assert found.marketplaces == (
        Marketplace("tack", "directory", str(mkt)),
        Marketplace("elsewhere", "github", "owner/elsewhere"),
    )
    tack = found.marketplace("tack")
    assert tack is not None
    assert agents.is_tack("claude-code", tack, paths)
    assert found.marketplace("nope") is None


def test_reading_codex(paths: Paths, standins: Standins) -> None:
    mkt = marketplace(paths, "foo")
    ok(agents.run(agents.register("codex", mkt), paths))
    ok(agents.run(agents.install("codex", "foo"), paths))
    url = "https://example.com/elsewhere.git"
    standins.marketplace("codex", "elsewhere", url, kind="git", plugins=["hand", "off"])
    standins.plugin("codex", "hand@elsewhere")
    standins.plugin("codex", "off@elsewhere", enabled=False)

    found = inv("codex", paths)

    assert found.plugins == (
        Installed("foo", "tack", True, "user"),
        Installed("hand", "elsewhere", True, "user"),
        Installed("off", "elsewhere", False, "user"),
    )
    assert found.marketplaces == (
        Marketplace("tack", "local", str(mkt)),
        Marketplace("elsewhere", "git", url),
    )
    tack = found.marketplace("tack")
    assert tack is not None
    assert agents.is_tack("codex", tack, paths)


@pytest.mark.parametrize("harness", HARNESSES)
def test_telling_tacks_marketplace_from_another_named_tack(
    tmp_path: Path, paths: Paths, harness: str
) -> None:
    local = "directory" if harness == "claude-code" else "local"
    mkt = str(paths.marketplace_dir)
    assert agents.is_tack(harness, Marketplace("tack", local, mkt), paths)
    assert agents.is_tack(harness, Marketplace("tack", local, mkt + "/"), paths)
    paths.data_dir.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "alias").symlink_to(paths.data_dir.parent)
    alias = str(tmp_path / "alias" / "data" / "marketplace")
    paths.marketplace_dir.mkdir(parents=True)
    assert agents.is_tack(harness, Marketplace("tack", local, alias), paths)

    assert not agents.is_tack(harness, Marketplace("tack", local, str(tmp_path / "other")), paths)
    assert not agents.is_tack(harness, Marketplace("tack", "github", "chocs-cat/tack"), paths)
    assert not agents.is_tack(harness, Marketplace("tack", "git", mkt), paths)
    assert not agents.is_tack(harness, Marketplace("tack", local, None), paths)
    assert not agents.is_tack(harness, Marketplace("tacky", local, mkt), paths)


def test_foreign_tack_marketplace_read_from_both(
    tmp_path: Path, paths: Paths, standins: Standins
) -> None:
    other = tmp_path / "other-tack"
    standins.marketplace("claude", "tack", other)
    standins.marketplace(
        "codex", "tack", "https://github.com/someone/tack.git", kind="git", plugins=[]
    )
    for h in HARNESSES:
        tack = inv(h, paths).marketplace("tack")
        assert tack is not None
        assert not agents.is_tack(h, tack, paths)


# --- the stand-ins behave as design.md's Harness facts say ---------------------------------


def test_list_shapes(paths: Paths) -> None:
    mkt = marketplace(paths, "foo")
    for cli in standin.CLIS:
        assert (
            raw(
                cli,
                "marketplace",
                "add",
                str(mkt),
                *(("--scope", "user") if cli == "claude" else ()),
            )[0]
            == 0
        )
    raw("claude", "install", "foo@tack", "--scope", "user")
    raw("codex", "add", "foo@tack")

    _, listed, _ = raw("claude", "list")
    (entry,) = listed
    assert {"id", "scope", "enabled", "version", "installPath", "readFromFolder"} <= set(entry)
    _, listed, _ = raw("claude", "marketplace", "list")
    (entry,) = listed
    assert entry["source"] == "directory"
    assert {"name", "source", "installLocation", "path"} <= set(entry)

    _, listed, _ = raw("codex", "list")
    assert set(listed) == {"installed", "available"}
    (entry,) = listed["installed"]
    assert {"pluginId", "name", "marketplaceName", "version", "installed", "enabled"} <= set(entry)
    _, listed, _ = raw("codex", "marketplace", "list")
    (entry,) = listed["marketplaces"]
    assert {"name", "root", "marketplaceSource"} <= set(entry)
    assert entry["marketplaceSource"] == {"sourceType": "local", "source": str(mkt)}


def test_registering_twice(paths: Paths, standins: Standins) -> None:
    mkt = marketplace(paths, "foo")
    for _ in range(2):
        code, out, _ = raw("claude", "marketplace", "add", str(mkt), "--scope", "user")
        assert (code, out["outcome"]) == (0, "ok")
    for again in (False, True):
        code, out, _ = raw("codex", "marketplace", "add", str(mkt))
        assert (code, out["marketplaceName"], out["alreadyAdded"]) == (0, "tack", again)
    for h in HARNESSES:
        assert len(inv(h, paths).marketplaces) == 1


def test_installing_an_installed_plugin(paths: Paths) -> None:
    mkt = marketplace(paths, "foo")
    for h in HARNESSES:
        ok(agents.run(agents.register(h, mkt), paths))
        ok(agents.run(agents.install(h, "foo"), paths))
        ok(agents.run(agents.install(h, "foo"), paths))
        assert ids(inv(h, paths)) == ["foo@tack"]


def test_installing_a_plugin_the_catalog_lacks(paths: Paths) -> None:
    mkt = marketplace(paths, "foo")
    raw("claude", "marketplace", "add", str(mkt), "--scope", "user")
    raw("codex", "marketplace", "add", str(mkt))
    code, out, err = raw("claude", "install", "nope@tack", "--scope", "user")
    assert (code, out["outcome"], out["failureCode"]) == (1, "failed", "not_found")
    assert err.startswith("✘ ")
    code, out, err = raw("codex", "add", "nope@tack")
    assert (code, out) == (1, None)
    assert err.startswith("Error: ")


def test_claude_code_uninstall_of_a_plugin_not_installed_fails() -> None:
    code, out, _ = raw("claude", "uninstall", "foo@tack", "--scope", "user")
    assert (code, out["outcome"], out["failureCode"]) == (1, "failed", "not_installed")


def test_codex_remove_always_succeeds(paths: Paths) -> None:
    code, out, _ = raw("codex", "remove", "foo@tack")
    assert (code, out["pluginId"]) == (0, "foo@tack")
    assert ok(agents.run(agents.uninstall("codex", "foo"), paths))["pluginId"] == "foo@tack"


def test_removing_a_marketplace(paths: Paths, standins: Standins) -> None:
    mkt = marketplace(paths, "foo", "bar")
    for h in HARNESSES:
        ok(agents.run(agents.register(h, mkt), paths))
        for n in ("foo", "bar"):
            ok(agents.run(agents.install(h, n), paths))
    standins.marketplace("claude", "elsewhere", "owner/elsewhere", kind="github", plugins=["x"])
    standins.plugin("claude", "x@elsewhere")
    for h in HARNESSES:
        ok(agents.run(agents.unregister(h), paths))

    # Claude Code uninstalls the marketplace's plugins, and only those.
    assert ids(inv("claude-code", paths)) == ["x@elsewhere"]
    # Codex leaves them installed, and its list no longer shows them.
    assert sorted(standins.state()["codex"]["plugins"]) == ["bar@tack", "foo@tack"]
    assert ids(inv("codex", paths)) == []


def test_removing_an_unregistered_marketplace_fails() -> None:
    code, out, _ = raw("claude", "marketplace", "remove", "tack", "--scope", "user")
    assert (code, out["failureCode"]) == (1, "not_configured")
    code, out, err = raw("codex", "marketplace", "remove", "tack")
    assert (code, out) == (1, None)
    assert err.startswith("Error: ")


def test_codex_list_hides_plugins_its_catalog_lacks(paths: Paths, standins: Standins) -> None:
    mkt = marketplace(paths, "foo", "bar")
    for h in HARNESSES:
        ok(agents.run(agents.register(h, mkt), paths))
        for n in ("foo", "bar"):
            ok(agents.run(agents.install(h, n), paths))
    # bar's catalog entry goes; neither agent uninstalls it.
    src = paths.data_dir.parent / "src" / "foo"
    plugins.update(paths, [plugins.Wanted("foo", src, {"name": "foo", "source": "./foo"})])
    standins.plugin("claude", "lost@gone")
    standins.plugin("codex", "lost@gone")

    assert ids(inv("claude-code", paths)) == ["bar@tack", "foo@tack", "lost@gone"]
    assert ids(inv("codex", paths)) == ["foo@tack"]
    assert sorted(standins.state()["codex"]["plugins"]) == ["bar@tack", "foo@tack", "lost@gone"]


def test_adding_another_marketplace_by_the_same_name(tmp_path: Path, paths: Paths) -> None:
    mkt = marketplace(paths, "foo")
    other = tmp_path / "other"
    write(
        other / ".claude-plugin" / "marketplace.json", json.dumps({"name": "tack", "plugins": []})
    )
    for h in HARNESSES:
        ok(agents.run(agents.register(h, other), paths))
    # Claude Code points the name at the new directory; Codex refuses.
    out = ok(agents.run(agents.register("claude-code", mkt), paths))
    assert out["marketplace"] == "tack"
    assert inv("claude-code", paths).marketplaces == (Marketplace("tack", "directory", str(mkt)),)
    out = agents.run(agents.register("codex", mkt), paths)
    assert out.error is not None
    assert "already added from a different source" in out.error
    assert inv("codex", paths).marketplaces == (Marketplace("tack", "local", str(other)),)


def test_codex_reads_its_own_catalog_first(tmp_path: Path) -> None:
    both = tmp_path / "both"
    write(both / ".claude-plugin" / "marketplace.json", '{"name": "claude-name", "plugins": []}')
    write(
        both / ".agents" / "plugins" / "marketplace.json", '{"name": "codex-name", "plugins": []}'
    )
    assert raw("codex", "marketplace", "add", str(both))[1]["marketplaceName"] == "codex-name"
    out = raw("claude", "marketplace", "add", str(both), "--scope", "user")[1]
    assert out["marketplace"] == "claude-name"


def test_stand_ins_answer_only_plugin_json_commands(standins: Standins) -> None:
    for args in (["plugin", "list"], ["mcp", "list", "--json"]):
        r = subprocess.run(["claude", *args], capture_output=True, text=True, check=False)
        assert r.returncode == 2
        assert "stand-in" in r.stderr
    assert len(standins.calls("claude")) == 2


def test_codex_commands_take_no_scope(paths: Paths, standins: Standins) -> None:
    mkt = marketplace(paths, "x")
    raw("codex", "marketplace", "add", str(mkt))
    before = standins.state()
    code, out, err = raw("codex", "add", "x@tack", "--scope", "user")
    assert (code, out) == (2, None)
    assert "doesn't know" in err
    assert standins.state() == before

"""`sync`'s plugin pass (design.md §9 *Deploying*, *Plugin ownership*),
against the stand-in agents. The manifest doesn't take `plugins` yet, so the
selections are set as `parse_plugins` reads them (`helpers.configure`)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tack import agents, cli, deploy, plugins, sync, text
from tack.config import Config
from tack.deploy import Install
from tests.helpers import configure, link, market, skill, tree, write
from tests.standin import Call, Standins

WHEN = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
NPM = {"source": "npm", "package": "@acme/x"}
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def never_enables_or_disables(standins: Standins) -> Iterator[None]:
    """tack never enables or disables a plugin (DEC-5), in any test here."""
    yield
    assert not [c for c in standins.calls() if c.args[1:2] in (["enable"], ["disable"])]


def source(home: Path, name: str, *plugin_names: str, entries: tuple[Any, ...] = ()) -> Path:
    """A `path` source at `~/<name>` with an empty skills directory and a
    catalog listing each plugin (with its files under `plugins/<plugin>`),
    then `entries` as they are."""
    root = home / name
    (root / "skills").mkdir(parents=True, exist_ok=True)
    for p in plugin_names:
        write(root / "plugins" / p / ".claude-plugin" / "plugin.json", json.dumps({"name": p}))
        write(root / "plugins" / p / "skills" / p / "SKILL.md", f"The {p} skill.\n")
    listed = [
        {"name": p, "source": f"./plugins/{p}", "description": f"The {p} plugin", "version": "1.0"}
        for p in plugin_names
    ]
    return market(root, *listed, *entries)


def run(cfg: Config, **kw: Any) -> sync.Result:
    return sync.sync(cfg, now=WHEN, **kw)


def listing(c: Call) -> bool:
    return c.args[-2:] == ["list", "--json"]


def ran(standins: Standins, cli_name: str | None = None, *, since: int = 0) -> list[str]:
    """The commands the stand-ins ran but `list` ones, as command lines."""
    calls = standins.calls(cli_name) if cli_name else standins.calls()[since:]
    return [shlex.join([c.cli, *c.args]) for c in calls if not listing(c)]


def changes(result: sync.Result) -> list[tuple[str, str | None, str]]:
    return [(c.action, c.harness or c.source, c.detail) for c in result.changes]


def installed(standins: Standins, cli_name: str) -> dict[str, dict[str, Any]]:
    return standins.state()[cli_name]["plugins"]


def registered(standins: Standins, cli_name: str) -> dict[str, dict[str, Any]]:
    return standins.state()[cli_name]["marketplaces"]


def record(cfg: Config) -> dict[str, dict[str, Install]]:
    return deploy.load_record(cfg.paths).plugins


def h(directory: Path) -> str:
    return plugins.tree_hash(directory)


def claude(*args: str) -> str:
    return shlex.join(["claude", "plugin", *args, "--scope", "user", "--json"])


def codex(*args: str) -> str:
    return shlex.join(["codex", "plugin", *args, "--json"])


# --- a first sync, and a second ---------------------------------------------------------


def test_a_first_sync_registers_and_installs_and_a_second_changes_nothing(
    home: Path, standins: Standins
) -> None:
    one = source(home, "one", "a", "b")
    cfg = configure(home, "one", one="*")
    m = cfg.paths.marketplace_dir

    result = run(cfg)

    assert result.problems == []
    assert ran(standins, "claude") == [
        claude("marketplace", "add", str(m)),
        claude("install", "a@tack"),
        claude("install", "b@tack"),
    ]
    assert ran(standins, "codex") == [
        codex("marketplace", "add", str(m)),
        codex("add", "a@tack"),
        codex("add", "b@tack"),
    ]
    # Each harness is listed before any step runs in it, and Claude Code goes first.
    assert [(c.cli, listing(c)) for c in standins.calls()] == [
        ("claude", True), ("claude", True), ("claude", False), ("claude", False),
        ("claude", False), ("codex", True), ("codex", True), ("codex", False),
        ("codex", False), ("codex", False),
    ]  # fmt: skip
    assert changes(result) == [
        ("copy", "one", f"a from {text.tilde(one / 'plugins' / 'a')}"),
        ("copy", "one", f"b from {text.tilde(one / 'plugins' / 'b')}"),
        ("write", None, text.tilde(m / plugins.CATALOG)),
        ("register", "claude-code", claude("marketplace", "add", str(m))),
        ("install", "claude-code", claude("install", "a@tack")),
        ("install", "claude-code", claude("install", "b@tack")),
        ("register", "codex", codex("marketplace", "add", str(m))),
        ("install", "codex", codex("add", "a@tack")),
        ("install", "codex", codex("add", "b@tack")),
    ]
    assert [c.source for c in result.changes[3:]] == [None, "one", "one", None, "one", "one"]

    # The copies, and tack's catalog keeping the upstream fields.
    for p in ("a", "b"):
        assert tree(m / "plugins" / p) == tree(one / "plugins" / p)
    assert json.loads((m / plugins.CATALOG).read_text()) == {
        "name": "tack",
        "owner": {"name": "tack"},
        "plugins": [
            {
                "name": p,
                "source": f"./plugins/{p}",
                "description": f"The {p} plugin",
                "version": "1.0",
            }
            for p in ("a", "b")
        ],
    }
    # What each agent has, and the record.
    for cli_name in ("claude", "codex"):
        assert set(installed(standins, cli_name)) == {"a@tack", "b@tack"}
        assert registered(standins, cli_name)["tack"]["location"] == str(m)
    data = json.loads((cfg.paths.state_dir / deploy.RECORD).read_text())
    assert data["version"] == 1
    expected = {p: {"source": "one", "hash": h(one / "plugins" / p)} for p in ("a", "b")}
    assert data["plugins"] == {"claude-code": expected, "codex": expected}

    # A second sync runs only the `list` commands and changes nothing.
    before, calls = tree(home), len(standins.calls())
    again = run(cfg)
    assert (again.changes, again.problems) == ([], [])
    assert len(standins.calls()) == calls + 4
    assert ran(standins, since=calls) == []
    assert tree(home) == before


# --- changed files, and what the record knows ----------------------------------------------


def test_a_changed_file_refreshes_the_copy_and_reinstalls_in_codex_only(
    home: Path, standins: Standins
) -> None:
    one = source(home, "one", "a", "b")
    cfg = configure(home, "one", one="*")
    run(cfg)
    old = h(one / "plugins" / "a")
    write(one / "plugins" / "a" / "skills" / "a" / "SKILL.md", "Changed.\n")
    calls = len(standins.calls())

    result = run(cfg)

    assert result.problems == []
    assert ran(standins, since=calls) == [codex("add", "a@tack")]
    assert [(a, w) for a, w, _ in changes(result)] == [("copy", "one"), ("reinstall", "codex")]
    m = cfg.paths.marketplace_dir
    assert (m / "plugins" / "a" / "skills" / "a" / "SKILL.md").read_text() == "Changed.\n"
    new = h(one / "plugins" / "a")
    assert record(cfg)["codex"]["a"] == Install("one", new)
    # Claude Code loads the copy in place; its record keeps the hash it was installed from.
    assert record(cfg)["claude-code"]["a"] == Install("one", old)


def test_a_stale_recorded_hash_reinstalls_in_codex(home: Path, standins: Standins) -> None:
    one = source(home, "one", "a", "b")
    cfg = configure(home, "one", one="*")
    run(cfg)
    rec = deploy.load_record(cfg.paths)
    rec.plugins["codex"]["a"] = Install("one", "stale")
    rec.plugins["claude-code"]["a"] = Install("one", "stale")
    deploy.save_record(cfg.paths, rec)
    calls = len(standins.calls())

    result = run(cfg)

    assert ran(standins, since=calls) == [codex("add", "a@tack")]
    assert changes(result) == [("reinstall", "codex", codex("add", "a@tack"))]
    assert record(cfg)["codex"]["a"] == Install("one", h(one / "plugins" / "a"))
    assert record(cfg)["claude-code"]["a"] == Install("one", "stale")


def test_installed_but_unrecorded_plugins(home: Path, standins: Standins) -> None:
    # Recorded with no command in Claude Code; reinstalled in Codex, since
    # its copy's age is unknown.
    one = source(home, "one", "a", "b")
    cfg = configure(home, "one", one="*")
    run(cfg)
    deploy.save_record(cfg.paths, deploy.Record(deploy.load_record(cfg.paths).links))
    calls = len(standins.calls())

    result = run(cfg)

    assert result.problems == []
    assert ran(standins, since=calls) == [codex("add", "a@tack"), codex("add", "b@tack")]
    assert [a for a, _, _ in changes(result)] == ["reinstall", "reinstall"]
    expected = {p: Install("one", h(one / "plugins" / p)) for p in ("a", "b")}
    assert record(cfg) == {"claude-code": expected, "codex": expected}


def test_a_recorded_plugin_follows_its_source(home: Path, standins: Standins) -> None:
    # The same files from another source: recorded from there, nothing reinstalled.
    source(home, "one", "a")
    two = home / "two"
    shutil.copytree(home / "one", two)
    run(configure(home, "one", "two", one=["a"]))
    calls = len(standins.calls())
    cfg = configure(home, "one", "two", two=["a"])
    result = run(cfg)
    assert ran(standins, since=calls) == []
    assert [a for a, _, _ in changes(result)] == []
    assert record(cfg)["codex"]["a"] == Install("two", h(two / "plugins" / "a"))
    assert record(cfg)["claude-code"]["a"].source == "two"


# --- deselecting -----------------------------------------------------------------------------


def test_deselecting_one_plugin_uninstalls_it_and_drops_its_copy(
    home: Path, standins: Standins
) -> None:
    source(home, "one", "a", "b")
    run(configure(home, "one", one="*"))
    m = home / ".local" / "share" / "tack" / "marketplace"
    calls = len(standins.calls())

    cfg = configure(home, "one", one=["a"])
    result = run(cfg)

    assert result.problems == []
    assert ran(standins, since=calls) == [claude("uninstall", "b@tack"), codex("remove", "b@tack")]
    assert changes(result) == [
        ("write", None, text.tilde(m / plugins.CATALOG)),
        ("uninstall", "claude-code", claude("uninstall", "b@tack")),
        ("uninstall", "codex", codex("remove", "b@tack")),
        ("delete", None, text.tilde(m / "plugins" / "b")),
    ]
    assert [c.source for c in result.changes[1:3]] == ["one", "one"]
    assert set(record(cfg)["claude-code"]) == set(record(cfg)["codex"]) == {"a"}
    assert set(plugins.copies(cfg.paths)) == {"a"}
    assert set(installed(standins, "claude")) == set(installed(standins, "codex")) == {"a@tack"}


def test_deselecting_the_last_plugin_unregisters_then_deletes_the_marketplace(
    home: Path, standins: Standins
) -> None:
    source(home, "one", "a")
    cfg = configure(home, "one", one="*")
    run(cfg)
    m = cfg.paths.marketplace_dir
    calls = len(standins.calls())

    result = run(configure(home, "one"))

    assert result.problems == []
    # Uninstall before unregister in both: Codex's `marketplace remove` leaves plugins installed.
    assert ran(standins, since=calls) == [
        claude("uninstall", "a@tack"),
        claude("marketplace", "remove", "tack"),
        codex("remove", "a@tack"),
        codex("marketplace", "remove", "tack"),
    ]
    assert changes(result)[-1] == ("delete", None, text.tilde(m))
    assert [a for a, _, _ in changes(result)] == [
        "write", "uninstall", "unregister", "uninstall", "unregister", "delete",
    ]  # fmt: skip
    assert not os.path.lexists(m)
    assert record(cfg) == {}
    assert "plugins" not in json.loads((cfg.paths.state_dir / deploy.RECORD).read_text())
    for cli_name in ("claude", "codex"):
        assert installed(standins, cli_name) == registered(standins, cli_name) == {}

    # Then nothing is involved: no call at all.
    calls = len(standins.calls())
    again = run(configure(home, "one"))
    assert (again.changes, again.problems) == ([], [])
    assert len(standins.calls()) == calls


def test_a_failed_unregister_leaves_a_catalog_matching_the_remaining_copies(
    home: Path, standins: Standins
) -> None:
    source(home, "one", "a")
    cfg = configure(home, "one", one="*")
    assert run(cfg).problems == []
    m = cfg.paths.marketplace_dir
    assert set(plugins.copies(cfg.paths)) == {"a"}
    standins.fail("codex", ["plugin", "marketplace", "remove", "tack"], "busy")
    calls = len(standins.calls())

    result = run(configure(home, "one"))

    (problem,) = result.problems
    assert (problem.kind, problem.harness, problem.message) == (
        "agent",
        "codex",
        "unregistering tack's marketplace failed: busy",
    )
    assert changes(result)[0] == ("write", None, text.tilde(m / plugins.CATALOG))
    assert ran(standins, since=calls) == [
        claude("uninstall", "a@tack"),
        claude("marketplace", "remove", "tack"),
        codex("remove", "a@tack"),
        codex("marketplace", "remove", "tack"),
    ]
    assert m.is_dir()
    assert (
        set(plugins.copies(cfg.paths))
        == {p["name"] for p in json.loads((m / plugins.CATALOG).read_text())["plugins"]}
        == set()
    )
    assert record(cfg) == {}
    assert "tack" in registered(standins, "codex")
    for cli_name in ("claude", "codex"):
        assert installed(standins, cli_name) == {}


def test_a_plugin_limited_to_codex_leaves_claude_code_unregistered(
    home: Path, standins: Standins
) -> None:
    source(home, "one", "a")
    cfg = configure(home, "one", one=[{"name": "a", "harnesses": ["codex"]}])
    result = run(cfg)
    assert result.problems == []
    assert standins.calls("claude") == []  # not involved: nothing targets it yet
    assert ran(standins, "codex") == [
        codex("marketplace", "add", str(cfg.paths.marketplace_dir)),
        codex("add", "a@tack"),
    ]
    again = run(cfg)  # the marketplace exists now, so Claude Code is listed, no more
    assert (again.changes, again.problems) == ([], [])
    assert ran(standins, "claude") == []
    assert registered(standins, "claude") == {}
    assert set(record(cfg)) == {"codex"}

    # Limiting a plugin installed in both to Codex takes it out of Claude Code.
    run(configure(home, "one", one="*"))
    calls = len(standins.calls())
    run(cfg)
    assert ran(standins, since=calls) == [
        claude("uninstall", "a@tack"),
        claude("marketplace", "remove", "tack"),
    ]
    assert set(installed(standins, "codex")) == {"a@tack"}
    assert registered(standins, "claude") == {}


def test_hidden_and_vanished_installs_when_deselected(home: Path, standins: Standins) -> None:
    source(home, "one", "a", "b")
    run(configure(home, "one", one="*"))
    # Claude Code's `b` was uninstalled by hand: its list doesn't show it.
    state = standins.state()
    del state["claude"]["plugins"]["b@tack"]
    (standins.directory / "state.json").write_text(json.dumps(state))
    calls = len(standins.calls())

    cfg = configure(home, "one", one=["a"])
    result = run(cfg)

    # Claude Code's is forgotten with no command; Codex's is uninstalled.
    assert ran(standins, since=calls) == [codex("remove", "b@tack")]
    assert result.problems == []
    assert set(record(cfg)["claude-code"]) == set(record(cfg)["codex"]) == {"a"}
    assert set(installed(standins, "codex")) == {"a@tack"}


def test_codex_list_hides_a_recorded_plugin(home: Path, standins: Standins) -> None:
    # A plugin the record lists but `codex plugin list` doesn't show (its
    # catalog entry is gone) is uninstalled when deselected.
    source(home, "one", "a", "b")
    cfg = configure(home, "one", one="*")
    run(cfg)
    m = cfg.paths.marketplace_dir
    catalog_file = m / plugins.CATALOG
    doc = json.loads(catalog_file.read_text())
    doc["plugins"] = [p for p in doc["plugins"] if p["name"] != "b"]
    catalog_file.write_text(json.dumps(doc))
    shown = agents.inventory("codex", cfg.paths)
    assert isinstance(shown, agents.Inventory)
    assert [p.name for p in shown.plugins] == ["a"]
    calls = len(standins.calls())

    run(configure(home, "one", one=["a"]))

    assert codex("remove", "b@tack") in ran(standins, since=calls)
    assert set(installed(standins, "codex")) == {"a@tack"}


# --- what tack leaves alone -----------------------------------------------------------


def test_a_disabled_plugin_is_neither_installed_again_nor_enabled(
    home: Path, standins: Standins
) -> None:
    source(home, "one", "a")
    cfg = configure(home, "one", one="*")
    run(cfg)
    standins.plugin("claude", "a@tack", enabled=False)
    standins.plugin("codex", "a@tack", enabled=False)
    calls = len(standins.calls())
    result = run(cfg)
    assert (result.changes, result.problems) == ([], [])
    assert ran(standins, since=calls) == []
    assert installed(standins, "claude")["a@tack"]["enabled"] is False
    assert installed(standins, "codex")["a@tack"]["enabled"] is False


def test_a_claude_code_install_at_another_scope_is_not_tacks(
    home: Path, standins: Standins
) -> None:
    source(home, "one", "a")
    standins.plugin("claude", "a@tack", scope="project")
    run(configure(home, "one", one="*"))
    assert claude("install", "a@tack") in ran(standins, "claude")


@pytest.mark.parametrize("adopt", [False, True])
def test_a_foreign_tack_marketplace_is_a_conflict(
    home: Path, standins: Standins, adopt: bool
) -> None:
    source(home, "one", "a")
    elsewhere = home / "elsewhere"
    market(elsewhere, name="tack")
    standins.marketplace("codex", "tack", elsewhere)
    # Another marketplace's plugin, in both: never touched.
    for cli_name in ("claude", "codex"):
        standins.marketplace(cli_name, "other", "acme/other", kind="github", plugins=["z"])
        standins.plugin(cli_name, "z@other")
    cfg = configure(home, "one", one="*")

    result = run(cfg, adopt=adopt)

    (problem,) = result.problems
    assert (problem.kind, problem.harness) == ("conflict", "codex")
    assert text.tilde(elsewhere) in problem.message
    assert ran(standins, "codex") == []
    assert set(installed(standins, "claude")) == {"a@tack", "z@other"}
    assert registered(standins, "codex")["tack"]["location"] == str(elsewhere)
    assert set(record(cfg)) == {"claude-code"}

    # Deselecting everything uninstalls tack's only.
    run(configure(home, "one"))
    for cli_name in ("claude", "codex"):
        assert set(installed(standins, cli_name)) == {"z@other"}
        assert "other" in registered(standins, cli_name)
    assert not [line for line in ran(standins) if "other" in line]


def test_a_foreign_tack_makes_the_cli_exit_1(home: Path, standins: Standins) -> None:
    # The manifest selects no plugin, but the record lists one in Codex.
    cfg = configure(home, "one")
    (home / "one" / "skills").mkdir(parents=True)
    deploy.save_record(cfg.paths, deploy.Record({}, {"codex": {"a": Install("one", "h")}}))
    standins.marketplace("codex", "tack", home / "elsewhere")
    assert cli.main(["sync", "--no-commit"]) == 1
    assert ran(standins) == []
    assert standins.calls("claude") == []
    assert record(cfg) == {"codex": {"a": Install("one", "h")}}


# --- missing and failing agents ----------------------------------------------------------


def test_a_missing_cli_where_a_plugin_goes(home: Path, standins: Standins) -> None:
    one = source(home, "one", "a")
    skill(one / "skills", "s")
    standins.remove("codex")
    cfg = configure(home, "one", one="*")

    result = run(cfg)

    (problem,) = result.problems
    assert (problem.kind, problem.harness) == ("agent", "codex")
    assert "`codex` isn't on PATH" in problem.message
    assert (home / ".claude" / "skills" / "s").is_symlink()  # the skills still link
    assert (home / ".agents" / "skills" / "s").is_symlink()
    assert set(installed(standins, "claude")) == {"a@tack"}
    assert set(record(cfg)) == {"claude-code"}


def test_a_missing_cli_nothing_targets(
    home: Path, standins: Standins, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(home, "one", "a")
    standins.remove("codex")
    tried: list[agents.Command] = []
    real = agents.run

    def spy(command: agents.Command, paths: Any) -> agents.Outcome:
        tried.append(command)
        return real(command, paths)

    monkeypatch.setattr(agents, "run", spy)
    result = run(configure(home, "one", one=[{"name": "a", "harnesses": ["claude-code"]}]))
    assert result.problems == []
    assert {c.harness for c in tried} == {"claude-code"}

    # Once the marketplace exists Codex is involved, and its missing CLI is passed over.
    tried.clear()
    result = run(configure(home, "one", one=[{"name": "a", "harnesses": ["claude-code"]}]))
    assert result.problems == []
    assert [c.kind for c in tried if c.harness == "codex"] == ["list"]


def test_a_failed_install(home: Path, standins: Standins) -> None:
    source(home, "one", "a", "b")
    standins.fail("codex", ["plugin", "add", "a@tack"], "the cache is read-only")
    cfg = configure(home, "one", one="*")

    result = run(cfg)

    (problem,) = result.problems
    assert (problem.kind, problem.source, problem.harness) == ("agent", "one", "codex")
    assert problem.message == "installing a failed: the cache is read-only"
    assert ("install", "codex", codex("add", "a@tack")) not in changes(result)
    assert set(installed(standins, "codex")) == {"b@tack"}
    assert set(record(cfg)["codex"]) == {"b"}
    assert set(record(cfg)["claude-code"]) == {"a", "b"}


def test_a_failed_list_stops_that_harness(home: Path, standins: Standins) -> None:
    source(home, "one", "a")
    standins.fail("claude", ["plugin", "list"], "not logged in")
    cfg = configure(home, "one", one="*")

    result = run(cfg)

    (problem,) = result.problems
    assert (problem.kind, problem.harness) == ("agent", "claude-code")
    assert problem.message == "listing its plugins failed: not logged in"
    assert [c.args[:2] for c in standins.calls("claude")] == [["plugin", "list"]]
    assert set(installed(standins, "codex")) == {"a@tack"}
    assert set(record(cfg)) == {"codex"}


def test_a_failed_uninstall_keeps_the_copy_and_the_record(home: Path, standins: Standins) -> None:
    source(home, "one", "a", "b")
    run(configure(home, "one", one="*"))
    standins.fail("claude", ["plugin", "uninstall", "b@tack"], "busy")
    cfg = configure(home, "one", one=["a"])

    result = run(cfg)

    (problem,) = result.problems
    assert (problem.kind, problem.source, problem.message) == (
        "agent",
        "one",
        "uninstalling b failed: busy",
    )
    assert set(record(cfg)["claude-code"]) == {"a", "b"}
    assert set(record(cfg)["codex"]) == {"a"}
    assert set(plugins.copies(cfg.paths)) == {"a", "b"}


# --- collisions, and plugins tack can't deploy ------------------------------------------------


def test_collisions_deploy_neither_and_leave_the_name_as_it_was(
    home: Path, standins: Standins
) -> None:
    source(home, "one", "a", "x")
    source(home, "two", "x")
    cfg = configure(home, "one", "two", one=["x"], two=["x"])
    result = run(cfg)
    assert [(p.kind, p.path) for p in result.problems] == [("collision", cfg.manifest)]
    assert result.problems[0].message.startswith("plugin 'x' is selected from sources one, two")
    assert ran(standins) == [  # registered, as a selected plugin targets each harness
        claude("marketplace", "add", str(cfg.paths.marketplace_dir)),
        codex("marketplace", "add", str(cfg.paths.marketplace_dir)),
    ]
    assert plugins.copies(cfg.paths) == {}

    # An earlier copy, catalog entry and installs of that name are left as they were.
    cfg = configure(home, "one", "two", one=["a", "x"])
    run(cfg)
    m = cfg.paths.marketplace_dir
    write(home / "one" / "plugins" / "x" / "skills" / "x" / "SKILL.md", "Changed.\n")
    before = (tree(m), record(cfg)["codex"]["x"])
    calls = len(standins.calls())
    cfg = configure(home, "one", "two", one=["a", "x"], two=["x"])
    result = run(cfg)
    assert [p.kind for p in result.problems] == ["collision"]
    assert result.changes == []
    assert ran(standins, since=calls) == []
    assert (tree(m), record(cfg)["codex"]["x"]) == before
    for cli_name in ("claude", "codex"):
        assert set(installed(standins, cli_name)) == {"a@tack", "x@tack"}


def test_claude_code_stays_registered_while_a_kept_plugin_is_installed(
    home: Path, standins: Standins
) -> None:
    # `x` collides in Codex only, and Claude Code still has it: unregistering
    # there would uninstall it (DEC-13).
    source(home, "one", "x")
    source(home, "two", "x")
    run(configure(home, "one", "two", one=["x"]))
    calls = len(standins.calls())
    only_codex = [{"name": "x", "harnesses": ["codex"]}]
    result = run(configure(home, "one", "two", one=only_codex, two=only_codex))
    assert [p.kind for p in result.problems] == ["collision"]
    assert ran(standins, since=calls) == []
    assert "tack" in registered(standins, "claude")
    assert set(installed(standins, "claude")) == {"x@tack"}


def test_plugins_tack_cannot_deploy(home: Path, standins: Standins) -> None:
    remote = {"name": "r", "source": {"source": "github", "repo": "acme/r", "sha": SHA}}
    source(home, "one", "a", entries=({"name": "n", "source": NPM}, remote))
    broken = home / "broken"
    (broken / "skills").mkdir(parents=True)
    write(broken / ".claude-plugin" / "marketplace.json", "{")
    cfg = configure(home, "one", "broken", one="*", broken="*")

    result = run(cfg)

    catalog_file = home / "one" / ".claude-plugin" / "marketplace.json"
    assert [(p.kind, p.source, p.path) for p in result.problems] == [
        ("source", "one", catalog_file),
        ("source", "one", catalog_file),
        ("source", "broken", broken / ".claude-plugin" / "marketplace.json"),
    ]
    n, r, b = (p.message for p in result.problems)
    assert n == "plugin 'n' can't be deployed: `npm` sources can't be pinned"
    assert r.startswith("plugin 'r' is in another repository (https://github.com/acme/r.git)")
    assert b.startswith(str(broken / ".claude-plugin" / "marketplace.json"))
    for cli_name in ("claude", "codex"):
        assert set(installed(standins, cli_name)) == {"a@tack"}
    assert set(plugins.copies(cfg.paths)) == {"a"}


def test_a_broken_plugin_fails_alone_and_keeps_its_copy_and_installs(
    home: Path, standins: Standins
) -> None:
    one = source(home, "one", "a", "b")
    elsewhere = write(home / "shared" / "notes.md", "Shared notes.\n")
    link(one / "plugins" / "b" / "notes.md", elsewhere)
    cfg = configure(home, "one", one="*")
    run(cfg)
    copy_b = cfg.paths.marketplace_dir / "plugins" / "b" / "notes.md"
    assert not copy_b.is_symlink()
    assert copy_b.read_text() == "Shared notes.\n"

    write(one / "plugins" / "a" / "skills" / "a" / "SKILL.md", "Changed.\n")
    link(one / "plugins" / "a" / "dangling", home / "nowhere")
    write(one / "plugins" / "b" / "skills" / "b" / "SKILL.md", "Changed too.\n")
    before = (tree(cfg.paths.marketplace_dir / "plugins" / "a"), record(cfg)["codex"]["a"])
    calls = len(standins.calls())

    result = run(cfg)

    (problem,) = result.problems
    assert (problem.kind, problem.source, problem.path) == ("source", "one", one / "plugins" / "a")
    assert "dangling is a link to nowhere" in problem.message
    assert ran(standins, since=calls) == [codex("add", "b@tack")]  # a is left alone
    assert (tree(cfg.paths.marketplace_dir / "plugins" / "a"), record(cfg)["codex"]["a"]) == before
    for cli_name in ("claude", "codex"):
        assert set(installed(standins, cli_name)) == {"a@tack", "b@tack"}


# --- a dry run, and a manifest without plugins ------------------------------------------------


def test_a_dry_run_runs_only_list_and_writes_nothing(home: Path, standins: Standins) -> None:
    one = source(home, "one", "a", "b", "c")
    cfg = configure(home, "one", one=["a", "b"])
    run(cfg)
    write(one / "plugins" / "a" / "skills" / "a" / "SKILL.md", "Changed.\n")
    before, agents_before, calls = tree(home), standins.state(), len(standins.calls())

    result = run(configure(home, "one", one=["a", "c"]), dry_run=True)

    assert result.problems == []
    assert all(listing(c) for c in standins.calls()[calls:])
    assert len(standins.calls()) == calls + 4
    assert tree(home) == before
    assert standins.state() == agents_before
    assert [(a, w, d) for a, w, d in changes(result) if a not in ("copy", "write", "delete")] == [
        ("install", "claude-code", claude("install", "c@tack")),
        ("uninstall", "claude-code", claude("uninstall", "b@tack")),
        ("reinstall", "codex", codex("add", "a@tack")),
        ("install", "codex", codex("add", "c@tack")),
        ("uninstall", "codex", codex("remove", "b@tack")),
    ]
    m = cfg.paths.marketplace_dir
    assert [
        (a, d.split(" ")[0]) for a, _, d in changes(result) if a in ("copy", "write", "delete")
    ] == [
        ("copy", "a"),
        ("copy", "c"),
        ("write", text.tilde(m / plugins.CATALOG)),
        ("delete", text.tilde(m / "plugins" / "b")),
    ]


def test_a_first_dry_run(home: Path, standins: Standins) -> None:
    source(home, "one", "a")
    cfg = configure(home, "one", one="*")
    before = tree(home)
    result = run(cfg, dry_run=True)
    assert result.problems == []
    assert all(listing(c) for c in standins.calls())
    assert tree(home) == before
    m = str(cfg.paths.marketplace_dir)
    assert [d for a, _, d in changes(result) if a in ("register", "install")] == [
        claude("marketplace", "add", m),
        claude("install", "a@tack"),
        codex("marketplace", "add", m),
        codex("add", "a@tack"),
    ]


def test_a_manifest_without_plugins_runs_no_agent(home: Path, standins: Standins) -> None:
    # The `plugins` key a skills-only sync writes is no different from before.
    one = source(home, "one", "a")
    skill(one / "skills", "s")
    write(home / "two" / ".claude-plugin" / "marketplace.json", "{")  # never read
    (home / "two" / "skills").mkdir(parents=True)
    cfg = configure(home, "one", "two")

    result = run(cfg)

    assert result.problems == []
    assert [c.action for c in result.changes] == ["link", "link"]
    assert standins.calls() == []
    assert not os.path.lexists(cfg.paths.marketplace_dir)
    file = cfg.paths.state_dir / deploy.RECORD
    links = {
        str(home / d / "skills" / "s"): str(one / "skills" / "s") for d in (".agents", ".claude")
    }
    assert file.read_text() == json.dumps({"version": 1, "links": links}, indent=2) + "\n"


# --- the text output -----------------------------------------------------------------------


def lines(result: sync.Result) -> list[str]:
    return [" ".join(line.split()) for line in text.result_text(result, "idle").splitlines()]


def test_the_text_output(home: Path, standins: Standins) -> None:
    one = source(home, "one", "a", "b")
    cfg = configure(home, "one", one="*")
    m = cfg.paths.marketplace_dir

    out = lines(run(cfg, dry_run=True))
    assert f"one would copy a from {text.tilde(one / 'plugins' / 'a')}" in out
    assert f"claude-code would run {claude('marketplace', 'add', str(m))}" in out
    assert f"codex would run {codex('add', 'a@tack')}" in out

    run(cfg)
    write(one / "plugins" / "a" / "skills" / "a" / "SKILL.md", "Changed.\n")
    out = lines(run(configure(home, "one", one=["a"])))
    assert f"one copied a from {text.tilde(one / 'plugins' / 'a')}" in out
    assert f"codex ran {codex('add', 'a@tack')}" in out  # a reinstall
    assert f"claude-code ran {claude('uninstall', 'b@tack')}" in out

    out = lines(run(configure(home, "one")))
    assert f"claude-code ran {claude('marketplace', 'remove', 'tack')}" in out
    assert f"codex ran {codex('marketplace', 'remove', 'tack')}" in out
    assert f"deleted {text.tilde(m)}" in out

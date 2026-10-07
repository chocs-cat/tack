from __future__ import annotations

import json
import shlex
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tack import agents, cli, deploy, status, sync
from tack.config import Config
from tack.deploy import Install
from tests.helpers import configure, git, link, load, market, repo, skill, tree, upstream, write
from tests.standin import Standins

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("selection", ["[]", '"*"'])
def test_path_source_presence_without_a_skills_directory(home: Path, selection: str) -> None:
    root = home / "one"
    root.mkdir()
    cfg = load(home, f'[[source]]\nname = "one"\npath = "~/one"\nskills = {selection}\n')

    assert status.status(cfg).sources[0].state == ("ok" if selection == "[]" else "missing")
    root.rmdir()
    assert status.status(cfg).sources[0].state == "missing"


def test_status(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    tip = git(up, "rev-parse", "HEAD").strip()
    mine = repo(home / "mine", {"skills/a/SKILL.md": "---\ndescription: a\n---\n"})
    skill(mine / "skills", "b")  # uncommitted
    manifest = (
        '[[source]]\nname = "mine"\npath = "~/mine"\n'
        f'[[source]]\nname = "up"\ngit = "{up}"\nref = "master"\n'
        '[[source]]\nname = "gone"\npath = "~/gone"\n'
    )
    cfg = load(home, manifest)
    sync.sync(cfg, now=WHEN)
    (home / ".agents" / "skills" / "b").unlink()
    link(home / ".agents" / "skills" / "c", home)  # not a selected skill: not listed

    st = status.status(cfg)
    by_name = {s.name: s for s in st.sources}
    assert by_name["mine"].state == "ok"
    assert by_name["mine"].uncommitted == ["b"]
    assert by_name["gone"].state == "missing"
    up_status = by_name["up"]
    assert (up_status.state, up_status.commit, up_status.locked) == ("ok", tip, WHEN)
    assert up_status.skills == ["x"]
    assert [(k.name, k.source, k.harnesses) for k in st.skills] == [
        ("a", "mine", {"claude-code": "linked", "codex": "linked"}),
        ("b", "mine", {"claude-code": "linked", "codex": "missing"}),
        ("x", "up", {"claude-code": "linked", "codex": "linked"}),
    ]


def test_git_source_states(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    manifest = f'[[source]]\nname = "up"\ngit = "{up}"\n'
    cfg = load(home, manifest)

    def state() -> str:
        return status.status(cfg).sources[0].state

    assert state() == "not pinned"
    sync.sync(cfg, now=WHEN)
    assert state() == "ok"
    checkout = cfg.paths.sources_dir / "up"
    write(checkout / "skills" / "x" / "SKILL.md", "edited")
    assert state() == "local changes"
    git(checkout, "checkout", "-q", "--", ".")
    git(up, "commit", "-q", "--allow-empty", "-m", "later")
    git(checkout, "fetch", "-q")
    git(checkout, "checkout", "-q", "--detach", "origin/master")
    assert state() == "off its pin"
    shutil.rmtree(checkout)
    assert state() == "not checked out"
    cfg = load(home, manifest + 'ref = "master"\n')
    assert status.status(cfg).sources[0].state == "manifest changed"


def test_collisions_and_conflicts(home: Path) -> None:
    skill(home / "one" / "skills", "dup")
    skill(home / "two" / "skills", "dup")
    skill(home / "one" / "skills", "solo")
    skill(home / ".claude" / "skills", "solo")  # a real directory in the way
    cfg = load(
        home,
        '[[source]]\nname = "one"\npath = "~/one"\n'
        '[[source]]\nname = "two"\npath = "~/two"\nharnesses = ["codex"]\n',
    )
    st = status.status(cfg)
    assert [(k.name, k.source, k.harnesses) for k in st.skills] == [
        ("dup", "one", {"claude-code": "missing", "codex": "collision"}),
        ("dup", "two", {"codex": "collision"}),
        ("solo", "one", {"claude-code": "conflict", "codex": "missing"}),
    ]


# --- plugins (design.md §9 *Plugin states*) -----------------------------------------

BOTH = ("claude-code", "codex")
NPM = {"source": "npm", "package": "@acme/x"}


def plugin_source(home: Path, name: str, *plugin_names: str, entries: tuple[Any, ...] = ()) -> Path:
    """A `path` source at `~/<name>` with an empty skills directory and a
    catalog listing each plugin, its files under `plugins/<plugin>`, then
    `entries` as they are."""
    root = home / name
    (root / "skills").mkdir(parents=True, exist_ok=True)
    for p in plugin_names:
        write(root / "plugins" / p / ".claude-plugin" / "plugin.json", json.dumps({"name": p}))
        write(root / "plugins" / p / "skills" / p / "SKILL.md", f"The {p} skill.\n")
    listed = [{"name": p, "source": f"./plugins/{p}", "version": "1.0"} for p in plugin_names]
    return market(root, *listed, *entries)


def states(st: status.Status) -> dict[tuple[str, str], dict[str, str]]:
    return {(p.name, p.source): dict(p.harnesses) for p in st.plugins}


def run_sync(cfg: Config) -> sync.Result:
    result = sync.sync(cfg, now=WHEN)
    assert [p for p in result.problems if p.kind != "conflict"] == []
    return result


def edit_plugin(home: Path) -> None:
    write(home / "one" / "plugins" / "a" / "skills" / "a" / "SKILL.md", "Edited.\n")


def one(home: Path) -> Config:
    plugin_source(home, "one", "a")
    return configure(home, "one", one=["a"])


def colliding(home: Path) -> Config:
    plugin_source(home, "one", "a", "b")
    plugin_source(home, "two", "a")
    return configure(home, "one", "two:codex", one=["a", "b"], two=["a"])


def _missing(home: Path, standins: Standins) -> Config:
    return one(home)


def _installed(home: Path, standins: Standins) -> Config:
    cfg = one(home)
    run_sync(cfg)
    return cfg


def _stale_copy(home: Path, standins: Standins) -> Config:
    cfg = _installed(home, standins)
    edit_plugin(home)
    return cfg


def _stale_codex_hash(home: Path, standins: Standins) -> Config:
    cfg = _installed(home, standins)
    rec = deploy.load_record(cfg.paths)
    rec.plugins["codex"]["a"] = Install("one", "0" * 64)
    deploy.save_record(cfg.paths, rec)
    return cfg


def _disabled(home: Path, standins: Standins) -> Config:
    cfg = _installed(home, standins)
    standins.plugin("claude", "a@tack", enabled=False)
    return cfg


def _conflict(home: Path, standins: Standins) -> Config:
    cfg = _installed(home, standins)
    standins.marketplace("codex", "tack", home / "elsewhere")
    return cfg


def _collision(home: Path, standins: Standins) -> Config:
    return colliding(home)


def _no_cli(home: Path, standins: Standins) -> Config:
    standins.remove("codex")
    return one(home)


def _list_fails(home: Path, standins: Standins) -> Config:
    cfg = _installed(home, standins)
    standins.fail("claude", ["plugin", "list"], "not logged in")
    return cfg


def _marketplace_list_fails(home: Path, standins: Standins) -> Config:
    cfg = _installed(home, standins)
    standins.fail("codex", ["plugin", "marketplace", "list"], "config.toml is broken")
    return cfg


def _unreadable(home: Path, standins: Standins) -> Config:
    cfg = _installed(home, standins)
    shutil.rmtree(home / "one" / "plugins" / "a")  # its copy would fail: never stale
    return cfg


def _disabled_and_stale(home: Path, standins: Standins) -> Config:
    cfg = _disabled(home, standins)
    edit_plugin(home)
    return cfg


def _collision_without_cli(home: Path, standins: Standins) -> Config:
    standins.remove("claude")
    return colliding(home)


# Each fixture, and the state it gives each plugin in each harness it targets.
FIXTURES: dict[str, tuple[Callable[[Path, Standins], Config], dict[tuple[str, str], dict]]] = {
    "missing": (_missing, {("a", "one"): dict.fromkeys(BOTH, "missing")}),
    "installed": (_installed, {("a", "one"): dict.fromkeys(BOTH, "installed")}),
    "stale copy": (_stale_copy, {("a", "one"): dict.fromkeys(BOTH, "stale")}),
    "stale in codex": (
        _stale_codex_hash,
        {("a", "one"): {"claude-code": "installed", "codex": "stale"}},
    ),
    "disabled": (_disabled, {("a", "one"): {"claude-code": "disabled", "codex": "installed"}}),
    "conflict": (_conflict, {("a", "one"): {"claude-code": "installed", "codex": "conflict"}}),
    "collision": (
        _collision,
        {
            ("a", "one"): dict.fromkeys(BOTH, "collision"),
            ("a", "two"): {"codex": "collision"},
            ("b", "one"): dict.fromkeys(BOTH, "missing"),
        },
    ),
    "no cli": (_no_cli, {("a", "one"): {"claude-code": "missing", "codex": "unavailable"}}),
    "list fails": (
        _list_fails,
        {("a", "one"): {"claude-code": "unavailable", "codex": "installed"}},
    ),
    "marketplace list fails": (
        _marketplace_list_fails,
        {("a", "one"): {"claude-code": "installed", "codex": "unavailable"}},
    ),
    "unreadable": (_unreadable, {("a", "one"): dict.fromkeys(BOTH, "installed")}),
    # DEC-15's order where states overlap.
    "disabled and stale": (
        _disabled_and_stale,
        {("a", "one"): {"claude-code": "disabled", "codex": "stale"}},
    ),
    "collision without a cli": (
        _collision_without_cli,
        {
            ("a", "one"): dict.fromkeys(BOTH, "collision"),
            ("a", "two"): {"codex": "collision"},
            ("b", "one"): {"claude-code": "unavailable", "codex": "missing"},
        },
    ),
}


@pytest.mark.parametrize("fixture", FIXTURES)
def test_plugin_states(home: Path, standins: Standins, fixture: str) -> None:
    build, expected = FIXTURES[fixture]
    cfg = build(home, standins)
    assert states(status.status(cfg)) == expected


def _plugin_of(change: sync.Change) -> str:
    """The plugin a `copy`, `install` or `reinstall` change is for."""
    if change.action == "copy":
        return change.detail.split(" ", 1)[0]
    (plugin_id,) = [a for a in shlex.split(change.detail) if a.endswith("@tack")]
    return plugin_id.removesuffix("@tack")


@pytest.mark.parametrize("fixture", FIXTURES)
def test_plugin_states_agree_with_sync(home: Path, standins: Standins, fixture: str) -> None:
    """`stale` is what a sync would copy or reinstall, among the plugins
    `status` calls `stale` or `installed`, and `missing` what it would
    install; after a real sync, those are `installed`."""
    cfg = FIXTURES[fixture][0](home, standins)
    st = status.status(cfg)
    cells = {(p.name, h): s for p in st.plugins for h, s in p.harnesses.items()}
    dry = sync.sync(cfg, dry_run=True, now=WHEN)
    copied = {_plugin_of(c) for c in dry.changes if c.action == "copy"}
    reinstalled = {(_plugin_of(c), c.harness) for c in dry.changes if c.action == "reinstall"}
    installs = {(_plugin_of(c), c.harness) for c in dry.changes if c.action == "install"}

    fresh_or_stale = {k for k, s in cells.items() if s in ("installed", "stale")}
    assert {(n, h) for n, h in fresh_or_stale if n in copied or (n, h) in reinstalled} == {
        k for k, s in cells.items() if s == "stale"
    }
    assert installs == {k for k, s in cells.items() if s == "missing"}

    fixed = {k for k, s in cells.items() if s in ("missing", "stale")}
    sync.sync(cfg, now=WHEN)
    after = status.status(cfg)
    assert {
        (p.name, h) for p in after.plugins for h, s in p.harnesses.items() if s == "installed"
    } >= fixed


@pytest.mark.parametrize(
    ("collision", "unavailable", "conflict", "installed", "enabled", "stale", "state"),
    [
        (True, True, True, False, False, True, "collision"),
        (False, True, True, True, False, True, "unavailable"),
        (False, False, True, False, False, True, "conflict"),
        (False, False, False, False, False, True, "missing"),
        (False, False, False, True, False, True, "disabled"),
        (False, False, False, True, True, True, "stale"),
        (False, False, False, True, True, False, "installed"),
        (False, False, False, True, False, False, "disabled"),
    ],
)
def test_the_first_state_that_applies(
    collision: bool,
    unavailable: bool,
    conflict: bool,
    installed: bool,
    enabled: bool,
    stale: bool,
    state: str,
) -> None:
    """DEC-15: collision, unavailable, conflict, missing, disabled, stale, installed."""
    assert (
        status.plugin_state(
            collision=collision,
            unavailable=unavailable,
            conflict=conflict,
            installed=installed,
            enabled=enabled,
            stale=stale,
        )
        == state
    )


def test_a_claude_code_install_at_another_scope_is_missing(home: Path, standins: Standins) -> None:
    """Installed means at user scope in Claude Code, as `sync` reads it. (The
    stand-in holds one install per id, so a real sync can't add the user one.)"""
    cfg = _installed(home, standins)
    standins.plugin("claude", "a@tack", scope="project")

    assert states(status.status(cfg)) == {
        ("a", "one"): {"claude-code": "missing", "codex": "installed"}
    }
    dry = sync.sync(cfg, dry_run=True, now=WHEN)
    assert [(c.action, c.harness) for c in dry.changes] == [("install", "claude-code")]


def test_a_plugin_tack_cant_deploy(home: Path, standins: Standins) -> None:
    plugin_source(home, "one", entries=({"name": "x", "source": NPM, "version": "2.0"},))
    cfg = configure(home, "one", one=["x"])
    sync.sync(cfg, now=WHEN)

    (p,) = status.status(cfg).plugins
    assert (p.name, p.harnesses, p.version, p.path) == (
        "x",
        dict.fromkeys(BOTH, "missing"),
        "2.0",
        None,
    )


def test_a_plugins_version_and_copy(home: Path, standins: Standins) -> None:
    root = plugin_source(home, "one", "a", "b")
    write(root / "plugins" / "a" / "plugin.json", json.dumps({"version": "3.1"}))
    cfg = configure(home, "one", one="*")

    def seen() -> list[tuple[str, str | None, Path | None]]:
        return [(p.name, p.version, p.path) for p in status.status(cfg).plugins]

    assert seen() == [("a", "3.1", None), ("b", "1.0", None)]
    run_sync(cfg)
    copies = cfg.paths.marketplace_dir / "plugins"
    assert seen() == [("a", "3.1", copies / "a"), ("b", "1.0", copies / "b")]


def test_each_source_lists_the_plugins_it_selects(home: Path, standins: Standins) -> None:
    plugin_source(home, "one", "a", "b")
    plugin_source(home, "two", "c")
    write(home / "broken" / ".claude-plugin" / "marketplace.json", "{")
    (home / "broken" / "skills").mkdir()
    cfg = configure(home, "one", "two", "broken", "gone", one=["b", "nope"], broken="*", gone="*")

    st = status.status(cfg)
    assert {s.name: s.plugins for s in st.sources} == {
        "one": ["b"],
        "two": [],
        "broken": [],
        "gone": [],
    }
    assert [(p.name, p.source) for p in st.plugins] == [("b", "one")]


def test_status_reads_plugins_without_writing(home: Path, standins: Standins) -> None:
    """Only the two `list` commands run, once per targeted harness, and
    nothing is written or created, not even tack's data directory."""
    cfg = _installed(home, standins)
    shutil.rmtree(cfg.paths.data_dir)
    before, calls = tree(home), len(standins.calls())

    status.status(cfg)

    assert tree(home) == before
    assert not cfg.paths.data_dir.exists()
    assert sorted(" ".join([c.cli, *c.args]) for c in standins.calls()[calls:]) == [
        "claude plugin list --json",
        "claude plugin marketplace list --json",
        "codex plugin list --json",
        "codex plugin marketplace list --json",
    ]


def test_status_takes_the_inventories_it_is_given(home: Path, standins: Standins) -> None:
    """Handed an agent's inventory (the TUI's one reading), `status` doesn't
    list that agent again; it lists a targeted one it wasn't handed."""
    cfg = _disabled(home, standins)
    inventories = agents.inventories(cfg.paths, BOTH)
    start = len(standins.calls())

    assert states(status.status(cfg, inventories)) == FIXTURES["disabled"][1]
    assert standins.calls()[start:] == []
    assert states(status.status(cfg, {"codex": inventories["codex"]})) == FIXTURES["disabled"][1]
    assert sorted(" ".join([c.cli, *c.args]) for c in standins.calls()[start:]) == [
        "claude plugin list --json",
        "claude plugin marketplace list --json",
    ]


def test_a_plugin_limited_to_codex_runs_no_claude(home: Path, standins: Standins) -> None:
    plugin_source(home, "one", "a")
    cfg = configure(home, "one", one=[{"name": "a", "harnesses": ["codex"]}])

    assert states(status.status(cfg)) == {("a", "one"): {"codex": "missing"}}
    assert standins.calls("claude") == []
    assert len(standins.calls("codex")) == 2


def test_status_json_gives_plugins(
    home: Path, standins: Standins, capsys: pytest.CaptureFixture[str]
) -> None:
    _conflict(home, standins)
    plugin_source(home, "two", entries=({"name": "x", "source": NPM},))
    skill(home / "two" / "skills", "s")
    cfg = configure(home, "one", "two", one=["a"], two=["x"])
    capsys.readouterr()

    assert cli.main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [{k: s[k] for k in ("name", "skills", "plugins")} for s in data["sources"]] == [
        {"name": "one", "skills": [], "plugins": ["a"]},
        {"name": "two", "skills": ["s"], "plugins": ["x"]},
    ]
    assert data["plugins"] == [
        {
            "name": "a",
            "source": "one",
            "harnesses": {"claude-code": "installed", "codex": "conflict"},
            "version": "1.0",
            "path": str(cfg.paths.marketplace_dir / "plugins" / "a"),
        },
        {
            "name": "x",
            "source": "two",
            "harnesses": {"claude-code": "missing", "codex": "conflict"},
            "version": None,
            "path": None,
        },
    ]


def test_status_json_without_plugins_runs_no_agent(
    home: Path, standins: Standins, capsys: pytest.CaptureFixture[str]
) -> None:
    skill(home / "mine" / "skills", "a")
    load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')

    assert cli.main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["plugins"] == []
    assert data["sources"][0]["plugins"] == []
    assert standins.calls() == []

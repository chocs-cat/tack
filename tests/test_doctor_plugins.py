"""`doctor`'s plugin checks (design.md *`doctor` checks*, the *(P0001)*
paragraph), against the stand-in agents."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from tack import cli, doctor, status, sync
from tack.config import Config
from tack.doctor import plugins as doctor_plugins
from tack.doctor.findings import Finding
from tests.helpers import configure, load, skill, write
from tests.standin import Standins
from tests.test_status import BOTH, FIXTURES, NPM, WHEN, one, plugin_source, run_sync

SHA = "a" * 40
ELSEWHERE = {"source": "github", "repo": "acme/x", "sha": SHA}

# What each state's finding says.
_SAYS = {
    "missing": "isn't installed in",
    "disabled": "is turned off in",
    "stale": "is out of date in",
}


def check(cfg: Config) -> list[Finding]:
    return list(doctor_plugins.check(cfg))


def calls(standins: Standins, start: int = 0) -> list[str]:
    return sorted(" ".join([c.cli, *c.args]) for c in standins.calls()[start:])


LISTS = [
    "claude plugin list --json",
    "claude plugin marketplace list --json",
    "codex plugin list --json",
    "codex plugin marketplace list --json",
]


def _covered(f: Finding) -> dict[tuple[str, str], str]:
    """The (plugin, harness) cells a state finding is about, and the state."""
    assert f.harness is not None
    if f.path is not None:  # one plugin's
        name = re.match(r"plugin '([^']+)' from", f.message)
        (state,) = [s for s, says in _SAYS.items() if f"{says} {f.harness}" in f.message]
        assert name
        return {(name.group(1), f.harness): state}
    stopped = re.search(rf"can't deploy (plugins? .+?) to {f.harness}", f.message)
    assert stopped
    state = "conflict" if "isn't tack's" in f.message else "unavailable"
    return {(n, f.harness): state for n in re.findall(r"'([^']+)'", stopped.group(1))}


# --- agreement with `status` ----------------------------------------------------------


@pytest.mark.parametrize("fixture", FIXTURES)
def test_state_findings_agree_with_status(home: Path, standins: Standins, fixture: str) -> None:
    """The per-plugin and per-harness `not-synced` findings cover exactly the
    cells `status` gives a state other than `installed` and `collision`, each
    with that state's finding; a collision is `name-collision`'s alone."""
    cfg = FIXTURES[fixture][0](home, standins)
    st = status.status(cfg)
    cells = {
        (p.name, h): s
        for p in st.plugins
        for h, s in p.harnesses.items()
        if s not in ("installed", "collision")
    }

    found = check(cfg)
    covered: dict[tuple[str, str], str] = {}
    for f in found:
        if f.id == "name-collision" or f.harness is None:
            continue  # a collision's, or a source's: a plugin whose files can't be read
        assert (f.id, f.severity) == ("not-synced", "warn")
        here = _covered(f)
        assert not set(here) & set(covered), f"{f.message} reports a cell twice"
        covered.update(here)
    assert covered == cells
    collided = {p.name for p in st.plugins if "collision" in p.harnesses.values()}
    assert sorted(f.message.split("'")[1] for f in found if f.id == "name-collision") == sorted(
        collided
    )


# --- agreement with `sync` (leftovers) -------------------------------------------------


def _deselected(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a", "b")
    run_sync(configure(home, "one", one=["a", "b"]))
    return configure(home, "one", one=["a"])


def _narrowed(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a")
    run_sync(configure(home, "one", one=["a"]))
    return configure(home, "one", one=[{"name": "a", "harnesses": ["codex"]}])


def _by_hand(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a")
    cfg = configure(home, "one", one=["a"])
    run_sync(cfg)
    standins.plugin("claude", "x@tack")
    return cfg


def _by_hand_untouched(home: Path, standins: Standins) -> Config:
    """With nothing selected, recorded or in tack's marketplace, `sync` runs
    no agent, so it uninstalls nothing, not even a `name@tack`."""
    standins.plugin("claude", "x@tack")
    skill(home / "mine" / "skills", "s")
    return load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')


def _hidden_in_codex(home: Path, standins: Standins) -> Config:
    """b deselected, and taken out of tack's catalog by hand, so Codex's list
    hides it; the record still lists it there."""
    cfg = _deselected(home, standins)
    file = cfg.paths.marketplace_dir / ".claude-plugin" / "marketplace.json"
    data = json.loads(file.read_text())
    data["plugins"] = [p for p in data["plugins"] if p["name"] != "b"]
    file.write_text(json.dumps(data))
    return cfg


def _collided(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a")
    run_sync(configure(home, "one", one=["a"]))
    plugin_source(home, "two", "a")
    return configure(home, "one", "two:codex", one=["a"], two=["a"])


def _root_gone(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a")
    plugin_source(home, "two", "b")
    cfg = configure(home, "one", "two", one=["a"], two=["b"])
    run_sync(cfg)
    shutil.rmtree(home / "two")
    return cfg


def _broken(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a")
    plugin_source(home, "two", "b")
    cfg = configure(home, "one", "two", one=["a"], two=["b"])
    run_sync(cfg)
    write(home / "two" / ".claude-plugin" / "marketplace.json", "{")
    return cfg


def _unreadable_narrowed(home: Path, standins: Standins) -> Config:
    """A plugin whose copy would fail is kept wherever it is (design.md
    *Deploying*), so narrowing it uninstalls nothing."""
    cfg = _narrowed(home, standins)
    shutil.rmtree(home / "one" / "plugins" / "a")
    return cfg


LEFTOVERS: dict[str, tuple[Callable[[Path, Standins], Config], set[tuple[str, str]]]] = {
    "deselected": (_deselected, {("b", "claude-code"), ("b", "codex")}),
    "narrowed to codex": (_narrowed, {("a", "claude-code")}),
    "installed by hand": (_by_hand, {("x", "claude-code")}),
    "installed by hand, nothing deployed": (_by_hand_untouched, set()),
    "hidden in codex": (_hidden_in_codex, {("b", "claude-code"), ("b", "codex")}),
    "collided": (_collided, set()),
    "root gone": (_root_gone, set()),
    "catalog broken": (_broken, set()),
    "unreadable and narrowed": (_unreadable_narrowed, set()),
}


def _uninstalled(change: sync.Change) -> tuple[str, str]:
    (plugin_id,) = [a for a in shlex.split(change.detail) if a.endswith("@tack")]
    assert change.harness
    return plugin_id.removesuffix("@tack"), change.harness


@pytest.mark.parametrize("case", LEFTOVERS)
def test_leftovers_agree_with_sync(home: Path, standins: Standins, case: str) -> None:
    build, expected = LEFTOVERS[case]
    cfg = build(home, standins)

    leftovers = {
        (f.message.split("@", 1)[0], f.harness)
        for f in check(cfg)
        if f.message.endswith("`tack sync` uninstalls it")
    }
    dry = sync.sync(cfg, dry_run=True, now=WHEN)
    assert leftovers == {_uninstalled(c) for c in dry.changes if c.action == "uninstall"}
    assert leftovers == expected


def test_a_leftover_finding(home: Path, standins: Standins) -> None:
    cfg = _narrowed(home, standins)
    (f,) = check(cfg)
    assert (f.id, f.severity, f.harness, f.path) == ("not-synced", "warn", "claude-code", None)
    assert f.message == (
        "a@tack is installed in claude-code, but the manifest doesn't deploy 'a' there; "
        "`tack sync` uninstalls it"
    )


def test_no_leftovers_in_a_harness_with_a_foreign_tack(home: Path, standins: Standins) -> None:
    cfg = _deselected(home, standins)
    standins.marketplace("codex", "tack", home / "elsewhere")

    found = check(cfg)
    assert [(f.harness, f.message.split(" ")[0]) for f in found] == [
        ("claude-code", "b@tack"),  # a leftover
        ("codex", "a"),  # the conflict, and nothing else there
    ]
    assert "isn't tack's" in found[1].message


# --- agreement with `sync` (problems, DEC-19) -------------------------------------------


def _gone(home: Path, standins: Standins) -> Config:
    """A selected plugin whose directory is gone, not yet installed."""
    cfg = one(home)
    shutil.rmtree(home / "one" / "plugins" / "a")
    return cfg


def _gone_but_kept(home: Path, standins: Standins) -> Config:
    """A plugin whose directory is gone, selected from one source and
    recorded from another whose catalog is broken: `sync` keeps it, so it
    copies nothing and its files' state is no problem (DEC-12)."""
    plugin_source(home, "one", "a")
    plugin_source(home, "two", "a", "b")
    run_sync(configure(home, "two", two=["a", "b"]))
    write(home / "two" / ".claude-plugin" / "marketplace.json", "{")
    shutil.rmtree(home / "one" / "plugins" / "a")
    return configure(home, "one", "two", one=["a"], two=["b"])


def _foreign_where_recorded(home: Path, standins: Standins) -> Config:
    """A foreign `tack` in Codex, where only the record lists plugins."""
    plugin_source(home, "one", "a")
    run_sync(configure(home, "one", one=["a"]))
    standins.marketplace("codex", "tack", home / "elsewhere")
    return configure(home, "one")


def _list_fails_where_recorded(home: Path, standins: Standins) -> Config:
    """Claude Code's `plugin list` fails, and only the record involves it."""
    plugin_source(home, "one", "a")
    cfg = configure(home, "one", one=["a"])
    run_sync(cfg)
    shutil.rmtree(cfg.paths.marketplace_dir)
    standins.fail("claude", ["plugin", "list"], "not logged in")
    return configure(home, "one", one=[{"name": "a", "harnesses": ["codex"]}])


def _list_fails_where_marketplace(home: Path, standins: Standins) -> Config:
    """Codex's `plugin list` fails, and only tack's marketplace directory
    involves it."""
    skill(home / "mine" / "skills", "s")
    cfg = load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')
    cfg.paths.marketplace_dir.mkdir(parents=True)
    standins.fail("codex", ["plugin", "list"], "config.toml is broken")
    return cfg


def _no_cli_undeployable(home: Path, standins: Standins) -> Config:
    """Codex's CLI is gone, and only a plugin tack can't deploy targets it."""
    plugin_source(home, "one", entries=({"name": "x", "source": NPM},))
    standins.remove("codex")
    return configure(home, "one", one=["x"])


def _undeployable(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a", entries=({"name": "x", "source": NPM},))
    return configure(home, "one", one=["a", "x"])


def _elsewhere(home: Path, standins: Standins) -> Config:
    plugin_source(home, "one", "a", entries=({"name": "r", "source": ELSEWHERE},))
    return configure(home, "one", one=["a", "r"])


PROBLEMS: dict[str, Callable[[Path, Standins], Config]] = {
    "directory gone, installed": FIXTURES["unreadable"][0],
    "directory gone, not installed": _gone,
    "directory gone, kept by its recorded source": _gone_but_kept,
    "foreign tack where only the record lists plugins": _foreign_where_recorded,
    "list fails where only the record involves it": _list_fails_where_recorded,
    "list fails where only the marketplace involves it": _list_fails_where_marketplace,
    "missing cli only an undeployable plugin targets": _no_cli_undeployable,
    "missing cli a deployable plugin targets": FIXTURES["no cli"][0],
    "broken catalog": _broken,
    "undeployable": _undeployable,
    "from another repository": _elsewhere,
    "collision": FIXTURES["collision"][0],
}


def _plugin_named(message: str) -> str | None:
    m = re.match(r"plugin '([^']+)'", message)
    return m.group(1) if m else None


@pytest.mark.parametrize("case", PROBLEMS)
def test_problems_agree_with_sync(home: Path, standins: Standins, case: str) -> None:
    """Each plugin problem a `sync` dry run reports has one finding, and each
    finding of these kinds one problem: `name-collision` and `collision` by
    name, a source's `not-synced` (but a name it lacks) and `source` by path
    and plugin, a harness's `unavailable` and `agent`, and its `conflict` and
    `conflict`, by harness."""
    cfg = PROBLEMS[case](home, standins)
    assert {s.state for s in status.status(cfg).sources} == {"ok"}
    found = [f for f in check(cfg) if not f.message.endswith("`tack sync` uninstalls it")]
    problems = sync.sync(cfg, dry_run=True, now=WHEN).problems
    assert problems
    assert {p.kind for p in problems} <= {"collision", "source", "agent", "conflict"}

    def harnesses(conflict: bool) -> Counter[str | None]:
        return Counter(
            f.harness
            for f in found
            if f.harness and f.path is None and ("isn't tack's" in f.message) == conflict
        )

    assert Counter(f.message.split("'")[1] for f in found if f.id == "name-collision") == Counter(
        p.message.split("'")[1] for p in problems if p.kind == "collision"
    )
    assert Counter(
        (f.path, _plugin_named(f.message))
        for f in found
        if f.id == "not-synced" and f.harness is None and "the manifest selects" not in f.message
    ) == Counter((p.path, _plugin_named(p.message)) for p in problems if p.kind == "source")
    assert harnesses(conflict=False) == Counter(p.harness for p in problems if p.kind == "agent")
    assert harnesses(conflict=True) == Counter(p.harness for p in problems if p.kind == "conflict")


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize("how", ["directory gone", "file unreadable"])
def test_a_plugin_whose_files_cant_be_read(
    home: Path, standins: Standins, installed: bool, how: str
) -> None:
    """One finding, at its directory, with the reason the dry run gives, and
    no state finding in either harness, whatever its state there."""
    if how == "file unreadable" and os.geteuid() == 0:
        pytest.skip("root reads any file")
    cfg = one(home)
    if installed:
        run_sync(cfg)
    directory = home / "one" / "plugins" / "a"
    if how == "directory gone":
        shutil.rmtree(directory)
    else:
        (directory / "skills" / "a" / "SKILL.md").chmod(0)

    (problem,) = sync.sync(cfg, dry_run=True, now=WHEN).problems
    assert (problem.kind, problem.path) == ("source", directory)
    reason = problem.message.removeprefix("plugin 'a': ")
    assert reason != problem.message
    states = {p.name: set(p.harnesses.values()) for p in status.status(cfg).plugins}
    assert states == {"a": {"installed" if installed else "missing"}}

    (f,) = check(cfg)
    assert (f.id, f.severity, f.path, f.harness) == ("not-synced", "warn", directory, None)
    assert (
        f.message == f"plugin 'a' from 'one' can't be copied, so tack leaves it as it is: {reason}"
    )


@pytest.mark.parametrize(
    ("case", "harness", "message"),
    [
        (
            "missing cli only an undeployable plugin targets",
            "codex",
            "`codex` isn't on PATH, so tack can't manage codex's plugins; install it",
        ),
        (
            "list fails where only the record involves it",
            "claude-code",
            "`claude plugin list --json` failed: not logged in; tack can't manage claude-code's "
            "plugins until it succeeds",
        ),
        (
            "list fails where only the marketplace involves it",
            "codex",
            "`codex plugin list --json` failed: config.toml is broken; tack can't manage codex's "
            "plugins until it succeeds",
        ),
        (
            "foreign tack where only the record lists plugins",
            "codex",
            "a marketplace named 'tack' from ~/elsewhere isn't tack's, so tack can't manage "
            "codex's plugins; remove or rename that marketplace",
        ),
    ],
)
def test_a_harness_finding_naming_no_plugin(
    home: Path, standins: Standins, case: str, harness: str, message: str
) -> None:
    cfg = PROBLEMS[case](home, standins)
    found = [f for f in check(cfg) if f.harness == harness and f.path is None]
    found = [f for f in found if not f.message.endswith("`tack sync` uninstalls it")]
    assert [(f.id, f.severity, f.message) for f in found] == [("not-synced", "warn", message)]


def test_a_harness_finding_leaves_out_an_unreadable_plugin(home: Path, standins: Standins) -> None:
    """A plugin whose files can't be read has its own finding, so the missing
    CLI's names only the others."""
    plugin_source(home, "one", "a", "b")
    cfg = configure(home, "one", one=["a", "b"])
    shutil.rmtree(home / "one" / "plugins" / "a")
    standins.remove("codex")

    assert [(f.path, f.harness, f.message) for f in check(cfg)] == [
        (
            home / "one" / "plugins" / "a",
            None,
            "plugin 'a' from 'one' can't be copied, so tack leaves it as it is: "
            "no plugin directory at ~/one/plugins/a",
        ),
        (
            home / "one" / "plugins" / "b",
            "claude-code",
            "plugin 'b' from 'one' isn't installed in claude-code; `tack sync` installs it",
        ),
        (
            None,
            "codex",
            "`codex` isn't on PATH, so tack can't deploy plugin 'b' to codex; install it",
        ),
    ]


# --- sources and collisions -----------------------------------------------------------


def test_source_findings_and_collisions(home: Path, standins: Standins) -> None:
    one = plugin_source(
        home,
        "one",
        "a",
        "dup",
        entries=({"name": "x", "source": NPM}, {"name": "r", "source": ELSEWHERE}),
    )
    plugin_source(home, "two", "dup")
    (home / "bare" / "skills").mkdir(parents=True)
    write(home / "broken" / ".claude-plugin" / "marketplace.json", "{")
    (home / "broken" / "skills").mkdir()
    cfg = configure(
        home,
        "one",
        "two",
        "bare",
        "broken",
        one=["a", "x", "nope", "r", "dup"],
        two=["dup"],
        bare=["p"],
        broken="*",
    )
    run_sync(configure(home, "one", one=["a"]))  # so `a` is installed: no finding for it

    found = [(f.id, f.severity, f.path, f.harness, f.message) for f in check(cfg)]
    catalog = one / ".claude-plugin" / "marketplace.json"
    broken = home / "broken" / ".claude-plugin" / "marketplace.json"
    assert found[:6] == [
        (
            "name-collision",
            "error",
            cfg.manifest,
            None,
            "plugin 'dup' is selected from sources one, two for claude-code, codex; "
            "tack deploys none of them -- deselect all but one",
        ),
        (
            "not-synced",
            "warn",
            catalog,
            None,
            "the manifest selects plugin 'nope' from 'one', whose catalog has no such plugin",
        ),
        (
            "not-synced",
            "warn",
            catalog,
            None,
            "plugin 'x' from 'one' can't be deployed: `npm` sources can't be pinned",
        ),
        (
            "not-synced",
            "warn",
            catalog,
            None,
            "plugin 'r' from 'one' is in another repository (https://github.com/acme/x.git), "
            "and tack doesn't deploy those yet",
        ),
        (
            "not-synced",
            "warn",
            home / "bare",
            None,
            "the manifest selects plugin 'p' from 'bare', which has no plugin catalog",
        ),
        (
            "not-synced",
            "warn",
            broken,
            None,
            f"source 'broken' has a broken plugin catalog, so tack leaves its plugins as they "
            f"are: {broken}: Expecting property name enclosed in double quotes: "
            "line 1 column 2 (char 1)",
        ),
    ]
    # Each plugin tack can't deploy, or from another repository, is reported
    # once, for its source; a collided name only as `name-collision`.
    assert found[6:] == []


def test_a_collided_plugin_tack_cant_deploy(home: Path, standins: Standins) -> None:
    plugin_source(home, "one", entries=({"name": "x", "source": NPM},))
    plugin_source(home, "two", "x")
    cfg = configure(home, "one", "two", one=["x"], two=["x"])

    assert [(f.id, f.path) for f in check(cfg)] == [
        ("name-collision", cfg.manifest),
        ("not-synced", home / "one" / ".claude-plugin" / "marketplace.json"),
    ]


def test_a_disabled_plugins_finding(home: Path, standins: Standins) -> None:
    cfg = FIXTURES["disabled"][0](home, standins)
    (f,) = check(cfg)
    assert (f.id, f.severity, f.path, f.harness) == (
        "not-synced",
        "warn",
        home / "one" / "plugins" / "a",
        "claude-code",
    )
    assert f.message == (
        "plugin 'a' from 'one' is turned off in claude-code; turn it on there, or limit its "
        "`harnesses` in the manifest"
    )


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        (
            "list fails",
            "`claude plugin list --json` failed: not logged in; tack can't deploy plugin 'a' "
            "to claude-code until it succeeds",
        ),
        (
            "marketplace list fails",
            "`codex plugin marketplace list --json` failed: config.toml is broken; tack can't "
            "deploy plugin 'a' to codex until it succeeds",
        ),
        ("no cli", "`codex` isn't on PATH, so tack can't deploy plugin 'a' to codex; install it"),
    ],
)
def test_unavailable_carries_the_agents_message(
    home: Path, standins: Standins, fixture: str, message: str
) -> None:
    cfg = FIXTURES[fixture][0](home, standins)
    harness = "claude-code" if fixture == "list fails" else "codex"
    found = [f for f in check(cfg) if f.harness == harness]
    assert [(f.id, f.severity, f.path, f.message) for f in found] == [
        ("not-synced", "warn", None, message)
    ]


def test_a_conflict_names_the_foreign_marketplace(home: Path, standins: Standins) -> None:
    plugin_source(home, "one", "a", "b")
    cfg = configure(home, "one", one=["a", "b"])
    standins.marketplace("claude", "tack", home / "elsewhere")

    found = [f for f in check(cfg) if f.harness == "claude-code"]
    assert [(f.id, f.path, f.message) for f in found] == [
        (
            "not-synced",
            None,
            "a marketplace named 'tack' from ~/elsewhere isn't tack's, so tack can't deploy "
            "plugins 'a' and 'b' to claude-code; remove or rename that marketplace",
        )
    ]


def test_findings_are_ordered(home: Path, standins: Standins) -> None:
    """Collisions by name, sources in manifest order, then each harness: its
    plugins' states by name and source, then the leftovers by name."""
    plugin_source(home, "one", "z", "b", "d", "c")
    plugin_source(home, "two", "y", "b")
    plugin_source(home, "three", "y", "a")
    run_sync(configure(home, "one", one=["z", "c", "d"]))
    standins.plugin("codex", "z@tack", enabled=False)
    cfg = configure(
        home,
        "one",
        "two",
        "three",
        one=["z", "b", "nope"],
        two=["y", "b", "gone"],
        three=["a", "y"],
    )

    assert [(f.id, f.harness, f.message.split(";")[0]) for f in check(cfg)] == [
        (
            "name-collision",
            None,
            "plugin 'b' is selected from sources one, two for claude-code, codex",
        ),
        (
            "name-collision",
            None,
            "plugin 'y' is selected from sources two, three for claude-code, codex",
        ),
        (
            "not-synced",
            None,
            "the manifest selects plugin 'nope' from 'one', whose catalog has no such plugin",
        ),
        (
            "not-synced",
            None,
            "the manifest selects plugin 'gone' from 'two', whose catalog has no such plugin",
        ),
        ("not-synced", "claude-code", "plugin 'a' from 'three' isn't installed in claude-code"),
        (
            "not-synced",
            "claude-code",
            "c@tack is installed in claude-code, but the manifest doesn't deploy 'c' there",
        ),
        (
            "not-synced",
            "claude-code",
            "d@tack is installed in claude-code, but the manifest doesn't deploy 'd' there",
        ),
        ("not-synced", "codex", "plugin 'a' from 'three' isn't installed in codex"),
        ("not-synced", "codex", "plugin 'z' from 'one' is turned off in codex"),
        (
            "not-synced",
            "codex",
            "c@tack is installed in codex, but the manifest doesn't deploy 'c' there",
        ),
        (
            "not-synced",
            "codex",
            "d@tack is installed in codex, but the manifest doesn't deploy 'd' there",
        ),
    ]


# --- which agents run (DEC-18) ---------------------------------------------------------


def test_plugins_for_both_harnesses_run_the_four_lists(home: Path, standins: Standins) -> None:
    cfg = FIXTURES["installed"][0](home, standins)
    start = len(standins.calls())

    doctor.run(cfg, project_checks=False)
    assert calls(standins, start) == LISTS


def test_no_plugins_selected_still_lists_both_agents(home: Path, standins: Standins) -> None:
    skill(home / "mine" / "skills", "s")
    cfg = load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')
    standins.plugin("claude", "x@hand")

    doctor.run(cfg, project_checks=False)
    assert calls(standins) == LISTS


def test_a_removed_cli_runs_nothing_and_says_nothing(home: Path, standins: Standins) -> None:
    skill(home / "mine" / "skills", "s")
    cfg = load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')
    standins.remove("codex")

    assert check(cfg) == []
    assert calls(standins) == LISTS[:2]


def test_a_removed_cli_a_plugin_targets_is_one_finding(home: Path, standins: Standins) -> None:
    plugin_source(home, "one", "a", "b")
    cfg = configure(home, "one", one=["a", "b"])
    standins.remove("codex")

    found = [(f.harness, f.message) for f in check(cfg) if f.harness == "codex"]
    assert found == [
        ("codex", "`codex` isn't on PATH, so tack can't deploy plugins 'a' and 'b' to codex; "
         "install it"),
    ]  # fmt: skip
    assert calls(standins) == LISTS[:2]


def test_a_removed_cli_only_a_plugin_tack_cant_deploy_targets(
    home: Path, standins: Standins
) -> None:
    """`sync` reports the missing CLI, so `doctor` does (DEC-19); the plugin
    is reported once, for its source, and the harness's finding names none."""
    plugin_source(home, "one", entries=({"name": "x", "source": NPM},))
    cfg = configure(home, "one", one=["x"])
    standins.remove("codex")

    assert [(f.path, f.harness) for f in check(cfg)] == [
        (home / "one" / ".claude-plugin" / "marketplace.json", None),
        (None, "codex"),
    ]


def test_projects_only_runs_no_agent(home: Path, standins: Standins) -> None:
    cfg = FIXTURES["installed"][0](home, standins)
    standins.plugin("claude", "x@hand")
    start = len(standins.calls())

    doctor.run(cfg, global_checks=False)
    assert calls(standins, start) == []
    doctor.run(cfg, project_checks=False)  # the same manifest does run them
    assert calls(standins, start) == LISTS


def test_doctor_json_lists_plugin_findings(
    home: Path, standins: Standins, capsys: pytest.CaptureFixture[str]
) -> None:
    FIXTURES["missing"][0](home, standins)

    assert cli.main(["doctor", "--json", "--global-only"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert findings == [
        {
            "id": "not-synced",
            "severity": "warn",
            "message": f"plugin 'a' from 'one' isn't installed in {h}; `tack sync` installs it",
            "path": str(home / "one" / "plugins" / "a"),
            "harness": h,
            "project": None,
            "fix": None,
        }
        for h in BOTH
    ]


# --- others' plugins: `unmanaged-plugin` and `duplicate-plugin` -------------------------


def others(cfg: Config) -> list[tuple[str, str | None, str]]:
    """The `unmanaged-plugin` and `duplicate-plugin` findings: id, harness, and
    the plugin installed outside tack."""
    out = []
    for f in check(cfg):
        if f.id == "unmanaged-plugin":
            out.append((f.id, f.harness, f.message.split(" ")[0]))
        elif f.id == "duplicate-plugin":
            out.append((f.id, f.harness, f.message.split("also has ")[1].split(":")[0]))
    return out


def hand(standins: Standins, cli: str, plugin_id: str, *, scope: str = "user") -> None:
    """Install a plugin by hand from its own marketplace. Codex lists only the
    plugins of a registered marketplace whose catalog has them."""
    name, market = plugin_id.split("@")
    if cli == "codex":
        where = f"https://example.com/{market}.git"
        standins.marketplace("codex", market, where, kind="git", plugins=[name])
    standins.plugin(cli, plugin_id, scope=scope)


def test_a_plugin_installed_by_hand_is_unmanaged(home: Path, standins: Standins) -> None:
    hand(standins, "claude", "x@hand")
    hand(standins, "codex", "y@shop")
    cfg = load(home)

    found = check(cfg)
    assert [(f.id, f.severity, f.path, f.harness, f.message) for f in found] == [
        (
            "unmanaged-plugin",
            "info",
            None,
            "claude-code",
            "x@hand is installed in claude-code outside tack; select it from its source in the "
            "manifest, or add 'hand' to [harness.claude-code] ignore_marketplaces",
        ),
        (
            "unmanaged-plugin",
            "info",
            None,
            "codex",
            "y@shop is installed in codex outside tack; select it from its source in the "
            "manifest, or add 'shop' to [harness.codex] ignore_marketplaces",
        ),
    ]


def test_ignored_marketplaces_are_not_reported(home: Path, standins: Standins) -> None:
    hand(standins, "claude", "s@synced")  # Claude Code's own
    hand(standins, "codex", "b@openai-bundled")  # Codex's own
    hand(standins, "claude", "c@company")
    hand(standins, "codex", "c@company")
    cfg = load(home, '[harness.claude-code]\nignore_marketplaces = ["company"]\n')

    assert others(cfg) == [("unmanaged-plugin", "codex", "c@company")]


def test_only_claude_codes_user_scope_is_audited(home: Path, standins: Standins) -> None:
    hand(standins, "claude", "p@hand", scope="project")
    hand(standins, "claude", "s@hand2", scope="synced")
    hand(standins, "claude", "l@hand3", scope="local")
    hand(standins, "claude", "u@hand4")

    assert others(load(home)) == [("unmanaged-plugin", "claude-code", "u@hand4")]


def test_a_plugin_from_a_foreign_tack_is_unmanaged(home: Path, standins: Standins) -> None:
    standins.marketplace("claude", "tack", "acme/tack", kind="github", plugins=["f"])
    standins.plugin("claude", "f@tack")

    assert others(load(home)) == [("unmanaged-plugin", "claude-code", "f@tack")]


@pytest.mark.parametrize("ignored", [False, True])
def test_a_deployed_plugin_installed_elsewhere_too_is_a_duplicate(
    home: Path, standins: Standins, ignored: bool
) -> None:
    plugin_source(home, "one", "a")
    manifest = '[harness.codex]\nignore_marketplaces = ["other"]\n' if ignored else ""
    cfg = configure(home, "one", manifest=manifest, one=["a"])
    run_sync(cfg)
    hand(standins, "claude", "a@other")
    hand(standins, "codex", "a@other")

    assert [(f.id, f.severity, f.path, f.harness, f.message) for f in check(cfg)] == [
        (
            "duplicate-plugin",
            "warn",
            None,
            h,
            f"the manifest deploys a@tack to {h}, which also has a@other: it loads both; "
            "uninstall it, or stop deploying 'a' there",
        )
        for h in BOTH
    ]


def test_a_plugin_not_deployed_to_a_harness_is_no_duplicate_there(
    home: Path, standins: Standins
) -> None:
    plugin_source(home, "one", "a")
    cfg = configure(home, "one", one=[{"name": "a", "harnesses": ["codex"]}])
    run_sync(cfg)
    hand(standins, "claude", "a@other")
    hand(standins, "codex", "a@other")

    assert others(cfg) == [
        ("unmanaged-plugin", "claude-code", "a@other"),
        ("duplicate-plugin", "codex", "a@other"),
    ]


def test_no_duplicates_in_a_harness_with_a_foreign_tack(home: Path, standins: Standins) -> None:
    plugin_source(home, "one", "a")
    cfg = configure(home, "one", one=["a"])
    standins.marketplace("claude", "tack", "acme/tack", kind="github", plugins=["f"])
    standins.plugin("claude", "f@tack")
    hand(standins, "claude", "a@other")

    assert others(cfg) == [
        ("unmanaged-plugin", "claude-code", "a@other"),
        ("unmanaged-plugin", "claude-code", "f@tack"),
    ]


def test_others_come_after_a_harness_s_own_findings(home: Path, standins: Standins) -> None:
    """Per harness: states, leftovers, then `duplicate-plugin` by name and
    `unmanaged-plugin` by id."""
    plugin_source(home, "one", "a", "b", "c")
    run_sync(configure(home, "one", one=["a", "b", "c"]))
    cfg = configure(home, "one", one=["b", "a", "d"])
    for plugin_id in ("z@hand", "b@other", "a@other", "y@hand"):
        hand(standins, "claude", plugin_id)

    assert [(f.id, f.harness, f.message.split(" ")[:2]) for f in check(cfg)] == [
        ("not-synced", None, ["the", "manifest"]),  # 'd' isn't in the catalog
        ("not-synced", "claude-code", ["c@tack", "is"]),
        ("duplicate-plugin", "claude-code", ["the", "manifest"]),
        ("duplicate-plugin", "claude-code", ["the", "manifest"]),
        ("unmanaged-plugin", "claude-code", ["y@hand", "is"]),
        ("unmanaged-plugin", "claude-code", ["z@hand", "is"]),
        ("not-synced", "codex", ["c@tack", "is"]),
    ]
    assert others(cfg) == [
        ("duplicate-plugin", "claude-code", "a@other"),
        ("duplicate-plugin", "claude-code", "b@other"),
        ("unmanaged-plugin", "claude-code", "y@hand"),
        ("unmanaged-plugin", "claude-code", "z@hand"),
    ]


def test_doctor_exit_codes_for_others_plugins(
    home: Path, standins: Standins, capsys: pytest.CaptureFixture[str]
) -> None:
    """`unmanaged-plugin` alone exits 0; a `duplicate-plugin` exits 1."""
    hand(standins, "claude", "x@hand")
    assert cli.main(["doctor", "--json"]) == 0
    assert [f["id"] for f in json.loads(capsys.readouterr().out)["findings"]] == [
        "unmanaged-plugin"
    ]

    plugin_source(home, "one", "x")
    run_sync(configure(home, "one", one=["x"]))
    capsys.readouterr()
    assert cli.main(["doctor", "--json"]) == 1
    assert [f["id"] for f in json.loads(capsys.readouterr().out)["findings"]] == [
        "duplicate-plugin"
    ]

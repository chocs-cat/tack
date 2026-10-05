from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from tack import catalog, config, plugins
from tack.catalog import Ignored, InRepository, InSource
from tack.config import Config
from tests.helpers import load, tree, write
from tests.standin import Standins

SHA = "0123456789abcdef0123456789abcdef01234567"
NPM = {"source": "npm", "package": "@acme/x"}
PI = """
[harness.pi]
skills_dir = "~/.pi/skills"
project_skills_dir = ".pi/skills"
instructions = "~/.pi/AGENTS.md"
project_instructions = "AGENTS.md"
hooks = ["~/.pi/hooks.json"]
project_hooks = [".pi/hooks.json"]
"""


def market(root: Path, *entries: Any, **doc: Any) -> Path:
    """A source at `root` whose catalog lists `entries`: a name `n` is
    `{"name": n, "source": "./plugins/n"}`, anything else is the entry itself."""
    listed = [{"name": e, "source": f"./plugins/{e}"} if isinstance(e, str) else e for e in entries]
    write(root / ".claude-plugin" / "marketplace.json", json.dumps({**doc, "plugins": listed}))
    return root


def configure(home: Path, *sources: str, manifest: str = "", **selections: Any) -> Config:
    """A Config whose `path` sources are `~/<name>`, each selecting the
    plugins `selections` gives it (none by default), as `parse_plugins` reads
    them: the manifest doesn't take `plugins` yet. A source written
    `name:h1,h2` targets those harnesses."""
    tables = []
    for s in sources:
        name, _, hs = s.partition(":")
        table = f'[[source]]\nname = "{name}"\npath = "~/{name}"\n'
        if hs:
            table += f"harnesses = {json.dumps(hs.split(','))}\n"
        tables.append(table)
    cfg = load(home, manifest + "\n" + "\n".join(tables))
    assert cfg.manifest is not None
    out = []
    for src in cfg.sources:
        value = selections.get(src.name, [])
        where = f"source {src.name!r}"
        specs = config.parse_plugins(value, src.harnesses, cfg.harnesses, cfg.manifest, where)
        out.append(dataclasses.replace(src, plugins=specs))
    return dataclasses.replace(cfg, sources=tuple(out))


def names(state: plugins.SourceState) -> list[str]:
    return [s.name for s in state.selected]


# --- selecting --------------------------------------------------------------------


def test_star_selects_every_plugin_in_catalog_order(home: Path) -> None:
    market(home / "m", "b", "a", "c")
    plan = plugins.plan(configure(home, "m", m="*"))
    (m,) = plan.sources
    assert (m.catalog_state, m.error, m.missing, m.ignored) == ("found", None, [], ())
    assert m.root == home / "m"
    assert names(m) == ["b", "a", "c"]
    for sel in m.selected:
        assert sel.source.name == "m"
        assert sel.harnesses == ("claude-code", "codex")
        assert sel.deployable
        assert sel.plugin.where == InSource(f"plugins/{sel.name}")
    for h in ("claude-code", "codex"):
        assert list(plan.plugins[h]) == ["b", "a", "c"]
    assert plan.plugins["codex"]["a"] is m.selected[1]
    assert not plan.collisions


def test_a_list_selects_only_the_names_it_lists(home: Path) -> None:
    market(home / "m", "a", "b", "c")
    (m,) = plugins.plan(configure(home, "m", m=["c", "gone", "a"])).sources
    assert names(m) == ["c", "a"]
    assert m.missing == ["gone"]


def test_per_plugin_harnesses(home: Path) -> None:
    market(home / "m", "a", "b")
    plan = plugins.plan(configure(home, "m", m=["a", {"name": "b", "harnesses": ["codex"]}]))
    a, b = plan.sources[0].selected
    assert (a.harnesses, b.harnesses) == (("claude-code", "codex"), ("codex",))
    assert list(plan.plugins["claude-code"]) == ["a"]
    assert list(plan.plugins["codex"]) == ["a", "b"]


def test_a_source_limited_to_codex(home: Path) -> None:
    market(home / "m", "a")
    plan = plugins.plan(configure(home, "m:codex", m="*"))
    assert plan.sources[0].selected[0].harnesses == ("codex",)
    assert plan.plugins == {"claude-code": {}, "codex": {"a": plan.sources[0].selected[0]}}


def test_only_built_in_harnesses_get_plugins(home: Path) -> None:
    # DEC-8: a source targeting `pi` and `codex` deploys to `codex` only, and a
    # source with no `harnesses` to the built-ins, not to every harness.
    market(home / "both", "a")
    market(home / "every", "b")
    plan = plugins.plan(configure(home, "both:pi,codex", "every", manifest=PI, both="*", every="*"))
    both, every = plan.sources
    assert both.selected[0].harnesses == ("codex",)
    assert every.selected[0].harnesses == ("claude-code", "codex")
    assert set(plan.plugins) == {"claude-code", "codex"}
    assert list(plan.plugins["codex"]) == ["a", "b"]
    assert list(plan.plugins["claude-code"]) == ["b"]


# --- where each plugin is -------------------------------------------------------------


def test_directories(home: Path) -> None:
    root = market(
        home / "m",
        {"name": "dotted", "source": "./plugins/x"},
        {"name": "whole", "source": "."},
        {"name": "slash", "source": "./"},
        {"name": "bare", "source": "y"},
        {"name": "local", "source": {"source": "local", "path": "./z"}},
        {"name": "remote", "source": {"source": "github", "repo": "acme/r", "sha": SHA}},
        metadata={"pluginRoot": "./plugins"},
    )
    plan = plugins.plan(configure(home, "m", m="*"))
    by_name = {s.name: s for s in plan.sources[0].selected}
    assert {n: s.directory for n, s in by_name.items()} == {
        "dotted": root / "plugins" / "x",
        "whole": root,
        "slash": root,
        "bare": root / "plugins" / "y",
        "local": root / "z",
        "remote": None,
    }
    remote = by_name["remote"]
    assert remote.plugin.where == InRepository("https://github.com/acme/r.git", None, SHA)
    assert remote.deployable
    for h in ("claude-code", "codex"):
        assert plan.plugins[h]["remote"] is remote


def test_undeployable_plugins_are_selected_but_go_nowhere(home: Path) -> None:
    market(
        home / "m",
        {"name": "npm", "source": NPM},
        {"name": "twice", "source": "./a"},
        "ok",
        {"name": "twice", "source": "./b"},
    )
    for value in ("*", ["npm", "twice", "ok"]):
        plan = plugins.plan(configure(home, "m", m=value))
        (m,) = plan.sources
        assert names(m) == ["npm", "twice", "ok"]  # a name listed twice is selected once
        assert m.missing == []
        npm, twice, ok = m.selected
        assert not npm.deployable
        assert not twice.deployable
        assert twice.plugin.entry["source"] == "./a"
        assert ok.deployable
        for h in ("claude-code", "codex"):
            assert list(plan.plugins[h]) == ["ok"]
        assert not plan.collisions


# --- collisions -----------------------------------------------------------------------


def test_two_sources_selecting_one_name_collide(home: Path) -> None:
    market(home / "one", "x", "a")
    market(home / "two", "x", "b")
    plan = plugins.plan(configure(home, "one", "two", one="*", two=["x", "b"]))
    assert plan.collisions == {"x": (["claude-code", "codex"], ["one", "two"])}
    for h in ("claude-code", "codex"):
        assert sorted(plan.plugins[h]) == ["a", "b"]
    # Each source still selects it.
    assert [names(s) for s in plan.sources] == [["x", "a"], ["x", "b"]]


def test_plugins_for_different_harnesses_collide(home: Path) -> None:
    # DEC-11: tack's marketplace holds one `x` for every harness.
    market(home / "one", "x")
    market(home / "two", "x")
    plan = plugins.plan(
        configure(
            home,
            "one",
            "two",
            one=[{"name": "x", "harnesses": ["codex"]}],
            two=[{"name": "x", "harnesses": ["claude-code"]}],
        )
    )
    assert plan.collisions == {"x": (["claude-code", "codex"], ["one", "two"])}
    assert plan.plugins == {"claude-code": {}, "codex": {}}


def test_collisions_take_every_harness_either_source_targets(home: Path) -> None:
    market(home / "one", "x")
    market(home / "two", "x")
    plan = plugins.plan(configure(home, "one", "two:codex", one="*", two="*"))
    assert plan.collisions == {"x": (["claude-code", "codex"], ["one", "two"])}
    assert plan.plugins == {"claude-code": {}, "codex": {}}

    # Both limited to codex: a collision there only.
    plan = plugins.plan(configure(home, "one:codex", "two:codex", one="*", two="*"))
    assert plan.collisions == {"x": (["codex"], ["one", "two"])}


def test_different_names_for_different_harnesses_do_not_collide(home: Path) -> None:
    market(home / "one", "x")
    market(home / "two", "y")
    plan = plugins.plan(
        configure(
            home,
            "one",
            "two",
            one=[{"name": "x", "harnesses": ["claude-code"]}],
            two=[{"name": "y", "harnesses": ["codex"]}],
        )
    )
    assert not plan.collisions
    assert list(plan.plugins["claude-code"]) == ["x"]
    assert list(plan.plugins["codex"]) == ["y"]


def test_an_undeployable_plugin_collides_too(home: Path) -> None:
    market(home / "one", {"name": "x", "source": NPM})
    market(home / "two", "x")
    plan = plugins.plan(configure(home, "one", "two", one=["x"], two=["x"]))
    assert plan.collisions == {"x": (["claude-code", "codex"], ["one", "two"])}
    assert plan.plugins == {"claude-code": {}, "codex": {}}


# --- catalogs -------------------------------------------------------------------------


def test_a_source_without_a_catalog(home: Path) -> None:
    write(home / "m" / "skills" / "a" / "SKILL.md")
    for value, missing in (("*", []), (["a", "b"], ["a", "b"])):
        plan = plugins.plan(configure(home, "m", m=value))
        (m,) = plan.sources
        assert (m.catalog_state, m.error, m.selected, m.missing) == (
            "no-catalog",
            None,
            [],
            missing,
        )
        assert plan.plugins == {"claude-code": {}, "codex": {}}


def test_a_source_whose_root_is_not_there(home: Path) -> None:
    for value in ("*", ["a"]):
        (m,) = plugins.plan(configure(home, "m", m=value)).sources
        assert m.root == home / "m"
        assert (m.catalog_state, m.error, m.selected, m.missing) == ("no-root", None, [], [])


@pytest.mark.parametrize(
    ("text", "message"), [('{"plugins": 1}', "needs a `plugins` list"), ("{", "marketplace.json")]
)
def test_a_broken_catalog(home: Path, text: str, message: str) -> None:
    write(home / "m" / ".claude-plugin" / "marketplace.json", text)
    # The Codex catalog isn't read in place of a broken Claude Code one.
    codex = {"plugins": [{"name": "a", "source": "./a"}]}
    write(home / "m" / ".agents" / "plugins" / "marketplace.json", json.dumps(codex))
    for value in ("*", ["a"]):
        (m,) = plugins.plan(configure(home, "m", m=value)).sources
        assert (m.catalog_state, m.selected, m.missing) == ("broken", [], [])
        assert m.error is not None
        assert message in m.error


def test_a_codex_catalog(home: Path) -> None:
    write(
        home / "m" / ".agents" / "plugins" / "marketplace.json",
        json.dumps({"plugins": [{"name": "a", "source": {"source": "local", "path": "./a"}}]}),
    )
    (m,) = plugins.plan(configure(home, "m", m="*")).sources
    assert m.catalog_state == "found"
    assert [(s.name, s.directory) for s in m.selected] == [("a", home / "m" / "a")]


def test_ignored_entries_are_passed_on(home: Path) -> None:
    market(home / "m", 1, {"name": "../up", "source": "./up"}, "a")
    (m,) = plugins.plan(configure(home, "m", m="*")).sources
    assert names(m) == ["a"]
    assert m.ignored == (Ignored(0, "not an object"), Ignored(1, "'../up' isn't a valid name"))


# --- what the plan touches -------------------------------------------------------------


def test_a_source_selecting_no_plugins_is_not_read(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(home / "quiet" / ".claude-plugin" / "marketplace.json", "not a catalog")
    market(home / "loud", "a")
    read: list[Path] = []
    real = catalog.read

    def spy(root: Path) -> catalog.Catalog | None:
        read.append(root)
        return real(root)

    monkeypatch.setattr(catalog, "read", spy)
    plan = plugins.plan(configure(home, "quiet", "loud", loud="*"))
    assert [s.source.name for s in plan.sources] == ["loud"]
    assert read == [home / "loud"]

    # A manifest selecting no plugins reads no catalog.
    read.clear()
    plan = plugins.plan(configure(home, "quiet", "loud"))
    assert (plan.sources, plan.plugins, plan.collisions) == (
        [],
        {"claude-code": {}, "codex": {}},
        {},
    )
    assert read == []


def test_planning_runs_no_agent_and_writes_nothing(home: Path, standins: Standins) -> None:
    market(home / "one", "a", {"name": "x", "source": NPM})
    market(home / "two", "a", {"name": "r", "source": {"source": "url", "url": "u", "sha": SHA}})
    write(home / "three" / ".claude-plugin" / "marketplace.json", "{")
    cfg = configure(home, "one", "two", "three", "gone", one="*", two="*", three="*", gone=["z"])
    before = tree(home)
    plan = plugins.plan(cfg)
    assert [s.catalog_state for s in plan.sources] == ["found", "found", "broken", "no-root"]
    assert plan.collisions == {"a": (["claude-code", "codex"], ["one", "two"])}
    assert standins.calls() == []
    assert tree(home) == before
    assert not cfg.paths.marketplace_dir.exists()

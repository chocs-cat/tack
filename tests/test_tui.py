from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from textual.coordinate import Coordinate
from textual.pilot import Pilot
from textual.widgets import DataTable, Input, Static, TabbedContent
from textual.widgets._header import HeaderTitle
from textual.widgets._tabbed_content import ContentTab, ContentTabs

from tack import __version__, cli, config, edit, outdated, status, sync
from tack.status import SourceStatus
from tack.text import tilde
from tack.tui import render
from tack.tui.app import FixedHeader, TackApp
from tack.tui.dialogs import ActionScreen, AddScreen
from tests import standin
from tests.helpers import commit, configure, load, market, repo, skill, skill_md, upstream, write
from tests.standin import Standins
from tests.test_status import BOTH, FIXTURES, NPM, WHEN, plugin_source, run_sync

Scenario = Callable[[TackApp, Pilot[None]], Awaitable[None]]


def drive(scenario: Scenario) -> None:
    """Run the app headless and hand it to `scenario`."""

    async def main() -> None:
        app = TackApp()
        async with app.run_test(size=(160, 48)) as pilot:
            await settle(pilot)
            await scenario(app, pilot)

    asyncio.run(main())


async def settle(pilot: Pilot[None]) -> None:
    """Wait for the background work, and what it hands back to the app."""
    for _ in range(3):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


def tab(app: TackApp) -> str:
    return app.query_one(TabbedContent).active


def rows(app: TackApp, name: str) -> list[list[str]]:
    table = app.query_one(f"#{name}-table", DataTable)
    return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


def labels(app: TackApp, name: str) -> list[str]:
    table = app.query_one(f"#{name}-table", DataTable)
    return [str(c.label) for c in table.columns.values()]


def detail(app: TackApp, name: str) -> str:
    return str(app.query_one(f"#{name}-detail", Static).render())


def body(app: TackApp) -> str:
    return str(app.screen.query_one("#dialog-body", Static).render())


def machine(home: Path, tmp_path: Path, *, project: dict[str, str] | None = None) -> Path:
    """A path source and a git source, synced; a project root if `project`."""
    up = upstream(tmp_path / "up", "x")
    skill(home / "mine" / "skills", "a")
    text = (
        '[[source]]\nname = "mine"\npath = "~/mine"\n'
        f'[[source]]\nname = "up"\ngit = "{up}"\nref = "master"\n'
    )
    if project is not None:
        repo(home / "Code" / "p", project)
        text = '[projects]\nroots = ["~/Code"]\n' + text
    sync.sync(load(home, text))
    return up


def test_opens_on_skills_when_all_is_well(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert tab(app) == "skills"
        assert rows(app, "skills") == [
            ["▾ mine (1)", "", ""],
            ["  a", "linked", "linked"],
            ["▾ up (1)", "", ""],
            ["  x", "linked", "linked"],
        ]
        assert rows(app, "sources") == [["mine", "path", "clean"], ["up", "git", "current"]]
        assert "mine  ~/mine" in str(app.query_one("#skills-detail", Static).render())
        await pilot.press("down")
        assert "from mine" in str(app.query_one("#skills-detail", Static).render())

    drive(scenario)


def test_sorts_skills_by_any_column(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)
    skill(home / "mine" / "skills", "B")
    sync.sync(config.load())
    (home / ".claude" / "skills" / "a").unlink()  # a: missing in claude-code

    def names(app: TackApp) -> list[str]:
        return [r[0] for r in rows(app, "skills")]

    def labels(app: TackApp) -> list[str]:
        return [str(c.label) for c in app.query_one("#skills-table", DataTable).columns.values()]

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("1", "g")  # it opens on Doctor, for the missing link; ungroup
        assert names(app) == ["B", "a", "x"]  # by name, as status orders them
        await pilot.press("o")
        assert names(app) == ["a", "B", "x"]  # ignoring case
        assert labels(app) == ["skill ▲", "source", "claude-code", "codex"]
        await pilot.press("o")
        assert names(app) == ["B", "a", "x"]  # by source; ties in the default order
        await pilot.press("o")
        assert names(app) == ["a", "B", "x"]  # problems first
        await pilot.press("O")
        assert names(app) == ["B", "x", "a"]
        assert labels(app)[2] == "claude-code ▼"
        await pilot.click("#skills-table", offset=(2, 0))  # the skill column's header
        assert names(app) == ["a", "B", "x"]
        await pilot.click("#skills-table", offset=(2, 0))
        assert names(app) == ["x", "B", "a"]
        assert app._selected("skills") == "mine/B"  # the cursor stays on its skill
        await pilot.press("r")
        await settle(pilot)
        assert names(app) == ["x", "B", "a"]
        assert labels(app)[0] == "skill ▼"
        await pilot.press("g")  # grouped: sorted within each source
        assert names(app) == ["▾ mine (2)", "  B", "  a", "▾ up (1)", "  x"]
        assert labels(app) == ["skill ▼", "claude-code", "codex"]
        await pilot.press("o")  # no source column: on to the first harness
        assert labels(app) == ["skill", "claude-code ▲", "codex"]
        await pilot.press("3")
        assert app.check_action("sort_next", ()) is False

    drive(scenario)


def test_groups_skills_by_source(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)
    skill(home / "mine" / "skills", "b")
    sync.sync(config.load())
    (home / ".claude" / "skills" / "a").unlink()  # a: missing in claude-code

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("1")
        assert rows(app, "skills") == [
            ["▾ mine (2)", "1 missing", ""],
            ["  a", "missing", "linked"],
            ["  b", "linked", "linked"],
            ["▾ up (1)", "", ""],
            ["  x", "linked", "linked"],
        ]
        await pilot.press("down", "down", "left")  # from b: folds mine, onto its row
        assert rows(app, "skills")[:2] == [["▸ mine (2)", "1 missing", ""], ["▾ up (1)", "", ""]]
        assert app._selected("skills") == "mine"
        await pilot.press("right")
        assert len(rows(app, "skills")) == 5
        await pilot.press("space")
        assert len(rows(app, "skills")) == 3
        await pilot.press("enter")
        assert len(rows(app, "skills")) == 5
        await pilot.press("space", "r")
        await settle(pilot)
        assert len(rows(app, "skills")) == 3  # folds hold through a refresh
        await pilot.press("g")  # ungrouped: the cursor goes to mine's first skill
        assert rows(app, "skills")[0] == ["a", "mine", "missing", "linked"]
        assert app._selected("skills") == "mine/a"
        await pilot.press("g")  # grouped again, still folded: onto mine's row
        assert len(rows(app, "skills")) == 3
        assert app._selected("skills") == "mine"

    drive(scenario)


def test_tui_group_by_source_false_opens_ungrouped(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)
    manifest = home / ".config" / "tack" / "tack.toml"
    manifest.write_text("[tui]\ngroup_by_source = false\n" + manifest.read_text())

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert rows(app, "skills")[0] == ["a", "mine", "linked", "linked"]
        assert app.check_action("group", ()) is True

    drive(scenario)


def test_stays_on_skills_and_applies_a_fix(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path, project={"CLAUDE.md": "Rules.\n"})
    project = home / "Code" / "p"

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert tab(app) == "skills"  # though Doctor has an error
        await pilot.press("4")
        assert tab(app) == "doctor"
        assert rows(app, "doctor") == [["error", "agents-md-missing", "~/Code/p", "agents-md"]]
        await pilot.press("f")
        await settle(pilot)
        assert isinstance(app.screen, ActionScreen)
        assert "would move CLAUDE.md -> AGENTS.md" in body(app)
        assert not (project / "AGENTS.md").exists()
        await pilot.press("y")
        await settle(pilot)
        assert "moved CLAUDE.md -> AGENTS.md" in body(app)
        assert (project / "AGENTS.md").read_text() == "Rules.\n"
        await pilot.press("n")
        await settle(pilot)
        assert not isinstance(app.screen, ActionScreen)
        assert rows(app, "doctor") == []

    drive(scenario)


def test_late_tab_events_do_not_swap_the_tabs(home: Path, tmp_path: Path) -> None:
    """On a slow machine the first tab's activation can arrive after you
    have moved to another tab. Acting on it would focus its table, which
    activates that tab again; with two such events in flight the tabs used
    to swap back and forth for good."""
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("4")
        assert tab(app) == "doctor"
        tabbed = app.query_one(TabbedContent)
        tabs = tabbed.get_child_by_type(ContentTabs)
        for name in ("skills", "doctor"):
            tabbed.post_message(TabbedContent.TabActivated(tabbed, tabs.get_content_tab(name)))
        await asyncio.wait_for(pilot.pause(0.2), timeout=5)
        assert tab(app) == "doctor"
        assert app.focused is app.query_one("#doctor-table")

    drive(scenario)


def test_stays_on_skills_and_updates_a_source(home: Path, tmp_path: Path) -> None:
    up = machine(home, tmp_path)
    tip = commit(up, {"skills/x/SKILL.md": skill_md("x") + "more\n"}, "improve x")

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert tab(app) == "skills"  # though a source is behind
        await pilot.press("3")
        assert tab(app) == "sources"
        assert rows(app, "sources")[1] == ["up", "git", "1 behind"]
        await pilot.press("down")
        detail = str(app.query_one("#sources-detail", Static).render())
        assert "1 commit behind" in detail
        assert "improve x" in detail
        assert "+more" in detail
        await pilot.press("u")
        await settle(pilot)
        assert "would update" in body(app)
        await pilot.press("y")
        await settle(pilot)
        assert config.load_lock(config.load().paths)["up"].commit == tip
        await pilot.press("n")
        await settle(pilot)
        assert rows(app, "sources")[1] == ["up", "git", "current"]

    drive(scenario)


def test_sync_shows_its_dry_run_first(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)
    link = home / ".claude" / "skills" / "a"
    link.unlink()

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("s")
        await settle(pilot)
        assert "would link a" in body(app)
        await pilot.press("n")  # cancel: nothing happens
        await settle(pilot)
        assert not link.exists()
        await pilot.press("s")
        await settle(pilot)
        await pilot.press("y")
        await settle(pilot)
        assert link.is_symlink()

    drive(scenario)


def test_nothing_to_do_cannot_be_confirmed(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("s")
        await settle(pilot)
        assert "nothing to do" in body(app)
        screen = app.screen
        assert isinstance(screen, ActionScreen)
        await pilot.press("y")
        await settle(pilot)
        assert screen.state == "idle"

    drive(scenario)


def test_adds_a_source(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)
    skill(home / "more" / "skills", "b")

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("3", "a")
        await settle(pilot)
        assert isinstance(app.screen, AddScreen)
        app.screen.query_one("#spec", Input).value = str(home / "more")
        await pilot.press("enter")
        await settle(pilot)
        assert "would write ~/.config/tack/tack.toml" in body(app)
        await pilot.press("y")
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        assert [s.name for s in config.load().sources] == ["mine", "up", "more"]
        assert rows(app, "skills")[-2:] == [["▾ more (1)", "", ""], ["  b", "linked", "linked"]]

    drive(scenario)


def test_adds_a_source_of_plugins(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The form's plugins field, split as the skills field is, reaches the add."""
    machine(home, tmp_path)
    write(home / "plugged" / "plugins" / "p" / "README.md", "p\n")
    write(home / "plugged" / "plugins" / "q" / "README.md", "q\n")
    market(home / "plugged", "p", "q")
    adds: list[dict[str, Any]] = []
    real = edit.add

    def add(cfg: config.Config, spec: str, **fields: Any) -> sync.Result:
        adds.append(fields)
        return real(cfg, spec, **fields)

    monkeypatch.setattr(edit, "add", add)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("3", "a")
        await settle(pilot)
        assert isinstance(app.screen, AddScreen)
        app.screen.query_one("#spec", Input).value = str(home / "plugged")
        app.screen.query_one("#plugins", Input).value = "p, q"
        await pilot.press("enter")
        await settle(pilot)
        assert "would write ~/.config/tack/tack.toml" in body(app)
        await pilot.press("y")
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        assert [a["plugins"] for a in adds] == [["p", "q"], ["p", "q"]]  # the preview, the add
        source = config.load().sources[-1]
        assert (source.name, source.skills, [p.name for p in source.plugins or ()]) == (
            "plugged",
            (),
            ["p", "q"],
        )

    drive(scenario)


# --- the Plugins tab (design.md *The TUI*) -----------------------------------------

# A harness column's order: conflict and collision, stale, disabled,
# unavailable, missing, installed; then plugins that don't go there.
RANK = {
    "conflict": 0, "collision": 0, "stale": 1, "disabled": 2, "unavailable": 3, "missing": 4,
    "installed": 5,
}  # fmt: skip
COLOR = {
    "installed": "green",
    **dict.fromkeys(("stale", "disabled", "missing"), "yellow"),
    **dict.fromkeys(("unavailable", "conflict", "collision"), "red"),
}


def test_the_tabs_and_their_keys(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert tab(app) == "skills"
        shown = app.query_one(TabbedContent).get_child_by_type(ContentTabs).query(ContentTab)
        assert [str(t.label_text) for t in shown] == ["Skills", "Plugins", "Sources", "Doctor"]
        for key, name in zip(
            "23414", ("plugins", "sources", "doctor", "skills", "doctor"), strict=True
        ):
            await pilot.press(key)
            assert tab(app) == name
            assert app.focused is app.query_one(f"#{name}-table")

    drive(scenario)


def plugin_cells(app: TackApp) -> dict[tuple[str, str], dict[str, tuple[str, str]]]:
    """The ungrouped Plugins table: each plugin's state and color in each
    harness it goes to."""
    table = app.query_one("#plugins-table", DataTable)
    out = {}
    for i in range(table.row_count):
        name, source, *cells = table.get_row_at(i)
        out[name, source] = {
            h: (str(c), str(c.style)) for h, c in zip(BOTH, cells, strict=True) if str(c) != "-"
        }
    return out


@pytest.mark.parametrize("fixture", FIXTURES)
def test_shows_every_plugin_state(home: Path, standins: Standins, fixture: str) -> None:
    """Each cell is the state `status` gives, colored as *The Plugins tab*
    says; each source's row counts what isn't `installed` by state, in the
    column's order, colored as the worst."""
    cfg = FIXTURES[fixture][0](home, standins)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        plugins = status.status(cfg).plugins
        await pilot.press("2")
        table = app.query_one("#plugins-table", DataTable)
        groups = {}
        for i in range(table.row_count):
            key = table.coordinate_to_cell_key(Coordinate(i, 0)).row_key.value or ""
            if "/" not in key:
                groups[key] = [(str(c), str(c.style) if c else "") for c in table.get_row_at(i)[1:]]
        expected = {}
        for source in sorted({p.source for p in plugins}):
            cells = []
            for h in BOTH:
                states = Counter(
                    st
                    for p in plugins
                    if p.source == source and (st := p.harnesses.get(h)) not in (None, "installed")
                )
                order = sorted(states, key=lambda st: (RANK[st], st))
                summary = ", ".join(f"{states[st]} {st}" for st in order)
                cells.append((summary, COLOR[order[0]] if order else ""))
            expected[source] = cells
        assert groups == expected
        await pilot.press("g")
        assert plugin_cells(app) == {
            (p.name, p.source): {h: (st, COLOR[st]) for h, st in p.harnesses.items()}
            for p in plugins
        }

    drive(scenario)


def test_sorts_plugins_by_a_harness_column(home: Path, standins: Standins) -> None:
    """In claude-code: f a collision, d stale, b disabled, c missing, e
    installed, and a not there at all."""
    plugin_source(home, "one", "a", "b", "c", "d", "e", "f")
    plugin_source(home, "two", "f")
    only_codex = {"name": "a", "harnesses": ["codex"]}
    run_sync(configure(home, "one", one=[only_codex, "b", "d", "e"]))
    standins.plugin("claude", "b@tack", enabled=False)
    write(home / "one" / "plugins" / "d" / "skills" / "d" / "SKILL.md", "Edited.\n")
    configure(home, "one", "two", one=[only_codex, "b", "c", "d", "e", "f"], two=["f"])

    def order(app: TackApp) -> list[str]:
        return [f"{r[0]}/{r[1]}" for r in rows(app, "plugins")]

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("2", "g")
        assert order(app) == ["a/one", "b/one", "c/one", "d/one", "e/one", "f/one", "f/two"]
        await pilot.press("o", "o", "o")
        assert labels(app, "plugins") == ["plugin", "source", "claude-code ▲", "codex"]
        assert order(app) == ["f/one", "f/two", "d/one", "b/one", "c/one", "e/one", "a/one"]
        await pilot.press("O")
        assert labels(app, "plugins")[2] == "claude-code ▼"
        assert order(app) == ["a/one", "e/one", "c/one", "b/one", "d/one", "f/one", "f/two"]
        await pilot.click("#plugins-table", offset=(2, 0))  # the plugin column's header
        assert labels(app, "plugins")[0] == "plugin ▲"
        await pilot.click("#plugins-table", offset=(2, 0))
        assert order(app) == ["f/one", "f/two", "e/one", "d/one", "c/one", "b/one", "a/one"]
        assert labels(app, "skills") == ["skill", "claude-code", "codex"]  # Skills' own

    drive(scenario)


def test_groups_plugins_by_source(home: Path, standins: Standins) -> None:
    """A row for each source whose `plugins` isn't `[]`, folded and grouped
    apart from Skills."""
    plugin_source(home, "one", "a", "b", "c")
    plugin_source(home, "two", "x")
    skill(home / "three" / "skills", "s")
    run_sync(configure(home, "one", "two", "three", one=["a", "b"]))
    standins.plugin("claude", "b@tack", enabled=False)
    configure(home, "one", "two", "three", one=["a", "b", "c"], two=["x"])

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("2")
        assert rows(app, "plugins") == [
            ["▾ one (3)", "1 disabled, 1 missing", "1 missing"],
            ["  a", "installed", "installed"],
            ["  b", "disabled", "installed"],
            ["  c", "missing", "missing"],
            ["▾ two (1)", "1 missing", "1 missing"],
            ["  x", "missing", "missing"],
        ]
        assert "one  ~/one" in detail(app, "plugins")  # a source's row: its detail
        assert app.check_action("toggle_fold", ()) is not False
        await pilot.press("down", "down", "left")  # from b: folds one, onto its row
        assert app._selected("plugins") == "one"
        await pilot.press("r")
        await settle(pilot)
        assert [r[0] for r in rows(app, "plugins")] == ["▸ one (3)", "▾ two (1)", "  x"]
        assert app._selected("plugins") == "one"
        await pilot.press("g")  # ungrouped: the cursor goes to one's first plugin
        assert rows(app, "plugins")[0] == ["a", "one", "installed", "installed"]
        assert app._selected("plugins") == "one/a"
        await pilot.press("1")
        assert [r[0] for r in rows(app, "skills")] == [
            "▾ one (0)", "▾ two (0)", "▾ three (1)", "  s",
        ]  # fmt: skip
        await pilot.press("o", "2")  # Skills' sort leaves Plugins' alone
        assert labels(app, "plugins") == ["plugin", "source", "claude-code", "codex"]
        await pilot.press("g")
        assert [r[0] for r in rows(app, "plugins")] == ["▸ one (3)", "▾ two (1)", "  x"]
        assert labels(app, "skills") == ["skill ▲", "claude-code", "codex"]
        for key, shown in (("1", True), ("2", True), ("3", False), ("4", False)):
            await pilot.press(key)
            for action in ("sort_next", "sort_reverse", "group"):
                assert app.check_action(action, ()) is shown, (key, action)

    drive(scenario)


def test_the_plugins_tab_without_plugins(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("2")
        assert rows(app, "plugins") == []
        assert labels(app, "plugins") == ["plugin", "claude-code", "codex"]
        assert detail(app, "plugins") == render.NO_PLUGINS
        assert "plugins field of `a` on Sources" in render.NO_PLUGINS

    drive(scenario)


def test_each_refresh_lists_each_agents_plugins_once(home: Path, standins: Standins) -> None:
    """The Plugins tab and the audit share one reading of each agent: count
    the stand-ins' calls after a refresh, not after the app opens
    (review-checklist §1)."""
    FIXTURES["installed"][0](home, standins)  # `a`, for both agents

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        (standins.directory / standin.CALLS).unlink()
        await pilot.press("r")
        await settle(pilot)
        assert sorted(" ".join([c.cli, *c.args]) for c in standins.calls()) == [
            "claude plugin list --json",
            "claude plugin marketplace list --json",
            "codex plugin list --json",
            "codex plugin marketplace list --json",
        ]
        assert rows(app, "plugins")[1] == ["  a", "installed", "installed"]

    drive(scenario)


def test_a_plugins_detail(home: Path, tmp_path: Path, standins: Standins) -> None:
    """Where it comes from (the source, its pin or directory, tack's copy),
    its version and description, and its state in each harness, colored."""
    write(
        home / "one" / "plugins" / "a" / ".claude-plugin" / "plugin.json",
        json.dumps({"name": "a", "version": "3.1", "description": "A, from plugin.json."}),
    )
    write(home / "one" / "plugins" / "b" / "README.md", "b\n")
    market(
        home / "one",
        {"name": "a", "source": "./plugins/a", "version": "1.0", "description": "From the entry."},
        {"name": "b", "source": "./plugins/b", "description": "B, from the entry."},
    )
    up = repo(
        tmp_path / "up",
        {
            "plugins/g/README.md": "g\n",
            ".claude-plugin/marketplace.json": json.dumps(
                {"plugins": [{"name": "g", "source": "./plugins/g", "version": "2.0"}]}
            ),
        },
    )
    cfg = load(
        home,
        '[[source]]\nname = "one"\npath = "~/one"\nskills = []\nplugins = ["a", "b"]\n'
        f'[[source]]\nname = "up"\ngit = "{up}"\nref = "master"\nskills = []\nplugins = ["g"]\n',
    )
    run_sync(cfg)
    standins.plugin("claude", "b@tack", enabled=False)
    copies = tilde(cfg.paths.marketplace_dir / "plugins")
    pin = config.load_lock(cfg.paths)["up"]

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("2", "down")
        assert detail(app, "plugins") == (
            "a  from one\n"
            "source: ~/one\n"
            f"copy: {copies}/a\n"
            "version: 3.1\n\n"
            "claude-code: installed\n"
            "codex: installed\n\n"
            "A, from plugin.json.\n"
        )
        await pilot.press("down")
        shown = app.query_one("#plugins-detail", Static).content
        assert isinstance(shown, Text)
        assert shown.plain.splitlines()[3:] == [
            "version: none",
            "",
            "claude-code: disabled",
            "codex: installed",
            "",
            "B, from the entry.",
        ]
        colors = {shown.plain[x.start : x.end].strip(): str(x.style) for x in shown.spans}
        assert (colors["disabled"], colors["installed"]) == ("yellow", "green")
        await pilot.press("down", "down")
        assert detail(app, "plugins") == (
            "g  from up\n"
            f"source: {up} (master), pinned {pin.commit[:12]} on {pin.locked.date().isoformat()}\n"
            f"copy: {copies}/g\n"
            "version: 2.0\n\n"
            "claude-code: installed\n"
            "codex: installed\n"
        )

    drive(scenario)


ELSEWHERE = {"source": "github", "repo": "acme/r", "sha": "0" * 40}


@pytest.mark.parametrize("plugin", ["u", "r", "gone", "a"])
def test_a_plugins_detail_gives_the_problem_sync_reports(home: Path, plugin: str) -> None:
    """One tack can't deploy, one from another repository, one whose
    directory is gone, and a name two sources select: each from a `path`
    source whose state is `ok`, with the message a `sync` dry run reports."""
    entries = ({"name": "u", "source": NPM}, {"name": "r", "source": ELSEWHERE}, "gone")
    plugin_source(home, "one", "a", entries=entries)
    plugin_source(home, "two", "a")
    cfg = configure(home, "one", "two", one=[plugin], two=["a"] if plugin == "a" else [])
    (problem,) = sync.sync(cfg, dry_run=True, now=WHEN).problems

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert app.status is not None
        assert [s.state for s in app.status.sources] == ["ok", "ok"]
        await pilot.press("2", "down")
        assert app._selected("plugins") == f"one/{plugin}"
        assert f"\n{problem.message}\n" in detail(app, "plugins")

    drive(scenario)


@pytest.mark.parametrize("change", ["plugins", "a broken catalog"])
def test_the_sources_detail_gives_what_outdated_does(
    home: Path, tmp_path: Path, change: str
) -> None:
    """A git source behind upstream: its changed plugins, or its
    `plugins_error`, line for line as `outdated`'s text; and the plugins it
    selects, after its skills."""

    def catalog(*names: str) -> str:
        return json.dumps({"plugins": [{"name": n, "source": f"./plugins/{n}"} for n in names]})

    up = repo(
        tmp_path / "up",
        {
            "plugins/m/plugin.json": json.dumps({"version": "1.0"}),
            "plugins/r/README.md": "r\n",
            ".claude-plugin/marketplace.json": catalog("m", "r"),
        },
    )
    cfg = load(
        home,
        f'[[source]]\nname = "up"\ngit = "{up}"\nref = "master"\nskills = []\nplugins = "*"\n',
    )
    run_sync(cfg)
    if change == "plugins":
        files = {
            "plugins/m/plugin.json": json.dumps({"version": "1.1"}),
            "plugins/n/README.md": "n\n",
            ".claude-plugin/marketplace.json": catalog("m", "n"),
        }
    else:
        files = {".claude-plugin/marketplace.json": "{"}
    commit(up, files, "change the plugins")
    report = outdated.outdated(cfg, diff=True)
    (source,) = report.sources
    printed = cli._outdated_text(report, {"up"}).splitlines()
    shas = tuple(c.commit[:12] for c in source.commits)
    changes = [line.strip() for line in printed[1:]]
    # The source's lines up to its commits (none touch a plugin of a broken
    # catalog's), then a blank line and the summary.
    changes = changes[
        : next(i for i, line in enumerate(changes) if not line or line.startswith(shas))
    ]
    expected = {
        "plugins": ["plugins modified: m (1.0 -> 1.1)", "plugins added: n", "plugins removed: r"],
        "a broken catalog": [source.plugins_error, "no selected skill changed"],
    }
    assert changes == expected[change]

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("3")
        lines = detail(app, "sources").splitlines()
        assert lines[2:4] == ["0 skills: ", "2 plugins: m, r"]
        at = next(i for i, line in enumerate(lines) if "1 commit behind" in line) + 1
        assert lines[at : at + len(changes)] == changes
        commits = [f"{c.commit[:12]} {c.subject}" for c in source.commits]
        assert lines[at + len(changes) :][: len(commits)] == commits

    drive(scenario)


def test_sync_previews_plugin_commands(home: Path, standins: Standins) -> None:
    FIXTURES["missing"][0](home, standins)  # `a`, for both agents

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("s")
        await settle(pilot)
        assert "would run claude plugin install a@tack --scope user --json" in body(app)
        assert "would run codex plugin add a@tack --json" in body(app)

    drive(scenario)


def test_actions_belong_to_their_tabs(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert tab(app) == "skills"
        assert app.check_action("update", ()) is False
        assert app.check_action("sync", ()) is True
        await pilot.press("3")
        assert app.check_action("update", ()) is True
        assert app.check_action("fix", ()) is False
        await pilot.press("u")  # `mine` is a path source
        await settle(pilot)
        assert not isinstance(app.screen, ActionScreen)

    drive(scenario)


def test_header_shows_the_version_and_manifest_and_stays_one_line(
    home: Path, tmp_path: Path
) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        title = app.format_title(app.title, app.sub_title).plain
        assert title == f"tack {__version__} • ~/.config/tack/tack.toml"
        await pilot.click(HeaderTitle)
        await pilot.pause()
        assert not app.query_one(FixedHeader).has_class("-tall")

    drive(scenario)


def test_header_says_when_there_is_no_manifest(home: Path) -> None:
    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert app.sub_title == "~/.config/tack/tack.toml (no file yet)"

    drive(scenario)


def test_a_bad_manifest_is_shown(home: Path) -> None:
    write(home / ".config" / "tack" / "tack.toml", "nonsense = 1\n")

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert "unknown key 'nonsense'" in str(app.query_one("#skills-detail", Static).render())
        assert app.sub_title == "~/.config/tack/tack.toml"
        await pilot.press("s")  # nothing to act on
        await settle(pilot)
        assert not isinstance(app.screen, ActionScreen)

    drive(scenario)


# --- rendering --------------------------------------------------------------------


PATH_SOURCE = SourceStatus("s", "path", "/x", None, Path("/x"), "ok")


def test_source_state() -> None:
    def plain(t: Text) -> str:
        return t.plain

    assert plain(render.source_state(PATH_SOURCE, None, fetching=False)) == "clean"
    edited = replace(PATH_SOURCE, uncommitted=["a", "b"], unpushed=["c"])
    assert plain(render.source_state(edited, None, fetching=False)) == "2 uncommitted, 1 unpushed"
    git_source = replace(
        PATH_SOURCE, kind="git", commit="0" * 40, locked=datetime(2026, 9, 27, tzinfo=UTC)
    )
    assert plain(render.source_state(git_source, None, fetching=True)) == "fetching..."
    behind = outdated.SourceReport("s", "u", None, "behind", behind=3)
    assert plain(render.source_state(git_source, behind, fetching=False)) == "3 behind"
    missing = replace(PATH_SOURCE, state="missing")
    assert plain(render.source_state(missing, None, fetching=False)) == "missing"


def test_source_detail_says_which_directory_a_missing_source_lacks(tmp_path: Path) -> None:
    """#40: a `path` source whose root is gone says its directory isn't there."""
    gone = replace(PATH_SOURCE, root=tmp_path / "gone", state="missing")
    assert "its directory isn't there\n" in render.source_detail(gone, None).plain
    (tmp_path / "gone").mkdir()
    assert "its skills directory isn't there\n" in render.source_detail(gone, None).plain


def test_diff_colors() -> None:
    t = render.diff("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
    assert t.plain == "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    styles = {t.plain[s.start : s.end].strip(): str(s.style) for s in t.spans}
    assert (styles["-old"], styles["+new"], styles["@@ -1 +1 @@"]) == ("red", "green", "cyan")


def test_bare_tack_outside_a_terminal_prints_usage(home: Path) -> None:
    r = subprocess.run([sys.executable, "-m", "tack"], capture_output=True, text=True)
    assert r.returncode == 2
    assert "usage: tack" in r.stderr

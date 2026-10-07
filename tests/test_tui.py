from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import DataTable, Input, Static, TabbedContent
from textual.widgets._header import HeaderTitle
from textual.widgets._tabbed_content import ContentTabs

from tack import __version__, config, outdated, sync
from tack.status import SourceStatus
from tack.tui import render
from tack.tui.app import FixedHeader, TackApp
from tack.tui.dialogs import ActionScreen, AddScreen
from tests.helpers import commit, load, repo, skill, skill_md, upstream, write

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
        await pilot.press("2")
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
        await pilot.press("3")
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
        await pilot.press("3")
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
        await pilot.press("2")
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
        await pilot.press("2", "a")
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


def test_actions_belong_to_their_tabs(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        assert tab(app) == "skills"
        assert app.check_action("update", ()) is False
        assert app.check_action("sync", ()) is True
        await pilot.press("2")
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

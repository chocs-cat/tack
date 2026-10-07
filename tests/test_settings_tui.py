from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from textual.pilot import Pilot
from textual.widgets import Checkbox, Input, Switch, TextArea

from tack import config
from tack.tui.app import TackApp
from tack.tui.dialogs import ActionScreen, ChooseScreen
from tack.tui.settings import SettingsScreen
from tests.helpers import write
from tests.test_tui import body, drive, machine, rows, settle


def manifest(home: Path) -> dict[str, Any]:
    return tomllib.loads((home / ".config" / "tack" / "tack.toml").read_text())


async def open_settings(app: TackApp, pilot: Pilot[None]) -> SettingsScreen:
    await pilot.press("comma")
    await pilot.pause()
    assert isinstance(app.screen, SettingsScreen)
    return app.screen


def test_saves_through_a_preview(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        screen = await open_settings(app, pilot)
        assert screen.query_one("#group", Switch).value
        screen.query_one("#after-save", Input).value = "true"
        screen.query_one("#group", Switch).value = False
        screen.query_one("#roots", TextArea).load_text("~/Code\n\n~/Work\n")
        screen.query_one("#harness-0-1", Checkbox).value = False  # mine: not to codex
        screen.query_one("#autocommit-0", Switch).value = True
        screen.query_one("#ref-1", Input).value = "main"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert isinstance(app.screen, ActionScreen)
        assert "would write ~/.config/tack/tack.toml" in body(app)
        assert manifest(home).get("after_save") is None  # nothing yet
        await pilot.press("y")
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        assert not isinstance(app.screen, SettingsScreen)
        saved = manifest(home)
        assert saved["after_save"] == "true"
        assert saved["tui"] == {"group_by_source": False}
        assert saved["projects"] == {"roots": ["~/Code", "~/Work"]}
        mine, up = saved["source"]
        assert mine == {
            "name": "mine",
            "path": "~/mine",
            "harnesses": ["claude-code"],
            "autocommit": True,
        }
        assert up["ref"] == "main"
        assert rows(app, "skills")[0][:2] == ["a", "mine"]  # the new default applies at once

    drive(scenario)


def test_values_back_at_their_defaults_are_removed(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)
    file = home / ".config" / "tack" / "tack.toml"
    text = file.read_text().replace(
        'path = "~/mine"\n', 'path = "~/mine"\nharnesses = ["claude-code"]\n'
    )
    file.write_text("[tui]\ngroup_by_source = false\n\n" + text)
    assert not config.load().tui.group_by_source

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        screen = await open_settings(app, pilot)
        screen.query_one("#group", Switch).value = True
        screen.query_one("#harness-0-1", Checkbox).value = True
        await pilot.press("ctrl+s")
        await settle(pilot)
        await pilot.press("y")
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        saved = manifest(home)
        assert saved["tui"] == {}
        assert "harnesses" not in saved["source"][0]

    drive(scenario)


def test_ignore_marketplaces_is_edited_by_hand_and_kept(home: Path, tmp_path: Path) -> None:
    """The Harnesses tab says `ignore_marketplaces` is edited in tack.toml, and
    saving an `ignore` list beside it leaves it alone (design.md *The TUI*)."""
    machine(home, tmp_path)
    file = home / ".config" / "tack" / "tack.toml"
    file.write_text('[harness.codex]\nignore_marketplaces = ["mine"]\n\n' + file.read_text())

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        screen = await open_settings(app, pilot)
        notes = [str(n.render()) for n in screen.query("#tab-harnesses .note")]
        assert any("ignore_marketplaces" in n and "by hand" in n for n in notes)
        screen.query_one("#ignore-1", TextArea).load_text("codebase-memory\n")
        await pilot.press("ctrl+s")
        await settle(pilot)
        await pilot.press("y")
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        assert manifest(home)["harness"]["codex"] == {
            "ignore_marketplaces": ["mine"],
            "ignore": ["codebase-memory"],
        }

    drive(scenario)


def test_cancelling_asks_before_discarding(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)
    before = (home / ".config" / "tack" / "tack.toml").read_text()

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        screen = await open_settings(app, pilot)
        await pilot.press("escape")  # nothing changed: it just closes
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        screen = await open_settings(app, pilot)
        screen.query_one("#after-save", Input).value = "true"
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ChooseScreen)
        await pilot.click("#cancel")  # keep editing
        await pilot.pause()
        assert app.screen is screen
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click("#choice-0")  # discard
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert (home / ".config" / "tack" / "tack.toml").read_text() == before

    drive(scenario)


def test_refuses_a_source_without_harnesses(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        screen = await open_settings(app, pilot)
        for j in range(2):
            screen.query_one(f"#harness-0-{j}", Checkbox).value = False
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert app.screen is screen

    drive(scenario)


def test_autopush_needs_autocommit(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        screen = await open_settings(app, pilot)
        push = screen.query_one("#autopush-0", Switch)
        assert push.disabled
        screen.query_one("#autocommit-0", Switch).value = True
        await pilot.pause()
        assert not push.disabled
        push.value = True
        screen.query_one("#autocommit-0", Switch).value = False
        await pilot.pause()
        assert push.disabled
        assert not push.value

    drive(scenario)


def test_the_apps_keys_do_nothing_behind_settings(home: Path, tmp_path: Path) -> None:
    machine(home, tmp_path)

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        screen = await open_settings(app, pilot)
        screen.query_one("#group", Switch).focus()
        await pilot.press("s", "2", "q")
        await pilot.pause()
        assert app.screen is screen
        assert app.is_running

    drive(scenario)


def test_needs_a_manifest_that_loads(home: Path) -> None:
    write(home / ".config" / "tack" / "tack.toml", "nonsense = 1\n")

    async def scenario(app: TackApp, pilot: Pilot[None]) -> None:
        await pilot.press("comma")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)

    drive(scenario)

"""The Settings screen: the manifest's settings, in tabs. Saving goes through
the same preview as any other action (tack.edit.settings writes them)."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Input,
    Label,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)

from tack.config import BUILTIN_HARNESSES, Config, UsageError
from tack.edit import Key
from tack.text import tilde
from tack.tui.dialogs import ChooseScreen

# Saves the changes (after its own preview), then calls back with whether it did.
Save = Callable[[dict[Key, Any], Callable[[bool], None]], None]


class SettingsScreen(ModalScreen[bool]):
    """Edit the manifest's settings; dismissed with whether they were saved.

    A modal screen, so the app's own keys (s, q, ...) don't act behind it."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    SettingsScreen { align: left top; background: $background; }
    SettingsScreen #settings-title { padding: 0 1; background: $panel; width: 1fr; }
    SettingsScreen TabbedContent { height: 1fr; }
    SettingsScreen VerticalScroll { height: 1fr; padding: 0 2; }
    SettingsScreen .note { color: $text-muted; height: auto; margin-top: 1; }
    SettingsScreen .row { height: auto; margin-top: 1; }
    SettingsScreen .row > Label { width: 18; padding-top: 1; }
    SettingsScreen .row > Input { width: 1fr; }
    SettingsScreen .row > TextArea { width: 1fr; height: 5; }
    SettingsScreen .row > Checkbox { width: auto; }
    SettingsScreen .row > Label.inline { width: auto; padding: 1 2 0 4; }
    SettingsScreen .hint { color: $text-muted; margin-left: 18; height: auto; }
    SettingsScreen .source { margin-top: 2; text-style: bold; height: auto; }
    SettingsScreen #bottom { height: auto; padding: 0 1; border-top: solid $panel; }
    SettingsScreen #file { width: 1fr; padding-top: 1; color: $text-muted; }
    SettingsScreen #bottom Button { margin-left: 1; }
    """

    def __init__(self, cfg: Config, save: Save) -> None:
        super().__init__()
        self.cfg = cfg
        self.save = save
        self.file = cfg.manifest or cfg.paths.manifest
        text = cfg.manifest.read_text(encoding="utf-8") if cfg.manifest else ""
        self.raw: dict[str, Any] = tomllib.loads(text)
        self.harnesses = list(cfg.harnesses)

    # --- the manifest as it is ---------------------------------------------------

    def _table(self, *path: str) -> dict[str, Any]:
        node: Any = self.raw
        for part in path:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return node if isinstance(node, dict) else {}

    def _sources(self) -> list[dict[str, Any]]:
        return self.raw.get("source", [])

    # --- layout ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("[b]Settings[/b]", id="settings-title")
        with TabbedContent(id="settings-tabs"):
            with TabPane("General", id="tab-general"), VerticalScroll():
                with Horizontal(classes="row"):
                    yield Label("after_save")
                    yield Input(
                        self.raw.get("after_save", ""), placeholder="(none)", id="after-save"
                    )
                yield Static(
                    "a command run after tack changes tack.toml or tack.lock; "
                    "{path} is the changed file",
                    classes="hint",
                )
                with Horizontal(classes="row"):
                    yield Label("Group skills")
                    yield Switch(self.cfg.tui.group_by_source, id="group")
                yield Static(
                    "whether the Skills tab opens grouped by source (g switches it until "
                    "the app closes)",
                    classes="hint",
                )
            with TabPane("Projects", id="tab-projects"), VerticalScroll():
                yield Static(
                    "doctor audits the git repositories under these roots.", classes="note"
                )
                for key, hint in (
                    ("roots", "one directory per line; ~ expands"),
                    ("exclude", "directories not searched, one per line"),
                    (
                        "owners",
                        "whose repositories are yours, one per line; a repository cloned "
                        "from anyone else isn't audited. Empty: every repository is yours",
                    ),
                ):
                    with Horizontal(classes="row"):
                        yield Label(key)
                        yield TextArea(self._lines(self._table("projects").get(key)), id=key)
                    yield Static(hint, classes="hint")
            with TabPane("Harnesses", id="tab-harnesses"), VerticalScroll():
                yield Static(
                    "Entries in a harness's skills directory that belong to someone else: "
                    "tack never touches them, and doctor doesn't report them. Harness paths "
                    "and new harnesses are edited in tack.toml by hand.",
                    classes="note",
                )
                for i, h in enumerate(self.harnesses):
                    with Horizontal(classes="row"):
                        yield Label(h)
                        ignore = self._table("harness", h).get("ignore")
                        yield TextArea(self._lines(ignore), id=f"ignore-{i}")
                    always = ["dot-entries", *BUILTIN_HARNESSES.get(h, {}).get("ignore", [])]
                    yield Static(
                        f"one per line; always ignored: {', '.join(always)}", classes="hint"
                    )
            with TabPane("Sources", id="tab-sources"), VerticalScroll():
                yield Static(
                    "Add and remove sources on the Sources tab (a, x). Which skills a source "
                    "deploys (skills) is edited in tack.toml by hand.",
                    classes="note",
                )
                for i, (src, raw) in enumerate(zip(self.cfg.sources, self._sources(), strict=True)):
                    where = tilde(src.path) if src.path is not None else str(src.git)
                    yield Static(Text.assemble(src.name, "  ", (where, "dim")), classes="source")
                    if src.git is not None:
                        with Horizontal(classes="row"):
                            yield Label("ref")
                            yield Input(
                                raw.get("ref", ""),
                                placeholder="(the remote's default branch)",
                                id=f"ref-{i}",
                            )
                    with Horizontal(classes="row"):
                        yield Label("subdir")
                        yield Input(raw.get("subdir", ""), placeholder="skills", id=f"subdir-{i}")
                    with Horizontal(classes="row"):
                        yield Label("harnesses")
                        chosen = raw.get("harnesses", self.harnesses)
                        for j, h in enumerate(self.harnesses):
                            yield Checkbox(h, h in chosen, id=f"harness-{i}-{j}")
                    if src.path is not None:
                        with Horizontal(classes="row"):
                            yield Label("autocommit")
                            yield Switch(src.autocommit, id=f"autocommit-{i}")
                            yield Label("autopush", classes="inline")
                            yield Switch(
                                src.autopush, id=f"autopush-{i}", disabled=not src.autocommit
                            )
        with Horizontal(id="bottom"):
            new = "" if self.cfg.manifest else " (a new file)"
            yield Static(f"saved to {tilde(self.file)}{new}", id="file")
            yield Button("Save", variant="primary", id="save")
            yield Button("Cancel", id="cancel")
        yield Footer()

    @staticmethod
    def _lines(value: Any) -> str:
        return "\n".join(value) if isinstance(value, list) else ""

    @on(Switch.Changed)
    def _autocommit_changed(self, event: Switch.Changed) -> None:
        """autopush needs autocommit."""
        sid = event.switch.id or ""
        if sid.startswith("autocommit-"):
            push = self.query_one(f"#autopush-{sid.removeprefix('autocommit-')}", Switch)
            push.disabled = not event.value
            if not event.value:
                push.value = False

    # --- what changed ------------------------------------------------------------

    def changes(self) -> dict[Key, Any]:
        """The edits as manifest changes: a value to set, or None to remove the
        key, which is what a value back at its default does. UsageError names
        what's wrong."""
        out: dict[Key, Any] = {}

        def put(key: Key, new: Any, default: Any, same: Callable[[Any, Any], bool] | None = None):
            node: Any = self.raw
            for part in key[:-1]:
                node = node[part] if isinstance(part, int) else node.get(part, {})
            current = node.get(key[-1], default) if isinstance(node, dict) else default
            if (same or (lambda a, b: a == b))(new, current):
                return
            out[key] = None if new == default else new

        def text(wid: str) -> str:
            return self.query_one(f"#{wid}", Input).value.strip()

        def items(wid: str) -> list[str]:
            area = self.query_one(f"#{wid}", TextArea)
            return [line.strip() for line in area.text.splitlines() if line.strip()]

        put(("after_save",), text("after-save"), "")
        put(("tui", "group_by_source"), self.query_one("#group", Switch).value, True)
        for key in ("roots", "exclude", "owners"):
            put(("projects", key), items(key), [])
        for i, h in enumerate(self.harnesses):
            put(("harness", h, "ignore"), items(f"ignore-{i}"), [])
        for i, src in enumerate(self.cfg.sources):
            if src.git is not None:
                put(("source", i, "ref"), text(f"ref-{i}"), "")
            put(("source", i, "subdir"), text(f"subdir-{i}") or "skills", "skills")
            chosen = [
                h
                for j, h in enumerate(self.harnesses)
                if self.query_one(f"#harness-{i}-{j}", Checkbox).value
            ]
            if not chosen:
                raise UsageError(f"{src.name} needs at least one harness")
            put(("source", i, "harnesses"), chosen, self.harnesses, lambda a, b: set(a) == set(b))
            if src.path is not None:
                for key in ("autocommit", "autopush"):
                    put(("source", i, key), self.query_one(f"#{key}-{i}", Switch).value, False)
        return out

    # --- saving ------------------------------------------------------------------

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        try:
            changes = self.changes()
        except UsageError as e:
            self.notify(str(e), title="Not saved", severity="error")
            return
        if not changes:
            self.notify("nothing has changed")
            return
        self.save(changes, self._saved)

    def _saved(self, saved: bool) -> None:
        if saved:
            self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    @work
    async def action_cancel(self) -> None:
        try:
            dirty = bool(self.changes())
        except UsageError:
            dirty = True
        if dirty:
            choice = await self.app.push_screen_wait(
                ChooseScreen("Discard your changes to the settings?", ["Discard"])
            )
            if choice is None:
                return
        self.dismiss(False)

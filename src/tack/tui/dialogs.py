"""The TUI's dialogs: an action's preview and result, the form for adding a
source, and the choice of which harness wins a hook mismatch."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable
from typing import Any, ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from tack import git
from tack.config import ConfigError, UsageError
from tack.sync import Result
from tack.text import plural
from tack.tui import render

Action = Callable[[bool], Result]  # runs the action, as a dry run when given True


class ActionScreen(ModalScreen[bool]):
    """An action's dry run, to confirm; then what it did. Dismissed with
    whether it ran."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "confirm", "Confirm"),
        Binding("n,escape", "close", "Close"),
        Binding("p", "pager", "Pager"),
    ]

    def __init__(
        self, title: str, run: Action, lock: threading.Lock, *, idle: str = "nothing to do"
    ) -> None:
        super().__init__()
        self.heading = title
        self.action = run
        self.checkouts = lock
        self.idle = idle
        # previewing -> ready (to confirm) or idle (nothing to do); ready -> running -> done
        self.state = "previewing"
        self.last: Result | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.heading, id="dialog-title")
            with VerticalScroll():
                yield Static("working out what would change...", id="dialog-body")
            with Horizontal(id="dialog-buttons"):
                yield Button("Confirm (y)", id="confirm", variant="primary", disabled=True)
                yield Button("Cancel (n)", id="close")

    def on_mount(self) -> None:
        self._run(dry_run=True)

    @work(thread=True, exclusive=True)
    def _run(self, *, dry_run: bool) -> None:
        if not self.checkouts.acquire(blocking=False):
            self.app.call_from_thread(self._show, Text("waiting for the fetch to finish..."))
            self.checkouts.acquire()
        try:
            result: Result | str = self.action(dry_run)
        except (UsageError, ConfigError) as e:
            result = str(e)
        finally:
            self.checkouts.release()
        self.app.call_from_thread(self._finish, result, dry_run)

    def _show(self, body: Text) -> None:
        self.query_one("#dialog-body", Static).update(body)

    def _finish(self, result: Result | str, dry_run: bool) -> None:
        confirm = self.query_one("#confirm", Button)
        if isinstance(result, str):
            self._show(Text(result, style="red"))
        else:
            self.last = result
            self._show(render.result(result, "nothing to do" if dry_run else self.idle))
        if dry_run and isinstance(result, Result) and result.changes:
            self.state = "ready"
            confirm.disabled = False
            confirm.focus()
            return
        self.state = "idle" if dry_run else "done"
        self.query_one("#close", Button).label = "Close (n)"
        if isinstance(result, Result) and not dry_run:
            summary = plural(len(result.changes), "change")
            if result.problems:
                summary += f", {plural(len(result.problems), 'problem')}"
            self.notify(summary, severity="error" if result.problems else "information")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.action_confirm()
        else:
            self.action_close()

    def action_confirm(self) -> None:
        if self.state != "ready":
            return
        self.state = "running"
        self.query_one("#confirm", Button).disabled = True
        self._show(Text("running..."))
        self._run(dry_run=False)

    def action_close(self) -> None:
        if self.state not in ("previewing", "running"):
            self.dismiss(self.state == "done")
        elif self.state == "previewing":
            self.dismiss(False)

    def action_pager(self) -> None:
        if self.last is not None and (patch := render.diffs(self.last)):
            page(self.app, patch)


def page(app: App[Any], patch: str) -> None:
    """Suspend the app and show `patch` in git's pager."""
    pager = git.run(None, "var", "GIT_PAGER").stdout.strip() or "less"
    env = {"LESS": "FRX", "LV": "-c", **os.environ}
    with app.suspend():
        subprocess.run(["sh", "-c", pager], input=patch, text=True, env=env, check=False)


class AddScreen(ModalScreen[dict[str, Any] | None]):
    """The form for `tack add`; dismissed with its fields, or None."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Add a source", id="dialog-title")
            yield Input(placeholder="a git URL, or a directory", id="spec")
            yield Input(placeholder="name (default: from the URL or directory)", id="name")
            yield Input(
                placeholder="skills to deploy, space-separated (default: all; none with plugins)",
                id="skills",
            )
            yield Input(
                placeholder="plugins to deploy, space-separated (default: none)", id="plugins"
            )
            yield Input(placeholder="ref: branch or tag to follow (git only)", id="ref")
            yield Input(placeholder="subdir holding the skills (default: skills)", id="subdir")
            with Horizontal(id="dialog-buttons"):
                yield Button("Preview", id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    def _value(self, id: str) -> str | None:
        return self.query_one(f"#{id}", Input).value.strip() or None

    def on_input_submitted(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        spec = self._value("spec")
        if spec is None:
            self.notify("a git URL or a directory is needed", severity="warning")
            return
        self.dismiss(
            {
                "spec": spec,
                "name": self._value("name"),
                "skills": (self._value("skills") or "").replace(",", " ").split(),
                "plugins": (self._value("plugins") or "").replace(",", " ").split(),
                "ref": self._value("ref"),
                "subdir": self._value("subdir"),
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChooseScreen(ModalScreen[str | None]):
    """A choice among a few names; dismissed with the one picked, or None."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, question: str, choices: list[str]) -> None:
        super().__init__()
        self.question = question
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question, id="dialog-title")
            with Horizontal(id="dialog-buttons"):
                for i, choice in enumerate(self.choices):
                    yield Button(
                        choice, id=f"choice-{i}", variant="primary" if i == 0 else "default"
                    )
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        self.dismiss(self.choices[int(bid.split("-")[1])] if bid.startswith("choice-") else None)

    def action_cancel(self) -> None:
        self.dismiss(None)

"""The tack app: Skills, Sources and Doctor tabs over the CLI's operations.

The local state (status and the audit) and the upstream fetch load in
background threads. Actions run through ActionScreen, which previews them as
a dry run first; an action and a fetch share a lock, so they never work in
one checkout at once.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.content import Content
from textual.events import Click
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from tack import __version__, commit, config, doctor, edit, outdated, scaffold, status, sync, update
from tack.config import Config, ConfigError
from tack.doctor.findings import SEVERITIES, Finding
from tack.sync import Result
from tack.text import tilde
from tack.tui import render
from tack.tui.dialogs import Action, ActionScreen, AddScreen, ChooseScreen, page

TABS = ("skills", "sources", "doctor")
_TAB_ACTIONS = {
    "update": "sources",
    "add": "sources",
    "remove": "sources",
    "pager": "sources",
    "fix": "doctor",
}


class FixedHeader(Header):
    """A Header that stays one line: Textual's grows taller on click."""

    def on_click(self, event: Click) -> None:
        event.prevent_default()  # stops Header's own handler, later in the MRO


class TackApp(App[None]):
    TITLE = "tack"
    CSS = """
    TabPane { padding: 0; }
    .pane { height: 1fr; }
    DataTable { width: 1fr; height: 1fr; }
    .detail { width: 1fr; height: 1fr; border-left: solid $primary; padding: 0 1; }
    ModalScreen { align: center middle; }
    #dialog {
        width: 90%; height: auto; max-height: 90%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #dialog VerticalScroll { height: auto; max-height: 30; }
    #dialog-title { text-style: bold; margin-bottom: 1; }
    #dialog-buttons { height: auto; margin-top: 1; }
    #dialog-buttons Button { margin-right: 2; }
    #dialog Input { margin-bottom: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "sync", "Sync"),
        Binding("u", "update", "Update"),
        Binding("a", "add", "Add"),
        Binding("x", "remove", "Remove"),
        Binding("f", "fix", "Fix"),
        Binding("p", "pager", "Pager"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab('skills')", "Skills", show=False),
        Binding("2", "tab('sources')", "Sources", show=False),
        Binding("3", "tab('doctor')", "Doctor", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__()
        self.config_dir = config_dir
        self.cfg: Config | None = None
        self.status: status.Status | None = None
        self.audit: doctor.Report | None = None
        self.upstream: outdated.Report | None = None
        self.fetching = False
        self.checkouts = threading.Lock()  # held by an action or a fetch, never both
        self.auto_tab = True  # until you pick a tab, the app picks one
        self._picking = False

    def format_title(self, title: str, sub_title: str) -> Content:
        if not sub_title:
            return Content(title)
        return Content.assemble(title, (" • ", "dim"), (sub_title, "dim"))

    def compose(self) -> ComposeResult:
        yield FixedHeader()
        with TabbedContent(initial="skills"):
            for tab in TABS:
                with TabPane(tab.capitalize(), id=tab), Horizontal(classes="pane"):
                    table: DataTable[Any] = DataTable(id=f"{tab}-table", cursor_type="row")
                    table.zebra_stripes = True
                    yield table
                    with VerticalScroll(classes="detail"):
                        yield Static(id=f"{tab}-detail")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"tack {__version__}"
        self.action_refresh()

    # --- loading --------------------------------------------------------------

    def action_refresh(self) -> None:
        manifest = config.Paths.from_env(self.config_dir and self.config_dir.absolute()).manifest
        self.sub_title = tilde(manifest) + ("" if manifest.is_file() else " (no file yet)")
        try:
            self.cfg = config.load(self.config_dir)
        except ConfigError as e:
            self.cfg = None
            self.notify(str(e), title="tack.toml", severity="error", timeout=30)
            for tab in TABS:
                self._detail(tab, Text(str(e), style="red"))
            return
        self.fetching = True
        self._load_local(self.cfg)
        self._load_upstream(self.cfg)

    @work(thread=True, exclusive=True, group="local")
    def _load_local(self, cfg: Config) -> None:
        try:
            st, audit = status.status(cfg), doctor.run(cfg)
        except ConfigError as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        self.call_from_thread(self._show_local, st, audit)

    @work(thread=True, exclusive=True, group="upstream")
    def _load_upstream(self, cfg: Config) -> None:
        with self.checkouts:
            try:
                report: outdated.Report | None = outdated.outdated(cfg, diff=True)
            except ConfigError as e:
                self.call_from_thread(self.notify, str(e), severity="error")
                report = None
        self.call_from_thread(self._show_upstream, report)

    def _show_local(self, st: status.Status, audit: doctor.Report) -> None:
        # Errors first, then warnings, then info; by project within each.
        order = {s: i for i, s in enumerate(SEVERITIES)}
        audit.findings.sort(key=lambda f: (order[f.severity], str(f.project or "")))
        self.status, self.audit = st, audit
        self._fill_skills()
        self._fill_sources()
        self._fill_doctor()
        self._pick_tab()

    def _show_upstream(self, report: outdated.Report | None) -> None:
        self.upstream, self.fetching = report, False
        self._fill_sources()
        self._pick_tab()

    def _pick_tab(self) -> None:
        """Open on the tab that needs attention, once everything has loaded."""
        if not self.auto_tab or self.fetching or self.status is None or self.audit is None:
            return
        self.auto_tab = False
        behind = self.upstream is not None and any(
            s.state == "behind" for s in self.upstream.sources
        )
        edits = any(s.uncommitted or s.unpushed for s in self.status.sources)
        tab = "doctor" if self.audit.failed else "sources" if behind or edits else "skills"
        self._picking = True
        self.query_one(TabbedContent).active = tab

    @on(TabbedContent.TabActivated)
    def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if self._picking:
            self._picking = False
        elif self.status is not None:
            self.auto_tab = False  # you picked one
        tab = event.pane.id or ""
        if tab in TABS:
            self._table(tab).focus()
        self.refresh_bindings()

    # --- the tabs -------------------------------------------------------------

    def _table(self, tab: str) -> DataTable[Any]:
        return self.query_one(f"#{tab}-table", DataTable)

    def _detail(self, tab: str, body: Text) -> None:
        self.query_one(f"#{tab}-detail", Static).update(body)

    def _selected(self, tab: str) -> str | None:
        table = self._table(tab)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def _refill(self, tab: str, columns: list[str], rows: list[tuple[str, list[Any]]]) -> None:
        """Replace a table's rows, keeping the cursor on the same key."""
        table = self._table(tab)
        keep = self._selected(tab)
        table.clear(columns=True)
        table.add_columns(*columns)
        for key, cells in rows:
            table.add_row(*cells, key=key)
        keys = [k for k, _ in rows]
        if keep in keys:
            table.move_cursor(row=keys.index(keep))
        self._show_detail(tab)

    def _fill_skills(self) -> None:
        if self.status is None or self.cfg is None:
            return
        harnesses = list(self.cfg.harnesses)
        rows = []
        for k in self.status.skills:
            cells: list[Any] = [k.name, k.source]
            for h in harnesses:
                state = k.harnesses.get(h)
                cells.append(Text(state, style=render.LINK_STYLE[state]) if state else "-")
            rows.append((f"{k.source}/{k.name}", cells))
        self._refill("skills", ["skill", "source", *harnesses], rows)

    def _fill_sources(self) -> None:
        if self.status is None:
            return
        rows = []
        for s in self.status.sources:
            state = render.source_state(s, self._upstream(s.name), fetching=self.fetching)
            rows.append((s.name, [s.name, s.kind, state]))
        self._refill("sources", ["source", "kind", "state"], rows)

    def _fill_doctor(self) -> None:
        if self.audit is None:
            return
        rows = []
        for i, f in enumerate(self.audit.findings):
            where = tilde(f.project) if f.project else "global"
            severity = Text(f.severity, style=render.SEVERITY_STYLE[f.severity])
            rows.append((str(i), [severity, f.id, where, f.fix or ""]))
        self._refill("doctor", ["severity", "finding", "where", "fix"], rows)
        if not rows:
            self._detail("doctor", Text("no findings", style="green"))

    def _upstream(self, name: str) -> outdated.SourceReport | None:
        if self.upstream is None:
            return None
        return next((r for r in self.upstream.sources if r.name == name), None)

    def _finding(self) -> Finding | None:
        key = self._selected("doctor")
        return self.audit.findings[int(key)] if self.audit is not None and key else None

    @on(DataTable.RowHighlighted)
    def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._show_detail((event.data_table.id or "").removesuffix("-table"))

    def _show_detail(self, tab: str) -> None:
        key = self._selected(tab)
        if key is None or self.status is None:
            return
        if tab == "skills":
            skill = next(k for k in self.status.skills if f"{k.source}/{k.name}" == key)
            self._detail(tab, render.skill_detail(skill))
        elif tab == "sources":
            source = next(s for s in self.status.sources if s.name == key)
            self._detail(tab, render.source_detail(source, self._upstream(key)))
        elif tab == "doctor" and (f := self._finding()) is not None:
            self._detail(tab, render.finding_detail(f))

    # --- actions --------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show each tab's actions only on that tab."""
        tab = _TAB_ACTIONS.get(action)
        if tab is None:
            return True
        return self.query_one(TabbedContent).active == tab

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def _act(self, title: str, run: Action, idle: str = "nothing to do") -> None:
        """Preview an action, run it once confirmed, then auto-commit as the CLI
        does, and refresh the tabs."""
        cfg = self.cfg
        if cfg is None:
            self.notify("fix tack.toml first", severity="error")
            return

        def with_commit(dry_run: bool) -> Result:
            result = run(dry_run)
            if not commit.disabled():
                result.extend(commit.autocommit(cfg, dry_run=dry_run))
            return result

        def done(ran: bool | None) -> None:
            if ran:
                self.action_refresh()

        self.push_screen(ActionScreen(title, with_commit, self.checkouts, idle=idle), done)

    def action_sync(self) -> None:
        cfg = self.cfg
        if cfg is not None:
            self._act("Sync", lambda dry: sync.sync(cfg, dry_run=dry), idle="already in sync")

    def action_update(self) -> None:
        name, cfg = self._selected("sources"), self.cfg
        if name is None or cfg is None:
            return
        if not any(s.name == name and s.git for s in cfg.sources):
            self.notify(f"{name} is a path source; only git sources are pinned")
            return
        self._act(
            f"Update {name}",
            lambda dry: update.update(cfg, [name], dry_run=dry),
            idle="already up to date",
        )

    def action_add(self) -> None:
        cfg = self.cfg
        if cfg is None:
            return

        def added(fields: dict[str, Any] | None) -> None:
            if fields is not None:
                spec = fields.pop("spec")
                self._act(f"Add {spec}", lambda dry: edit.add(cfg, spec, **fields, dry_run=dry))

        self.push_screen(AddScreen(), added)

    def action_remove(self) -> None:
        name, cfg = self._selected("sources"), self.cfg
        if name is not None and cfg is not None:
            self._act(f"Remove {name}", lambda dry: edit.remove(cfg, name, dry_run=dry))

    def action_fix(self) -> None:
        f, cfg = self._finding(), self.cfg
        if f is None or cfg is None:
            return
        if f.fix is None or f.project is None:
            self.notify(f"{f.id} has no fix tack can apply")
            return
        fix, project = f.fix, f.project

        def fixed(source: str | None) -> None:
            self._act(
                f"Fix {fix} in {tilde(project)}",
                lambda dry: scaffold.scaffold(cfg, fix, project, source=source, dry_run=dry),
                idle="nothing to fix",
            )

        if f.id == "hook-mismatch":

            def chosen(source: str | None) -> None:
                if source is not None:
                    fixed(source)

            self.push_screen(
                ChooseScreen("Whose version of the hook wins?", list(cfg.harnesses)), chosen
            )
        else:
            fixed(None)

    def action_pager(self) -> None:
        if self.query_one(TabbedContent).active != "sources":
            return
        name = self._selected("sources")
        up = self._upstream(name) if name else None
        if up is not None and up.diff:
            page(self, up.diff)
        else:
            self.notify("no upstream diff to show")

"""The tack app: Skills, Plugins, Sources and Doctor tabs over the CLI's
operations.

The local state (status and the audit) and the upstream fetch load in
background threads. Actions run through ActionScreen, which previews them as
a dry run first; an action and a fetch share a lock, so they never work in
one checkout at once.
"""

from __future__ import annotations

import contextlib
import threading
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, cast

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.content import Content
from textual.css.query import NoMatches
from textual.events import Click
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from tack import (
    __version__,
    agents,
    commit,
    config,
    doctor,
    edit,
    outdated,
    scaffold,
    status,
    sync,
    update,
)
from tack.config import Config, ConfigError
from tack.doctor.findings import SEVERITIES, Finding
from tack.sync import Result
from tack.text import tilde
from tack.tui import render
from tack.tui.dialogs import Action, ActionScreen, AddScreen, ChooseScreen, page
from tack.tui.settings import SettingsScreen

TABS = ("skills", "plugins", "sources", "doctor")
# The tabs each action belongs to; the others' belong to every tab.
_TAB_ACTIONS: dict[str, tuple[str, ...]] = {
    "update": ("sources",),
    "add": ("sources",),
    "remove": ("sources",),
    "pager": ("sources",),
    "fix": ("doctor",),
    "sort_next": ("skills", "plugins"),
    "sort_reverse": ("skills", "plugins"),
    "group": ("skills", "plugins"),
}
# A harness column sorts problems first; a skill that doesn't go to the
# harness comes last.
_LINK_ORDER = {"conflict": 0, "collision": 0, "stale": 1, "missing": 2, "linked": 3}
# The same for a plugin (design.md *The TUI*, the Plugins bullet).
_PLUGIN_ORDER = {
    "conflict": 0, "collision": 0, "stale": 1, "disabled": 2, "unavailable": 3, "missing": 4,
    "installed": 5,
}  # fmt: skip

_Item = status.SkillStatus | status.PluginStatus


@dataclass(frozen=True)
class _Kind:
    """What sets the Skills and Plugins tables apart: the name column, the
    order a harness column sorts by, the state a group row doesn't count, and
    the states' colors."""

    column: str
    order: Mapping[str, int]
    fine: str
    style: Mapping[str, str]


_KINDS = {
    "skills": _Kind("skill", _LINK_ORDER, "linked", render.LINK_STYLE),
    "plugins": _Kind("plugin", _PLUGIN_ORDER, "installed", render.PLUGIN_STYLE),
}


@dataclass
class _View:
    """A table's sort (the column, and whether it is reversed), grouping and
    folded sources: each tab's own, held through refreshes until the app
    closes."""

    sort: tuple[str, bool] | None = None
    grouped: bool = True  # set from the manifest's [tui] once it has been read
    folded: set[str] = field(default_factory=set)


class FixedHeader(Header):
    """A Header that stays one line: Textual's grows taller on click."""

    def on_click(self, event: Click) -> None:
        event.prevent_default()  # stops Header's own handler, later in the MRO


class GroupedTable(DataTable[Any]):
    """The Skills or Plugins table, whose source rows fold while it is
    grouped."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "toggle_fold", "Fold"),
        Binding("left,h", "fold", "Fold", show=False),
        Binding("right,l", "unfold", "Unfold", show=False),
    ]

    @property
    def tack(self) -> TackApp:
        return cast("TackApp", self.app)

    @property
    def tab(self) -> str:
        return (self.id or "").removesuffix("-table")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return self.tack.views[self.tab].grouped or action != "toggle_fold"

    def action_toggle_fold(self) -> None:
        self.tack.fold(self.tab, None)

    def action_fold(self) -> None:
        if self.tack.views[self.tab].grouped:
            self.tack.fold(self.tab, True)
        else:
            self.action_cursor_left()

    def action_unfold(self) -> None:
        if self.tack.views[self.tab].grouped:
            self.tack.fold(self.tab, False)
        else:
            self.action_cursor_right()


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
        Binding("o", "sort_next", "Sort"),
        Binding("O", "sort_reverse", "Reverse sort", show=False),
        Binding("g", "group", "Group"),
        Binding("r", "refresh", "Refresh"),
        Binding("comma", "settings", "Settings"),
        Binding("1", "tab('skills')", "Skills", show=False),
        Binding("2", "tab('plugins')", "Plugins", show=False),
        Binding("3", "tab('sources')", "Sources", show=False),
        Binding("4", "tab('doctor')", "Doctor", show=False),
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
        self.views = {tab: _View() for tab in _KINDS}
        self._grouping_set = False

    def format_title(self, title: str, sub_title: str) -> Content:
        if not sub_title:
            return Content(title)
        return Content.assemble(title, (" • ", "dim"), (sub_title, "dim"))

    def compose(self) -> ComposeResult:
        yield FixedHeader()
        with TabbedContent(initial="skills"):
            for tab in TABS:
                with TabPane(tab.capitalize(), id=tab), Horizontal(classes="pane"):
                    kind = GroupedTable if tab in _KINDS else DataTable
                    table: DataTable[Any] = kind(id=f"{tab}-table", cursor_type="row")
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
        if not self._grouping_set:  # g changes it from then on
            for view in self.views.values():
                view.grouped = self.cfg.tui.group_by_source
            self._grouping_set = True
        self.fetching = True
        self._load_local(self.cfg)
        self._load_upstream(self.cfg)

    @work(thread=True, exclusive=True, group="local")
    def _load_local(self, cfg: Config) -> None:
        try:
            # Each agent's plugins are listed once, for the Plugins tab and
            # the audit both (design.md *The TUI*).
            inventories = agents.inventories(cfg.paths, config.PLUGIN_HARNESSES)
            st = status.status(cfg, inventories)
            audit = doctor.run(cfg, inventories=inventories)
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
        with contextlib.suppress(NoMatches):  # the app quit while this was loading
            for tab in _KINDS:
                self._fill(tab)
            self._fill_sources()
            self._fill_doctor()

    def _show_upstream(self, report: outdated.Report | None) -> None:
        self.upstream, self.fetching = report, False
        with contextlib.suppress(NoMatches):  # the app quit while this was fetching
            self._fill_sources()

    def _show_tab(self, tab: str) -> None:
        """Activate `tab` and focus its table. Focusing a table queues a
        message that activates the tab it's in; one still queued from earlier
        would undo a tab set directly, but not this, which queues after it."""
        self.query_one(TabbedContent).active = tab
        self._table(tab).focus()

    @on(TabbedContent.TabActivated)
    def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab = event.pane.id or ""
        with contextlib.suppress(NoMatches):  # the app is closing
            # A late event for a tab that is no longer active is ignored:
            # focusing its table would activate that tab again, and two such
            # events would swap the tabs back and forth for good.
            if tab != self.query_one(TabbedContent).active:
                return
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

    def _refill(
        self,
        tab: str,
        columns: list[str],
        rows: list[tuple[str, list[Any]]],
        labels: list[str] | None = None,
        keep: str | None = None,
    ) -> None:
        """Replace a table's rows, keeping the cursor on the same key (or on
        `keep`). Each column's key is its name in `columns`, and its label that
        or `labels`'."""
        table = self._table(tab)
        keep = keep or self._selected(tab)
        table.clear(columns=True)
        for key, label in zip(columns, labels or columns, strict=True):
            table.add_column(label, key=key)
        for key, cells in rows:
            table.add_row(*cells, key=key)
        keys = [k for k, _ in rows]
        if keep in keys:
            table.move_cursor(row=keys.index(keep))
        self._show_detail(tab)

    def _harnesses(self, tab: str) -> list[str]:
        """The harness columns: every harness on Skills, on Plugins those that
        take plugins, in the same order."""
        names = list(self.cfg.harnesses) if self.cfg is not None else []
        return names if tab == "skills" else [h for h in names if h in config.PLUGIN_HARNESSES]

    def _columns(self, tab: str) -> list[str]:
        source = [] if self.views[tab].grouped else ["source"]
        return [_KINDS[tab].column, *source, *self._harnesses(tab)]

    def _items(self, tab: str) -> list[_Item]:
        if self.status is None:
            return []
        return list(self.status.skills if tab == "skills" else self.status.plugins)

    def _groups(self, tab: str) -> list[str]:
        """The sources with a row while grouped, in the manifest's order: on
        Plugins, those whose `plugins` isn't `[]`, and none while no plugin
        is selected."""
        if (
            self.status is None
            or self.cfg is None
            or (tab == "plugins" and not self.status.plugins)
        ):
            return []
        selecting = {s.name for s in self.cfg.sources if tab == "skills" or s.plugins != ()}
        return [s.name for s in self.status.sources if s.name in selecting]

    def _fill(self, tab: str, keep: str | None = None) -> None:
        """Fill Skills or Plugins: grouped, a row per source (in the
        manifest's order) with its skills or plugins beneath unless it is
        folded. Row keys are `source/name` for a skill or a plugin and the
        bare name for a source, which can't contain a slash. With no plugin
        selected, Plugins is empty and says so."""
        if self.status is None or self.cfg is None:
            return
        view = self.views[tab]
        harnesses = self._harnesses(tab)
        items = self._sorted(tab, self._items(tab))
        rows: list[tuple[str, list[Any]]] = []
        if view.grouped:
            for name in self._groups(tab):
                group = [k for k in items if k.source == name]
                rows.append((name, self._group_cells(tab, name, group, harnesses)))
                if name not in view.folded:
                    rows += [(f"{name}/{k.name}", self._cells(tab, k, harnesses)) for k in group]
        else:
            rows = [(f"{k.source}/{k.name}", self._cells(tab, k, harnesses)) for k in items]
        # The cursor stays on its row; when that row is gone (folded away,
        # or a source row after ungrouping), it goes to the nearest one.
        keys = [key for key, _ in rows]
        keep = keep or self._selected(tab)
        if keep is not None and keep not in keys:
            source = keep.split("/")[0]
            keep = (
                source
                if source in keys
                else next((key for key in keys if key.startswith(f"{source}/")), None)
            )
        columns = self._columns(tab)
        labels = list(columns)
        if view.sort is not None and view.sort[0] in columns:
            column, reverse = view.sort
            labels[columns.index(column)] += " ▼" if reverse else " ▲"
        self._refill(tab, columns, rows, labels, keep)
        if not rows and tab == "plugins":
            self._detail(tab, Text(render.NO_PLUGINS))

    def _cells(self, tab: str, k: _Item, harnesses: list[str]) -> list[Any]:
        cells: list[Any] = [f"  {k.name}"] if self.views[tab].grouped else [k.name, k.source]
        for h in harnesses:
            state = k.harnesses.get(h)
            cells.append(Text(state, style=_KINDS[tab].style[state]) if state else "-")
        return cells

    def _group_cells(
        self, tab: str, name: str, group: list[_Item], harnesses: list[str]
    ) -> list[Any]:
        """A source's row: its name and how many skills or plugins it selects,
        and per harness how many of them aren't linked or installed there,
        by state in the column's sort order."""
        kind = _KINDS[tab]
        arrow = "▸" if name in self.views[tab].folded else "▾"
        cells: list[Any] = [Text.assemble(f"{arrow} ", (name, "bold"), f" ({len(group)})")]
        for h in harnesses:
            states = Counter(
                st for k in group if (st := k.harnesses.get(h)) is not None and st != kind.fine
            )
            order = sorted(states, key=lambda st: (kind.order[st], st))
            summary = ", ".join(f"{states[st]} {st}" for st in order)
            cells.append(Text(summary, style=kind.style[order[0]]) if order else "")
        return cells

    def _sorted(self, tab: str, items: list[_Item]) -> list[_Item]:
        """`items` in the tab's sort; ties, like the unsorted table, by name
        and then source (the order status gives them)."""
        sort, kind = self.views[tab].sort, _KINDS[tab]
        if sort is None:
            return items
        column, reverse = sort

        def key(k: _Item) -> str | int:
            if column == kind.column:
                return k.name.casefold()
            if column == "source":
                return k.source.casefold()
            state = k.harnesses.get(column)
            return kind.order[state] if state else len(kind.order)

        return sorted(items, key=key, reverse=reverse)  # stable, reversed or not

    def _sort_by(self, tab: str, column: str) -> None:
        """Sort the tab's table by `column`; if it already is, reverse it."""
        view = self.views[tab]
        if view.sort is not None and view.sort[0] == column:
            view.sort = (column, not view.sort[1])
        else:
            view.sort = (column, False)
        self._fill(tab)

    def fold(self, tab: str, fold: bool | None) -> None:
        """Fold (True), unfold (False) or toggle (None) the source group under
        the tab's cursor; folding from an item's row moves the cursor to its
        source."""
        view, key = self.views[tab], self._selected(tab)
        if not view.grouped or key is None:
            return
        source, on_source = key.split("/")[0], "/" not in key
        fold = source not in view.folded if fold is None else fold
        if not fold and not on_source:
            return
        if fold:
            view.folded.add(source)
        else:
            view.folded.discard(source)
        self._fill(tab, keep=source)

    @on(DataTable.RowSelected, "GroupedTable")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        if "/" not in str(event.row_key.value):  # enter, or a click on the selected row
            self.fold(cast("GroupedTable", event.data_table).tab, None)

    def _grouped_tab(self) -> str | None:
        """The active tab, if it is Skills or Plugins: the tab the sort and
        group actions act on."""
        tab = self.query_one(TabbedContent).active
        return tab if tab in _KINDS else None

    def action_group(self) -> None:
        if (tab := self._grouped_tab()) is not None:
            self.views[tab].grouped = not self.views[tab].grouped
            self._fill(tab)

    @on(DataTable.HeaderSelected, "GroupedTable")
    def _header_selected(self, event: DataTable.HeaderSelected) -> None:
        self._sort_by(cast("GroupedTable", event.data_table).tab, str(event.column_key.value))

    def action_sort_next(self) -> None:
        if (tab := self._grouped_tab()) is None:
            return
        sort, columns = self.views[tab].sort, self._columns(tab)
        at = columns.index(sort[0]) + 1 if sort and sort[0] in columns else 0
        self.views[tab].sort = None
        self._sort_by(tab, columns[at % len(columns)])

    def action_sort_reverse(self) -> None:
        if (tab := self._grouped_tab()) is None:
            return
        view = self.views[tab]
        if view.sort is None:  # the default order is by name
            view.sort = (self._columns(tab)[0], False)
        self._sort_by(tab, view.sort[0])

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
        if tab == "skills" and "/" in key:
            skill = next(k for k in self.status.skills if f"{k.source}/{k.name}" == key)
            self._detail(tab, render.skill_detail(skill))
        elif tab == "plugins" and "/" in key:
            plugin = next(p for p in self.status.plugins if f"{p.source}/{p.name}" == key)
            self._detail(tab, render.plugin_detail(plugin))
        elif tab in ("skills", "plugins", "sources"):
            source = next(s for s in self.status.sources if s.name == key)
            self._detail(tab, render.source_detail(source, self._upstream(key)))
        elif tab == "doctor" and (f := self._finding()) is not None:
            self._detail(tab, render.finding_detail(f))

    # --- actions --------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show each tab's actions only on the tabs they belong to."""
        tabs = _TAB_ACTIONS.get(action)
        if tabs is None:
            return True
        return self.query_one(TabbedContent).active in tabs

    def action_tab(self, tab: str) -> None:
        self._show_tab(tab)

    def _act(
        self,
        title: str,
        run: Action,
        idle: str = "nothing to do",
        then: Callable[[bool], None] | None = None,
    ) -> None:
        """Preview an action, run it once confirmed, then auto-commit as the CLI
        does, and refresh the tabs; `then` hears whether it ran."""
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
            if then is not None:
                then(bool(ran))

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

    def action_settings(self) -> None:
        cfg = self.cfg
        if cfg is None:
            self.notify("fix tack.toml first", severity="error")
            return

        def save(changes: dict[edit.Key, Any], then: Callable[[bool], None]) -> None:
            def saved(ran: bool) -> None:
                # A new default for grouping applies at once; otherwise g's
                # choice for this session stands.
                if ran and ("tui", "group_by_source") in changes and self.cfg is not None:
                    for tab, view in self.views.items():
                        view.grouped = self.cfg.tui.group_by_source
                        self._fill(tab)
                then(ran)

            self._act(
                "Save settings",
                lambda dry: edit.settings(cfg, changes, dry_run=dry),
                idle="nothing to change",
                then=saved,
            )

        self.push_screen(SettingsScreen(cfg, save))

    def action_pager(self) -> None:
        if self.query_one(TabbedContent).active != "sources":
            return
        name = self._selected("sources")
        up = self._upstream(name) if name else None
        if up is not None and up.diff:
            page(self, up.diff)
        else:
            self.notify("no upstream diff to show")

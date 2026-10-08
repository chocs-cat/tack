"""What the TUI shows for each row and each result, as Rich text.

Plain functions over the same results the CLI prints, so they can be tested
without running the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text

from tack import catalog, outdated, plugins, text
from tack.doctor.findings import Finding
from tack.doctor.skills import frontmatter, skill_problem
from tack.status import PluginStatus, SkillStatus, SourceStatus
from tack.sync import Result
from tack.text import plural, tilde

SEVERITY_STYLE = {"error": "bold red", "warn": "yellow", "info": "cyan"}
LINK_STYLE = {
    "linked": "green",
    "missing": "yellow",
    "stale": "yellow",
    "conflict": "red",
    "collision": "red",
}
# design.md *The TUI*, *The Plugins tab*.
PLUGIN_STYLE = {
    "installed": "green",
    "stale": "yellow",
    "disabled": "yellow",
    "missing": "yellow",
    "unavailable": "red",
    "conflict": "red",
    "collision": "red",
}
NO_PLUGINS = (
    "No plugin is selected.\n\nA source's `plugins` in the manifest, or the plugins field "
    "of `a` on Sources, selects them."
)
_PROBLEM_KINDS = (
    "source", "conflict", "collision", "after-save", "commit", "push", "refused", "error",
)  # fmt: skip


def diff(patch: str) -> Text:
    """A unified diff, colored."""
    out = Text()
    for line in patch.splitlines():
        if line.startswith(("+++", "---")):
            style = "bold"
        elif line.startswith("+"):
            style = "green"
        elif line.startswith("-"):
            style = "red"
        elif line.startswith("@@"):
            style = "cyan"
        elif line.startswith("diff "):
            style = "bold"
        else:
            style = ""
        out.append(line + "\n", style=style)
    return out


# --- skills ---------------------------------------------------------------------


def skill_detail(k: SkillStatus) -> Text:
    out = Text()
    out.append(k.name, style="bold")
    out.append(f"  from {k.source}\n")
    if k.path is not None:
        out.append(f"{tilde(k.path)}\n")
    out.append("\n")
    for harness, state in k.harnesses.items():
        out.append(f"{harness}: ")
        out.append(f"{state}\n", style=LINK_STYLE.get(state, ""))
    if k.path is None:
        return out
    out.append("\n")
    if problem := skill_problem(k.path):
        out.append(problem + "\n", style="yellow")
        return out
    try:
        meta = frontmatter((k.path / "SKILL.md").read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError):
        meta = {}
    out.append(meta.get("description", ""))
    return out


# --- plugins --------------------------------------------------------------------


@dataclass(frozen=True)
class PluginAbout:
    """What a plugin's detail shows beyond its `status`: its description and
    the problems `sync` reports about it, read in the background."""

    description: str | None = None
    problems: list[str] = field(default_factory=list)


def plugin_abouts(plan: plugins.Plan) -> dict[tuple[str, str], PluginAbout]:
    """Each selected plugin's, by source and name. Its description is the
    first string `description` among its `plugin.json` files, else its
    catalog entry's (design.md *The Plugins tab*)."""
    out: dict[tuple[str, str], PluginAbout] = {}
    for state in plan.sources:
        for sel in state.selected:
            read = catalog.files(sel.directory) if sel.directory else lambda _: None
            description = catalog.description(sel.plugin.entry, read)
            out[sel.source.name, sel.name] = PluginAbout(description, plugins.problems(sel, plan))
    return out


def plugin_detail(p: PluginStatus, source: SourceStatus | None, about: PluginAbout) -> Text:
    """Where a plugin comes from (its source and the source's pin, or a
    `path` source's directory), tack's copy, its version, its state in each
    harness it targets, what `sync` reports about it, and its description."""
    out = Text()
    out.append(p.name, style="bold")
    out.append(f"  from {p.source}\n")
    if source is not None:
        pinned = f", {_pin(source)}" if source.kind == "git" else ""
        out.append(f"source: {_location(source)}{pinned}\n")
    if p.path is not None:
        out.append(f"copy: {tilde(p.path)}\n")
    out.append(f"version: {p.version or 'none'}\n\n")
    for harness, state in p.harnesses.items():
        out.append(f"{harness}: ")
        out.append(f"{state}\n", style=PLUGIN_STYLE[state])
    for problem in about.problems:
        out.append(f"\n{problem}\n", style="red")
    if about.description:
        out.append(f"\n{about.description}\n")
    return out


# --- sources --------------------------------------------------------------------


def source_state(s: SourceStatus, up: outdated.SourceReport | None, *, fetching: bool) -> Text:
    """A source's state, briefly, for its row."""
    if s.kind == "path":
        if s.state != "ok":
            return Text(s.state, style="red")
        edits = []
        if s.uncommitted:
            edits.append(f"{len(s.uncommitted)} uncommitted")
        if s.unpushed:
            edits.append(f"{len(s.unpushed)} unpushed")
        return Text(", ".join(edits), style="yellow") if edits else Text("clean", style="green")
    if up is not None:
        if up.state == "current":
            return Text("current", style="green")
        if up.state == "behind":
            return Text(f"{up.behind} behind", style="yellow")
        return Text(up.state, style="red")
    if s.state != "ok":
        return Text(s.state, style="red")
    return Text("fetching..." if fetching else "pinned", style="dim")


def _location(s: SourceStatus) -> str:
    return tilde(s.location) if s.kind == "path" else f"{s.location} ({s.ref or 'default branch'})"


def _pin(s: SourceStatus) -> str:
    if s.commit and s.locked:
        return f"pinned {s.commit[:12]} on {s.locked.date().isoformat()}"
    return "not pinned"


def source_detail(
    s: SourceStatus, up: outdated.SourceReport | None, *, selects_plugins: bool = False
) -> Text:
    """`selects_plugins`: whether the source's `plugins` isn't `[]`, which
    `outdated`'s text needs to say what didn't change."""
    out = Text()
    out.append(s.name, style="bold")
    out.append(f"  {_location(s)}\n")
    if s.commit and s.locked:
        out.append(f"{_pin(s)}\n")
    if s.state != "ok":
        out.append(text.source_note(s.state, s.name, s.root) + "\n", style="red")
    out.append(f"{plural(len(s.skills), 'skill')}: {', '.join(s.skills)}\n")
    if s.plugins:
        out.append(f"{plural(len(s.plugins), 'plugin')}: {', '.join(s.plugins)}\n")
    if s.uncommitted:
        out.append(f"uncommitted edits to {', '.join(s.uncommitted)}\n", style="yellow")
    if s.unpushed:
        out.append(f"unpushed commits touching {', '.join(s.unpushed)}\n", style="yellow")
    if up is None:
        return out
    out.append("\n")
    if up.state == "current":
        out.append("up to date with upstream\n", style="green")
        return out
    if up.state != "behind":
        out.append(f"{up.message}\n", style="red")
        return out
    span = f"{(up.pin or '')[:12]} -> {(up.tip or '')[:12]}"
    out.append(f"{plural(up.behind, 'commit')} behind ({span}); u updates\n", style="yellow")
    if up.rewritten:
        out.append("upstream rewrote its history: the tip no longer contains the pin\n", "red")
    for line in text.upstream_changes(up, selects_plugins):
        out.append(f"{line}\n")
    for c in up.commits:
        out.append(f"{c.commit[:12]} ", style="dim")
        out.append(f"{c.subject}\n")
    if up.diff:
        out.append("\n")
        out.append_text(diff(up.diff))
    return out


# --- doctor ---------------------------------------------------------------------


def finding_detail(f: Finding) -> Text:
    out = Text()
    out.append(f.severity, style=SEVERITY_STYLE[f.severity])
    out.append(f"  {f.id}\n", style="bold")
    out.append(f"{tilde(f.project) if f.project else 'global'}\n")
    if f.path is not None:
        out.append(f"{tilde(f.path)}\n")
    out.append(f"\n{f.message}\n")
    if f.fix:
        out.append(f"\nf applies the {f.fix} fix (tack scaffold {f.fix})\n", style="green")
    return out


# --- results --------------------------------------------------------------------


def result(r: Result, idle: str) -> Text:
    """A changing command's result, as the CLI prints it, colored."""
    out = Text()
    in_diff = False
    for line in text.result_text(r, idle).splitlines():
        if line.startswith(("--- ", "+++ ")):
            in_diff = True
        if in_diff and line[:1] in "+-@ " and line:
            out.append_text(diff(line))
            continue
        in_diff = False
        if line.startswith("note: "):
            out.append(line + "\n", style="cyan")
        elif line.split(":", 1)[0] in _PROBLEM_KINDS:
            out.append(line + "\n", style="red")
        else:
            out.append(line + "\n")
    return out


def diffs(r: Result) -> str:
    """Every diff in a result, for a pager."""
    return "".join(c.diff for c in r.changes if c.diff)

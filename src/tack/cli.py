"""tack command line.

    tack sync [--dry-run] [--adopt]                         deploy what the manifest says
    tack status                                             what is deployed where
    tack outdated [SOURCE...] [--diff]                      what upstream has changed
    tack update [SOURCE...] [--dry-run]                     move pins to upstream's tip
    tack add GIT_URL|PATH [--name N] [--skill S...] ...     add a source
    tack remove SOURCE [--dry-run]                          remove a source
    tack doctor [PATH...] [--global-only|--projects-only]   audit
    tack scaffold FIX PATH [--from HARNESS] [--dry-run]     apply a doctor fix to a project
    tack                                                    the TUI (in a terminal)

Every command takes --json (the result goes to stdout as JSON) and
--config DIR (the directory holding tack.toml). sync, update, add, remove and
scaffold also commit pending edits to the skills of path sources with `autocommit`;
--no-commit (or TACK_NO_COMMIT=1) skips that for one run.

Exit codes: 0 ok / nothing to report, 1 findings or a partial failure,
2 usage or configuration error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tack import (
    __version__,
    commit,
    config,
    doctor,
    edit,
    outdated,
    scaffold,
    status,
    sync,
    text,
    update,
)
from tack.config import Config, ConfigError, UsageError
from tack.doctor.findings import Finding
from tack.text import tilde

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print the result as JSON")
    common.add_argument(
        "--config",
        metavar="DIR",
        help="the directory holding tack.toml (default: $TACK_CONFIG, else ~/.config/tack)",
    )

    # For the commands that change things, and so auto-commit.
    changes = argparse.ArgumentParser(add_help=False)
    changes.add_argument(
        "--dry-run", action="store_true", help="say what would change; change nothing"
    )
    changes.add_argument(
        "--no-commit",
        action="store_true",
        help="don't auto-commit edits to your own skills this run (also: TACK_NO_COMMIT=1)",
    )

    parser = argparse.ArgumentParser(
        prog="tack",
        description="Keep agent skills deployed identically to every coding agent, "
        "and audit projects so Claude Code and Codex stay interchangeable.",
    )
    parser.add_argument("--version", action="version", version=f"tack {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser(
        "sync",
        parents=[common, changes],
        help="make every harness match the manifest and the lockfile",
        description="Fetch and check out git sources at their pins (pinning new ones), "
        "link the selected skills into each harness, and remove tack's links to skills "
        "no longer selected. Exits 1 on a conflict or a source it couldn't update.",
    )
    p.add_argument(
        "--adopt",
        action="store_true",
        help="take over conflicting entries (a real directory is moved aside, never deleted)",
    )
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser(
        "status",
        parents=[common],
        help="what is deployed where, and each source's state (read-only)",
    )
    p.set_defaults(func=cmd_status)

    p = sub.add_parser(
        "outdated",
        parents=[common],
        help="how far each git source's pin is behind upstream",
        description="Fetch each git source and compare its pin with the tip of its ref: "
        "the commits between them and the selected skills that changed. Moves nothing. "
        "Exits 1 when a source is behind or can't be compared.",
    )
    p.add_argument("sources", nargs="*", metavar="SOURCE", help="these sources (default: all)")
    p.add_argument("--diff", action="store_true", help="show the diff of the changed skills")
    p.set_defaults(func=cmd_outdated)

    p = sub.add_parser(
        "update",
        parents=[common, changes],
        help="move git sources' pins to the tip of their refs, then sync",
        description="Re-pin git sources to the current tip of their refs, write the "
        "lockfile, and sync. `tack outdated --diff` shows what that takes in.",
    )
    p.add_argument("sources", nargs="*", metavar="SOURCE", help="these sources (default: all)")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser(
        "add",
        parents=[common, changes],
        help="add a source to the manifest, then sync",
        description="Add a git repository (a URL) or a local directory as a source. A git "
        "source is pinned to the tip of its ref and fetched first; nothing is written unless "
        "it deploys cleanly.",
    )
    p.add_argument("spec", metavar="GIT_URL|PATH", help="a git URL, or a directory of your own")
    p.add_argument("--name", metavar="N", help="the source's name (default: from the URL or path)")
    p.add_argument(
        "--skill",
        dest="skills",
        metavar="S",
        nargs="+",
        action="extend",
        default=[],
        help="deploy only these skills (default: all of them)",
    )
    p.add_argument("--ref", metavar="R", help="the branch or tag to follow (default: the remote's)")
    p.add_argument("--subdir", metavar="D", help="where the skills are (default: skills)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser(
        "remove",
        parents=[common, changes],
        help="remove a source, its links and its checkout",
        description="Remove a source from the manifest and the lockfile, sync (removing its "
        "links), and delete tack's checkout of it unless that has local changes.",
    )
    p.add_argument("source", metavar="SOURCE")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser(
        "doctor",
        parents=[common],
        help="audit harnesses and projects (read-only)",
        description="Report skills, instructions and hooks that break the conventions. "
        "Exits 1 when there is an error or a warning.",
    )
    p.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="audit these projects (or search these directories) instead of the configured roots",
    )
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--global-only", action="store_true", help="skip the project checks")
    scope.add_argument("--projects-only", action="store_true", help="skip the global checks")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser(
        "scaffold",
        parents=[common, changes],
        help="apply a doctor fix to a project (never commits)",
        description="Write, move and remove files in a project so that doctor's findings "
        "with this fix go away. Tracked files move through git and what tack writes is "
        "staged; nothing is committed. Exits 1 when the fix can't be applied safely, "
        "having changed nothing.",
    )
    p.add_argument(
        "fix", choices=list(scaffold.FIXES), metavar="FIX", help=", ".join(scaffold.FIXES)
    )
    p.add_argument("path", metavar="PATH", help="the project")
    p.add_argument(
        "--from",
        dest="source",
        metavar="HARNESS",
        help="for hooks: whose version wins where both harnesses have a hook but differ",
    )
    p.set_defaults(func=cmd_scaffold)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from tack import tui

            return tui.run()
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        cfg = config.load(Path(args.config).expanduser() if args.config else None)
        return args.func(args, cfg)
    except (ConfigError, UsageError) as e:
        if args.json:
            kind = "config" if isinstance(e, ConfigError) else "usage"
            print(json.dumps({"error": kind, "message": str(e)}, indent=2))
        else:
            print(f"tack: {e}", file=sys.stderr)
        return EXIT_USAGE


def _plain(obj: Any) -> Any:
    """A result as JSON-ready data."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")
    return obj


def _print_json(data: Any) -> None:
    print(json.dumps(_plain(data), indent=2, ensure_ascii=False))


# --- sync ------------------------------------------------------------------------


def cmd_sync(args: argparse.Namespace, cfg: Config) -> int:
    result = sync.sync(cfg, dry_run=args.dry_run, adopt=args.adopt)
    return _report(args, _autocommit(args, cfg, result))


def cmd_update(args: argparse.Namespace, cfg: Config) -> int:
    result = update.update(cfg, args.sources, dry_run=args.dry_run)
    return _report(args, _autocommit(args, cfg, result), idle="already up to date")


def cmd_add(args: argparse.Namespace, cfg: Config) -> int:
    result = edit.add(
        cfg,
        args.spec,
        name=args.name,
        skills=args.skills,
        ref=args.ref,
        subdir=args.subdir,
        dry_run=args.dry_run,
    )
    return _report(args, _autocommit(args, cfg, result))


def cmd_remove(args: argparse.Namespace, cfg: Config) -> int:
    result = edit.remove(cfg, args.source, dry_run=args.dry_run)
    return _report(args, _autocommit(args, cfg, result))


def cmd_scaffold(args: argparse.Namespace, cfg: Config) -> int:
    project = Path(args.path).expanduser().absolute()
    result = scaffold.scaffold(cfg, args.fix, project, source=args.source, dry_run=args.dry_run)
    return _report(args, _autocommit(args, cfg, result), idle="nothing to fix")


def _autocommit(args: argparse.Namespace, cfg: Config, result: sync.Result) -> sync.Result:
    """`result`, followed by the auto-commit that ends every command changing
    things (with the manifest as it was when the command started)."""
    if args.no_commit or commit.disabled():
        return result
    return result.extend(commit.autocommit(cfg, dry_run=args.dry_run))


def _report(args: argparse.Namespace, result: sync.Result, idle: str = "already in sync") -> int:
    if args.json:
        _print_json(result)
    else:
        print(text.result_text(result, idle))
    return EXIT_FINDINGS if result.problems else EXIT_OK


# --- status ----------------------------------------------------------------------


def cmd_status(args: argparse.Namespace, cfg: Config) -> int:
    st = status.status(cfg)
    if args.json:
        _print_json(st)
    else:
        print(_status_text(st, cfg))
    return EXIT_OK


def _status_text(st: status.Status, cfg: Config) -> str:
    if not st.sources:
        where = tilde(cfg.manifest or cfg.paths.manifest)
        return f"no sources in {where}"
    width = max(len(s.name) for s in st.sources)
    selecting = {src.name for src in cfg.sources if src.plugins != ()}
    lines = ["sources"]
    for s in st.sources:
        if s.kind == "path":
            lines.append(f"  {s.name:<{width}}  {tilde(s.location)}")
        else:
            lines.append(f"  {s.name:<{width}}  {s.location} ({s.ref or 'default branch'})")
        notes = []
        if s.commit and s.locked:
            notes.append(f"pinned {s.commit[:12]} on {s.locked.date().isoformat()}")
        if s.state != "ok":
            notes.append(text.source_note(s.state, s.name, s.root))
        notes.append(text.plural(len(s.skills), "skill"))
        if s.name in selecting:
            notes.append(text.plural(len(s.plugins), "plugin"))
        if s.uncommitted:
            notes.append(f"uncommitted edits to {', '.join(s.uncommitted)}")
        if s.unpushed:
            notes.append(f"unpushed commits touching {', '.join(s.unpushed)}")
        lines.append(f"  {'':<{width}}  {'; '.join(notes)}")

    if st.skills:
        rows = [(k.name, k.source, k.harnesses) for k in st.skills]
        lines += ["", *_state_table("skill", rows, list(cfg.harnesses), "collision")]
    if st.plugins:
        rows = [(p.name, p.source, p.harnesses) for p in st.plugins]
        lines += ["", *_state_table("plugin", rows, config.PLUGIN_HARNESSES, "unavailable")]
    return "\n".join(lines)


def _state_table(
    what: str,
    rows: Sequence[tuple[str, str, Mapping[str, str]]],
    harnesses: Sequence[str],
    widest: str,
) -> list[str]:
    """A table of `what`, its source, and its state in each harness (`-`
    where it doesn't target one), each harness column at least as wide as
    `widest`."""
    name_w = max(len(what), *(len(name) for name, _, _ in rows))
    src_w = max(len("source"), *(len(src) for _, src, _ in rows))
    cols = [max(len(h), len(widest)) for h in harnesses]
    head = "  ".join(f"{h:<{w}}" for h, w in zip(harnesses, cols, strict=True))
    lines = [f"{what:<{name_w}}  {'source':<{src_w}}  {head}".rstrip()]
    for name, src, states in rows:
        cells = "  ".join(
            f"{states.get(h, '-'):<{w}}" for h, w in zip(harnesses, cols, strict=True)
        )
        lines.append(f"{name:<{name_w}}  {src:<{src_w}}  {cells}".rstrip())
    return lines


# --- outdated --------------------------------------------------------------------

_SHOWN_COMMITS = 10


def cmd_outdated(args: argparse.Namespace, cfg: Config) -> int:
    report = outdated.outdated(cfg, args.sources, diff=args.diff)
    if args.json:
        _print_json(report)
    else:
        print(_outdated_text(report, {s.name for s in cfg.sources if s.plugins != ()}))
    return EXIT_FINDINGS if report.failed else EXIT_OK


def _outdated_text(report: outdated.Report, with_plugins: set[str]) -> str:
    """`with_plugins` names the sources that select plugins."""
    if not report.sources:
        return "no git sources"
    width = max(len(s.name) for s in report.sources)
    pad = " " * (width + 2)
    lines: list[str] = []
    for s in report.sources:
        on = f"on {s.ref}" if s.ref else "on the default branch"
        if s.state == "current":
            lines.append(f"{s.name:<{width}}  up to date {on} ({(s.pin or '')[:12]})")
            continue
        if s.state != "behind":
            lines.append(f"{s.name:<{width}}  {s.message}")
            continue
        span = f"{(s.pin or '')[:12]} -> {(s.tip or '')[:12]}"
        lines.append(f"{s.name:<{width}}  {text.plural(s.behind, 'commit')} behind {on} ({span})")
        if s.rewritten:
            lines.append(f"{pad}upstream rewrote its history: the tip no longer contains the pin")
        by_change = {
            change: [k.name for k in s.skills if k.change == change]
            for change in ("modified", "added", "removed")
        }
        lines += [
            f"{pad}{change}: {', '.join(names)}" for change, names in by_change.items() if names
        ]
        for change in ("modified", "added", "removed"):
            if plugins := [_changed_plugin(p) for p in s.plugins if p.change == change]:
                lines.append(f"{pad}plugins {change}: {', '.join(plugins)}")
        if s.plugins_error:
            lines.append(f"{pad}{s.plugins_error}")
        if not s.skills and not s.plugins:
            compared = s.name in with_plugins and not s.plugins_error
            lines.append(f"{pad}no selected skill {'or plugin ' if compared else ''}changed")
        lines += [f"{pad}{c.commit[:12]} {c.subject}" for c in s.commits[:_SHOWN_COMMITS]]
        if len(s.commits) > _SHOWN_COMMITS:
            lines.append(f"{pad}... and {len(s.commits) - _SHOWN_COMMITS} more")
        if s.diff:
            lines += ["", s.diff.rstrip("\n"), ""]
    while lines and not lines[-1]:
        lines.pop()

    total = len(report.sources)
    behind = sum(s.state == "behind" for s in report.sources)
    unknown = sum(s.state not in ("current", "behind") for s in report.sources)
    if not behind and not unknown:
        summary = f"{text.plural(total, 'git source')}, all up to date"
    else:
        parts = [f"{behind} of {text.plural(total, 'git source')} behind"]
        if unknown:
            parts.append(f"{unknown} not compared")
        summary = ", ".join(parts)
        if behind:
            summary += "; `tack update` moves the pins"
    return "\n".join([*lines, "", summary])


def _changed_plugin(p: outdated.ChangedPlugin) -> str:
    """A changed plugin and its versions (design.md *Tracking plugins
    upstream*): both for a modified one, a single one when they are equal;
    the tip's for an added one, the pin's for a removed one."""
    was, now = p.version["from"], p.version["to"]
    if p.change == "modified" and (was or now):
        shown = was if was == now else f"{was or 'none'} -> {now or 'none'}"
    else:
        shown = now if p.change == "added" else was if p.change == "removed" else None
    return f"{p.name} ({shown})" if shown else p.name


# --- doctor ----------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace, cfg: Config) -> int:
    report = doctor.run(
        cfg,
        [Path(p).expanduser().absolute() for p in args.paths],
        global_checks=not args.projects_only,
        project_checks=not args.global_only,
    )
    if args.json:
        print(json.dumps(_doctor_json(report), indent=2, ensure_ascii=False))
    else:
        print(_doctor_text(report, cfg, show_global=not args.projects_only))
    return EXIT_FINDINGS if report.failed else EXIT_OK


def _doctor_json(report: doctor.Report) -> dict[str, Any]:
    def plain(f: Finding) -> dict[str, Any]:
        return {k: str(v) if isinstance(v, Path) else v for k, v in asdict(f).items()}

    return {
        "manifest": str(report.manifest) if report.manifest else None,
        "projects": [str(p) for p in report.projects],
        "clones": [str(p) for p in report.clones],
        "findings": [plain(f) for f in report.findings],
        "counts": report.counts,
    }


def _doctor_text(report: doctor.Report, cfg: Config, *, show_global: bool) -> str:
    lines: list[str] = []
    if report.manifest:
        lines.append(f"manifest: {tilde(report.manifest)}")
    else:
        lines.append(
            f"no manifest at {tilde(cfg.paths.manifest)}: built-in harnesses, no sources, "
            "no project roots"
        )

    groups: dict[Path | None, list[Finding]] = {}
    for f in report.findings:
        groups.setdefault(f.project, []).append(f)
    width = max((len(f.id) for f in report.findings), default=0)
    for project, findings in sorted(
        groups.items(), key=lambda g: (g[0] is not None, str(g[0] or ""))
    ):
        lines += ["", "global" if project is None else tilde(project)]
        for f in findings:
            where = ""
            if f.path:
                inside = project is not None and f.path.is_relative_to(project)
                where = str(f.path.relative_to(project)) if inside else tilde(f.path)
            fix = f"  (fix: {f.fix})" if f.fix else ""
            lines.append(f"  {f.severity:<5}  {f.id:<{width}}  {where}{fix}")
            lines.append(f"  {'':<5}  {'':<{width}}  {f.message}")

    counts = report.counts
    summary = ", ".join(
        f"{n} {label if n == 1 else plural}"
        for n, label, plural in (
            (counts["error"], "error", "errors"),
            (counts["warn"], "warning", "warnings"),
            (counts["info"], "info", "info"),
        )
        if n
    )
    scope = [f"{len(cfg.harnesses)} harnesses"] if show_global else []
    scope.append(f"{len(report.projects)} project{'' if len(report.projects) == 1 else 's'}")
    if report.clones:
        n = len(report.clones)
        scope[-1] += f" ({n} clone{'' if n == 1 else 's'} of others' projects skipped)"
    lines += ["", f"{summary or 'no findings'} -- checked {', '.join(scope)}"]
    return "\n".join(lines)

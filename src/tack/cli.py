"""tack command line.

    tack sync [--dry-run] [--adopt]                         deploy what the manifest says
    tack status                                             what is deployed where
    tack doctor [PATH...] [--global-only|--projects-only]   audit

Every command takes --json (the result goes to stdout as JSON) and
--config DIR (the directory holding tack.toml).

Exit codes: 0 ok / nothing to report, 1 findings or a partial failure,
2 usage or configuration error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tack import __version__, config, doctor, status, sync
from tack.config import Config, ConfigError
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

    parser = argparse.ArgumentParser(
        prog="tack",
        description="Keep agent skills deployed identically to every coding agent, "
        "and audit projects so Claude Code and Codex stay interchangeable.",
    )
    parser.add_argument("--version", action="version", version=f"tack {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser(
        "sync",
        parents=[common],
        help="make every harness match the manifest and the lockfile",
        description="Fetch and check out git sources at their pins (pinning new ones), "
        "link the selected skills into each harness, and remove tack's links to skills "
        "no longer selected. Exits 1 on a conflict or a source it couldn't update.",
    )
    p.add_argument("--dry-run", action="store_true", help="say what would change; change nothing")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        cfg = config.load(Path(args.config).expanduser() if args.config else None)
        return args.func(args, cfg)
    except ConfigError as e:
        if args.json:
            print(json.dumps({"error": "config", "message": str(e)}, indent=2))
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


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# --- sync ------------------------------------------------------------------------

_VERBS = {
    "pin": ("pin", "pinned"),
    "clone": ("clone", "cloned"),
    "checkout": ("check out", "checked out"),
    "write": ("write", "wrote"),
    "link": ("link", "linked"),
    "relink": ("relink", "relinked"),
    "unlink": ("remove", "removed"),
    "adopt": ("adopt", "adopted"),
}


def cmd_sync(args: argparse.Namespace, cfg: Config) -> int:
    result = sync.sync(cfg, dry_run=args.dry_run, adopt=args.adopt)
    if args.json:
        _print_json(result)
    else:
        print(_sync_text(result))
    return EXIT_FINDINGS if result.problems else EXIT_OK


def _sync_text(result: sync.Result) -> str:
    rows = [(c.harness or c.source or "", c) for c in result.changes]
    width = max((len(label) for label, _ in rows), default=0)
    lines = []
    for label, c in rows:
        present, past = _VERBS[c.action]
        verb = f"would {present}" if result.dry_run else past
        lines.append(f"{label:<{width}}  {verb} {c.detail}")
    for p in result.problems:
        label = " ".join(x for x in (p.source, p.harness) if x)
        lines.append(f"{p.kind}: {label + ': ' if label else ''}{p.message}")
    n = len(result.changes)
    if not n:
        summary = "already in sync"
    else:
        summary = f"would make {_plural(n, 'change')}" if result.dry_run else _plural(n, "change")
    if result.problems:
        summary += f", {_plural(len(result.problems), 'problem')}"
    return "\n".join([*lines, *([""] if lines else []), summary])


# --- status ----------------------------------------------------------------------

_SOURCE_STATES = {
    "missing": "its skills directory isn't there",
    "not pinned": "not pinned yet; `tack sync` pins it",
    "manifest changed": "the manifest's git or ref changed since it was pinned; "
    "`tack update {name}` re-pins it",
    "not checked out": "not checked out; `tack sync` fetches it",
    "local changes": "tack's checkout has local changes",
    "off its pin": "checked out away from its pin; `tack sync` fixes it",
}


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
            notes.append(_SOURCE_STATES[s.state].format(name=s.name))
        notes.append(_plural(len(s.skills), "skill"))
        if s.uncommitted:
            notes.append(f"uncommitted edits to {', '.join(s.uncommitted)}")
        if s.unpushed:
            notes.append(f"unpushed commits touching {', '.join(s.unpushed)}")
        lines.append(f"  {'':<{width}}  {'; '.join(notes)}")

    if st.skills:
        harnesses = list(cfg.harnesses)
        name_w = max(len("skill"), *(len(k.name) for k in st.skills))
        src_w = max(len("source"), *(len(k.source) for k in st.skills))
        cols = [max(len(h), len("collision")) for h in harnesses]
        head = "  ".join(f"{h:<{w}}" for h, w in zip(harnesses, cols, strict=True))
        lines += ["", f"{'skill':<{name_w}}  {'source':<{src_w}}  {head}".rstrip()]
        for k in st.skills:
            cells = "  ".join(
                f"{k.harnesses.get(h, '-'):<{w}}" for h, w in zip(harnesses, cols, strict=True)
            )
            lines.append(f"{k.name:<{name_w}}  {k.source:<{src_w}}  {cells}".rstrip())
    return "\n".join(lines)


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

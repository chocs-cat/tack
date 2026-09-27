"""tack command line.

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
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tack import __version__, config, doctor
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
    except ConfigError as e:
        if args.json:
            print(json.dumps({"error": "config", "message": str(e)}, indent=2))
        else:
            print(f"tack: {e}", file=sys.stderr)
        return EXIT_USAGE
    return args.func(args, cfg)


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

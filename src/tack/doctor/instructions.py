"""Instruction-file checks: whether every harness ends up reading the same
instructions, globally and in each project."""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator
from pathlib import Path

from tack import git
from tack.config import Config
from tack.doctor.findings import Finding, Severity
from tack.text import tilde

LOCAL_MD = "CLAUDE.local.md"  # Claude Code's personal, uncommitted instructions
MAX_DEPTH = 5  # Claude Code follows imports this many hops deep

_FENCE = re.compile(r"\s*(```|~~~)")
_CODE_SPAN = re.compile(r"(`+).*?\1")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_IMPORT = re.compile(r"(?:^|(?<=\s))@(\S+)")


def imports(file: Path) -> list[Path]:
    """The files `file` imports with `@path`, resolved but not necessarily existing.

    Claude Code's rules: a token at the start of a line or after whitespace,
    outside code blocks, code spans and HTML comments; `~` is the home
    directory and a relative path is relative to the importing file.
    """
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[Path] = []
    in_fence = False
    for line in _COMMENT.sub("", text).splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.extend(
            _resolve(m.group(1), file.parent) for m in _IMPORT.finditer(_CODE_SPAN.sub("", line))
        )
    return out


def _resolve(token: str, base: Path) -> Path:
    def path(t: str) -> Path:
        p = Path(t).expanduser()
        return p if p.is_absolute() else base / p

    # "see @AGENTS.md." -- punctuation after a path isn't part of it.
    p, trimmed = path(token), path(token.rstrip(".,;:!?)"))
    return trimmed if not p.exists() and trimmed.exists() else p


def reads(src: Path, dst: Path) -> bool:
    """Whether reading `src` also reads `dst`: they are the same file (one is a
    symlink to the other) or `src` imports `dst`, directly or transitively."""
    if not src.is_file() or not dst.is_file():
        return False
    target = dst.resolve()
    if src.resolve() == target:
        return True
    seen = {src.resolve()}
    frontier = [src]
    for _ in range(MAX_DEPTH):
        nxt: list[Path] = []
        for f in frontier:
            for imp in imports(f):
                r = imp.resolve()
                if r == target:
                    return True
                if r not in seen and r.is_file():
                    seen.add(r)
                    nxt.append(r)
        frontier = nxt
    return False


def _text(file: Path) -> str | None:
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def check_global(cfg: Config) -> Iterator[Finding]:
    for a, b in itertools.combinations(cfg.harnesses.values(), 2):
        fa, fb = a.instructions, b.instructions
        ta, tb = _text(fa), _text(fb)
        if not (ta or "").strip() and not (tb or "").strip():
            continue
        if ta is None or tb is None:
            have, lack = (a, b) if ta is not None else (b, a)
            yield Finding(
                "instructions-split",
                "warn",
                f"{tilde(lack.instructions)} doesn't exist, so {lack.name} gets none of the "
                f"instructions in {tilde(have.instructions)}",
                path=lack.instructions,
                harness=lack.name,
            )
            continue
        same = (
            fa.resolve() == fb.resolve()
            or (a.imports and reads(fa, fb))
            or (b.imports and reads(fb, fa))
            or ta.strip() == tb.strip()
        )
        if not same:
            yield Finding(
                "instructions-split",
                "warn",
                f"{tilde(fa)} ({a.name}) and {tilde(fb)} ({b.name}) differ and neither imports "
                "the other: two copies that will drift",
                path=fa,
            )


def check_project(cfg: Config, project: Path) -> Iterator[Finding]:
    claude, codex = cfg.harnesses["claude-code"], cfg.harnesses["codex"]
    claude_md = project / claude.project_instructions
    agents_md = project / codex.project_instructions
    local_md = project / LOCAL_MD
    c_name, a_name = claude.project_instructions, codex.project_instructions

    def found(
        fid: str, severity: Severity, message: str, path: Path, fix: str | None = None
    ) -> Finding:
        return Finding(fid, severity, message, path=path, project=project, fix=fix)

    if (_text(claude_md) or "").strip() and not agents_md.exists():
        yield found(
            "agents-md-missing",
            "error",
            f"{c_name} has instructions but there is no {a_name}: Codex gets none of them",
            claude_md,
            "agents-md",
        )
    if claude_md.exists() and agents_md.exists() and not reads(claude_md, agents_md):
        yield found(
            "claude-md-no-import",
            "warn",
            f"{c_name} doesn't import {a_name} (add `@{a_name}`): two copies that will drift",
            claude_md,
            "agents-md",
        )
    if claude_md.exists() and agents_md.exists():
        tracked = git.tracked(project, c_name, a_name)
        if len(tracked) == 1:
            untracked = a_name if c_name in tracked else c_name
            yield found(
                "instructions-untracked",
                "warn",
                f"{next(iter(tracked))} is committed but {untracked} isn't",
                project / untracked,
            )
    if (
        local_md.exists()
        and agents_md.exists()
        and not reads(local_md, agents_md)
        and not reads(claude_md, agents_md)
    ):
        yield found(
            "local-md-suppresses-agents",
            "error",
            f"{LOCAL_MD} exists and nothing imports {a_name}, so Claude Code reads the "
            f"personal file but not {a_name}",
            local_md,
            "agents-md",
        )

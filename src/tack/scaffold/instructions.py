"""The `agents-md` fix: `AGENTS.md` is a project's instructions, and `CLAUDE.md`
imports it.

With no `AGENTS.md`, `CLAUDE.md` moves there. With both, `CLAUDE.md` gains the
import and loses every paragraph `AGENTS.md` has word for word; the rest is
Claude Code's alone. A `CLAUDE.local.md` beside `AGENTS.md` with no `CLAUDE.md`
gets a `CLAUDE.md` that is just the import. Then a `@AGENTS.md` line in
`CLAUDE.local.md` is redundant, and goes.
"""

from __future__ import annotations

import os
import re

from tack.config import Config
from tack.doctor.instructions import LOCAL_MD, import_tokens, reads
from tack.scaffold.writer import Refusal, Writer

_FENCE = re.compile(r"\s*(```|~~~)")
# An agent named in prose, not in a path like `.claude/skills` or `CLAUDE.md`.
_AGENT = re.compile(r"(?<![\w./-])(Claude|Codex)(?![\w-])")


def fix(cfg: Config, w: Writer, source: str | None) -> None:
    claude = cfg.harnesses["claude-code"].project_instructions
    agents = cfg.harnesses["codex"].project_instructions
    claude_md, agents_md = w.project / claude, w.project / agents
    token = os.path.relpath(agents_md, claude_md.parent)
    line = f"@{token}\n"

    if not agents_md.exists():
        text = _read(w, claude)
        w.move(claude, agents)
        w.write(claude, line)
        for n, text_line in enumerate(text.splitlines(), 1):
            if _AGENT.search(text_line):
                w.note(f"{agents}:{n} names one agent: {text_line.strip()}")
        for n, imported in import_tokens(text):
            w.note(f"{agents}:{n} imports {imported}, which Codex doesn't follow")
    elif not claude_md.exists():
        w.write(claude, line)
    elif not reads(claude_md, agents_md):
        shared = {_key(p) for _, p in paragraphs(_read(w, agents))}
        kept = [p for _, p in paragraphs(_read(w, claude)) if _key(p) not in shared]
        w.write(claude, line + "".join("\n" + p for p in kept))
        n = 3  # the import, then a blank line
        for p in kept:
            end = n + p.count("\n") - 1
            where = f"{n}" if end == n else f"{n}-{end}"
            w.note(f"{claude}:{where} is for Claude Code only; move what Codex needs to {agents}")
            n = end + 2

    local = w.project / LOCAL_MD
    text = w.read(LOCAL_MD)
    if text is None:
        return
    redundant = os.path.relpath(agents_md, local.parent)
    imports = {n for n, t in import_tokens(text) if t in (redundant, f"./{redundant}")}
    lines = text.splitlines(keepends=True)
    drop = {n for n in imports if lines[n - 1].strip().lstrip("@") in (redundant, f"./{redundant}")}
    if drop:
        w.write(LOCAL_MD, "".join(li for n, li in enumerate(lines, 1) if n not in drop))


def paragraphs(text: str) -> list[tuple[int, str]]:
    """The blank-line-separated blocks of `text`, each with its first line's
    number and ending in a newline; a fenced code block is never split."""
    out: list[tuple[int, str]] = []
    block: list[str] = []
    start = 0
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if not in_fence and not line.strip():
            if block:
                out.append((start, "\n".join(block) + "\n"))
                block = []
            continue
        if not block:
            start = n
        block.append(line.rstrip())
        if _FENCE.match(line):
            in_fence = not in_fence
    if block:
        out.append((start, "\n".join(block) + "\n"))
    return out


def _key(paragraph: str) -> str:
    return paragraph.strip()


def _read(w: Writer, rel: str) -> str:
    text = w.read(rel)
    if text is None:
        raise Refusal(f"can't read {rel} as UTF-8 text")
    return text

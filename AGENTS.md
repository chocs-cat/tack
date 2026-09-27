# Working on tack

Instructions for coding agents. Claude Code reads this through `CLAUDE.md`'s
`@AGENTS.md` import.

tack is built in phases. [docs/design.md](docs/design.md) is the spec and
the source of truth: read it before any change, and change it first when a
decision changes. Don't write implementation code for a phase until the
maintainer has approved the design and started that phase — the phases are
listed at the end of the design.

Checks, all of which must pass: `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run ty check`. Tests build everything in a
temporary directory with a scratch `HOME` (see `tests/conftest.py`); never
let one touch the real home directory.

tack is meant to be publishable: nothing in it may assume the maintainer's
setup (a dotfiles tool, a home-directory path, a particular agent beyond the
built-in harness defaults).

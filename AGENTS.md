# Working on tack

Instructions for coding agents. Claude Code reads this through `CLAUDE.md`'s
`@AGENTS.md` import.

tack is in its design phase. [docs/design.md](docs/design.md) is the spec and
the source of truth: read it before any change, and change it first when a
decision changes. Don't write implementation code for a phase until the
maintainer has approved the design and started that phase — the phases are
listed at the end of the design.

tack is meant to be publishable: nothing in it may assume the maintainer's
setup (a dotfiles tool, a home-directory path, a particular agent beyond the
built-in harness defaults).

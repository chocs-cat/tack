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

## Releases

Releases are automated with release-please, from Conventional Commits;
[CONTRIBUTING.md](CONTRIBUTING.md) has the process and the one-time setup.

- **Conventional Commits** for commit messages and pull request titles (CI
  checks titles): `feat:`, `fix:`, `perf:`, `docs:`, `refactor:`, `test:`,
  `ci:`, `build:`, `chore:`, with a scope where useful (`fix(tui): …`). The
  type decides the version bump and the changelog entry, so choose it for the
  user-visible effect: `feat` → minor, `fix` and `perf` → patch, `feat!` or a
  `BREAKING CHANGE:` footer → major (minor while below 1.0). The other types
  release nothing on their own.
- Don't edit versions or `CHANGELOG.md`; release-please owns them. It keeps a
  release pull request open, and merging it tags `vX.Y.Z`, creates the GitHub
  release, publishes to PyPI and updates the Homebrew tap. That merge is the
  maintainer's call.
- To force a version, add a `Release-As: X.Y.Z` footer to a commit. Never move
  or delete a pushed release tag. A bad release is fixed forward.

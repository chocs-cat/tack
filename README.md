<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/chocs-cat/tack/master/docs/logo-dark.svg">
  <img alt="tack" src="https://raw.githubusercontent.com/chocs-cat/tack/master/docs/logo-light.svg" height="64">
</picture>

Keep your coding agents' skills deployed identically to Claude Code and Codex
from one manifest of sources — your own skill repos and pinned third-party
ones — and audit your projects so either agent sees the same instructions,
skills, and hooks.

`tack sync` deploys skills from the manifest's sources, `tack status` shows
what is where, `tack outdated` and `tack update` track upstream, `tack add`
and `tack remove` edit the manifest, `tack doctor` audits, and
`tack scaffold` applies the fixes it suggests. A `path` source with
`autocommit = true` (and `autopush`) has its skill edits committed, and
pushed, whenever a command that changes things runs. A bare `tack` opens a
TUI over all of it: Skills (grouped by source, and sortable), Sources and
Doctor tabs, and a Settings screen for the manifest, with every action
previewed before it runs. [The design](docs/design.md) has the details.

## Install

```sh
brew install chocs-cat/tap/tack
# or
uv tool install tack-agents     # or: pipx install tack-agents
```

macOS and Linux, Python 3.11 or later, and git.

## Use

```sh
tack                      # the TUI
tack add https://github.com/cloudflare/skills.git --skill wrangler
tack sync --dry-run       # what would change
tack sync                 # fetch pinned sources, link skills into every harness
tack status               # sources, pins, and which skills are linked where
tack outdated --diff      # what upstream changed in the skills you deploy
tack update cloudflare    # take it: move the pin, then sync
tack remove cloudflare    # its table, pin, links and checkout
tack doctor               # audit the harnesses and the projects under projects.roots
tack doctor --json        # for scripts; exit 1 when there is an error or warning
tack scaffold hooks ~/Code/app --dry-run   # the diff a doctor fix would make
```

## Agent skill

[`skills/tack/SKILL.md`](skills/tack/SKILL.md) teaches coding agents to run
tack for you through its `--json` CLI. Deploy it with tack itself:

```sh
tack add https://github.com/chocs-cat/tack.git   # a source named tack, linked into every harness
tack update tack                                  # later: take in a newer version
```

Or copy `skills/tack` into your agents' skills directories.

## Development

```sh
uv sync
uv run tack …             # the checkout, not an installed copy
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the commit convention and how releases
are cut.

## License

MIT; see [LICENSE](LICENSE).

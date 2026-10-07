<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/chocs-cat/tack/master/docs/logo-dark.svg">
  <img alt="tack" src="https://raw.githubusercontent.com/chocs-cat/tack/master/docs/logo-light.svg" height="64">
</picture>

Keep your coding agents' skills and plugins deployed identically to Claude
Code and Codex from one manifest of sources — your own skill repos and
pinned third-party ones — and audit your projects so either agent sees the same instructions,
skills, and hooks.

`tack sync` deploys skills and selected plugins from the manifest's sources,
`tack status` shows which skills are where, `tack outdated` and `tack update`
track upstream, `tack add` and `tack remove` edit the manifest, `tack doctor`
audits, and `tack scaffold` applies the fixes it suggests. A `path` source with
`autocommit = true` (and `autopush`) has its skill edits committed, and
pushed, whenever a command that changes things runs. A bare `tack` opens a
TUI over all of it: Skills (grouped by source, and sortable), Sources and
Doctor tabs, and a Settings screen for the manifest, with every action
previewed before it runs.

## Install

tack runs on macOS and Linux and needs git. Install it one of two ways;
either gives you the `tack` command.

### Homebrew

```sh
brew install chocs-cat/tap/tack
```

The formula lives in the `chocs-cat/tap` tap and brings its own Python.

### PyPI

```sh
uv tool install tack-agents
```

This installs the `tack-agents` package from PyPI (`tack` is taken there)
into its own environment. It needs Python 3.11 or later;
`pipx install tack-agents` works the same way.

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

## Manifest and plugins

Sources live in `~/.config/tack/tack.toml` (or `$TACK_CONFIG/tack.toml`).
Each `[[source]]` selects skills and, optionally, plugins:

| Source field | Default | Meaning |
|---|---|---|
| `name` | required | A unique source name. |
| `path` / `git` | required | Exactly one: a local directory or a git clone URL. |
| `ref` | remote's default branch | The branch or tag a git source follows. |
| `subdir` | `skills` | The skills directory, relative to the source root. |
| `skills` | `"*"` | All skills, or a list of names and `{ name = "a", harnesses = ["codex"] }` tables. `[]` selects none and needs no skills directory, only the source root. |
| `plugins` | `[]` | Plugins from the source's catalog: `"*"`, or a list shaped like `skills`. Only `claude-code` and `codex` take plugins. |
| `harnesses` | every harness | Limit the whole source; a plugin may further limit its harnesses. |
| `autocommit` / `autopush` | `false` | Commit a path source's skill edits when tack changes things, and optionally push them. |

For a source that supplies only plugins:

```toml
[[source]]
name = "claude-plugins-official"
git = "https://github.com/anthropics/claude-plugins-official.git"
skills = []
plugins = ["skill-creator"]
```

The source's catalog is `.claude-plugin/marketplace.json`, or
`.agents/plugins/marketplace.json` if the first is absent. This release
deploys plugins whose files are inside the source; catalog entries pointing
at other repositories are reported as source problems.

`sync` copies selected plugins into a local marketplace named `tack`, then
registers it and installs `<name>@tack` through `claude plugin` and `codex
plugin`. `claude` or `codex` is needed on `PATH` only when a selected plugin
targets that agent; a missing CLI or a failed command is an `agent` problem
(exit `1`), and skills and the other agent's plugins still deploy. Changed
files are copied again, with Codex reinstalled; Claude Code loads tack's
copy in place. Deselected plugins are uninstalled, including through
`tack remove`.

`tack sync --dry-run` lists the commands as `would run` and writes nothing;
`--json` includes the command lines and harnesses in its changes. tack never
enables or disables plugins, and a source sync can't reach keeps its
existing plugins. A sync with no plugin selections, marketplace directory,
or recorded installs runs no agent CLI. Plugin selections are edited by
hand; `status`, `doctor`, and the TUI don't show plugins yet.

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

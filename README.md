<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/chocs-cat/tack/master/docs/logo-dark.svg">
  <img alt="tack" src="https://raw.githubusercontent.com/chocs-cat/tack/master/docs/logo-light.svg" height="64">
</picture>

Keep your coding agents' skills and plugins deployed identically to Claude
Code and Codex from one manifest of sources — your own skill repos and
pinned third-party ones — and audit your projects so either agent sees the same instructions,
skills, and hooks.

`tack sync` deploys skills and selected plugins from the manifest's sources,
`tack status` shows which skills and plugins are where, `tack outdated` and
`tack update` track upstream, `tack add` and `tack remove` edit the manifest,
`tack doctor` audits, and `tack scaffold` applies the fixes it suggests. A
`path` source with `autocommit = true` (and `autopush`) has its skill edits
committed, and pushed, whenever a command that changes things runs. A bare
`tack` opens a TUI over all of it: Skills, Plugins (each grouped by source,
and sortable), Sources and Doctor tabs, keyed `1` to `4`, and a Settings
screen for the manifest, with every action previewed before it runs.

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
tack add https://github.com/anthropics/claude-plugins-official.git --plugin skill-creator
tack sync --dry-run       # what would change
tack sync                 # fetch pinned sources, link skills into every harness
tack status               # sources, pins, and where skills and plugins are deployed
tack outdated --diff      # what upstream changed in the skills and plugins you deploy
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

For a source that supplies only plugins, which `tack add … --plugin
skill-creator` writes:

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

`tack add SOURCE --plugin P…` selects plugins from the source's catalog,
each name once in the order given; without `--skill` it writes `skills = []`,
so the source deploys only those plugins and needs no skills directory.
`add` refuses (exit `2`, nothing written) a `--plugin` the catalog doesn't
have (or a source with no catalog, or a broken one, with its error), one
`sync` couldn't deploy (from another repository, a source tack can't pin, or
files that can't be read), giving the reason `sync` would, and one another
source already selects. Without `--plugin`, refusing a source with no skills
lists the plugins `--plugin` would accept. A dry run of a git source doesn't
clone it, so it checks neither its skills nor its plugins. `plugins = "*"`
is written by hand.

`tack sync --dry-run` lists the commands as `would run` and writes nothing;
`--json` includes the command lines and harnesses in its changes. tack never
enables or disables plugins, and a source sync can't reach keeps its
existing plugins. A sync with no plugin selections, marketplace directory,
or recorded installs runs no agent CLI. Beyond `add`, plugin selections are
edited by hand. The TUI's Plugins tab shows each selected plugin's state in
each agent, grouped and sorted as Skills is but on its own; a plugin's detail
gives its source and pin, tack's copy, its version and description, and any
problem `sync` reports about it.

`tack status` shows each selected plugin's state in each agent it targets,
read through `claude plugin list` and `codex plugin list` (and their
`marketplace list`), which it runs only for an agent a selected plugin
targets; it changes nothing. A plugin is in the first of these that applies:

- `collision`: two sources select the name; tack deploys neither.
- `unavailable`: the agent's CLI isn't on `PATH`, or listing its plugins fails.
- `conflict`: the agent has a marketplace named `tack` that isn't tack's.
- `missing`: not installed.
- `disabled`: installed, but turned off in the agent; tack leaves it off.
- `stale`: tack's copy, or Codex's, predates the plugin's files; `sync` refreshes it.
- `installed`: installed from tack's marketplace, enabled, and current.

Plugins are read from their source as it is now: for a source whose own
state isn't `ok`, `sync` first holds it or checks out its pin.

`tack status --json` adds `plugins`, one object per selected plugin with
`name`, `source`, `harnesses` (agent → state), `version` and `path` (its
copy in tack's marketplace, or null), and gives each source `plugins`, the
names it selects.

`tack outdated` compares a git source's selected plugins between its pin and
the tip, from its catalog at each end: each one *modified* (its catalog
entry changed, or a file under its directory), *added* or *removed*, with
its version at each end (`plugins modified: a (1.0 -> 1.1)`); the commits
it lists include those touching selected plugins; and `--diff` adds each
changed plugin's diff after the skills', its files and then its catalog
entry. A catalog broken at either end leaves the plugins uncompared and says
why. `--json` gives each source `plugins` (`name`, `change`, and `version`
as `{"from", "to"}`) and `plugins_error` (null unless the catalog is
broken), and each commit `plugins`. A source that selects no plugins is
reported as before. `tack update` then takes the change: tack's copy is
refreshed and the plugin reinstalled in Codex.

`tack doctor` audits plugins too. It lists every installed agent's plugins
(the same two `list` commands, for each agent whose CLI is on `PATH`),
whether or not the manifest selects any; `--projects-only` runs neither.
A finding about an agent's plugins names the agent:

- `not-synced` (warn): a selected plugin that is `missing`, `disabled` or
  `stale` in an agent, or that an agent can't take (`unavailable`,
  `conflict`); a listed plugin the source's catalog lacks, one tack can't
  deploy, a broken catalog, or a plugin whose files can't be read, so that
  `sync` can't copy it (at its directory, with the reason `sync` gives); one
  of tack's plugins that `sync` would uninstall.
- `name-collision` (error): two sources select the same plugin name.
- `duplicate-plugin` (warn): a plugin tack deploys to an agent is also
  installed there from another marketplace, so the agent loads both.
- `unmanaged-plugin` (info): a plugin installed from another marketplace, by
  hand or by another manager; selecting it from its source keeps it the same
  across agents and machines.

An agent's problem is a finding wherever `sync` reports it: a CLI that isn't
on `PATH` when a selected plugin targets that agent, a failing `list`
whenever `sync` would run that agent at all (a selected plugin targets it,
tack has recorded installs there, or tack's marketplace exists), and a
foreign `tack` marketplace when a selected plugin targets the agent or tack
has recorded installs there. Its finding names the plugins it stops that
have no finding of their own, or says only what is wrong with the agent.

Built-in harnesses need no table; `[harness.claude-code]` or
`[harness.codex]` appears only to change a setting. Their
`ignore_marketplaces` lists marketplaces whose plugins belong to the agent or
to another program, which `doctor` doesn't report as unmanaged; it adds to
the built-in list (Claude Code's `builtin`, `inline`, `skills-dir` and
`synced`; Codex's `openai-bundled`, `openai-curated-remote` and
`openai-primary-runtime`). Only these two harnesses take it:

```toml
[harness.claude-code]
ignore_marketplaces = ["company-tools"]
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

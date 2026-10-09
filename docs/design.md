# tack — design

Status: **approved** (2026-09-27); every phase is done, and tack 0.1.0 is
released on PyPI and Homebrew. Phase 9, refinements to the TUI, and phase
10, the agent skill, were approved on 2026-09-28. This document is the spec. Decisions below were settled with the maintainer in an
interview; where one is still open it says so, in
[Open questions](#open-questions). Work after phase 10 is shaped as
projects in [projects/](projects/index.md), whose design lands here; choices
this document left open are logged in [decisions.md](decisions.md) and cited
as `(DEC-n)`.

**Plugins** are designed here and being built by project
[P0001](projects/P0001-plugins.md). Text marked *(P0001)* belongs to that
project, and some of it isn't built yet (the project's chunk ledger says what
is); the mark comes off when the project completes.

## Contents

1. [What tack is](#what-tack-is)
2. [Principles](#principles)
3. [Concepts](#concepts)
4. [Files and locations](#files-and-locations)
5. [The manifest: `tack.toml`](#the-manifest-tacktoml)
6. [The lockfile: `tack.lock`](#the-lockfile-tacklock)
7. [Commands](#commands)
8. [Ownership and conflicts](#ownership-and-conflicts)
9. [Plugins](#plugins) *(P0001)*
10. [Auto-commit](#auto-commit)
11. [`doctor` checks](#doctor-checks)
12. [Scaffolding](#scaffolding)
13. [The TUI](#the-tui)
14. [The agent skill](#the-agent-skill)
15. [Releasing](#releasing)
16. [Harness facts tack relies on](#harness-facts-tack-relies-on)
17. [Implementation](#implementation)
18. [Phases](#phases)
19. [Migrating the maintainer's setup](#migrating-the-maintainers-setup)
20. [Open questions](#open-questions)

## What tack is

A CLI and a TUI that keep a person's **agent skills** deployed
identically to every coding agent they use, from one manifest of sources, and
audit their projects so **Claude Code and Codex stay interchangeable**:
the same instructions, the same skills, the same hooks, whichever agent you
start.

It does three jobs:

- **Deploy skills.** Each skill comes from a *source* — a local checkout you
  edit, or a git repository pinned to a commit — and is linked into each
  agent's skills directory. *(P0001)* Plugins come from the same sources and
  are installed into every agent that takes them; see [Plugins](#plugins).
- **Track upstream.** Pinned sources show what changed upstream, with a diff,
  and move only when you say so.
- **Audit.** `doctor` reports anything that breaks the conventions: unmanaged
  or duplicated skills, instruction files that will drift, skills or hooks only
  one agent can see.

### Non-goals

- **Not a dotfiles manager.** tack does not sync its own config between
  machines; whatever you use for dotfiles (or nothing) does.
- **Not an installer for other tools' integrations.** Skills, hooks, and
  instruction blocks written by another program's installer (an MCP server's
  `install` command, a terminal multiplexer's hook) stay that program's. tack
  lists them as ignored, never rewrites them.
- **Not a manager of global instructions.** How the user-level instruction
  files are kept (e.g. one agent-neutral `AGENTS.md` that the Claude file
  imports) is the user's; `doctor` only checks that the agents end up reading
  the same thing.
- **No MCP server management** in the first version (see
  [Open questions](#open-questions)), beyond the servers a deployed plugin
  carries *(P0001)*.
- **Not a plugin translator.** tack installs the same plugin directory in
  every agent it targets; each agent loads the parts it supports *(P0001)*.
- **No Windows support.** Deployment is symlinks.

## Principles

1. **Built for one setup, assumes none.** Developed against the maintainer's
   machine (macOS, Claude Code + Codex, dotfiles in chezmoi), but nothing in
   tack names chezmoi, hardcodes a path, or assumes a dotfiles tool. The two
   supported agents are built-in defaults, not special cases.
2. **Every source is the same kind of thing.** Your own public skills repo, a
   private one, a vendor's collection: each is one manifest entry, deployed the
   same way. Adding a private skills repo later is one more entry.
3. **Nothing changes under you.** Git sources are pinned in a lockfile; an
   upstream change arrives only through `tack update`, after you have seen it.
4. **tack only touches what it owns.** It never overwrites or deletes a path it
   did not create, and never edits a project repository on its own.
5. **One writer per file.** Where another program owns a file, tack stays out
   of it — the lesson from two-writer bugs where one tool silently reverts
   another's update.
6. **Scriptable first.** Every command takes `--json` and has stable exit
   codes; the TUI is a view over the same operations, never the only way to do
   something.

## Concepts

| Term | Meaning |
|---|---|
| **Harness** | A coding agent tack deploys to. Built in: `claude-code`, `codex`. Each has a user skills directory, a project skills directory, a user instructions file, and hook files. |
| **Source** | Where skills (and plugins, *P0001*) come from: a `path` (a local checkout, linked in place) or a `git` repository (cloned by tack, pinned to a commit). |
| **Skill** | A directory containing `SKILL.md`, found inside a source's skills directory (`skills/` by default). Its directory name is its name. |
| **Deployment** | A symlink `<harness skills dir>/<name> → <skill directory>`. |
| **Plugin** *(P0001)* | A bundle an agent installs as one unit (skills, commands, agents, hooks, MCP servers…), listed in a source's *catalog*: its marketplace file. Its name is its catalog entry's name. |
| **tack's marketplace** *(P0001)* | The local marketplace, named `tack`, that holds a copy of every selected plugin and is registered with each agent that takes plugins; a deployed plugin is installed from it as `<name>@tack`. |
| **Manifest** | `tack.toml`: the sources and which of their skills (and plugins) go to which harnesses. Hand-edited or changed by `tack add`/`remove`. |
| **Lockfile** | `tack.lock`: the commit each git source is pinned to. Written only by tack. |
| **Project** | A git repository under one of the configured project roots, audited by `doctor`. |

## Files and locations

tack follows the XDG base directory spec, with the usual fallbacks.

| What | Default | Override |
|---|---|---|
| Manifest | `$XDG_CONFIG_HOME/tack/tack.toml` (`~/.config/tack/tack.toml`) | `TACK_CONFIG` env or `--config` (a directory) |
| Lockfile | beside the manifest: `~/.config/tack/tack.lock` | follows the manifest |
| Git source checkouts | `$XDG_DATA_HOME/tack/sources/<source>/` (`~/.local/share/tack/…`) | `TACK_DATA` |
| tack's marketplace *(P0001)* | `$XDG_DATA_HOME/tack/marketplace/` | `TACK_DATA` |
| Plugins from other repositories *(P0001)* | `$XDG_DATA_HOME/tack/plugins/<source>/<plugin>/` | `TACK_DATA` |
| Ownership record | `$XDG_STATE_HOME/tack/state.json` (`~/.local/state/tack/…`) | `TACK_STATE` |

Checkouts live under *data*, not *cache*: deployed links point into them, so
deleting them breaks skills. The same goes for tack's marketplace: Claude Code
loads plugins from it in place.

The manifest and lockfile are the two files meant to travel between machines
(and to be kept in dotfiles). Checkouts and the ownership record are
per-machine and rebuilt by `tack sync`.

## The manifest: `tack.toml`

```toml
# Run after tack changes this file or tack.lock. {path} is the changed file.
# Optional; how the change gets back into your dotfiles is up to you.
after_save = "chezmoi re-add {path}"

[projects]
roots = ["~/Code"]
exclude = ["~/Code/Archive", "~/Code/cruzainet"]
owners = ["johnfoland", "cruzainet", "chocs-cat"]   # repos cloned from anyone else aren't audited

# Built-in harnesses need no table; one appears only to change a setting.
[harness.claude-code]
ignore = ["codebase-memory"]   # owned by its installer; `synced` is ignored by default

[harness.codex]
ignore = ["codebase-memory"]

[[source]]
name = "mine"
path = "~/Code/skills"
autocommit = true              # see Auto-commit
autopush = true

[[source]]
name = "cloudflare"
git = "https://github.com/cloudflare/skills.git"
ref = "main"
skills = [
  "agents-sdk", "cloudflare", "cloudflare-email-service", "cloudflare-one",
  "cloudflare-one-migrations", "durable-objects", "sandbox-stable",
  "turnstile-spin", "web-perf", "workers-best-practices", "wrangler",
]

[[source]]
name = "vercel"
git = "https://github.com/vercel-labs/skills.git"
skills = ["find-skills"]

[[source]]
name = "corral"
git = "https://github.com/chocs-cat/corral.git"
ref = "master"
skills = ["corral"]

[[source]]
name = "claude-plugins-official"
git = "https://github.com/anthropics/claude-plugins-official.git"
skills = []
plugins = ["skill-creator"]
```

### Projects fields

| Field | Default | Meaning |
|---|---|---|
| `roots` | none | Directories searched for projects (see [`doctor` checks](#doctor-checks)). |
| `exclude` | none | Paths not searched. |
| `owners` | none (every repo is yours) | Who your repositories belong to. A repository whose `origin` remote belongs to another owner is a *clone* of someone else's project, and `doctor` skips it. |

Paths expand `~`, and a relative path is relative to the manifest's directory.

### Source fields

| Field | Applies to | Default | Meaning |
|---|---|---|---|
| `name` | all | required | Identifier used in the lockfile, the checkout path, and commands. Unique. |
| `path` | path | — | A local directory, linked in place. Exactly one of `path`/`git`. `~` expands; a relative path is relative to the manifest's directory. |
| `git` | git | — | A clone URL. |
| `ref` | git | the remote's default branch | The branch or tag `update` follows. |
| `subdir` | all | `skills` | Where the skill directories are, relative to the source root. |
| `skills` | all | `"*"` | Which skills to deploy: `"*"`, or a list. A list entry is a name, or `{ name = "…", harnesses = ["claude-code"] }` to limit that skill. A source with `skills = []` needs no skills directory *(P0001)*: it is missing (a `status` state, a `doctor` finding, a source `sync` holds) only when its root isn't there. |
| `plugins` *(P0001)* | all | `[]` (none) | Which plugins in the source's catalog to deploy: `"*"`, or a list shaped like `skills`. See [Plugins](#plugins) (DEC-3). |
| `harnesses` | all | every harness | Limit the whole source. |
| `autocommit` | path | `false` | Commit pending edits to this source's skills when tack runs. |
| `autopush` | path | `false` | Push auto-commits. Needs `autocommit`. |

### Harness fields

Built-in values shown; any can be overridden, and a new `[harness.<name>]`
table with all of them defines another agent.

| Field | `claude-code` | `codex` |
|---|---|---|
| `skills_dir` | `~/.claude/skills` | `~/.agents/skills` |
| `project_skills_dir` | `.claude/skills` | `.agents/skills` |
| `instructions` | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` |
| `project_instructions` | `CLAUDE.md` | `AGENTS.md` |
| `hooks` | `["~/.claude/settings.json"]` | `["~/.codex/hooks.json", "~/.codex/config.toml"]` |
| `project_hooks` | `[".claude/settings.json"]` | `[".codex/hooks.json", ".codex/config.toml"]` |
| `imports` | `true` | `false` |
| `ignore` | `["synced"]` + any dot-entry | any dot-entry |
| `ignore_marketplaces` *(P0001)* | `["builtin", "inline", "skills-dir", "synced"]` | `["openai-bundled", "openai-curated-remote", "openai-primary-runtime"]` |

`hooks` and `project_hooks` list every file the harness reads hooks from (a
single string is accepted); a `.json` file keeps them under a top-level
`hooks` key, a `.toml` file in `[[hooks.<Event>]]` tables. `imports` says
whether the harness follows `@path` imports in its instruction files.

`ignore` names entries in `skills_dir` that belong to someone else: tack never
touches them and `doctor` does not report them as unmanaged. For a built-in
harness it adds to the built-in list rather than replacing it.

*(P0001)* `ignore_marketplaces` names marketplaces whose plugins belong to the
agent itself or to someone else (the built-in ones are the agents' own:
claude.ai's synced plugins, Codex's bundled ones); `doctor` doesn't report
their plugins as unmanaged. It is a list of marketplace names, and adds to
the built-in list the same way. Only the built-in harnesses take plugins:
tack drives their own CLIs, and a harness defined in the manifest has none
it could drive (DEC-8), so `ignore_marketplaces` in its table is a
configuration error.

### TUI fields

`[tui]` holds the TUI's defaults; the CLI ignores it.

| Field | Default | Meaning |
|---|---|---|
| `group_by_source` | `true` | Whether the Skills tab (and the Plugins tab, *P0001*) opens grouped by source (see [The TUI](#the-tui)). |

### Writing the manifest

tack edits `tack.toml` only through `add`/`remove` and the TUI's Settings,
and as text, so comments and layout survive: it appends one `[[source]]`
table after the last, or cuts one out together with the comment lines
directly above its header, and leaves every other line alone. Settings
changes values the same way: it replaces a key's lines (from the key through
the end of its value), inserts a missing key after the last key of its
table, deletes a key it clears, and adds a missing table before the first
`[[source]]` table (or at the end). A key that is absent and set to its
default stays absent. The edit is kept only if the new text parses to the
old manifest with exactly those changes; otherwise tack writes nothing and
asks for the change to be made by hand (exit `2`). A manifest that sets
these keys another way (a dotted key, an inline table) is left alone the
same way. (A TOML round-trip library was the first plan, but tomlkit keeps a
table's leading comments in the table before it, so cutting a table moves its
neighbours' comments.) After writing either file it runs `after_save` once per file changed,
with `{path}` replaced by the absolute path (shell-quoted; the command runs
under `sh -c`), and reports a failure without undoing the write. A
`--dry-run` writes nothing and runs nothing.

## The lockfile: `tack.lock`

TOML, written only by tack, one table per git source:

```toml
# Generated by tack. Do not edit; use `tack update`.
version = 1

[source.cloudflare]
git = "https://github.com/cloudflare/skills.git"
ref = "main"
commit = "4f1c…"             # full SHA
locked = 2026-09-27T12:00:00Z
```

- A git source with no lock entry is pinned on first `sync` to the current tip
  of its `ref`, and the lock is written. An entry has no `ref` when the source
  follows the remote's default branch.
- If the manifest's `git` or `ref` for a source no longer matches its lock
  entry, `sync` refuses that source until `tack update <source>` re-pins it.
- `sync` never drops an entry, so a source commented out and later restored
  comes back at the same pin; `tack remove` drops it.
- `path` sources are not locked: they are whatever is checked out.
- *(P0001)* Plugins add no entries. A plugin inside a source is pinned with
  it, and one from another repository is pinned by the commit its catalog
  names at the source's pin (DEC-4).

A checkout is tack's, but `sync` still refuses to move one with local
changes (it reports them instead of discarding them). A checkout that has
gone missing is cloned again at its pin. A checkout `sync` clones and then
can't bring to its pin (the pin isn't in the repository, or the checkout
fails) is deleted again, so the next `sync` clones it afresh rather than
refusing a checkout that holds no files (DEC-22, #54).

## Commands

All commands take `--json` (machine-readable output, no prompts) and
`--config DIR`. Exit codes: `0` success / nothing to report, `1` findings or a
partial failure, `2` usage or configuration error.

| Command | What it does |
|---|---|
| `tack sync [--dry-run] [--adopt] [--no-commit]` | Make every harness match the manifest and lock: fetch/check out git sources at their pinned commits, create missing links, remove links to skills no longer selected. Reports conflicts instead of overwriting (see [Ownership](#ownership-and-conflicts)); `--adopt` takes them over. |
| `tack status` | What is deployed where, each source's pin or checkout state, and pending auto-commits (uncommitted and unpushed skill edits in `path` sources). Read-only; exits `0`. |
| `tack outdated [SOURCE…] [--diff]` | Fetch each git source's `ref` and show how far its pin is behind: commits, and which *selected* skills changed. `--diff` prints the diff limited to those skills. |
| `tack update [SOURCE…] [--dry-run] [--no-commit]` | Move pins to the current tip of `ref`, write the lock, then `sync`. |
| `tack add GIT_URL\|PATH [--name N] [--skill S…] [--plugin P…] [--ref R] [--subdir D] [--dry-run] [--no-commit]` | Add a source to the manifest (then `sync`). `--plugin` is *P0001*. |
| `tack remove SOURCE [--dry-run] [--no-commit]` | Remove a source from the manifest and its links (then `sync`). |
| `tack doctor [PATH…] [--global-only\|--projects-only]` | Audit; see [`doctor` checks](#doctor-checks). Read-only. |
| `tack scaffold FIX PATH [--from HARNESS] [--dry-run] [--no-commit]` | Apply one `doctor` fix to one project; see [Scaffolding](#scaffolding). |
| `tack` (no arguments, in a terminal) | Launch the TUI; see [The TUI](#the-tui). |

`sync`, `update`, `add`, `remove` and `scaffold` also commit pending edits to
your own skills; see [Auto-commit](#auto-commit).

*(P0001)* `sync` (and so `update`, `add` and `remove`) deploys plugins as
well as skills, `status` reports them, and `outdated` tracks them; see
[Plugins](#plugins).

`sync` is idempotent and safe to run from a login hook or a dotfiles
tool's post-apply step; bootstrapping a new machine is: install tack, put the
manifest and lock in place, `tack sync`.

### Tracking upstream

Only git sources are tracked; naming a `path` source, or a name the manifest
doesn't have, to `outdated` or `update` is a usage error. With no names, both
take every git source.

**`outdated`** fetches into tack's checkouts, which it never moves, and
compares each pin with the tip of its `ref`. It reports how many commits the
pin is behind, the commits that touch selected skills, and each selected skill
that changed, as *modified*, *added* or *removed* (for a source taking `"*"`,
every skill at the pin or the tip is selected, so a new upstream skill shows as
added). A renamed skill is its old name removed and its new one added, and a
file moved from one skill to another changes both: git's rename detection
plays no part, here or for plugins. Every changed file counts, whatever
characters its name holds. A tip whose history no longer contains the pin
(upstream rewrote it) is flagged. A source that isn't pinned, isn't checked out, or whose manifest
entry changed since it was pinned can't be compared; it is reported with the
command that fixes it. `--diff` adds `git diff` output limited to the changed
skills. Exits `1` when any source is behind or couldn't be compared.

**`update`** re-pins each source to the tip of its `ref`, including one whose
`git` or `ref` changed in the manifest, and leaves the entry alone (its
`locked` time too) when the tip is the pin. Then it syncs with the new pins,
writing the lock once. The new pin is the tip when `update` runs, so run
`outdated --diff` just before it to see what you are taking.

### Adding and removing sources

**`add`** reads its argument as a git URL when it has a scheme (`https://…`)
or is in git's `host:path` form (nothing before the colon contains a slash),
and as a local directory otherwise; a directory becomes a `path` source,
written as an absolute path or with `~`. The name defaults to the
repository's or directory's name without `.git`, except that a repository
named `skills` takes its owner's name (`cloudflare/skills` becomes
`cloudflare`). `--skill` limits the source to those skills (`"*"` otherwise);
`--subdir` sets where its skills are. *(P0001)* `--plugin` selects plugins
from the source's catalog (`plugins` stays `[]` otherwise); given without
`--skill`, it writes `skills = []`, so the source deploys only the plugins.
Both take names, each written once in the order given, `plugins` after
`skills`; a source taking every plugin (`plugins = "*"`) is written by
hand.

Before writing anything, `add` pins a git source to the tip of its ref and
clones it, then refuses (exit `2`, nothing written, a fresh clone removed) a
name already in the manifest, a source already in it (the same `path`, or the
same `git` and `ref`), a source with no skills in its `subdir`, a `--skill`
the source doesn't have, and a skill another source already deploys to the
same harness. *(P0001)* It refuses the same way a `--plugin` the catalog
doesn't have (a source with no catalog has none, and one with a broken
catalog none either: the refusal gives the catalog's error), one tack can't
deploy (see [Catalogs](#catalogs)) or whose files can't be read, so that its
copy would fail (each with the reason `sync` gives; a plugin from
[another repository](#plugins-from-other-repositories) is checked by its
entry alone), and a plugin another
source already selects (DEC-11). With `--plugin` and no
`--skill`, the source's skills aren't checked: it deploys none. Without
`--plugin`, the refusal of a source with no skills (no skills directory, or
none in it) lists the plugins `--plugin` would accept from its catalog,
sorted, if there are any. Otherwise it
appends the table and syncs. A git source it can't
reach is reported (exit `1`) with nothing written. A new source is always
pinned afresh, replacing any lock entry left under its name. A dry run doesn't
clone, so it checks neither a git source's skills nor its plugins, even when
tack's checkout of an earlier source by that name is still there (one
`remove` left for its local changes): only the new pin says what they are.

**`remove`** cuts the source's table, drops its lock entry, syncs (which
removes its links, and uninstalls its plugins *(P0001)*), and then deletes
tack's checkout of it and its plugin clones, unless the
checkout has local changes: those are reported and the checkout is left where
it is. A name only the lockfile has (a source commented out of the manifest)
loses its entry and its checkout the same way. A `path` source's directory is
never touched.

## Ownership and conflicts

A path in a harness skills directory is **tack's** if it is a symlink and
either the ownership record lists it, or its target is inside tack's data
directory or inside a configured source. Only tack's paths are ever replaced
or removed.

The ownership record, `state.json`, maps each link tack made (or found
already pointing where the manifest says) to its target. A listed link counts
as tack's only while it still points there, so repointing one by hand takes
it back. The record is what lets `sync` remove the links of a `path` source
that has been dropped from the manifest.

Anything else at a path tack wants — a real directory, a symlink elsewhere, a
link into another manager's library — is a **conflict**: `sync` skips that
skill, reports it, and exits `1`. `sync --adopt` replaces conflicting entries
after moving any real directory to
`$XDG_STATE_HOME/tack/adopted/<timestamp>/<harness>/<skill>` (never deleting
it); a foreign symlink is simply replaced.

Two sources offering the same skill name is a manifest error: tack deploys
neither, leaves whatever is at that name alone, and says which sources
collide. Deselect one.

A source `sync` can't bring up to date (a missing `path`, a failed fetch, a
refused checkout) is reported, and its skills' links are left as they are
rather than removed.

## Plugins

*(P0001)* A **plugin** is a bundle an agent installs as one unit: skills,
commands, agents, hooks, MCP servers and more. Claude Code and Codex both
install plugins from *marketplaces*, directories whose catalog lists them, and
each keeps what it installed in files it rewrites itself
(`~/.claude/settings.json`, `~/.codex/config.toml`). tack gives plugins the
treatment skills get: the manifest selects them from pinned sources, `sync`
installs them into every harness that takes plugins, `status` and the TUI
show them, `outdated` and `update` track upstream, and `doctor` audits them.

### Catalogs

A source offers plugins through a catalog at its root:
`.claude-plugin/marketplace.json` (Claude Code's format) or, failing that,
`.agents/plugins/marketplace.json` (Codex's). A source with neither offers no
plugins. Each entry of the catalog's `plugins` array is a plugin, named by its
`name`; its `source` says where the plugin's files are:

- **In the source**: a relative path (`"./plugins/foo"`, `"./"` or `"."` for
  the source root, a bare name under `metadata.pluginRoot`, or Codex's
  `{"source": "local", "path": "./plugins/foo"}`), resolved from the source
  root. A path that leaves the source can't be deployed.
- **In another git repository**: a `url`, `github` or `git-subdir` source
  (Claude Code's) or `git-subdir` (Codex's) with a full 40-character commit
  `sha`. tack clones the repository at that commit; see
  [Plugins from other repositories](#plugins-from-other-repositories).
- **Anything else** — a git source pinned only to a `ref`, `npm`, `archive`,
  `command` — can't be pinned by tack, so it can't be deployed.

The two formats differ only in where the file is and in Codex's `local`
source, so tack reads both the same way, following the agents' own rules:

- A path is `"."`, `"./"`, a path starting with `./`, or a *bare name* (one
  path component with no `/`) that resolves under `metadata.pluginRoot`,
  itself a relative path inside the source (`"./plugins"` or `"plugins"`). A
  bare name with no usable `pluginRoot`, any other string, and any path with
  a `..` component can't be deployed. A `local` source's `path` follows the
  same rules.
- `github` takes `repo` as `owner/repo`, meaning
  `https://github.com/<owner>/<repo>.git`; `url` takes a full git URL;
  `git-subdir` takes `url` as either, and `path`, the plugin's directory
  inside that repository (a leading `./` allowed, no `..`). Each is deployable
  only with `sha`, 40 lowercase hexadecimal digits; a `ref` beside it is
  ignored. A full git URL is what `add` reads as one (a scheme, like
  `https://` or `file://`, or git's `host:path` form); any other `url`, a
  local path included, can't be deployed. A `git-subdir` `path` of `.` or
  `./` is the whole repository, as if the entry were a `url` one (#29).
- A source object of another type, or missing a field its type needs, can't
  be deployed, and the reason names what is wrong.
- A catalog file that isn't a JSON object with a `plugins` array is broken:
  its source offers no plugins, and a source that selects plugins reports it.
  The `.agents/plugins/` catalog isn't read in place of a broken
  `.claude-plugin/` one. An entry that isn't an object, or whose `name` isn't
  a valid name (as for skills), is ignored; a name listed twice can't be
  deployed.

Whether a plugin's directory exists is found when tack copies it, not when it
reads the catalog, so the same reading serves a catalog taken from git at
any commit (`outdated`). A plugin's **version** is the first string `version`
in its `.claude-plugin/plugin.json`, `plugin.json` or `.codex-plugin/plugin.json`
(Codex reads a root `plugin.json`, and `.codex-plugin/` as a fallback), else
its entry's `version`, else none: both agents prefer `plugin.json` to the
entry.

A selected plugin that can't be deployed is reported: `sync` deploys the
source's other plugins and exits `1`, and `add` refuses it. Both agents
install plugins only from marketplaces, so a plugin published for either one
already has a catalog; a repository holding one plugin and no catalog is not a
plugin source.

### Selecting plugins

`plugins` in a `[[source]]` table selects plugins as `skills` selects skills:
`"*"`, or a list of names and `{ name = "…", harnesses = [...] }` tables. It
defaults to `[]`, none (DEC-3). A source can supply only plugins, with
`skills = []`, as the manifest example above does. A plugin goes to every
harness its source targets that takes plugins — the built-in `claude-code`
and `codex` (DEC-8) —
and a plugin's `harnesses` may name only those. A source that selects plugins
(`"*"` or a non-empty list) but targets neither of them is a configuration
error too (DEC-10). A listed plugin the catalog
doesn't have is reported like a listed skill the source doesn't have
(`not-synced`). Two sources selecting the same plugin name is a manifest
error, even for different harnesses, since tack's marketplace holds one
plugin per name (DEC-11): tack deploys neither in any harness, says which
sources collide, and leaves that name's copy and installs as they are
(`name-collision`).

A source's catalog is read only when the source selects plugins, so a
manifest without them reads none. A source *selects* each plugin its
selection names that its catalog has, deployable or not, and a selected
plugin counts toward a collision either way. A name its catalog lists twice
is one plugin, which can't be deployed. A source with no catalog file
selects nothing under `"*"`, and lacks every name it lists. A source whose
root isn't there (a missing `path`, a git source a dry run hasn't cloned)
and a source whose catalog is broken select nothing and lack nothing, as a
source without its skills directory reports no missing skills; the broken
catalog is reported.

Many skill repositories ship a catalog whose one plugin is the whole
repository (`"source": "./"`), holding the same skills the source offers.
Deploying that plugin and those skills gives the agent each skill twice, so a
source normally takes one or the other; `add --plugin` writes `skills = []`
for that reason.

### Deploying

tack keeps one marketplace of its own, named `tack`, in
`$XDG_DATA_HOME/tack/marketplace/` (DEC-1):

- `plugins/<name>/` holds a copy of each selected plugin, taken from the
  source's checkout at its pin, from a `path` source as it is, or from the
  plugin's clone at its commit
  ([another repository](#plugins-from-other-repositories)): everything
  but `.git` (at any depth), with each symlink copied as the file or
  directory it points to (DEC-2). A symlink that points nowhere, or to a
  directory that contains it (a loop), fails that plugin, as does a plugin
  directory that isn't there. A copy is refreshed only when its files differ
  from the plugin's (by the hash in [Plugin ownership](#plugin-ownership));
  it is built beside the old one and swapped in, so an agent starting a
  session meanwhile never reads half a copy. A plugin that fails keeps the
  copy it had, if any, and its installs: `sync` installs, reinstalls and
  uninstalls nothing for it (DEC-12).
- `.claude-plugin/marketplace.json` is tack's catalog: `name` `tack`,
  `owner` `{"name": "tack"}`, and an entry for each plugin with a copy, by
  name. Each entry is the plugin's upstream catalog entry with its `source`
  replaced by `"./plugins/<name>"` and `headers` and `headersHelper` dropped
  (they apply only to sources tack doesn't deploy). So the agents show the
  upstream description, author, homepage, version and category, and a plugin
  whose entry declares its components (it has no `plugin.json`) still loads.
  tack writes the file only when its content changes. Codex reads this
  catalog too, so there is no `.agents/plugins/` one.

Only tack writes this directory. `sync` brings it up to date whenever a
plugin is selected or the directory exists (so it never creates the directory
only to remove it, and a directory that stays never names a copy it deleted),
then makes each harness match it by running that agent's own CLI, never by
editing the agent's files (principle 5): `claude plugin …` and `codex plugin …`, found on
`PATH`, with `--json` and stdin closed, run in tack's data directory (or, if
that doesn't exist yet, an empty temporary one) so that no project's plugin
settings apply. A command fails when it exits non-zero or its output isn't
the JSON it should be; the agent's message is Claude Code's `message` from
its JSON, else the last line either agent wrote to stderr, without Codex's
`Error: ` prefix. It reads what each agent has from `plugin list` and
`plugin marketplace list` (their output is described in
[Harness facts](#harness-facts-tack-relies-on)), then, for each harness that
takes plugins:

1. **Register** the marketplace, if a selected plugin targets the harness
   and it has no conflicting `tack` (see [Plugin ownership](#plugin-ownership)):
   `claude plugin marketplace add <dir> --scope user`, `codex plugin
   marketplace add <dir>`. Registering it again is a no-op for both.
2. **Install** each selected plugin that isn't installed (the agent's `plugin
   list` doesn't show it from tack's marketplace; a disabled one is
   installed): `claude plugin install <name>@tack --scope user`, `codex
   plugin add <name>@tack`. When Codex was unregistered and the record lists
   plugins there, read its inventory again after registering: its first
   list hid those installs. A dry run can't register to reveal them, so it
   treats the recorded plugins as installed until a real run checks (DEC-14).
3. **Reinstall** in Codex each plugin whose files changed since tack
   installed it there (an `update`, an edit in a `path` source): Codex
   installs a copy of a plugin in its own cache and doesn't refresh it, so
   `sync` runs `codex plugin add` again. Claude Code loads a plugin from a
   local marketplace in place, so the change reaches it with nothing to run.
   Either agent picks up a change at its next session.
4. **Uninstall** each of tack's plugins in the harness (those the agent lists
   from tack's marketplace, and those the record lists) that is no longer
   selected for it: `claude plugin uninstall <name>@tack --scope user`,
   `codex plugin remove <name>@tack`. A copy no selected plugin needs is
   deleted once no harness has it installed.
5. **Unregister** the marketplace from a harness no selected plugin targets
   any more, after step 4 (removing a marketplace from Codex leaves its
   plugins installed): `claude plugin marketplace remove tack --scope user`,
   `codex plugin marketplace remove tack`. Removing it from Claude Code
   uninstalls its plugins, so there it stays registered while a plugin tack
   keeps as it is (DEC-12) is installed (DEC-13). With no plugins selected
   anywhere, the directory goes too, once every harness whose CLI is on
   `PATH` has it unregistered and the record lists no plugin.

The result lists these as changes `copy` (into tack's marketplace),
`register`, `install`, `reinstall`, `uninstall` and `unregister`, with the
harness each applies to. The detail of each of the last five is the command
line it runs, so a dry run lists the commands; a `copy` names the plugin and
the directory it is copied from. Writing tack's catalog is a `write` change,
and deleting a plugin's copy or tack's marketplace directory a `delete`.

`sync` deploys skills first, then plugins. It runs a harness's CLI only when
a selected plugin targets that harness, the record lists a plugin tack
installed there, or tack's marketplace directory exists, so a manifest
without plugins never needs either agent installed (DEC-3). A harness a
selected plugin targets whose CLI isn't on `PATH` gets no plugins: that is a
problem of kind `agent` (exit `1`), and its skills still deploy. Elsewhere a
missing CLI is passed over, and the record keeps that harness's entries. A
command that fails is reported the same way, with the agent's message, and
the other plugins carry on; a `list` command that fails stops that harness's
steps. A selected plugin tack can't deploy, a broken catalog, a plugin
whose copy fails, and one whose clone `sync` can't bring to its commit
([Plugins from other repositories](#plugins-from-other-repositories)) are
problems of kind `source`; a plugin name two sources
select is a `collision`. `--dry-run` runs only the `list` commands, lists
the commands it would run, and writes nothing. `--adopt` doesn't apply to
plugins.

A source `sync` holds (a missing `path`, a failed fetch, a refused checkout,
a `path` source that is missing as [Source fields](#source-fields) says; see
[Ownership and conflicts](#ownership-and-conflicts)), a source whose root
isn't there (a git source a dry run hasn't cloned), and a source whose
catalog is broken keep their plugins as they are: `sync` copies, installs,
reinstalls and uninstalls none of the plugins the record says came from
them or that they select, and keeps their copies and their entries in
tack's catalog (DEC-12). So, as with a held source's skills, a plugin such a
source selects that isn't installed yet waits until the source is reachable,
and a dry run lists no uninstall for a source it hasn't cloned. These are
*kept* plugins, as are a collided name's, a plugin whose copy fails, and a
plugin from another repository whose clone isn't `ok` once `sync` has
brought it to its commit (in a dry run, one whose clone isn't `ok`).

tack installs and uninstalls plugins but never enables or disables one
(DEC-5). Turning a tack plugin off in an agent (`/plugin`) is the user's
choice, which `status` shows as `disabled` and `doctor` reports; limiting the
plugin's `harnesses` says it in the manifest instead. Nor does tack set a
plugin's options (`claude plugin configure`) or resolve its dependencies: a
plugin that needs another needs that one selected too, and since tack copies
entries unchanged, a dependency named without a marketplace resolves within
tack's.

### Plugin ownership

In a harness, a plugin is **tack's** when it was installed from a marketplace
named `tack` whose directory is tack's marketplace. tack never installs,
uninstalls, enables or disables any other plugin, and never touches another
marketplace's registration. A marketplace named `tack` registered from
anywhere else is a **conflict**: `sync` runs none of the steps in
[Deploying](#deploying) in that harness, not even registering (Claude Code
would repoint the name at tack's directory; see
[Harness facts](#harness-facts-tack-relies-on)), and, where a selected plugin
targets the harness or the record lists one there, reports it and exits `1`;
removing or renaming that marketplace clears it.

The ownership record, `state.json`, also lists the plugins tack installed in
each harness, each with the source that last supplied it (when another
source takes over a name, the record follows it) and a hash of the files it
was installed from (tack's copy when tack installed it there, or in Codex
last reinstalled it), so `sync` knows when Codex's copy is stale (DEC-6) and
which plugins a held source keeps (DEC-12). Claude Code loads tack's copy in
place, so its hash stays the one recorded when tack installed the plugin or
first recorded an install it found; nothing compares it. It is a `plugins`
key beside `links`, harness → plugin name → `{"source": …, "hash": …}`, left out when
it lists no plugin, so a record without plugins is the one an older tack
writes. The record is also how tack knows
which Codex plugins it installed: Codex's `plugin list` leaves out a plugin
whose marketplace entry is gone, though it is still installed.

A plugin's **hash** is a SHA-256 over its directory's files, in order of
their paths relative to it: each file's path, whether it is executable, and
its contents. Symlinks count as what they point to, `.git` is left out, and
directories count only through their files. So a plugin's directory and
tack's copy of it hash the same, and comparing the two says whether the copy
is stale.

### Plugin states

`status`, the TUI and `doctor` give each selected plugin a state in each
harness it targets:

| State | Meaning |
|---|---|
| `installed` | Installed from tack's marketplace, enabled, and from the current files. |
| `missing` | Not installed. |
| `stale` | tack's copy, or Codex's, predates the plugin's files: `sync` fixes it. |
| `disabled` | Installed but turned off in the agent. |
| `conflict` | The harness has a foreign marketplace named `tack`. |
| `collision` | Two sources select the name, for this harness or another (DEC-11). |
| `unavailable` | The agent's CLI isn't on `PATH`, or its `plugin list` or `plugin marketplace list` fails (DEC-16). |

A plugin is in the first of these states that applies, in this order:
`collision`, `unavailable`, `conflict`, `missing`, `disabled`, `stale`,
`installed` (DEC-15). Each reads what `sync` reads:

- *Installed* is what step 2 of [Deploying](#deploying) means: the agent's
  `plugin list` shows the plugin from tack's marketplace (Claude Code's at
  user scope), enabled or not. `disabled` is such a plugin with `enabled`
  false.
- `stale` is what `sync` would copy or reinstall: tack's copy is
  missing or its hash (see [Plugin ownership](#plugin-ownership)) isn't the
  plugin's directory's, in any harness; and in Codex also when the record has
  no hash for the plugin there, or one that isn't the plugin's directory's.
  A plugin with no directory to compare (one tack can't deploy, one
  whose files can't be read, so that its copy would fail, or one from
  another repository whose clone isn't `ok`) is never `stale`.
- Each reads the plugin's files as its source has them now (DEC-17), so
  `stale` and `missing` are what `sync` would do for a source whose state is
  `ok`. For any other, `sync` first holds the source or checks out its pin,
  and its plugins can read `stale` or `missing` where `sync` then changes
  nothing; the source's state says what `sync` does first.
- `status` runs a harness's two `list` commands once, and only when a
  selected plugin targets that harness, so a manifest without plugins runs
  no agent (DEC-3). It writes nothing and still exits `0`.

`status --json` adds `plugins`, one object per selected plugin, sorted by
name and then source as skills are: `name`, `source`, `harnesses` (harness →
state, for the harnesses it targets), `version` (as [Catalogs](#catalogs)
says, read from the plugin's directory in its source, or in its clone
while the clone is `ok`, or null), `path`
(its copy in tack's marketplace, or null when there is none) and
`repository`: null for a plugin in its source or one tack can't deploy;
for one from [another repository](#plugins-from-other-repositories), an
object with `url` and `path` (the entry's URL as [Catalogs](#catalogs)
reads it, and a `git-subdir`'s path, null for the whole repository),
`commit` (the catalog's, all forty digits), `clone` (the clone's path) and
`state` (the clone's, as the plan read it: `in the way`, `not cloned`,
`local changes`, `off its commit` or `ok`). A name two
sources select is one object per source. Each source's object gains
`plugins`, the names it selects, beside `skills`.

### Plugins from other repositories

A plugin whose catalog entry names another git repository and a commit is
cloned into `$XDG_DATA_HOME/tack/plugins/<source>/<plugin>/` and checked out
at that commit; for `git-subdir`, the plugin is the entry's `path` inside it.
The commit comes from the catalog at the source's pin, so the source's pin
pins the plugin too and the lockfile needs no entry for it (DEC-4). When an
`update` brings a catalog naming a new commit, the next `sync` fetches it. A
clone with local changes is refused, as a checkout is, and a clone that has
gone missing is cloned again. `remove` deletes its source's clones.

A clone is the whole repository, cloned from the entry's URL
([Catalogs](#catalogs)), and tack keeps it as it keeps a git source's
checkout, with the same code (DEC-21):

- A clone's **state** is the first of these that applies: `in the way`
  (something at its path isn't a git checkout), `not cloned` (nothing is
  there), `local changes` (its tracked files differ from its `HEAD`;
  untracked files don't count, as for a checkout), `off its commit` (its
  `HEAD` isn't the entry's commit), and `ok`.
- `sync` brings a clone to its commit before it copies the plugin: the
  clone of each such plugin it would copy (selected, a name no other source
  selects, from a source it doesn't keep as it is), after the sources and
  before tack's marketplace, in name order. A plugin another source also
  selects, or that a held source or one whose catalog can't be read
  selects, leaves its clone as it is. One `not
  cloned` is cloned and checked out at the commit; one `off its commit` is
  checked out at it. Either first fetches the commit when the clone lacks
  it: the remote's branches and tags, then, if none reaches it, the commit
  by its id. The clone's `origin` follows the entry's URL, as a checkout's
  follows `git`, so a catalog that moves a plugin to another repository
  fetches from the new one. These are changes `clone` (detail: the URL) and
  `checkout` (the commit's first twelve digits), with the plugin's source
  and the clone's path. A clone `sync` makes and then can't bring to the
  commit is deleted again, as a checkout is (DEC-22).
- A clone `in the way` or with `local changes` is left untouched and fails
  its plugin, as a clone, a fetch or a checkout that fails does, and as a
  commit the repository doesn't have after the fetch by id. Each is a
  problem of kind `source`: `plugin '<name>': ` followed by what a source's
  checkout says in the same case (`... has local changes; discard or move
  them`, `... isn't in <url>`), with the plugin's source and the clone's
  path. The plugin is kept as one whose copy fails is (DEC-12).
- A dry run clones and fetches nothing: it lists the `clone` and `checkout`
  it would make, and keeps a plugin whose clone isn't `ok`, as it keeps the
  plugins of a source it hasn't cloned.
- `sync` deletes no clone: a plugin no longer selected keeps its clone, as
  a source commented out of the manifest keeps its checkout. After its
  sync, `remove` deletes each clone under `plugins/<source>/` as it deletes
  the source's checkout (a `delete` change, or, for one with local changes
  or that isn't a git checkout, a problem, the clone left where it is), then
  that directory once it is empty; a name only the lockfile has loses its
  clones the same way.
- A plugin's files are its clone's (at `path` for `git-subdir`) only while
  the clone is `ok`. Otherwise, in [Plugin states](#plugin-states), it has
  no directory to compare and is never `stale`, and the clone's state says
  what `sync` does first, as a source's state does for its plugins
  (DEC-17); its files aren't read for a problem either. A
  clone `in the way` or with `local changes` is a problem `sync` reports,
  so `doctor` reports it (DEC-19) and the TUI's detail gives it, for a
  plugin whose clone `sync` would bring (see above); `not cloned` and `off
  its commit` are what `sync` fixes, and no problem. Such a plugin's state
  is read as any other's (`missing`, `disabled` or `installed`, never
  `stale`), and, as in a dry run, it is kept: `doctor` reports no leftover
  for it in a harness it no longer targets.
- `add` checks a plugin from another repository by its entry alone, even
  when a clone by that name is already there (one `remove` left): the
  clone comes with the `sync` that follows, which reports a clone or copy
  that fails (exit `1`, the table written).

### Tracking plugins upstream

`outdated` compares a source's selected plugins between its pin and the tip
of its ref, as it does skills. It reads the source's catalog at each end from
git, as [Catalogs](#catalogs) reads one from disk (the same two files, in the
same order, a symlink followed as a checkout would follow it), and only for a
source that selects plugins. A catalog file that is a symlink leaving the
repository, or leading nowhere, is broken at that commit: git has nothing
outside the repository to read. A source whose
catalog is broken at either end has no plugin changes, and says why
(DEC-20). The selected plugins are, for `plugins = "*"`, every plugin in the
catalog at the pin or the tip, so a new upstream plugin shows as added; for a
list, the names it lists, a name in neither catalog being left out.

- A plugin in both catalogs is *modified* when its catalog entry changed
  (compared as JSON values), or, for a plugin in the source, when a file
  under its directory at the pin or at the tip changed. One from another
  repository, or one tack can't deploy, changes only with its entry (a new
  commit among them). A name the catalog lists twice has as its entry all
  of that name's entries, in order.
- *Added* and *removed* follow the catalog: a selected plugin in the tip's
  catalog and not the pin's, or the other way round.
- Each changed plugin shows its version at the pin and at the tip, as
  `status` takes it ([Catalogs](#catalogs)), its `plugin.json` files read
  from git at that commit under its directory there; null at the end that
  doesn't have it.
- The commits listed are those touching selected skills or selected plugins.
  A commit touches a plugin when it changes a file under the plugin's
  directory (at the pin or the tip), or changes a catalog file and the
  plugin's entry differs between the commit and its first parent (DEC-20).
  As for skills, a merge commit, whose own change git doesn't list, touches
  nothing.
- `--diff` adds, after the skills' diff, each changed plugin's in name
  order: the diff under its directory at the pin and at the tip, then, when
  its entry changed, a unified diff of the entry as JSON (indented two
  spaces, keys in the catalog's order), headed `a/<catalog file>#<name>` and
  `b/<catalog file>#<name>`, or `/dev/null` at the end without it. For a
  *modified* plugin from another repository at both ends, with the same URL
  and a different commit, the entry's diff is followed by the diff between
  its two commits (DEC-23). `outdated` fetches each commit its clone lacks,
  as `sync` would (the remote's branches and tags, then the commit by its
  id), and never checks out, moves or creates a clone; a clone with local
  changes or off its commit is fetched into all the same. The diff is the
  repository's between the pin's commit and the tip's, limited to the
  entry's `path` at each end (the whole repository when either end has
  none), its file names headed `a/<name>@<commit>/` and `b/<name>@<commit>/`
  (each commit's first twelve digits) so they don't read as the source's.
  When there is no such diff to give, a line of its own says why, in place
  of it: `plugin '<name>': no diff between its commits: ` then `it isn't
  cloned; `tack sync` clones it`, what `sync` says of a clone in the way, or
  the fetch's failure as `sync` gives it (`can't fetch <url>: …`, `pinned
  commit <commit> isn't in <url>`, the commit's first twelve digits). A
  plugin whose URL changed, or that is in the source at either end, has its
  entry's diff only.

`outdated --json` gives each source `plugins` beside `skills`: one object per
changed plugin, sorted by name, with `name`, `change` and `version`
(`{"from": …, "to": …}`, either null), and `plugins_error`, why its plugins
couldn't be compared, or null; and each commit `plugins` beside `skills`, the
selected plugins it touches, sorted. The text lists the changed plugins
after the skills, a line per kind of change as for skills
(`plugins modified: a (1.0 -> 1.1), b`), each with its versions in
parentheses when it has one at either end: for *modified* both (`none` for
the end without one, a single version when they are equal), the tip's for
*added*, the pin's for *removed*. `plugins_error` is a line of its own. A source that selects plugins and has neither changed says "no
selected skill or plugin changed", or, when its plugins weren't compared
(`plugins_error`), "no selected skill changed".

## Auto-commit

For each `path` source with `autocommit = true`, the commands that change
things — `sync`, `update`, `add`, `remove` and `scaffold` — also commit
pending edits to its skills. `doctor`, `status` and `outdated`
only report, and never commit.

1. Skip, with a note, if the skills directory isn't in a git work tree, or the
   repository is mid-merge, mid-rebase, mid-cherry-pick or mid-revert, on a
   detached HEAD, or has conflicts.
2. Stage only changes inside the source's skill directories (the directories
   in its `subdir`) — never anything else in the repository, not even a loose
   file beside them in `subdir`, so unrelated work is not swept into the
   commit. Anything else already staged stays staged, and out of the commit.
3. Commit as the user, with their git configuration (hooks and signing
   included), and a message naming the changed skills with a verb for each
   kind of change: `Add foo; update interview, pr-body-md; remove bar`.
4. If `autopush`, push the current branch to its upstream while commits
   touching skills are unpushed: right after an auto-commit, and again on a
   later run if that push failed (offline, say). Each run tries once. A
   rejected push (the remote moved) is reported, not retried or rebased:
   fixing it is the user's call.

The commit comes after the command's own work, so a command stopped by a
usage or configuration error (exit `2`) commits nothing. A skip is a note and
leaves the exit code alone; a failed commit or push is a problem (exit `1`),
and a failed commit leaves its changes staged. `--dry-run` says what would be
committed and pushed and changes nothing. `--no-commit` (or
`TACK_NO_COMMIT=1`) skips auto-commit for one run. `status` and `doctor`
report uncommitted and unpushed skill edits: exactly the ones auto-commit
takes. A commit touches each skill it changes a file in, whatever characters
the file's name holds, and both skills of a file moved from one to the
other.

Why on-run rather than a background watcher: no daemon to install or keep
alive, and the delay is only until tack next runs.

## `doctor` checks

Each finding has a stable id, a severity, a location, and (where one exists) the
`scaffold` fix. Severity: **error** (something an agent cannot see or will
read wrong), **warn** (will drift or break later), **info**.

### Global

| Id | Sev. | Finding |
|---|---|---|
| `unmanaged-skill` | warn | An entry in a harness skills directory that tack doesn't own and isn't in `ignore` — e.g. installed by hand or by another manager. |
| `dangling-link` | error | A skill link whose target is gone. |
| `not-synced` | warn | A selected skill missing from a harness it targets, or a link pointing somewhere other than the manifest says — including a tack link to a skill no longer selected, a listed skill its source doesn't have, and a source that isn't there (a missing `path`, a git source not yet checked out). *(P0001)* Also a selected plugin that isn't `installed` in a harness it targets (any other [state](#plugin-states)), a tack plugin no longer selected, a listed or selected plugin its source's catalog doesn't have or tack can't deploy, and whatever else `sync` would report about plugins (DEC-7, DEC-19). |
| `name-collision` | error | Two sources select the same skill name for the same harness, or *(P0001)* the same plugin name for any harnesses (DEC-11). |
| `unmanaged-plugin` *(P0001)* | info | A plugin installed in a harness at user scope from a marketplace other than tack's and not in `ignore_marketplaces`: installed by hand or by another manager, so nothing keeps it the same across agents and machines. Selecting it from its source does. |
| `duplicate-plugin` *(P0001)* | warn | A plugin tack deploys to a harness is also installed there, under the same name, from another marketplace: the agent loads both. |
| `bad-skill` | warn | `SKILL.md` missing, without frontmatter, without a `description`, or with a `name` that differs from its directory. |
| `dirty-source` | info | A `path` source has uncommitted or unpushed skill edits. |
| `instructions-split` | warn | The harnesses' user instruction files don't resolve to the same content: neither is an import of or symlink to the other, and their text differs. |
| `hook-one-harness` | info | A user-level hook registered for one harness only. Installer-owned hooks are common here, so this is informational. |
| `unreadable-file` | error | A hook file (user or project) that isn't valid JSON or TOML: the harness can't read it either. |

*(P0001)* The plugin checks read each agent's plugins through its CLI
(`claude plugin list --json`, `codex plugin list --json`, and their
`marketplace list`), as `sync` runs it: once per run, in each built-in
harness whose CLI is on `PATH`, whether or not the manifest selects plugins
(DEC-18); `--projects-only` runs no agent. A harness whose CLI isn't on
`PATH`, or whose `list` fails, has no plugins to report. Every plugin problem
a `sync` dry run would report has a finding (DEC-19), so it is a
`not-synced` finding (its plugins are `unavailable`, DEC-16) where `sync`
reports an `agent` problem: a missing CLI when a selected plugin targets
the harness, a failing `list` when `sync` runs the harness's CLI at all (see
*Leftovers*). Project-scoped plugins aren't audited: in Claude Code only
`user`-scope installs count, as for `sync`. In detail:

- **A selected plugin's state.** `not-synced` takes the plugin's
  [state](#plugin-states) in each harness it targets, as `status` gives it,
  for each one that isn't `installed`: one finding per plugin and harness
  for `missing`, `disabled` and `stale`, and one per harness for
  `unavailable` (with the agent's message) and for `conflict`. A `collision`
  is `name-collision`'s, and a plugin with a source finding (one tack can't
  deploy, whose files can't be read, or whose clone is `in the way` or has
  `local changes`) is reported once, for its source,
  instead.
- **A harness.** The per-harness `unavailable` comes as the paragraph above
  says, and `conflict` (with the foreign marketplace's location) where a
  selected plugin targets the harness or the record lists one there: where
  `sync` reports them (DEC-19). Each names the plugins it stops that have no
  finding of their own, and says only what is wrong with the harness when
  there are none.
- **A source.** `not-synced` for each name a source lists that its catalog
  doesn't have (or that it has no catalog for), each selected plugin tack
  can't deploy (with the reason), and a broken catalog, located at the
  catalog file, or the source root when there is none; and for each plugin
  the manifest deploys from it whose files can't be read, so that its copy
  would fail (with the reason, as `sync` gives it), located at the plugin's
  directory; and for each plugin from another repository whose clone is `in
  the way` or has `local changes`, where `sync` would bring it (with the
  message `sync` gives), located at the clone.
- **Leftovers.** `not-synced` for each of tack's plugins in a harness that
  `sync` would uninstall there (step 4 of [Deploying](#deploying)): one the
  manifest no longer deploys to it and that `sync` doesn't keep, a kept one
  being a collided name, a plugin from another repository whose clone isn't
  `ok`, one whose files
  can't be read (its copy would fail), or one whose recorded source's catalog
  can't be read (its root isn't there, or the catalog is broken). There are
  none in a harness whose CLI `sync` wouldn't run (no selected plugin targets
  it, the record lists none there, and tack's marketplace directory doesn't
  exist).
- **Collisions.** `name-collision` once per plugin name two sources select,
  located at the manifest.
- **Others' plugins.** `unmanaged-plugin` for each plugin installed from a
  marketplace that isn't tack's (a foreign `tack` among them) and isn't in
  the harness's `ignore_marketplaces`. `duplicate-plugin` for each plugin
  the manifest deploys to the harness (selected for it, deployable, and
  selected by no other source) that the harness also has from another
  marketplace, whatever `ignore_marketplaces` says; such a plugin isn't
  also `unmanaged-plugin`.

In a harness with a foreign `tack`, nothing is tack's: none of its plugins
is a leftover or a duplicate. A finding about a harness names it. Like
`status`, these checks read each source as it is now (DEC-17): what they
say `sync` would do is what it does for a source whose state is `ok`.

### Per project

| Id | Sev. | Finding | Fix |
|---|---|---|---|
| `agents-md-missing` | error | `CLAUDE.md` has content but there is no `AGENTS.md`: Codex gets no instructions. | `agents-md` |
| `claude-md-no-import` | warn | Both files exist but `CLAUDE.md` doesn't import `AGENTS.md`: two copies that will drift. | `agents-md` |
| `instructions-untracked` | warn | One instruction file is committed and the other isn't. | — |
| `local-md-suppresses-agents` | error | A `CLAUDE.local.md` exists beside an `AGENTS.md`, and neither it nor `CLAUDE.md` imports `AGENTS.md`, so Claude Code reads the personal file but not the repo's `AGENTS.md`. | `agents-md` |
| `codex-skills-dir` | error | Skills under `.codex/skills`, which Codex doesn't read. | `skills-dir` |
| `claude-only-skills` | error | Skills in `.claude/skills` that aren't in `.agents/skills` (or there is no `.agents/skills`): Codex can't see them. | `skills-dir` |
| `codex-only-skills` | error | Skills in `.agents/skills` that aren't in `.claude/skills` (or there is no `.claude/skills`): Claude Code can't see them. | `skills-dir` |
| `duplicate-skill-copies` | warn | Both `.claude/skills` and `.agents/skills` are real directories. | `skills-dir` |
| `hook-one-harness` | warn | A hook in one harness's project hook file with no counterpart in the other's. | `hooks` |
| `hook-mismatch` | warn | Counterpart hooks exist but differ (event, matcher, or command). | `hooks` |
| `hook-hardcoded-home` | info | A hook command contains an absolute home path; it breaks on another machine or clone. | — |

A project is any git repository found under `projects.roots` (not descending
into another repository's working tree, `node_modules`, hidden directories, or
excluded paths). With no `[projects]` table there are no roots, and only the
global checks run. `tack doctor PATH…` audits the given paths instead of the
roots: a path that is a repository is one project, any other directory is
searched like a root.

**Clones.** When `projects.owners` is set, a repository whose `origin` URL
names another owner (`github.com/<owner>/…`, `git@host:<owner>/…`, and so on;
case-insensitive, any host) is someone else's project cloned for reference:
`doctor` skips it rather than report conventions its authors never chose. A
repository without an `origin`, or with a local one, is yours; so is your
fork of someone else's. The summary says how many clones were skipped and
`--json` lists them. Naming a clone on the command line audits it anyway.

**Imports and hooks.** "Imports" follows Claude Code's rules: an `@path`
token at the start of a line or after whitespace, outside code, relative to
the importing file, followed transitively; a symlink to the other file counts
too. Two hooks in different harnesses are *counterparts* when their commands
are the same once every path in them is reduced to its file name (so
`~/.claude/hooks/gate` and `~/.codex/hooks/gate` match) and, for the global
check, their event is the same. Matchers compare as sets of `|`-separated
alternatives, merged across entries, so four `SessionStart` entries matching
`startup`, `resume`, `clear` and `compact` equal one matching
`startup|resume|clear|compact`. Hooks compare as `scaffold hooks` writes
them: `args` folded into the command, `$CLAUDE_PROJECT_DIR` and
`$(git rev-parse --show-toplevel)` read as the same thing, and an
`apply_patch` matcher reads as `Edit|Write`.

**Exit code.** `1` when there is an error or warn finding; info findings alone
exit `0`.

## Scaffolding

`tack scaffold FIX PATH` applies one fix to one project: it writes, moves and
removes files so that `doctor`'s findings with that fix go away, and **never
commits**. A tracked file is moved or removed through git (`git mv`, so
history follows, and `git rm`), and a file it writes is staged if git tracks
it or tack created it (and git doesn't ignore it), leaving one change to
review and commit; untracked files stay untracked. It prints what it changed and what
to review; `--dry-run` prints the diff of each file it would write instead,
and changes nothing. With no finding for the fix it says so and exits `0`. A
fix it can't apply safely changes nothing, says why, and exits `1`.

**`agents-md`** makes `AGENTS.md` the project's instructions and `CLAUDE.md`
an import of it.

- With no `AGENTS.md`, it moves `CLAUDE.md` there and writes `CLAUDE.md` as
  `@AGENTS.md`.
- With both, it puts `@AGENTS.md` at the top of `CLAUDE.md` and removes each
  paragraph of `CLAUDE.md` that `AGENTS.md` has word for word (a fenced code
  block is one paragraph). What is left is for Claude Code only. `AGENTS.md`
  isn't touched.
- With only a `CLAUDE.local.md` beside `AGENTS.md`, it writes `CLAUDE.md` as
  `@AGENTS.md`.
- It removes an `@AGENTS.md` line from `CLAUDE.local.md`, now redundant.

It lists for review the lines it moved into `AGENTS.md` that name one agent
(`Claude`, `Codex`) or import a file (Codex doesn't follow imports), and the
lines it left in `CLAUDE.md`.

**`skills-dir`** makes `.agents/skills` the one real skills directory and
`.claude/skills` a relative symlink to it. Each entry of `.claude/skills` and
`.codex/skills` that `.agents/skills` lacks is moved there; one it already has
— an identical copy, or a link to it — is removed, and entries git ignores
(a `.DS_Store`) go with their directory. Then `.claude/skills` becomes the
link and `.codex/skills` is removed. If an entry differs from its namesake in
`.agents/skills`, or `.claude/skills` or `.codex/skills` is a link to
somewhere else, it changes nothing and lists what to reconcile by hand.

**`hooks`** registers each project hook one harness has and another lacks in
the other's hook file, with the same event and matcher, so `doctor` pairs them
up. When both have a hook but the two differ (`hook-mismatch`), `--from
HARNESS` says whose version replaces the other's; without it the fix lists
them and changes nothing.

- tack writes only JSON hook files (`.claude/settings.json`,
  `.codex/hooks.json`), creating one if needed and rewriting it with
  two-space indents. A registration it would have to change in
  `.codex/config.toml` is reported for you to change.
- A copy translates what has an exact equivalent: `args` are folded into
  Codex's single `command` string, `$CLAUDE_PROJECT_DIR` (which Codex doesn't
  set) becomes `$(git rev-parse --show-toplevel)`, and Codex's `apply_patch`
  matcher becomes `Edit|Write`. Only `type`, `command`, `timeout` and
  `statusMessage` are copied; any other field, and a hook that isn't a
  command, is reported instead.
- It warns when a matcher names a tool the other harness doesn't have (Codex
  has only `Bash`, `apply_patch` with its aliases `Edit` and `Write`, and MCP
  tools), and when a hook that sees edits (its matcher includes `Edit`,
  `Write`, `apply_patch`, or every tool) reads the tool payload — its command,
  or a script in the project the command runs, mentions `tool_input` or
  `file_path` — because the harnesses' edit payloads differ.
- After writing a Codex hook file it notes that Codex asks you to trust new
  hooks (`/hooks`).

The durable pattern for a hook both agents run is the one the `courses`
repository uses: keep the logic in a committed script that does not depend on
the tool payload, and register an identical one-line command for each
harness.

## The TUI

`tack` with no arguments, in a terminal, opens a Textual app over the same
operations as the CLI. Piped or scripted, it prints the usage and exits `2`
as before, so nothing waits on a screen no one sees. The app takes its
manifest from `TACK_CONFIG` or the default location; the header shows tack's
version and that manifest's path.

Three tabs (four with Plugins, *P0001*), each a list with a detail pane for
the selected row:

- **Skills** — each selected skill, its source, and its state in each
  harness (linked, missing, stale, conflict, collision), grouped by source
  and sortable by any column (below). The detail shows where it comes from
  and its `SKILL.md` description, or what is wrong with it.
- **Plugins** *(P0001)* — each selected plugin, its source, and its
  [state](#plugin-states) in each harness that takes plugins, grouped and
  sorted as Skills is (a harness column puts conflict and collision first,
  then stale, disabled, unavailable, missing, installed, and plugins that
  don't go to that harness). The detail shows where it comes from (the
  source, its pin, and for a plugin from another repository its repository
  and commit), its version and description, or what is wrong with it.
- **Sources** — each source's state: how far behind upstream a git source
  is, or that it isn't pinned or checked out; a path source's uncommitted and
  unpushed skill edits. The detail shows the pin, the commits since, the
  changed skills (and plugins, *P0001*), and their diff. *(P0001)* It names
  the plugins the source selects after its skills, when it selects any, and
  gives its changed plugins, its `plugins_error` and "no selected skill or
  plugin changed" as `outdated`'s text does.
- **Doctor** — the findings by project, colored by severity. The detail
  shows the message, the path, and the fix. Errors come first, then warnings,
  then info.

It opens on Skills and stays there until you pick another tab: it never
moves you, even when Doctor or Sources has something to show. *(P0001)* The
tabs run Skills, Plugins, Sources, Doctor, and `1` to `4` select them in that
order. The Plugins tab's grouping and sort are its own, held like Skills'.
The audit and
the upstream fetch (`outdated --diff`) run in the background, so the app
opens at once and fills each tab as they finish. `r` runs them again.
*(P0001)* Each run lists each agent's plugins once (its two `list`
commands), for the Plugins tab and the audit together.

**Sorting.** Click a column's header to sort the Skills table by it, and
click it again to reverse; `o` moves the sort to the next column and `O`
reverses it. The sorted column's header shows ▲ or ▼. Names sort
alphabetically, ignoring case. A harness column puts problems first:
conflict and collision, then stale, then missing, then linked, then skills
that don't go to that harness. Ties keep the default order, by name and then
source. The sort holds through refreshes for as long as the app is open.

**Grouping.** The Skills tab groups skills by source, in the manifest's
order: a row for each source shows its name and how many skills it selects,
and under each harness how many of them aren't linked there (`1 missing`),
colored like the states; its skills are indented beneath it, sorted within
the group. While grouped, the source column is hidden, so the sort cycles
through the other columns, and the groups keep the manifest's order, as on
the Sources tab. `space` or `enter` folds or unfolds the group under the
cursor (so does clicking its row once it is selected), `←` (or `h`) folds it,
from any of its rows, and `→` (or `l`) unfolds it; a folded group shows only
its row, and folds hold through refreshes. A source's row shows that source's
detail, as on Sources. `g` turns grouping off or on until the app closes;
`[tui] group_by_source` (default `true`) sets how the app opens, and
Settings changes it.

**The Plugins tab** *(P0001)* has a column for the plugin, one for its
source while ungrouped, and one for each harness that takes plugins, in the
order the Skills tab shows them. It sorts, groups and folds as Skills does,
by the plugin state order above, with a sort, a grouping and folds of its
own: `o`, `O`, `g`, the fold keys and a header click change the tab they
are used on, and `[tui] group_by_source` sets how both tabs open. A group
row stands for each source that selects plugins (whose `plugins` isn't
`[]`), in the manifest's order, with how many plugins it selects and, under
each harness, how many of them aren't `installed` there, by state, in the
column's sort order (`1 disabled, 1 missing`). `installed` is green;
`stale`, `disabled` and `missing` are yellow; `unavailable`, `conflict` and
`collision` are red. With no plugin selected, the tab says so, and that a
source's `plugins` in the manifest, or the plugins field of `a` on Sources,
selects them. A plugin's detail names its source and that source's pin (a
`path` source's directory), tack's copy of the plugin if there is one, its
version, its description, and its state in each harness it targets. For a
plugin from another repository it adds, after the source, its `repository`
from `status --json` as two lines: `repository: <url> at <commit>` (the
commit's first twelve digits; `<url> (<path>)` for a `git-subdir`) and
`clone: <the clone's path> (<its state>)`, the path with `~` for the home
directory as the detail's other paths are. For a
plugin `sync` reports a problem about (one tack can't deploy, one from
another repository whose clone is `in the way` or has `local changes`, one
whose files can't be read, or a name two sources
select), it gives that problem as `sync` words it, reading the source as it
is now, as the states do (DEC-17). A plugin's description
is the first string `description` among its `plugin.json` files, read as its
[version](#catalogs) is, else its catalog entry's, else none.

**Settings.** `,` opens a Settings screen over the manifest, in tabs:

- **General** — `after_save`, and the TUI's defaults (`group_by_source`).
- **Projects** — `roots`, `exclude` and `owners`, one entry per line.
- **Harnesses** — each harness's `ignore` list: what it adds to the built-in
  one, which the screen shows beside it.
- **Sources** — for each source: `ref` (git), `subdir`, `harnesses` (a
  checkbox per harness; all checked means the default, every harness), and
  `autocommit` and `autopush` (path; `autopush` needs `autocommit`).

Adding and removing sources stays on the Sources tab. Per-skill selections
(`skills`), plugin selections (`plugins`, *P0001*) and `ignore_marketplaces`,
harness paths and new harnesses are edited by hand, and the screen says so.
Saving (`ctrl+s`) goes through the same preview as any other
action: its dry run shows the manifest's diff, and nothing is written until
you confirm; then `after_save` runs and the tabs refresh. Cancelling
(`escape`) asks before discarding changes. A change to what gets deployed (a
source's `subdir` or `harnesses`, an `ignore` list) takes effect at the next
`s`; a git source whose `ref` changed shows `manifest changed` until `u`
updates it. Settings writes only what could be written by hand, so the TUI
is still never the only way to do something (principle 6).

Apart from Settings, it changes nothing the CLI can't. `s` syncs; on Sources, `u` updates the
selected source, `a` adds one (a form taking what `tack add` takes) and `x`
removes the selected one; on Doctor, `f` applies the selected finding's fix,
first asking which harness wins a `hook-mismatch`. Every action first shows
its dry run, auto-commit included, and does nothing until you confirm. Then
it runs, auto-commits as the CLI does, shows what it did in the same dialog,
and refreshes the tabs. Opening the app commits nothing. An action waits for
a running fetch to finish, so the two never work in one checkout at once.

Diffs show colored in the detail pane and in an action's preview; `p`
suspends the app and opens the diff in git's pager (`git var GIT_PAGER`).

## The agent skill

tack ships a skill of its own, `skills/tack/SKILL.md`, that teaches coding
agents to run tack for the user: the `--json` CLI rather than the TUI, a dry
run shown before every change, the manifest's fields, auto-commit and
`--no-commit`, and `doctor`'s findings and their `scaffold` fixes (and
plugins, *P0001*). It is generic, like tack, and versions with the code.

The repository is itself a source, so tack deploys the skill like any other:
`tack add https://github.com/chocs-cat/tack.git` adds a source named `tack`
that links it into every harness, and `tack update tack` takes in a newer
one. Anyone else copies `skills/tack` into their agents' skills directories.
The skill isn't deployed without a manifest entry: tack deploys only what
the manifest selects (principle 4).

A test keeps the skill honest: it must pass `bad-skill`, and every `tack`
command in its shell blocks must parse with tack's own argument parser, so a
renamed command or flag fails CI until the skill follows.

## Releasing

tack is published to PyPI as `tack-agents` and to Homebrew as `tack`, from the
`chocs-cat/homebrew-tap` tap (`brew install chocs-cat/tap/tack`). The
repository and the tap are public.

- **Versions and the changelog** come from Conventional Commits, through
  release-please. `feat` bumps the minor version, and so does a breaking
  change while tack is below 1.0; `fix` and `perf` bump the patch; the other
  types release nothing on their own. release-please keeps a release pull
  request open with the bump and a `CHANGELOG.md` section, and merging it
  tags `vX.Y.Z` and creates the GitHub release. The version is in
  `pyproject.toml`, `src/tack/__init__.py` and `uv.lock`; release-please
  updates all three. The first release is `0.1.0`.
- **PyPI.** The release workflow then builds the sdist and wheel, uploads
  them by trusted publishing (no token) from a `pypi` environment, and
  attaches them to the GitHub release.
- **Homebrew.** Then it writes the formula and pushes it to the tap as one
  commit, `tack X.Y.Z`. The formula builds from the PyPI sdist, with a
  `resource` for each runtime dependency at the version the release tag's
  `uv.lock` pins, so Homebrew installs what CI tested: `scripts/formula.py`
  reads the pins from a checkout of the tag (`uv export --frozen`) and takes
  each sdist's URL and hash from PyPI; it runs the same way by hand. Other
  projects' releases push to the same tap, so the push rebases and retries
  when it is rejected. A job on macOS then audits the formula
  (`brew audit --strict`), installs it from the tap and runs
  `tack --version`. Pushing needs a `TAP_TOKEN` organization secret, a
  fine-grained token with Contents read/write on the tap alone.
- The formula uses Homebrew's newest Python (`python@3.14`), so CI tests 3.11
  through 3.14.

Setup no file can do is listed in `CONTRIBUTING.md`: the PyPI pending
publisher (project `tack-agents`, owner `chocs-cat`, repository `tack`,
workflow `release.yml`, environment `pypi`), the `pypi` environment, letting
Actions create pull requests, the `TAP_TOKEN` organization secret, and
optionally a `RELEASE_PLEASE_TOKEN` so release pull requests run CI without
approval.

## Harness facts tack relies on

Verified 2026-09-27 against Claude Code 2.1.283 and codex-cli 0.155.1 and
their documentation. `doctor`'s checks encode these; a harness release that
changes one means a check changes.

- **Codex skills** load from `.agents/skills` in every directory from the
  working directory up to the repository root, then `~/.agents/skills`,
  `/etc/codex/skills`, and bundled system skills. `.codex/skills` is not read.
- **Claude Code skills** load from `.claude/skills` and `~/.claude/skills`, and
  follow symlinked directories (verified with a symlinked `.claude/skills`).
- **Claude Code reads `AGENTS.md` natively** only when no `CLAUDE.md` or
  `CLAUDE.local.md` exists in the working directory or above it. A
  `CLAUDE.md` containing `@AGENTS.md` loads it in every case and never twice.
- **Imports in `~/.claude/CLAUDE.md`** (e.g. `@~/.codex/AGENTS.md`) load
  without the external-import approval dialog that project files get.
- **Codex hooks** load from `~/.codex/hooks.json`, `~/.codex/config.toml`,
  `<repo>/.codex/hooks.json`, and `<repo>/.codex/config.toml`; project hooks
  only once the project is trusted. `hooks.json` has the same shape as the
  `hooks` block of Claude Code's `settings.json`.
- **Codex hook matchers** accept `Edit`/`Write` as aliases for `apply_patch`,
  but the payload differs: Codex sends `tool_name: "apply_patch"` with the
  patch in `tool_input.command`, where Claude Code sends
  `tool_input.file_path`.
- **Codex hook trust** is keyed on a hash of the hook definition. A new or
  changed definition needs one approval (`/hooks`); changing a script the hook
  calls does not.
- **Codex command hooks** have `command` (one shell string), `timeout`,
  `statusMessage`, `async` and `additionalContextLimit`, and no `args`. They
  run in the session's working directory, and nothing names the project
  root: Claude Code's `CLAUDE_PROJECT_DIR` has no Codex counterpart. The
  shell tool matches `Bash` in both harnesses, with the command in
  `tool_input.command`.

*(P0001)* Plugin facts, verified 2026-10-05 against Claude Code 2.1.289 and
codex-cli 0.157.1, in a scratch `HOME`, and their documentation. Re-verified
2026-10-09 against Claude Code 2.1.289 and codex-cli 0.160.1 by
`tools/agent_facts.py` and by `tack sync`, `update` and `remove` in a
scratch `HOME`, all but the reserved names, Codex turning `commands/` into
skills, and symlinked plugin directories:

- **Claude Code plugins** are managed by `claude plugin` (`marketplace
  add|list|remove`, `install`, `uninstall`, `list`, `enable`, `disable`,
  `update`), each taking `--json`. `marketplace add <dir>` registers a
  `directory` marketplace in `extraKnownMarketplaces` of
  `~/.claude/settings.json` and in `~/.claude/plugins/known_marketplaces.json`;
  adding it again succeeds and changes nothing. Adding a directory whose
  catalog has the name of a marketplace registered from elsewhere also
  succeeds, and points that name at the new directory, so registering tack's
  marketplace over a foreign `tack` would take it over; tack doesn't (see
  [Plugin ownership](#plugin-ownership)). `install <p>@<m> --scope user`
  sets `enabledPlugins` in `settings.json` and records the install in
  `~/.claude/plugins/installed_plugins.json`; installing an installed plugin
  succeeds and changes nothing. `uninstall` of a plugin that isn't installed
  exits `1` (`failureCode` `not_installed`). `marketplace remove` uninstalls
  the marketplace's plugins. Claude Code rewrites `settings.json` itself.
- **Claude Code loads in place** a plugin whose catalog entry is a relative
  path in a marketplace added from a local directory (`plugin list --json`
  shows it as `readFromFolder`), so a change to its files reaches the next
  session with nothing to run. Its recorded version is `unknown` when neither
  the plugin nor the marketplace is a git repository. `install` also copies
  the plugin into `~/.claude/plugins/cache/<m>/<p>/<version>/`, the
  `installPath` that `plugin list` shows, and nothing refreshes that copy;
  Claude Code reads the folder, not the copy (`plugin details` lists a skill
  added to the folder after the install; seen 2026-10-09 in 2.1.289).
  `uninstall` leaves the copy, marked `.orphaned_at`, for Claude Code to
  clear.
- **Claude Code refuses reserved marketplace names** (`claude-plugins-official`
  and the other official ones) unless the marketplace is a GitHub source under
  `anthropics`, so a local copy of an official catalog can't be registered
  under its own name. One marketplace per name may be registered.
- **Codex plugins** are managed by `codex plugin` (`marketplace
  add|list|upgrade|remove`, `add`, `remove`, `list`), each taking `--json`
  and none taking `--scope` (their `--help`, re-checked 2026-10-09 against
  codex-cli 0.160.1); there is no command to enable or
  disable a plugin. `marketplace add <dir>`
  reads a Claude Code catalog (`.claude-plugin/marketplace.json`) as well as
  its own (`.agents/plugins/marketplace.json`), its own first when there are
  both, and records `[marketplaces.<name>]` with `source_type = "local"` in
  `~/.codex/config.toml`; adding it again reports `alreadyAdded`, and adding
  another directory under a registered name fails.
  `add <p>@<m>` copies the plugin into
  `~/.codex/plugins/cache/<m>/<p>/local/`, records `[plugins."<p>@<m>"]
  enabled = true`, and turns a Claude Code plugin's `commands/` into skills;
  it accepts a plugin with only `.claude-plugin/plugin.json`. Running `add`
  again refreshes the copy; changing the plugin's files doesn't. `remove`
  succeeds whether or not the plugin is installed, and `marketplace remove`
  leaves the marketplace's plugins installed. Codex rewrites `config.toml`
  itself.
- **Symlinked plugin directories.** Both agents installed a plugin whose
  directory in a local marketplace is a symlink to a directory outside it, but
  Claude Code's `plugin validate` says it dereferences only symlinks that stay
  inside the marketplace; tack doesn't rely on it (DEC-2).

*(P0001)* Their output, verified 2026-10-05 against the same versions, in a
scratch `HOME`, and re-verified 2026-10-09 against Claude Code 2.1.289 and
codex-cli 0.160.1 as above, all but the stdin wait:

- **stdin.** Run with stdin an open pipe, `claude` waits three seconds for
  input and warns before it carries on; with stdin closed it doesn't.
- **`claude plugin list --json`** prints an array, one object per installed
  plugin: `id` (`<name>@<marketplace>`), `scope` (`user`, `project`, `local`,
  or `synced` for claude.ai's), `enabled`, `version`, `installPath`, and for a
  plugin loaded in place `readFromFolder`. A plugin stays listed after its
  marketplace entry and directory are gone, and `uninstall` still removes it.
- **`claude plugin marketplace list --json`** prints an array of `name`,
  `source` (`directory`, `github`, `git`, …), `installLocation`, and for a
  `directory` marketplace `path`.
- **Claude Code's commands** (`marketplace add`, `install`, `uninstall`,
  `marketplace remove`) print one JSON object with `outcome` `ok` or `failed`,
  a `message`, and on failure a `failureCode`; a failure exits `1` and also
  writes `✘ …` to stderr. `marketplace remove` of a marketplace that isn't
  registered fails (`not_configured`), as `install` of a plugin the
  marketplace lacks, or from a marketplace that isn't registered, does
  (`not_found`).
- **`codex plugin list --json`** prints `{"installed": […], "available": […]}`;
  each installed plugin has `pluginId`, `name`, `marketplaceName`, `version`,
  `installed` and `enabled`. It lists only plugins of registered marketplaces
  whose catalog still has them: one left installed after its entry or its
  marketplace was removed is missing from the list (though still in
  `config.toml`), and `remove` still uninstalls it. Registering the
  marketplace again lists it again, still installed (DEC-14; checked
  2026-10-07 against codex-cli 0.160.1 by `tools/agent_facts.py`).
- **`codex plugin marketplace list --json`** prints `{"marketplaces": […]}`,
  each with `name`, `root`, and `marketplaceSource` (`sourceType` `local` or
  `git`, and `source`, a path or URL).
- **Codex's commands** print a JSON object on success (`marketplace add`:
  `marketplaceName`, `installedRoot`, `alreadyAdded`; `add`: `pluginId`,
  `version`, `installedPath`). A failure exits `1`, prints nothing on stdout,
  and writes `Error: <message>` to stderr, as `add` of a plugin the
  marketplace lacks (or from a marketplace that isn't registered) and
  `marketplace remove` of one that isn't registered do.
- **The agents' own marketplaces**, the built-in `ignore_marketplaces`,
  seen 2026-10-09 in `plugin list --json` and `plugin marketplace list
  --json` on a signed-in setup, read only. Claude Code 2.1.289 lists
  claude.ai's synced plugins from `synced`, with scope `synced`; `builtin`,
  `inline` and `skills-dir` weren't seen, that setup having no such plugin
  (`claude plugin init`'s help names a plugin it scaffolds
  `<name>@skills-dir`). codex-cli 0.160.1 lists its own plugins from
  `openai-bundled`, `openai-curated-remote` and `openai-primary-runtime`,
  all three seen; `marketplace list` shows `openai-bundled` and
  `openai-primary-runtime` as `local` and leaves `openai-curated-remote`
  out. A marketplace the user added (`claude-plugins-official` among them)
  is listed under its own name in both. A fresh scratch `HOME` has none of
  the agents' own, so `tools/agent_facts.py` can't check them.

## Implementation

- Python ≥ 3.11 (`tomllib`), packaged with uv and hatchling, like corral.
  Distribution name `tack-agents` (`tack` is taken on PyPI); the command is
  `tack`.
- Dependencies: `textual` (the TUI), always installed. Manifest edits are text edits
  checked by re-parsing (see [Writing the manifest](#writing-the-manifest)),
  so no TOML writer. Git through `subprocess`, no Git library.
- CLI with `argparse`, `--json` on every command.
- Checks: `pytest`, `ruff check`, `ruff format --check`, `ty check`.
- Layout: `src/tack/` with `config.py` (manifest, lock, harnesses),
  `sources.py` (checkout, pin, fetch; *(P0001)* plugins' clones too),
  `deploy.py` (links, ownership),
  one module per command for `sync`, `status`, `outdated` and `update`,
  `edit.py` (`add`, `remove` and the manifest's text edits),
  `commit.py` (auto-commit), `doctor/` (one module per check group),
  `scaffold/` (one module per fix), `cli.py`, and `tui/` (the app, its
  views and its dialogs, over the same functions the CLI calls). Outside
  the package, `scripts/formula.py` writes the Homebrew formula, and
  `skills/tack/` is the agent skill. *(P0001)* `catalog.py` reads catalogs,
  `plugins.py` plans plugins and keeps tack's marketplace, and `agents.py`
  runs the agents' plugin CLIs; `sync`, `status`, `doctor` and the TUI go
  through them.
- Tests build throwaway harness directories, projects and git remotes in a
  temporary directory; nothing in the test suite touches the real home
  directory. The TUI is driven through Textual's test pilot. *(P0001)* No
  test runs a real agent: the suite puts stand-in `claude` and `codex`
  executables first on `PATH`, which answer from files in the temporary
  directory, behave as [Harness facts](#harness-facts-tack-relies-on)
  describes, and record how they were called. Every other `PATH` directory
  holding a `claude` or `codex` is replaced by a mirror of its other
  programs (DEC-9), so even a test that takes a stand-in away can't reach a
  real agent.

## Phases

Each phase ends usable and reviewed before the next begins.

1. **Design** — this document. Done when the maintainer approves it.
2. **`doctor`** — config loading, harness model, every check above,
   `--json`. Accepted when it runs clean against the maintainer's machine
   except for real findings, each of which is either fixed or explained.
   Read-only, so it is safe to ship before tack deploys anything.
3. **Sources and `sync`** — path and git sources, the lockfile, ownership,
   conflicts and `--adopt`, `after_save`, `status`. Ends with the migration
   below.
4. **Tracking** — `outdated`, `update`, `add`, `remove`.
5. **Auto-commit** for path sources.
6. **Scaffolding** — the three fixes.
7. **TUI** (Textual) over the same operations: deployed skills per harness,
   sources with outdated counts and diffs, `doctor` findings with their fixes;
   see [The TUI](#the-tui).
8. **Release** — PyPI `tack-agents`, Homebrew formula in
   `chocs-cat/homebrew-tap`; see [Releasing](#releasing).
9. **TUI refinements** — the header (tack's version and the manifest's
   path, one line when clicked), sorting and grouping on Skills, and
   Settings; see [The TUI](#the-tui).
10. **Agent skill** — `skills/tack/SKILL.md`, deployable with `tack add`;
    see [The agent skill](#the-agent-skill).

All ten are done. Later work is planned as projects in
[projects/](projects/index.md) instead of new phases; a project is activated,
and implementation starts, once the maintainer approves its design.

## Migrating the maintainer's setup

**Done 2026-09-27.** Until then chezmoi deployed skills: `symlink_*.tmpl`
entries under `private_dot_claude/skills/` and `dot_agents/skills/`, and
`git-repo` externals cloning third-party sources into
`~/.local/share/agent-skills/`. The migration, at the end of phase 3:

1. Write `~/.config/tack/tack.toml` matching the current deployment (the
   example above), and `chezmoi add` it. The lockfile is added after step 3:
   the first `sync` writes it, and its `after_save` (`chezmoi re-add`) fails
   that once because chezmoi doesn't manage the file yet.
2. `chezmoi forget` the 32 skill symlinks and delete the three skill externals
   from `.chezmoiexternal.toml.tmpl` — *before* `sync`, so a later `chezmoi
   apply` doesn't recreate them.
3. `tack sync --adopt`: tack replaces the chezmoi-made links with its own.
4. `tack doctor` clean; then delete `~/.local/share/agent-skills/`.
5. Update the global instructions' "Global skills" section to describe tack.
6. New machines. chezmoi doesn't install software itself; the dotfiles'
   Brewfile does, through the existing `run_once_after_install-homebrew.sh`
   script that runs `brew bundle install`. Since phase 8 the Brewfile has
   `brew "chocs-cat/tap/tack"`, with the tap beside `johnfoland/tap` and
   trusted the same way, on every machine including the maintainer's, which
   runs unreleased changes with `uv run tack` in the checkout. Until then,
   tack was installed by hand: `uv tool install -e ~/Code/tack`, as corral is.
   chezmoi also places the manifest and lockfile, and a `run_onchange_after_`
   script keyed on `tack.lock` runs `tack sync` whenever the pins change.
   Both scripts belong to the dotfiles, not to tack.

## Open questions

- **MCP servers.** Deferred. Claude Code keeps user-level MCP servers in
  `~/.claude.json`, which running sessions rewrite wholesale, so tack would
  have to go through `claude mcp add/remove` rather than edit files; Codex
  keeps them in `config.toml`. Worth doing only with a way to express one
  server for both. *(P0001)* A plugin carrying a `.mcp.json` is one such
  way: deploying it gives both agents the server.
- **Plugins one agent can't fully load.** Each agent loads only the parts of
  a plugin it supports (Codex's documentation lists skills, MCP servers,
  apps and hooks; Claude Code's adds commands, agents, LSP servers and more,
  and no apps). Should `doctor` warn when a plugin deployed to both has parts one of
  them ignores, as the skills question below asks for tools?
- **Harness-specific skills.** Some skills assume one agent's tools (e.g. a
  structured question tool). Per-skill `harnesses` covers deployment; should
  `bad-skill` also warn when a skill deployed to both names a tool only one
  has?
- **Renaming on collision.** Deselecting is the only remedy for now. Renaming
  a link would disagree with the skill's frontmatter `name`.
- **Global hook parity.** Installer-owned hooks make `hook-one-harness`
  noisy at user level; it may need an ignore list like skills do.

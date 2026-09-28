# tack — design

Status: **approved** (2026-09-27); every phase is done, and tack 0.1.0 is
released on PyPI and Homebrew. This document
is the spec. Decisions below were settled with the maintainer in an
interview; where one is still open it says so, in
[Open questions](#open-questions).

## Contents

1. [What tack is](#what-tack-is)
2. [Principles](#principles)
3. [Concepts](#concepts)
4. [Files and locations](#files-and-locations)
5. [The manifest: `tack.toml`](#the-manifest-tacktoml)
6. [The lockfile: `tack.lock`](#the-lockfile-tacklock)
7. [Commands](#commands)
8. [Ownership and conflicts](#ownership-and-conflicts)
9. [Auto-commit](#auto-commit)
10. [`doctor` checks](#doctor-checks)
11. [Scaffolding](#scaffolding)
12. [The TUI](#the-tui)
13. [Releasing](#releasing)
14. [Harness facts tack relies on](#harness-facts-tack-relies-on)
15. [Implementation](#implementation)
16. [Phases](#phases)
17. [Migrating the maintainer's setup](#migrating-the-maintainers-setup)
18. [Open questions](#open-questions)

## What tack is

A CLI and a TUI that keep a person's **agent skills** deployed
identically to every coding agent they use, from one manifest of sources, and
audit their projects so **Claude Code and Codex stay interchangeable**:
the same instructions, the same skills, the same hooks, whichever agent you
start.

It does three jobs:

- **Deploy skills.** Each skill comes from a *source* — a local checkout you
  edit, or a git repository pinned to a commit — and is linked into each
  agent's skills directory.
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
  [Open questions](#open-questions)).
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
| **Source** | Where skills come from: a `path` (a local checkout, linked in place) or a `git` repository (cloned by tack, pinned to a commit). |
| **Skill** | A directory containing `SKILL.md`, found inside a source's skills directory (`skills/` by default). Its directory name is its name. |
| **Deployment** | A symlink `<harness skills dir>/<name> → <skill directory>`. |
| **Manifest** | `tack.toml`: the sources and which of their skills go to which harnesses. Hand-edited or changed by `tack add`/`remove`. |
| **Lockfile** | `tack.lock`: the commit each git source is pinned to. Written only by tack. |
| **Project** | A git repository under one of the configured project roots, audited by `doctor`. |

## Files and locations

tack follows the XDG base directory spec, with the usual fallbacks.

| What | Default | Override |
|---|---|---|
| Manifest | `$XDG_CONFIG_HOME/tack/tack.toml` (`~/.config/tack/tack.toml`) | `TACK_CONFIG` env or `--config` (a directory) |
| Lockfile | beside the manifest: `~/.config/tack/tack.lock` | follows the manifest |
| Git source checkouts | `$XDG_DATA_HOME/tack/sources/<source>/` (`~/.local/share/tack/…`) | `TACK_DATA` |
| Ownership record | `$XDG_STATE_HOME/tack/state.json` (`~/.local/state/tack/…`) | `TACK_STATE` |

Checkouts live under *data*, not *cache*: deployed links point into them, so
deleting them breaks skills.

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
| `skills` | all | `"*"` | Which skills to deploy: `"*"`, or a list. A list entry is a name, or `{ name = "…", harnesses = ["claude-code"] }` to limit that skill. |
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

`hooks` and `project_hooks` list every file the harness reads hooks from (a
single string is accepted); a `.json` file keeps them under a top-level
`hooks` key, a `.toml` file in `[[hooks.<Event>]]` tables. `imports` says
whether the harness follows `@path` imports in its instruction files.

`ignore` names entries in `skills_dir` that belong to someone else: tack never
touches them and `doctor` does not report them as unmanaged. For a built-in
harness it adds to the built-in list rather than replacing it.

### Writing the manifest

tack edits `tack.toml` only through `add`/`remove` (and the TUI), and as
text, so comments and layout survive: it appends one `[[source]]` table after
the last, or cuts one out together with the comment lines directly above its
header, and leaves every other line alone. The edit is kept only if the new
text parses to the old manifest with exactly that source added or removed;
otherwise tack writes nothing and asks for the change to be made by hand
(exit `2`). (A TOML round-trip library was the first plan, but tomlkit keeps a
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

A checkout is tack's, but `sync` still refuses to move one with local
changes (it reports them instead of discarding them). A checkout that has
gone missing is cloned again at its pin.

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
| `tack add GIT_URL\|PATH [--name N] [--skill S…] [--ref R] [--subdir D] [--dry-run] [--no-commit]` | Add a source to the manifest (then `sync`). |
| `tack remove SOURCE [--dry-run] [--no-commit]` | Remove a source from the manifest and its links (then `sync`). |
| `tack doctor [PATH…] [--global-only\|--projects-only]` | Audit; see [`doctor` checks](#doctor-checks). Read-only. |
| `tack scaffold FIX PATH [--from HARNESS] [--dry-run] [--no-commit]` | Apply one `doctor` fix to one project; see [Scaffolding](#scaffolding). |
| `tack` (no arguments, in a terminal) | Launch the TUI; see [The TUI](#the-tui). |

`sync`, `update`, `add`, `remove` and `scaffold` also commit pending edits to
your own skills; see [Auto-commit](#auto-commit).

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
added). A tip whose history no longer contains the pin (upstream rewrote it)
is flagged. A source that isn't pinned, isn't checked out, or whose manifest
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
`--subdir` sets where its skills are.

Before writing anything, `add` pins a git source to the tip of its ref and
clones it, then refuses (exit `2`, nothing written, a fresh clone removed) a
name already in the manifest, a source already in it (the same `path`, or the
same `git` and `ref`), a source with no skills in its `subdir`, a `--skill`
the source doesn't have, and a skill another source already deploys to the
same harness. Otherwise it appends the table and syncs. A git source it can't
reach is reported (exit `1`) with nothing written. A new source is always
pinned afresh, replacing any lock entry left under its name. A dry run doesn't
clone, so it can't check a git source's skills.

**`remove`** cuts the source's table, drops its lock entry, syncs (which
removes its links), and then deletes tack's checkout of it, unless the
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
takes.

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
| `not-synced` | warn | A selected skill missing from a harness it targets, or a link pointing somewhere other than the manifest says — including a tack link to a skill no longer selected, a listed skill its source doesn't have, and a source that isn't there (a missing `path`, a git source not yet checked out). |
| `name-collision` | error | Two sources select the same skill name for the same harness. |
| `bad-skill` | warn | `SKILL.md` missing, without frontmatter, without a `description`, or with a `name` that differs from its directory. |
| `dirty-source` | info | A `path` source has uncommitted or unpushed skill edits. |
| `instructions-split` | warn | The harnesses' user instruction files don't resolve to the same content: neither is an import of or symlink to the other, and their text differs. |
| `hook-one-harness` | info | A user-level hook registered for one harness only. Installer-owned hooks are common here, so this is informational. |
| `unreadable-file` | error | A hook file (user or project) that isn't valid JSON or TOML: the harness can't read it either. |

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
manifest from `TACK_CONFIG` or the default location.

Three tabs, each a list with a detail pane for the selected row:

- **Skills** — each selected skill, its source, and its state in each
  harness (linked, missing, stale, conflict, collision). The detail shows
  where it comes from and its `SKILL.md` description, or what is wrong with
  it.
- **Sources** — each source's state: how far behind upstream a git source
  is, or that it isn't pinned or checked out; a path source's uncommitted and
  unpushed skill edits. The detail shows the pin, the commits since, the
  changed skills, and their diff.
- **Doctor** — the findings by project, colored by severity. The detail
  shows the message, the path, and the fix. Errors come first, then warnings,
  then info.

It opens on the tab that needs attention: Doctor if it has an error or a
warning, else Sources if a source is behind or has uncommitted or unpushed
edits, else Skills. The audit and the upstream fetch (`outdated --diff`) run
in the background, so the app opens at once on Skills and moves to that tab
when both are done, unless you have picked a tab by then. `r` runs them
again.

It changes nothing the CLI can't. `s` syncs; on Sources, `u` updates the
selected source, `a` adds one (a form taking what `tack add` takes) and `x`
removes the selected one; on Doctor, `f` applies the selected finding's fix,
first asking which harness wins a `hook-mismatch`. Every action first shows
its dry run, auto-commit included, and does nothing until you confirm. Then
it runs, auto-commits as the CLI does, shows what it did in the same dialog,
and refreshes the tabs. Opening the app commits nothing. An action waits for
a running fetch to finish, so the two never work in one checkout at once.

Diffs show colored in the detail pane and in an action's preview; `p`
suspends the app and opens the diff in git's pager (`git var GIT_PAGER`).

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
  `tack --version`. Pushing needs a `TAP_TOKEN` secret, a fine-grained token
  with Contents read/write on the tap alone.
- The formula uses Homebrew's newest Python (`python@3.14`), so CI tests 3.11
  through 3.14.

Setup no file can do is listed in `CONTRIBUTING.md`: the PyPI pending
publisher (project `tack-agents`, owner `chocs-cat`, repository `tack`,
workflow `release.yml`, environment `pypi`), the `pypi` environment, letting
Actions create pull requests, the `TAP_TOKEN` secret, and optionally a
`RELEASE_PLEASE_TOKEN` so release pull requests run CI without approval.

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
  `sources.py` (checkout, pin, fetch), `deploy.py` (links, ownership),
  one module per command for `sync`, `status`, `outdated` and `update`,
  `edit.py` (`add`, `remove` and the manifest's text edits),
  `commit.py` (auto-commit), `doctor/` (one module per check group),
  `scaffold/` (one module per fix), `cli.py`, and `tui/` (the app, its
  views and its dialogs, over the same functions the CLI calls). Outside
  the package, `scripts/formula.py` writes the Homebrew formula.
- Tests build throwaway harness directories, projects and git remotes in a
  temporary directory; nothing in the test suite touches the real home
  directory. The TUI is driven through Textual's test pilot.

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
  server for both.
- **Harness-specific skills.** Some skills assume one agent's tools (e.g. a
  structured question tool). Per-skill `harnesses` covers deployment; should
  `bad-skill` also warn when a skill deployed to both names a tool only one
  has?
- **Renaming on collision.** Deselecting is the only remedy for now. Renaming
  a link would disagree with the skill's frontmatter `name`.
- **Global hook parity.** Installer-owned hooks make `hook-one-harness`
  noisy at user level; it may need an ignore list like skills do.

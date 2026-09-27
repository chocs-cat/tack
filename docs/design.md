# tack — design

Status: **draft for review** (2026-09-27). No code yet; this document is the
spec for it. Decisions below were settled with the maintainer in an interview;
where one is still open it says so, in [Open questions](#open-questions).

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
12. [Harness facts tack relies on](#harness-facts-tack-relies-on)
13. [Implementation](#implementation)
14. [Phases](#phases)
15. [Migrating the maintainer's setup](#migrating-the-maintainers-setup)
16. [Open questions](#open-questions)

## What tack is

A CLI (and later a TUI) that keeps a person's **agent skills** deployed
identically to every coding agent they use, from one manifest of sources, and
audits their projects so **Claude Code and Codex stay interchangeable**:
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
git = "https://github.com/johnfoland/corral.git"
ref = "master"
skills = ["corral"]
```

### Source fields

| Field | Applies to | Default | Meaning |
|---|---|---|---|
| `name` | all | required | Identifier used in the lockfile, the checkout path, and commands. Unique. |
| `path` | path | — | A local directory, linked in place. Exactly one of `path`/`git`. |
| `git` | git | — | A clone URL. |
| `ref` | git | the remote's default branch | The branch or tag `update` follows. |
| `subdir` | all | `skills` | Where the skill directories are, relative to the source root. |
| `skills` | all | `"*"` | Which skills to deploy: `"*"`, or a list. A list entry is a name, or `{ name = "…", harnesses = ["claude-code"] }` to limit that skill. |
| `harnesses` | all | every harness | Limit the whole source. |
| `autocommit` | path | `false` | Commit pending edits to this source's skills when tack runs. |
| `autopush` | path | `false` | Push after an auto-commit. |

### Harness fields

Built-in values shown; any can be overridden, and a new `[harness.<name>]`
table with all of them defines another agent.

| Field | `claude-code` | `codex` |
|---|---|---|
| `skills_dir` | `~/.claude/skills` | `~/.agents/skills` |
| `project_skills_dir` | `.claude/skills` | `.agents/skills` |
| `instructions` | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` |
| `project_instructions` | `CLAUDE.md` | `AGENTS.md` |
| `hooks` | `~/.claude/settings.json` | `~/.codex/hooks.json` |
| `project_hooks` | `.claude/settings.json` | `.codex/hooks.json` |
| `ignore` | `["synced"]` + any dot-entry | any dot-entry |

`ignore` names entries in `skills_dir` that belong to someone else: tack never
touches them and `doctor` does not report them as unmanaged.

### Writing the manifest

tack edits `tack.toml` only through `add`/`remove` (and the TUI), with
[tomlkit](https://github.com/python-poetry/tomlkit) so comments and layout
survive. After writing either file it runs `after_save` once per file changed,
with `{path}` replaced by the absolute path, and reports a failure without
undoing the write.

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
  of its `ref`, and the lock is written.
- If the manifest's `git` or `ref` for a source no longer matches its lock
  entry, `sync` refuses that source until `tack update <source>` re-pins it.
- `path` sources are not locked: they are whatever is checked out.

## Commands

All commands take `--json` (machine-readable output, no prompts) and
`--config DIR`. Exit codes: `0` success / nothing to report, `1` findings or a
partial failure, `2` usage or configuration error.

| Command | What it does |
|---|---|
| `tack sync [--dry-run] [--adopt]` | Make every harness match the manifest and lock: fetch/check out git sources at their pinned commits, create missing links, remove links to skills no longer selected. Reports conflicts instead of overwriting (see [Ownership](#ownership-and-conflicts)); `--adopt` takes them over. |
| `tack status` | What is deployed where, each source's pin or checkout state, and pending auto-commits. Read-only. |
| `tack outdated [SOURCE…] [--diff]` | Fetch each git source's `ref` and show how far its pin is behind: commits, and which *selected* skills changed. `--diff` prints the diff limited to those skills. |
| `tack update [SOURCE…]` | Move pins to the current tip of `ref`, write the lock, then `sync`. |
| `tack add GIT_URL\|PATH [--name N] [--skill S…] [--ref R]` | Add a source to the manifest (then `sync`). |
| `tack remove SOURCE` | Remove a source from the manifest and its links (then `sync`). |
| `tack doctor [PATH…] [--global-only\|--projects-only]` | Audit; see [`doctor` checks](#doctor-checks). Read-only. |
| `tack scaffold CHECK PATH [--dry-run]` | Apply the fix for one `doctor` finding to one project; see [Scaffolding](#scaffolding). |
| `tack` (no arguments, later) | Launch the TUI. |

`sync` is idempotent and safe to run from a login hook or a dotfiles
tool's post-apply step; bootstrapping a new machine is: install tack, put the
manifest and lock in place, `tack sync`.

## Ownership and conflicts

A path in a harness skills directory is **tack's** if it is a symlink and
either the ownership record lists it, or its target is inside tack's data
directory or inside a configured source. Only tack's paths are ever replaced
or removed.

Anything else at a path tack wants — a real directory, a symlink elsewhere, a
link into another manager's library — is a **conflict**: `sync` skips that
skill, reports it, and exits `1`. `sync --adopt` replaces conflicting entries
after moving any real directory to `$XDG_STATE_HOME/tack/adopted/<timestamp>/`
(never deleting it).

Two sources offering the same skill name is a manifest error: tack deploys
neither and says which sources collide. Deselect one.

## Auto-commit

For each `path` source with `autocommit = true` that is a git repository,
every tack command **except `doctor` and `status`** (which stay read-only)
first commits pending edits:

1. Skip, with a note, if the repository is mid-merge, mid-rebase, on a
   detached HEAD, or has conflicts.
2. Stage only changes under the source's `subdir` — never anything else in the
   repository, so unrelated work is not swept into the commit.
3. Commit as the user, with a message naming the changed skills
   (`Update interview, pr-body-md`).
4. If `autopush`, push. A rejected push (the remote moved) is reported, not
   retried or rebased: fixing it is the user's call.

`--no-commit` (or `TACK_NO_COMMIT=1`) skips this for one run. `status` and
`doctor` report uncommitted and unpushed skill edits.

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
| `not-synced` | warn | A selected skill missing from a harness it targets, or a link pointing somewhere other than the manifest says. |
| `name-collision` | error | Two sources offer the same skill name. |
| `bad-skill` | warn | `SKILL.md` missing, without frontmatter, without a `description`, or with a `name` that differs from its directory. |
| `dirty-source` | info | A `path` source has uncommitted or unpushed skill edits. |
| `instructions-split` | warn | The harnesses' user instruction files don't resolve to the same content: neither is an import of or symlink to the other, and their text differs. |
| `hook-one-harness` | info | A user-level hook registered for one harness only. Installer-owned hooks are common here, so this is informational. |

### Per project

| Id | Sev. | Finding | Fix |
|---|---|---|---|
| `agents-md-missing` | error | `CLAUDE.md` has content but there is no `AGENTS.md`: Codex gets no instructions. | `agents-md` |
| `claude-md-no-import` | warn | Both files exist but `CLAUDE.md` doesn't import `AGENTS.md`: two copies that will drift. | `agents-md` |
| `instructions-untracked` | warn | One instruction file is committed and the other isn't. | — |
| `local-md-suppresses-agents` | error | A `CLAUDE.local.md` exists and neither it nor a committed `CLAUDE.md` imports `AGENTS.md`, so Claude Code reads the personal file but not the repo's `AGENTS.md`. | `agents-md` |
| `codex-skills-dir` | error | Skills under `.codex/skills`, which Codex doesn't read. | `skills-dir` |
| `claude-only-skills` | error | Real skill directories in `.claude/skills` with no `.agents/skills`: Codex can't see them. | `skills-dir` |
| `duplicate-skill-copies` | warn | Both `.claude/skills` and `.agents/skills` are real directories. | `skills-dir` |
| `hook-one-harness` | warn | A hook in one harness's project hook file with no counterpart in the other's. | `hooks` |
| `hook-mismatch` | warn | Counterpart hooks exist but differ (event, matcher, or command). | `hooks` |
| `hook-hardcoded-home` | info | A hook command contains an absolute home path; it breaks on another machine or clone. | — |

A project is any git repository found under `projects.roots` (not descending
into another repository's working tree, `node_modules`, or excluded paths).

## Scaffolding

`tack scaffold <fix> <project>` writes the files that resolve a finding and
**never commits**; it prints what it changed, and `--dry-run` prints the diff
instead.

| Fix | Does |
|---|---|
| `agents-md` | Moves `CLAUDE.md`'s content into `AGENTS.md` (`git mv` when tracked, so history follows), writes `CLAUDE.md` as `@AGENTS.md`, and removes a now-redundant `@AGENTS.md` line from `CLAUDE.local.md`. Leaves wording that addresses one agent by name for the user to review, and lists those lines. |
| `skills-dir` | Moves skills to `.agents/skills/` (`git mv`), replaces `.claude/skills` with a symlink to it, removes `.codex/skills` after confirming its contents are copies or links. |
| `hooks` | Copies a hook registration to the other harness's project hook file so both are identical. Warns when the command parses the tool payload (mentions `tool_input`, `file_path`, …), because the harnesses' payloads differ — see below. |

The durable pattern for a hook both agents run is the one the `courses`
repository uses: keep the logic in a committed script that does not depend on
the tool payload, and register an identical one-line command for each
harness.

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

## Implementation

- Python ≥ 3.11 (`tomllib`), packaged with uv and hatchling, like corral.
  Distribution name `tack-agents` (`tack` is taken on PyPI); the command is
  `tack`.
- Dependencies: `tomlkit` (round-trip manifest edits), `textual` (TUI, phase 6
  only). Git through `subprocess`, no Git library.
- CLI with `argparse`, `--json` on every command.
- Checks: `pytest`, `ruff check`, `ruff format --check`, `ty check`.
- Layout: `src/tack/` with `config.py` (manifest, lock, harnesses),
  `sources.py` (checkout, pin, fetch), `deploy.py` (links, ownership),
  `commit.py` (auto-commit), `doctor/` (one module per check group),
  `scaffold.py`, `cli.py`, and later `tui/`.
- Tests build throwaway harness directories, projects and git remotes in a
  temporary directory; nothing in the test suite touches the real home
  directory.

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
   sources with outdated counts and diffs, `doctor` findings with their fixes.
8. **Release** — PyPI `tack-agents`, Homebrew formula in `johnfoland/tap`.

## Migrating the maintainer's setup

Today (the interim from 2026-09-27), chezmoi deploys skills: `symlink_*.tmpl`
entries under `private_dot_claude/skills/` and `dot_agents/skills/`, and
`git-repo` externals cloning third-party sources into
`~/.local/share/agent-skills/`. At the end of phase 3:

1. Write `~/.config/tack/tack.toml` matching the current deployment (the
   example above), and `chezmoi add` it with the lockfile.
2. `chezmoi forget` the 32 skill symlinks and delete the three skill externals
   from `.chezmoiexternal.toml.tmpl` — *before* `sync`, so a later `chezmoi
   apply` doesn't recreate them.
3. `tack sync --adopt`: tack replaces the chezmoi-made links with its own.
4. `tack doctor` clean; then delete `~/.local/share/agent-skills/`.
5. Update the global instructions' "Global skills" section to describe tack.
6. New machines: chezmoi installs tack (Brewfile) and the manifest; a
   `run_onchange_` script keyed on `tack.lock` runs `tack sync`. That script
   is the maintainer's dotfiles, not tack.

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
- **TUI design.** Sketched in phase 7 only; to be designed when phases 2–4
  exist to build it on.

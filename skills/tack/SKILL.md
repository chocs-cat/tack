---
name: tack
description: Manage agent skills and plugins and audit agent setup with the `tack` CLI — deploy skills and selected plugins to Claude Code and Codex from one manifest (`~/.config/tack/tack.toml`) of sources (your own directories and pinned git repos), add or remove a source, see which skills are deployed where, check what changed upstream and take it, and audit projects so both agents see the same instructions (AGENTS.md / CLAUDE.md), skills (.agents/skills / .claude/skills) and hooks. Use this whenever the user wants to install, deploy, add, remove, update or sync skills or plugins, asks why a skill doesn't show up in one agent, asks what skills are installed or where one comes from, creates a new skill in a skills repo tack deploys, mentions tack.toml or tack.lock, or wants a repo checked or fixed so Claude Code and Codex read the same instructions, skills and hooks.
---

# tack

tack deploys **skills** and selected **plugins** to coding agents (a
*harness*: `claude-code` and `codex` are built in) from one manifest of
**sources**, and audits projects
so both agents see the same instructions, skills and hooks.

- A **source** is a `path` (a local directory the user edits, linked in
  place) or a `git` repository (cloned by tack, pinned to a commit).
- A **skill** is a directory holding `SKILL.md`, inside the source's `subdir`
  (`skills/` by default). Its directory name is its name.
- A **deployment** is a symlink `<harness skills dir>/<name> -> <skill dir>`:
  `~/.claude/skills/<name>` for Claude Code, `~/.agents/skills/<name>` for
  Codex.
- A **plugin** is a bundle listed in a source's catalog at
  `.claude-plugin/marketplace.json`, else `.agents/plugins/marketplace.json`.
  tack copies it into its own `tack` marketplace and installs `<name>@tack`
  through each agent's CLI. Only the built-in harnesses take plugins.

**Use the CLI with `--json`, not the TUI.** A bare `tack` opens a TUI for the
human (outside a terminal it prints the usage and exits `2`). Every command
takes `--json` and `--config DIR`. Exit codes: `0` success or nothing to
report, `1` findings or a partial failure, `2` a usage or configuration
error (nothing was changed).

## Files

| File | Where | Who writes it |
|---|---|---|
| Manifest `tack.toml` | `$TACK_CONFIG/tack.toml`, else `~/.config/tack/tack.toml` | the user, or `tack add`/`remove` |
| Lockfile `tack.lock` | beside the manifest | tack only: never edit it |
| Git checkouts | `$XDG_DATA_HOME/tack/sources/<source>/` (`~/.local/share/tack/…`) | tack only |
| Plugin marketplace | `$XDG_DATA_HOME/tack/marketplace/` | tack only |
| Ownership record | `$XDG_STATE_HOME/tack/state.json` | tack only |

After tack changes the manifest or the lockfile it runs the manifest's
`after_save` command, if there is one (often a dotfiles tool picking up the
change). Mention that when you report a change.

Never edit a skill through a git source's checkout (or a harness link that
points into one): tack owns those, and `sync` refuses to move a checkout with
local changes. The user's own skills live in `path` sources; edit them there.

## Look before acting

```sh
tack status --json            # sources (state, pin, pending edits) and skills (state per harness)
tack doctor --json            # audit the harnesses and the projects under [projects] roots
tack doctor --json ~/Code/app # audit one project (or search one directory)
tack outdated --json          # how far each git source is behind upstream
tack outdated SOURCE --diff   # the diff of the skills that changed
```

`status` lists each skill with `harnesses: {"claude-code": "linked", ...}`;
a state is `linked`, `missing`, `stale` (a link pointing elsewhere),
`conflict` (something tack doesn't own is in the way) or `collision` (two
sources offer that name). A source's `state` is `ok`, `missing`,
`not pinned`, `manifest changed`, `not checked out`, `local changes` or
`off its pin`; `uncommitted` and `unpushed` list pending edits to a path
source's skills.

`outdated` reports each git source as `current`, `behind` (with `behind`, the
`commits` and the changed `skills`), `not pinned`, `manifest changed`,
`not checked out` or `error`, with the command that fixes it in `message`.

`status`, `doctor`, and the TUI don't show plugins yet; upstream reports
still track skills. Plugin selections are edited in the manifest by hand.

## Changing things

Run every changing command with `--dry-run --json` first, show the user what
it would do, and run it for real once they agree.

```sh
tack sync                           # make every harness match the manifest and lock
tack sync --adopt                   # also take over conflicting entries
tack add https://github.com/org/skills.git --skill a b   # a git source, only skills a and b
tack add ~/Code/my-skills           # a local directory of the user's own skills
tack update SOURCE                  # move a git source's pin to the tip of its ref, then sync
tack remove SOURCE                  # its manifest table, lock entry, links and checkout
```

- **`sync`** fetches git sources at their pins (pinning a new one to its
  tip), links selected skills, and removes tack's links to skills no longer
  selected. It never replaces what it doesn't own: that is a `conflict`,
  reported with exit `1`. `--adopt` takes it over, moving a real directory to
  `$XDG_STATE_HOME/tack/adopted/…` (never deleting it); ask before using it.
  After skills it copies selected plugins into tack's marketplace, registers
  it and installs `<name>@tack` through `claude plugin` and `codex plugin`.
  Changed files refresh the copy and reinstall in Codex; Claude Code loads
  tack's copy in place. Deselected plugins are uninstalled. The `claude` or
  `codex` executable is needed on `PATH` only when a selected plugin targets
  that agent: a missing CLI or failed command is an `agent` problem (exit
  `1`), and the other plugins and skills carry on. A dry run runs only the
  agents' `list` commands and lists other commands as `would run`; JSON
  changes include their command lines and harnesses. tack never enables or
  disables a plugin, and holds an unreachable source's plugins as they are.
  A manifest without plugins runs no agent unless tack has an existing
  marketplace or recorded installs to clean up. `--adopt` doesn't apply to plugins.
- **`add`** takes a git URL or a directory. The name defaults to the repo's
  or directory's name (a repo named `skills` takes its owner's name);
  `--name`, `--ref`, `--subdir` and `--skill` override. It refuses (exit
  `2`, nothing written) a name or source already there, a source with no
  skills, and a skill another source already deploys.
- **`update`** takes in upstream changes; run `outdated SOURCE --diff` first
  and let the user see what they are taking. A source whose `git` or `ref`
  changed in the manifest shows `manifest changed` until `update` re-pins it.
- **`remove`** keeps a checkout that has local changes, and never touches a
  `path` source's directory. Its sync uninstalls that source's plugins too.

**Auto-commit.** A `path` source with `autocommit = true` has its skill edits
committed (and with `autopush = true`, pushed) by every changing command:
`sync`, `update`, `add`, `remove` and `scaffold`. Only changes inside its
skill directories are committed. If the user is mid-edit and doesn't want
that yet, pass `--no-commit` (or set `TACK_NO_COMMIT=1`). A dry run says what
it would commit and push.

### Editing the manifest by hand

`add` and `remove` cover sources; for anything else, edit `tack.toml` and
then run `tack sync --dry-run`. The source fields, for a git source and a
`path` source:

```toml
[[source]]
name = "vendor"
git = "https://github.com/org/skills.git"
ref = "main"                  # the branch or tag to follow (default: the remote's)
subdir = "skills"             # where the skill directories are
skills = ["a", { name = "b", harnesses = ["codex"] }]         # default "*": all of them
plugins = ["p", { name = "q", harnesses = ["codex"] }]       # default []: none
harnesses = ["codex"]         # limit the whole source (default: every harness)

[[source]]
name = "mine"
path = "~/Code/my-skills"     # a local directory, used as it is
autocommit = true             # commit skill edits when tack runs (path sources only)
autopush = true               # and push them
```

`plugins` is `"*"` or a list shaped like `skills`; plugin harnesses may name
only `claude-code` and `codex`, and a source selecting plugins must target at
least one of them. `skills = []` deploys no skills and needs no skills
directory, only the source root. Use it for a plugin-only source:

```toml
[[source]]
name = "plugins"
path = "~/Code/my-plugins"
skills = []
plugins = ["p"]
```

This release deploys plugins inside their source. A catalog entry for a
plugin in another repository, an unsupported entry or a broken catalog is a
`source` problem. Many catalogs bundle a whole skills repository as one
plugin; selecting its skills as well gives an agent two copies of each skill.

`[harness.<name>] ignore = [...]` names entries in a harness's skills
directory that belong to another program; tack leaves them alone and `doctor`
doesn't report them. `[projects] roots`, `exclude` and `owners` set what
`doctor` audits (a repo whose `origin` belongs to someone not in `owners` is
skipped as a clone).

### Adding a new skill

In a `path` source, create `<source dir>/<subdir>/<name>/SKILL.md` with
frontmatter giving `name` (the same as the directory) and `description`.
With `skills = "*"` (the default) the next `tack sync` links it into every
harness; with a list, add the name to it first.

## Auditing projects

`doctor` findings have a stable `id`, a `severity` (`error`, `warn`, `info`),
a `message`, the `path`, the `project` (null for global ones), and the
`scaffold` fix where one exists. It exits `1` on any error or warning.

The conventions it checks: `AGENTS.md` is the project's instructions and
`CLAUDE.md` imports it (`@AGENTS.md`); `.agents/skills` is the one real
skills directory and `.claude/skills` a symlink to it; every project hook is
registered for both harnesses (`.claude/settings.json` and
`.codex/hooks.json`).

```sh
tack scaffold agents-md ~/Code/app --dry-run   # the diff the fix would make
tack scaffold skills-dir ~/Code/app
tack scaffold hooks ~/Code/app --from claude-code   # whose hook wins a mismatch
```

`scaffold` writes, moves and removes files so the findings with that fix go
away. It moves tracked files through git and stages what it writes, but
**never commits**: review the change with the user and commit it the way the
project commits. A fix it can't apply safely changes nothing and says why
(exit `1`). After a Codex hook file changes, Codex asks the user to trust
the new hooks (`/hooks`).

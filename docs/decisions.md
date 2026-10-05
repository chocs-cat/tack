# Decisions

Settled questions, so they aren't reopened by accident. Each entry says what
was decided and why, and is cited from the docs and the code as `(DEC-n)`.

- Add new entries at the end, numbered one past the greatest existing ID,
  with the month they were settled.
- To change one, discuss it first, then edit the entry in place (don't delete
  it): say what replaced it, when, and why, and update every doc and code site
  that cites it. Never give a changed decision a new ID.

Each entry has this shape:

```markdown
## DEC-1: <short title> (YYYY-MM)

What was decided and why, in a paragraph or two: the alternatives it rules
out and the reason they lost.

*Where:* the docs that carry the rule, if any.
```

## DEC-1: Plugins deploy through one marketplace tack owns (2026-10)

Added during project P0001. tack copies each selected plugin into a local
marketplace of its own, named `tack`, registers that one marketplace with each
agent, and installs `<name>@tack`, all through the agents' own `claude plugin`
and `codex plugin` CLIs. Its catalog carries each plugin's upstream entry
(description, author, homepage, version, components) with only the `source`
replaced, so the agents show the upstream details.

Registering each source's own catalog as a marketplace was the alternative,
and the maintainer weighed it: plugin IDs would match upstream
(`skill-creator@claude-plugins-official`). It lost on three facts. Claude Code
refuses the official marketplace names from a local directory, so the most
common catalogs could only be registered as GitHub sources that each agent
clones and moves itself, out of tack's pin. An agent registers one
marketplace per name, so tack would have to take over registrations the user
made by hand, and removing a marketplace uninstalls every plugin from it,
including ones tack didn't install (principle 4). And a marketplace holding
both tack's plugins and hand-installed ones leaves no way to tell from an ID
which are tack's. Linking plugins into `~/.claude/skills` (Claude Code loads
those as `@skills-dir` plugins) works for one agent only. Editing the agents'
settings files directly breaks principle 5: both agents rewrite them. The cost
is the `@tack` suffix, and a second copy when the same plugin is also
installed from upstream, which `doctor` reports (`duplicate-plugin`).

*Where:* design.md, *Plugins* (*Deploying*, *Plugin ownership*).

## DEC-2: Plugins are copied into tack's marketplace, not linked (2026-10)

Added during project P0001. A plugin's directory in tack's marketplace is a
copy of its source (without `.git`, symlinks dereferenced), refreshed by
`sync`, rather than a symlink to the source. Both agents installed a plugin
through such a symlink in testing, but Claude Code's validator says it
dereferences only symlinks that stay inside the marketplace, so links that
leave it work by accident. A marketplace rooted at tack's data directory, so
that checkouts sit inside it, would need copies for `path` sources anyway. The
cost: an edit to a plugin in a `path` source reaches the agents at the next
`sync` rather than live; Codex needs a reinstall for every change regardless.

*Where:* design.md, *Plugins* (*Deploying*), *Harness facts tack relies on*.

## DEC-3: A source deploys no plugins unless it lists them (2026-10)

Added during project P0001. `plugins` defaults to `[]`, where `skills`
defaults to `"*"`. Catalogs list up to hundreds of plugins (Anthropic's lists
over 300), and many skill repositories already ship a catalog: a `"*"`
default would make an existing source start installing plugins the day tack
learned about them. `"*"` stays available by asking for it.

*Where:* design.md, *Source fields*, *Plugins* (*Selecting plugins*).

## DEC-4: Plugins from other repositories are pinned by their catalog (2026-10)

Added during project P0001. A catalog entry whose plugin lives in another git
repository is deployable only when it names a full commit `sha`; tack clones
that repository and checks out that commit. The sha is read from the catalog
at the source's pin, so the source's pin pins the plugin transitively and
`tack.lock` gains no entries. All 262 such entries in Anthropic's catalog name
a sha. Entries pinned only to a `ref`, and `npm`, `archive` and `command`
sources, would let a plugin change without `tack update`, against principle 3,
so tack doesn't deploy them. Pinning those in the lockfile was the
alternative; it would give a plugin a pin of its own outside its source's,
and wasn't needed for any catalog examined.

*Where:* design.md, *The lockfile*, *Plugins* (*Catalogs*, *Plugins from other
repositories*).

## DEC-5: tack never enables or disables a plugin (2026-10)

Added during project P0001. `sync` installs and uninstalls plugins but leaves
whether an installed one is on to the agent. Codex has no command to enable
or disable a plugin, and its `config.toml` is the agent's to write
(principle 5), so tack couldn't do it in both agents; doing it only in Claude
Code would make the agents behave differently. A plugin turned off in an
agent shows as `disabled` and is reported by `doctor` as `not-synced`; the
manifest says the same thing durably by limiting the plugin's `harnesses`.

*Where:* design.md, *Plugins* (*Deploying*, *Plugin states*), *`doctor`
checks*.

## DEC-6: Plugin installs are recorded in state.json version 1 (2026-10)

Added during project P0001. `state.json` gains a `plugins` key: per harness,
each plugin tack installed and a hash of the files it was installed from. The
record stays `version: 1` because the key is additive: an older tack ignores
it, and when that tack rewrites the record without it, the next `sync`
reinstalls the Codex copies, which is harmless. Bumping the version would make
an older tack refuse the record, which bites anyone who runs two tack
versions, a released one and a checkout. Comparing Codex's cache with tack's
copy instead would depend on how Codex lays out its cache, which it changes
on install (it adds converted command skills).

*Where:* design.md, *Plugins* (*Plugin ownership*).

## DEC-7: Plugin findings extend `not-synced` and `name-collision` (2026-10)

Added during project P0001. A plugin that isn't installed as the manifest
says, and two sources selecting one plugin name, are reported under the
existing `not-synced` and `name-collision` ids rather than new plugin ids:
they are the same failures as for skills, fixed the same way (`sync`, or
deselecting one), and a script watching those ids keeps catching them. What
has no skill counterpart gets new ids: `unmanaged-plugin` (info, since
agents ship and sync plugins of their own; `ignore_marketplaces` quiets
those) and `duplicate-plugin` (warn).

*Where:* design.md, *`doctor` checks*, *Harness fields*.

## DEC-8: Only the built-in harnesses take plugins (2026-10)

Added during project P0001. tack deploys plugins only to `claude-code` and
`codex`, running `claude` and `codex` from `PATH`. A harness defined in the
manifest is a set of paths, and plugins are installed by commands whose
behavior tack has to know, so there is no field to give one a plugin CLI.
Overriding a built-in harness's paths doesn't change where its CLI keeps
plugins. A plugin's `harnesses` naming any other harness is a configuration
error.

*Where:* design.md, *Harness fields*, *Plugins* (*Selecting plugins*).

## DEC-9: Tests hide the real agents by mirroring their PATH directories (2026-10)

Added during P0001-C01-c. The test suite's PATH has each directory holding a
real `claude` or `codex` replaced by a mirror of it: a directory of links to
everything in it but the agents, in the same place on PATH. The brief had
those directories dropped, with `git` linked back if that took it away. On a
machine with the agents installed by Homebrew, that drops every other program
in Homebrew's `bin`, and a version manager's shim that looks further down
PATH for the real program (asdf's `uv`, which the formula test runs) then
fails. Linking back only what PATH finds first misses those lookups too.
The mirror keeps every other program where it was and still leaves no real
agent to find. It is built once per test session, since a directory such as
Homebrew's `bin` holds hundreds of programs.

*Where:* design.md, *Implementation*; `tests/standin.py` (`isolate`).

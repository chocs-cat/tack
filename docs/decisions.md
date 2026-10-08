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

## DEC-10: A source that selects plugins must target a harness that takes them (2026-10)

Added in the review of P0001-C01. A source that selects plugins (`plugins =
"*"` or a non-empty list) whose `harnesses` name neither `claude-code` nor
`codex` is a configuration error, as a plugin's own `harnesses` naming
another harness already is (DEC-8). The alternative was to plan such
plugins for no harness and say nothing: the manifest would ask for plugins
that `sync` never installs and `status` never shows, with nothing to say
why. `plugins = []` is fine anywhere.

*Where:* design.md, *Plugins* (*Selecting plugins*).

## DEC-11: Plugin names collide across harnesses (2026-10)

Added in the review of P0001-C02. Two sources selecting the same plugin name
collide whatever harnesses each targets: tack deploys neither in any
harness, and the collision is reported for every harness either targets.
Skills collide per harness because each harness has a skills directory of
its own, so two sources can fill the same name in two of them. Plugins have
one directory for every harness, tack's marketplace (DEC-1), which holds one
`plugins/<name>/` and one catalog entry per name, and both agents install
`<name>@tack` from it, so one source's `x` for Claude Code and another's
for Codex can't both be there. The alternative, letting one of them win in
both harnesses, would install a plugin into a harness the manifest didn't
ask for, with no rule to say which.

*Where:* design.md, *Plugins* (*Selecting plugins*, *Plugin states*),
*Adding and removing sources*, *`doctor` checks*.

## DEC-12: A held source's plugins are left as they are (2026-10)

Added in the review of P0001-C02. A source `sync` holds (a missing `path`, a
failed fetch, a refused checkout), and a source whose catalog is broken,
keep their plugins exactly as they are: `sync` copies, installs, reinstalls
and uninstalls none of the plugins the record says came from them, and
keeps their copies and their entries in tack's catalog. A plugin whose copy
fails is kept the same way. This is what a held source's skills get, their
links left alone. The plan selects nothing for such a source, so the
alternative, treating its plugins as deselected, would uninstall them over
an unreachable remote or a typo in an upstream catalog, and install them
again once it is fixed. The record names each plugin's source, which is how
`sync` tells which installed plugins a held source keeps.

*Clarified in the review of P0001-C03 (2026-10):* it covers the plugins such
a source selects as well as those the record lists from it, since a held
source's newly selected skills aren't linked either, and a source whose root
isn't there (a git source a dry run hasn't cloned) keeps its plugins too, so
a dry run doesn't list uninstalls the real run wouldn't make.

*Where:* design.md, *Plugins* (*Deploying*, *Plugin ownership*).

## DEC-13: Claude Code keeps tack's marketplace while a kept plugin is installed (2026-10)

Added during P0001-C03-c. `sync` doesn't unregister tack's marketplace from
Claude Code while a plugin it keeps as it is (DEC-12: a collided name, a
plugin from another repository, a plugin whose copy failed) is installed
there, even when no selected plugin targets Claude Code any more. Claude
Code's `marketplace remove` uninstalls the marketplace's plugins, so step 5
would uninstall a plugin that no step may touch: `x` installed in both
harnesses and then selected by two sources for Codex only is a collision
whose Claude Code install DEC-11 leaves alone, and unregistering would take
it away. Codex's `marketplace remove` leaves plugins installed, so Codex
needs no such rule. The marketplace is unregistered at the next `sync` that
keeps nothing installed there.

*Where:* design.md, *Plugins* (*Deploying*, step 5).

## DEC-14: Recheck recorded Codex installs after registering (2026-10)

Added during P0001-C04-b. When `sync` registers tack's marketplace in Codex
and the record lists plugins there, it reads Codex's inventory again before
installing: Codex's list while unregistered hides even installed plugins.
Using that first list would reinstall unchanged plugins on a held source's
recovery, contrary to the brief; trusting the record alone would miss a
plugin uninstalled by hand while the marketplace was unregistered. The
second inventory distinguishes those cases with the existing CLI contract.
A dry run cannot register to reveal them, so it assumes recorded plugins
are installed; the next real run checks them.

*Where:* design.md, *Plugins* (*Deploying*, step 2).

## DEC-15: A plugin is in the first state that applies (2026-10)

Added at the cut of P0001-C05. A plugin's states can overlap in a harness: a
collided name in a harness whose CLI isn't installed, a disabled plugin whose
copy is out of date. `status`, the TUI's cell and `doctor`'s `not-synced`
each take one state, so the first that applies wins: `collision`,
`unavailable`, `conflict`, `missing`, `disabled`, `stale`, `installed`. A
manifest error comes first, since no agent fixes it; then what stops tack
reading the harness at all (with no CLI it can't see a conflict either);
then whether the plugin is installed, and only then how fresh it is.
`disabled` comes before `stale` because a disabled plugin loads in neither
case, and turning it back on is the user's choice (DEC-5), while `sync`
refreshes a stale copy unasked. Listing every state that applies was the
alternative; none of the three readers has room for more than one.

*Where:* design.md, *Plugins* (*Plugin states*).

## DEC-16: A harness whose plugin list fails is `unavailable` (2026-10)

Added at the cut of P0001-C05. `unavailable` meant a CLI that isn't on
`PATH`. One that is there but whose `plugin list` or `plugin marketplace
list` fails (a broken install, output tack can't read) leaves tack just as
unable to say what the harness has, and `sync` stops that harness's steps
the same way. A state of its own would be one more for the TUI's sort and
`doctor`'s mapping to place, for a case they treat alike; `status` has no
problems list to carry the agent's message, which `sync` reports as an
`agent` problem.

*Where:* design.md, *Plugins* (*Plugin states*), *`doctor` checks*.

## DEC-17: `status` reads a source's plugins as they are on disk (2026-10)

Added in the review of P0001-C05 (#38). A plugin's `stale` and `missing`
compare tack's copy, the record and the agents with the plugin's files as its
source has them now, so they are what `sync` would copy, reinstall and
install for a source whose own state is `ok`. For any other, `sync` first
holds the source (DEC-12) or checks out its pin, and the plugin can read
`stale` or `missing` where `sync` then changes nothing: the source's state,
on its own line, says what `sync` does first, as it does for a held
source's skills, which read `missing` too. Reading a git source's plugins
at its pin, or giving a held source's plugins a state of their own, was the
alternative: neither helps a held `path` source, and the second is one more
state for the TUI and `doctor` to place for a case the source already
reports.

*Where:* design.md, *Plugins* (*Plugin states*).

## DEC-18: `doctor` lists the plugins of each agent that is installed (2026-10)

Added at the cut of P0001-C06, with the maintainer. `doctor`'s plugin checks
run each built-in harness's two `list` commands whenever its CLI is on
`PATH` and the global checks run, whether or not the manifest selects
plugins. `unmanaged-plugin` exists to find plugins installed by hand, and a
user who hasn't selected any plugin yet is the one most likely to have
them, as `unmanaged-skill` is reported without any skill selected. So "a
manifest without plugins runs no agent" (DEC-3) holds for `sync` and
`status`, which change or show only what tack deploys; `doctor`, an audit,
runs the agents that are there. A missing CLI is still no finding unless a
selected plugin targets that harness, and `--projects-only` runs no agent.
Running them only when `sync` would (a selection, a record entry or tack's
marketplace) was the alternative: it would leave hand-installed plugins
unreported until the user adopted plugins in tack, at the cost of two
`list` commands per agent on every `doctor` run.

*Where:* design.md, *`doctor` checks*.

## DEC-19: `doctor` reports every plugin problem a `sync` would (2026-10)

Added in the review of P0001-C06. Each plugin problem a `sync` dry run
reports has a `doctor` finding, for a source whose state is `ok` (DEC-17): a
`collision` is `name-collision`; a `source` problem (a broken catalog, a
plugin tack can't deploy or from another repository, a plugin whose files
can't be read so that its copy would fail) is the source's `not-synced`; an
`agent` problem (a missing CLI a selected plugin's harness needs, a `list`
that fails in a harness `sync` runs) and a `conflict` (a foreign `tack` where
a selected plugin targets the harness or the record lists one there) are the
harness's `not-synced`, even when it names no plugin of its own. The cut of
P0001-C06 had built these findings from the plugins' states instead, so a
plugin whose directory is gone read `installed` and had no finding while
every `sync` reported it and exited `1`, and a harness only the record
involved had no finding for a foreign `tack` or a failing `list`. Building
them from the states alone was the alternative: it leaves `doctor` quiet
about a problem that fails `sync` every run, which is what an audit is for.
A plugin is still named once: one with a source finding gets no per-plugin
state finding, and a harness's finding names only the plugins that have no
finding of their own.

*Where:* design.md, *`doctor` checks*.

## DEC-20: `outdated` doesn't compare plugins across a broken catalog (2026-10)

Added at the cut of P0001-C07. `outdated` reads a source's catalog at the pin
and at the tip from git. When either is broken (*Catalogs*), it reports no
plugin changes for that source and says why in the source's
`plugins_error`, with the catalog's error; its skills are compared as
before. Reading a broken catalog as one with no plugins was the alternative:
every selected plugin would show as added or removed, though `sync` keeps a
broken catalog's plugins exactly as they are (DEC-12), so neither `update`
nor the next `sync` would remove or add any of them. Inside the range, a
catalog that can't be read at a commit counts as one with no entries, so the
commit that breaks it and the one that fixes it each touch the plugins whose
entries they hide or restore.

*Where:* design.md, *Plugins* (*Tracking plugins upstream*).

## DEC-21: A plugin's clone is kept as a source's checkout is (2026-10)

Added at the cut of P0001-C10. A plugin from another repository is a full
clone of that repository under `plugins/<source>/<plugin>/`, brought to the
catalog's commit by the code that brings a git source's checkout to its pin:
cloned when it isn't there, fetched only when it lacks the commit, refused
with local changes or with something else in the way, its `origin`
following the entry's URL. A commit no branch or tag reaches is fetched by
its id, since a catalog may pin a commit off the default branch. `sync`
deletes no clone, as it deletes no checkout; `remove` deletes a source's
clones with its checkout. A plugin whose clone isn't at its commit reads its
state with no directory to compare, as a source that isn't `ok` explains its
plugins' states (DEC-17). A shallow fetch of the one commit was the
alternative: smaller for a large repository, but a second implementation of
fetching and checking out beside the checkouts', and `outdated --diff`
needs the pin's commit and the tip's in one repository anyway. Deleting a
deselected plugin's clone, as its copy is deleted, was the other: no agent
reads a clone (they load tack's copy), so keeping it costs only disk, and a
plugin selected again comes back without a fetch.

*Where:* design.md, *Plugins* (*Catalogs*, *Plugins from other
repositories*, *Plugin states*), *Adding and removing sources*.

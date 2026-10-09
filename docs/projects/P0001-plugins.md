# Project P0001 — Plugins for Claude Code and Codex

- **State:** active
- **Created:** 2026-10-05
- **Ready:** 2026-10-05
- **Completed:** —
- **Decisions:** DEC-1 – DEC-23

## 1. Problem and outcome

tack deploys skills from one manifest of sources, pins git sources in
`tack.lock`, and tracks upstream with `outdated` and `update`. Both agents
also install *plugins*, bundles that can carry skills, commands, agents, hooks
and MCP servers, and nothing keeps those the same between the two agents or
across machines: each is installed by hand, per agent, from marketplaces each
agent clones and moves on its own schedule
([#22](https://github.com/chocs-cat/tack/issues/22)).

The outcome: plugins get the treatment skills get. A source's catalog (its
marketplace file) offers plugins; the manifest selects them; `sync` installs
the same plugin directory, pinned with its source, into Claude Code and Codex
through their own CLIs; `status` and a TUI Plugins tab show them; `outdated`
and `update` track upstream, versions included; `doctor` reports plugins that
drift or that something other than tack installed. A new machine gets the
same plugins from the manifest, the lock and `tack sync`.

This is one project because every part hangs on one mechanism, tack's own
marketplace (DEC-1), whose ownership, state and pinning rules each command has
to share.

## 2. Boundaries

In scope: user-scope plugins in the built-in harnesses; catalogs in Claude
Code's and Codex's formats; plugins inside a source and plugins in other git
repositories pinned by a commit in the catalog; `sync`, `status`, `outdated`,
`update`, `add`, `remove`, `doctor`, the TUI and the agent skill.

Not in scope:

- **Project-scoped plugins**: a repository's `.claude/settings.json`
  `enabledPlugins` or `.codex/config.toml` plugins are neither deployed nor
  audited ([#24](https://github.com/chocs-cat/tack/issues/24)).
- **Translating plugins** between formats, or warning about parts one agent
  ignores: an open question in design.md.
- **Catalog entries tack can't pin**: `npm`, `archive`, `command`, and git
  entries without a commit (DEC-4).
- **Enabling and disabling** plugins (DEC-5), setting their options
  (`claude plugin configure`), and resolving their dependencies.
- **Adopting** plugins installed by hand: `doctor` reports them
  (`unmanaged-plugin`, `duplicate-plugin`) and the user moves them.
- **Plugins for harnesses defined in the manifest** (DEC-8).
- **Settings screen**: plugin selections are edited by hand, like skills.
- **Skills deployed twice**, as skills and inside a whole-repository plugin:
  documented, not checked
  ([#25](https://github.com/chocs-cat/tack/issues/25)).

Compatibility: a manifest without `plugins` behaves exactly as before in
`sync` and `status`, and runs no agent CLI there (DEC-3); `doctor` lists
the plugins of each agent that is installed, to report hand-installed ones
(DEC-18). `state.json` stays version 1, so an older tack
still reads what a newer one writes (DEC-6). `tack.lock` is unchanged
(DEC-4). The `not-synced` and `name-collision` ids keep their meaning for
skills and gain plugin cases (DEC-7).

## 3. Design questions

| Question | Resolution | Authority / decision | State |
|---|---|---|---|
| How does a plugin get into each agent? | One local marketplace tack owns, named `tack`, registered and installed through `claude plugin` and `codex plugin`; never by editing the agents' files. Its catalog carries each upstream entry with only `source` replaced. | design.md *Plugins › Deploying*; DEC-1 | resolved |
| Copy plugins into it, or link them? | Copy (no `.git`, symlinks dereferenced), refreshed by `sync`. | *Deploying*; DEC-2 | resolved |
| Where does a source declare its plugins? | A catalog at its root: `.claude-plugin/marketplace.json`, else `.agents/plugins/marketplace.json`. No catalog, no plugins. | *Catalogs* | resolved |
| Which catalog entries can tack deploy? | Plugins inside the source (relative paths, Codex `local`), and git entries (`url`, `github`, `git-subdir`) naming a full commit. Others are reported and refused. | *Catalogs*; DEC-4 | resolved |
| How are plugins selected, and what is the default? | A `plugins` source field shaped like `skills`; default `[]`. | *Source fields*, *Selecting plugins*; DEC-3 | resolved |
| Which harnesses take plugins, and how does tack find their CLIs? | `claude-code` and `codex` only, running `claude` and `codex` from `PATH`. | *Harness fields*, *Selecting plugins*; DEC-8 | resolved |
| Can a source supply only plugins? | Yes: `skills = []` needs no skills directory. | *Source fields* | resolved |
| What does "the same plugin in both agents" mean? | The same directory installed in each targeted agent; each loads the parts it supports. No translation. | *Non-goals*; *Open questions* | resolved |
| How does a change reach each agent? | Claude Code loads in place from tack's marketplace; Codex is reinstalled (`codex plugin add`) when the plugin's files changed since tack installed it. | *Deploying* step 3; *Harness facts* | resolved |
| Where does tack record what it installed? | `state.json`, a `plugins` key per harness with a hash of the installed files, still version 1. | *Plugin ownership*; DEC-6 | resolved |
| What is tack's, and what is a conflict? | `@tack` plugins from tack's own marketplace directory; a foreign marketplace named `tack` blocks plugins in that harness. | *Plugin ownership* | resolved |
| What if the user turns a tack plugin off in an agent? | Left off; shown as `disabled`, reported as `not-synced`. | *Deploying*, *Plugin states*; DEC-5 | resolved |
| How do pins and upstream tracking map onto plugins and their versions? | No lock entries: plugins pin with their source, and other-repository plugins through the catalog's commit. `outdated` reports changed plugins with versions at pin and tip. | *The lockfile*, *Tracking plugins upstream*; DEC-4 | resolved |
| In what order are plugins removed? | Uninstall each plugin, then unregister the marketplace (Codex keeps a removed marketplace's plugins). | *Deploying* steps 4–5; *Harness facts* | resolved |
| What if an agent isn't installed? | No agent CLI runs without plugins; a targeted harness with no CLI is an `agent` problem, and its skills still deploy. | *Deploying* | resolved |
| Which plugin states exist? | `installed`, `missing`, `stale`, `disabled`, `conflict`, `collision`, `unavailable`. | *Plugin states* | resolved |
| What does `doctor` report? | Plugin cases of `not-synced` and `name-collision`; new `unmanaged-plugin` (info) and `duplicate-plugin` (warn); `ignore_marketplaces` with built-in defaults. | *`doctor` checks*, *Harness fields*; DEC-7 | resolved |
| What do `sync`, `status` and `outdated` emit? | `sync` changes `copy`, `register`, `install`, `reinstall`, `uninstall`, `unregister` and problems of kind `agent`; `status --json` `plugins`; `outdated --json` per-source and per-commit `plugins`. | *Deploying*, *Plugin states*, *Tracking plugins upstream* | resolved |
| How do `add` and `remove` handle plugins? | `add --plugin P…` (writing `skills = []` without `--skill`), with refusals; `remove` uninstalls through `sync` and deletes plugin clones. | *Adding and removing sources* | resolved |
| Where do plugins appear in the TUI? | A Plugins tab after Skills; tabs keyed `1`–`4`; grouping and sorting like Skills. | *The TUI* | resolved |
| How do tests avoid running a real agent? | Stand-in `claude` and `codex` executables first on `PATH`. | *Implementation* | resolved |

## 4. Authority changes

| Document and section | Change | Why this is the durable home |
|---|---|---|
| design.md, header | Notes P0001 and the *(P0001)* mark for unreleased text. | Readers of the spec need to know what isn't built yet. |
| design.md, *What tack is*, *Non-goals* | Plugins as part of deploying; no translation; MCP only through plugins. | The scope statement. |
| design.md, *Concepts*, *Files and locations* | Plugin, tack's marketplace; the marketplace and clone directories. | Where every term and path is defined. |
| design.md, *The manifest* | Example source; `plugins` and `skills = []` in *Source fields*; `ignore_marketplaces` and built-in-only plugins in *Harness fields*. | The manifest's contract. |
| design.md, *The lockfile* | Plugins add no entries. | The lock's contract. |
| design.md, *Commands*, *Adding and removing sources* | `--plugin`; plugin refusals; `remove` uninstalls and deletes clones. | Command behavior lives there. |
| design.md, *Plugins* (new) | Catalogs, selection, deploying, ownership, states, other repositories, tracking. | One cohesive subject the other sections point to. |
| design.md, *`doctor` checks* | `not-synced`, `name-collision` extended; `unmanaged-plugin`, `duplicate-plugin`; how plugin checks read the agents. | The findings' contract. |
| design.md, *The TUI* | Plugins tab, tab keys, Sources detail, Settings. | The TUI's spec. |
| design.md, *The agent skill* | Covers plugins. | What the skill teaches. |
| design.md, *Harness facts tack relies on* | Plugin facts verified against Claude Code 2.1.289 and codex-cli 0.157.1. | Required for any new harness assumption. |
| design.md, *Implementation* | `catalog.py`, `plugins.py`, `agents.py`; stand-in CLIs in tests. | Layout and test rules. |
| design.md, *Open questions* | MCP through plugins; plugins one agent can't fully load. | Where open questions live. |
| decisions.md | DEC-1 – DEC-8. | Choices the spec left open. |
| design.md, *Plugins* › *Catalogs* (P0001-C01 cut) | How both formats' paths, git sources and `sha` are read; broken catalogs, ignored and duplicate entries; directory existence checked at copy time; `version`'s three `plugin.json` locations. | The rules an executor would otherwise invent; the agents' docs, verified 2026-10-05. |
| design.md, *Plugins* › *Deploying* (P0001-C01 cut) | `.git` at any depth, loops and missing directories fail a plugin; copies swapped in; tack's catalog's exact shape; CLIs run with stdin closed, in a temporary directory when the data directory is missing; what counts as a failure and the agent's message. | Where `sync`'s mechanics live. |
| design.md, *Plugins* › *Plugin ownership*, *Plugin states* (P0001-C01 cut) | The plugin hash; Codex installs known from the record; `version` points at *Catalogs*. | Ownership and staleness rules. |
| design.md, *Harness facts tack relies on* (P0001-C01 cut) | The agents' `--json` output and failure forms, stdin, Codex's `list` hiding orphaned plugins, Claude Code's `uninstall` without the entry. | Required for any new harness assumption; verified 2026-10-05 against Claude Code 2.1.289 and codex-cli 0.157.1. |
| design.md, *Implementation* (P0001-C01 cut) | Stand-ins follow *Harness facts*; no real agent left on `PATH`. | The test rules. |
| design.md, *Harness facts tack relies on* (P0001-C01 execution) | Claude Code's `marketplace add` repoints a same-named marketplace; Codex refuses one, and reads its own catalog first; installing from an unregistered marketplace fails in both. | Found by probing the real agents for the stand-ins. |
| design.md, *Implementation*; decisions.md (P0001-C01 execution) | Other `PATH` directories holding an agent are mirrored without it (DEC-9). | The brief's rule broke version-manager shims. |
| design.md, *Plugin ownership*, *Deploying* step 1 (P0001-C01 review) | A foreign `tack` stops every step in that harness, registering included. | Registering would repoint the user's marketplace in Claude Code. |
| design.md, *Selecting plugins*; decisions.md (P0001-C01 review) | A source selecting plugins must target `claude-code` or `codex` (DEC-10); which plugins a source selects, and what a missing catalog, a missing root and a broken catalog mean. | The rules P0001-C02's plan implements. |
| design.md, *Selecting plugins*, *Plugin states*, *Adding and removing sources*, *`doctor` checks*; decisions.md (P0001-C02 review) | Plugin names collide across harnesses (DEC-11); a name a catalog lists twice is one plugin. | tack's one marketplace holds one copy per name; the per-harness rule was copied from skills (brief-checklist §2). |
| design.md, *Deploying*, *Plugin ownership*; decisions.md (P0001-C02 review) | Which harnesses run a CLI and when a missing one is a problem; what "installed" means; step 4's candidates and when a copy is deleted; when the directory goes; change details and problem kinds; a foreign `tack` reported only where it matters; the record's `plugins` shape with each plugin's source; held sources, broken catalogs and failed copies keep their plugins (DEC-12). | The D2 note "to pin at the cut", and what P0001-C03's `sync` would otherwise invent. |
| design.md, *Harness facts tack relies on* (P0001-C02 review) | No `codex plugin` command takes `--scope`. | Checked against codex-cli 0.157.1's `--help`; the stand-in enforces it. |
| design.md, *Deploying* step 5; decisions.md (P0001-C03 execution) | Claude Code keeps tack's marketplace registered while a kept plugin is installed there (DEC-13). | Its `marketplace remove` uninstalls the marketplace's plugins; the brief's step 5 would have uninstalled kept ones (brief-checklist §3). |
| design.md, *Deploying*, *Plugin ownership*, *Source fields*; decisions.md (P0001-C03 review) | tack's marketplace is brought up to date whenever a plugin is selected or it exists (#33); which sources keep their plugins (held, no root, broken catalog) and which plugins (recorded and selected), named *kept*; DEC-12 clarified to match; the record's source follows the manifest; Claude Code's recorded hash; a `skills = []` source is missing only without its root. | What P0001-C04 would otherwise invent, and the shapes C03's executor chose where the docs were silent. |
| design.md, *Deploying* step 2; decisions.md (P0001-C04 execution) | Codex's inventory is read again after registering when the record lists plugins there; a dry run assumes them installed (DEC-14). | Codex hides an unregistered marketplace's plugins, so the brief's recovery would have reinstalled them (brief-checklist §4). |
| design.md, header, *Deploying*, *Harness facts tack relies on* (P0001-C04 review) | What the *(P0001)* mark means once part is built; a `path` source is held when missing as *Source fields* says; Codex lists a kept plugin again once its marketplace is registered again, checked against codex-cli 0.160.1. | The header and the held-source list had gone stale with C04; DEC-14's assumption needed the real agent. |
| design.md, *Plugin states*; decisions.md (P0001-C05 cut) | The order states apply in (DEC-15); a failing `list` is `unavailable` (DEC-16); what *installed* and `stale` read, matching `sync`; when `status` runs the agents; the `--json` objects' order, `version`'s source, and `path` null without a copy. | What P0001-C05's executor would otherwise invent. |
| design.md, *Plugin states*; decisions.md (P0001-C05 review) | Plugins are read from their source as it is now; `stale` and `missing` match `sync` for a source whose state is `ok` (DEC-17, #38). | The cut's "exactly what `sync` would copy" ignored the holds and checkouts `sync` does first (brief-checklist §5). |
| design.md, *`doctor` checks*, *Harness fields*; decisions.md (P0001-C06 cut) | `doctor` lists each installed agent's plugins whatever the manifest selects (DEC-18, with the maintainer); each plugin finding's cases, grouping, exclusions and location; `ignore_marketplaces` a list of names, an error on a manifest-defined harness. | What P0001-C06's executor would otherwise invent. |
| design.md, *`doctor` checks* (P0001-C06 execution) | *Leftovers* keeps a plugin whose files can't be read, and there are none in a harness `sync` doesn't run. | The bullet dropped members of *Deploying*'s kept plugins (brief-checklist §6). |
| design.md, *`doctor` checks*; decisions.md (P0001-C06 review) | Every plugin problem a `sync` dry run reports has a `doctor` finding: a plugin whose files can't be read, and a harness's `unavailable` and `conflict` wherever `sync` reports them (DEC-19, #44). | The cut built these from the plugins' states and missed problems `sync` reports every run (brief-checklist §6). |
| design.md, *Tracking plugins upstream*; decisions.md (P0001-C07 cut) | How `outdated` reads catalogs and versions at a commit, a broken catalog at either end (DEC-20), which plugins are selected, what *modified* means for each kind, which commits touch a plugin, the `--diff` entry diff's format, `plugins_error` and the text lines. | What P0001-C07's executor would otherwise invent. |
| design.md, *Tracking plugins upstream* (P0001-C07 review) | A catalog symlinked out of the repository is broken at that commit; a source whose plugins weren't compared says "no selected skill changed". | The executor's choices where the section was silent. |
| design.md, *Tracking upstream*, *Auto-commit*, *Adding and removing sources* (P0001-C08 cut) | A renamed skill is removed and added, and any file name counts (#46, #47); `--plugin` takes names, written after `skills`; each plugin refusal and its reason, a broken catalog's included, and a plugin whose files can't be read; which plugins the no-skills refusal lists; a dry run checks no git source's plugins. | What P0001-C08's executor would otherwise invent; the unreadable plugin is the member `sync`'s problems had that the refusals' list lacked (brief-checklist §6). |
| design.md, *Adding and removing sources*, *TUI fields*, *The TUI* (P0001-C08 review, P0001-C09 cut) | A git source's dry run checks neither its skills nor its plugins, whatever tack's checkout holds (#49); the Plugins tab's columns, its own sort, grouping and folds, which sources get a group row and its summary, the state colors, the empty tab, a plugin's detail (pin, copy, version, description and `sync`'s problem, read as the states are), the Sources detail's plugins, and one read of each agent per refresh; `group_by_source` sets both tabs. | What P0001-C09's executor would otherwise invent; the dry run matches the sentence that already said it couldn't check. |
| design.md, *Catalogs*, *Plugins from other repositories*, *Plugin states*, *Adding and removing sources*, *Implementation*; decisions.md (P0001-C10 cut) | A catalog `url` is a git URL as `add` reads one, and a `git-subdir` `path` of `.` the whole repository (#29); a clone is the whole repository, kept by the checkouts' code: its five states, cloning, fetching (by id as a last resort), refusals and their messages, `origin` following the entry, the dry run, no deletion by `sync`, `remove` deleting clones one by one; a plugin's files read only from an `ok` clone; `add` checks such a plugin by its entry (DEC-21). | What D8's executors would otherwise invent; the section was one paragraph. |
| design.md, *The lockfile*, *Deploying*, *Plugin states*, *Plugins from other repositories*, *`doctor` checks*, *The TUI*; decisions.md (P0001-C10 review, P0001-C11 cut) | A checkout or clone `sync` makes and can't bring to its commit is deleted (DEC-22, #54); which clones `sync` brings, when, in what order, and its problems' source and path; a copy taken from a clone; a clone that fails among `sync`'s problems and the kept plugins; `version` from an `ok` clone; `doctor`'s source finding for a clone `in the way` or with `local changes`, state findings for one not `ok`, and no leftover for it; the TUI's problems; `add` ignoring a clone already there. The "until D8" paragraph goes. | What P0001-C11's executor would otherwise invent; the passages the C10 cut said this cut rewrites. |
| design.md, *Plugin states*, *The TUI*, *Tracking plugins upstream*; decisions.md (P0001-C11 review, P0001-C12 cut) | `status --json`'s `repository` (URL, path, commit, clone, the clone's state as the plan read it); the Plugins tab's detail lines for it; `outdated --diff` between a plugin's two commits, fetched into its clone, never creating or moving one, with a line saying why when there is none (DEC-23). | What P0001-C12's executor would otherwise invent; C10's cut left these "pinned at their own cut". |

## 5. Delivery plan

These are ordered outcomes, not pre-sized chunks. `/relay-next` may keep one
item in one chunk or split it where reviewability requires.

Throughout: the stand-in `claude` and `codex` executables come with the first
item that runs an agent CLI (D2), and no test runs a real one. A chunk that
adds or changes a command, flag, `--json` shape or manifest field updates
`README.md` and `skills/tack/SKILL.md` with it. No chunk may accept the
`plugins` field before `sync` deploys it: D1 lands in the same chunk as D2,
or its chunk leaves the field rejected as an unknown key.

### D1 — Catalogs and plugin selection

**Build:** the `plugins` source field (`"*"`, names, `{ name, harnesses }`
tables; a plugin's harnesses within the source's and among the built-in
ones), and `skills = []` needing no skills directory (*Source fields*,
*Selecting plugins*; DEC-3, DEC-8, DEC-10). `ignore_marketplaces` moved to
D4 at the P0001-C01 review: `doctor` is its only reader, and accepting it
sooner would accept a field that does nothing. `catalog.py`
reads both catalog formats and classifies each entry: in the source (with its
directory), in another repository (URL, optional path, commit), or not
deployable (with the reason); and gives each plugin's version (*Catalogs*;
DEC-4). `plugins.py` plans the selected plugins per harness, the listed ones
the catalog lacks, the undeployable ones, and collisions, beside the skills
plan.

**Depends on:** none.

**Done when:** config tests cover each field rule and error (a manifest
harness in a plugin's `harnesses`, a harness outside the source's, a name
listed twice, a bad type); catalog tests cover both formats and each entry
kind (`"./plugins/x"`, `"./"`, `"."`, a bare name under
`metadata.pluginRoot`, Codex `local`, a path leaving the source, `url`,
`github` and `git-subdir` with and without a 40-character `sha`, `npm`,
`archive`, `command`), the catalog precedence, and version from `plugin.json`
over the entry; plan tests cover `"*"`, a list, per-plugin harnesses,
collisions and missing names; a `skills = []` source with no skills directory
isn't reported as missing, while one with `skills = "*"` still is.

### D2 — `sync` deploys plugins

**Build:** tack's marketplace (copies without `.git`, symlinks dereferenced,
the catalog of upstream entries with `source` replaced and `headers` and
`headersHelper` dropped); `agents.py` running both CLIs with `--json` from
tack's data directory; `sync`'s five steps per harness, with the change
actions and `agent` problems; ownership and the foreign-`tack` conflict; the
`plugins` key in `state.json` and Codex reinstalls on a changed hash; no
agent CLI run without plugins; `--dry-run` listing commands; `remove`
uninstalling through `sync` (*Deploying*, *Plugin ownership*, *Files and
locations*; DEC-1, DEC-2, DEC-5, DEC-6). The stand-in CLIs in
`tests/conftest.py`. The plugin-only source example in *Selecting plugins*
moves into the manifest example under *The manifest*, and
`test_design_example_manifest_parses` asserts it.

Notes from the P0001-C01 review: with no plugin selected, `sync` removes
tack's marketplace (step 5) and must not call `plugins.update`, which would
create it. What a held source or a broken catalog does to its plugins was
pinned at the P0001-C02 review (DEC-12).

**Depends on:** D1.

**Done when:** tests against the stand-ins show, per harness, the exact
commands in order (register before install; uninstall before unregister); a
second `sync` runs no install; a changed plugin file brings a Codex reinstall
and no Claude Code command; deselecting uninstalls and drops the copy; the
last plugin gone unregisters both and deletes the directory; a foreign `tack`
marketplace is a conflict with no installs in that harness and exit `1`; a
missing CLI is an `agent` problem while skills still link; a failed install
reports the agent's message and the other plugins still install; a dry run
runs no command and writes nothing; a manifest without plugins makes no CLI
call; no enable or disable command is ever issued; a symlink is copied as its
target and a dangling one fails only that plugin; the catalog keeps upstream
fields; `state.json` stays version 1 and a record without `plugins` loads.
`README.md` and the agent skill describe `plugins` and what `sync` does.

### D3 — `status` reports plugins

**Build:** each selected plugin's state in each harness it targets, read
through the agents' `list --json` commands, in the text output and `status
--json` (*Plugin states*).

**Depends on:** D2.

**Done when:** stand-in fixtures produce every state (`installed`,
`missing`, `stale` from tack's copy and from a Codex hash, `disabled`,
`conflict`, `collision`, `unavailable`); a test pins the `--json` shape
(`plugins` objects; each source's `plugins`); `status` still exits `0`.

### D4 — `doctor` audits plugins

**Build:** the plugin cases of `not-synced` and `name-collision`,
`unmanaged-plugin`, `duplicate-plugin`, and the `ignore_marketplaces`
harness field with its built-in defaults, which this item accepts in the
manifest (*`doctor` checks*, *Harness fields*; DEC-7).

**Depends on:** D3.

**Done when:** each finding comes from stand-in fixtures with its severity
and location; a manifest without plugins still reports `unmanaged-plugin`
when an agent is installed (DEC-18); plugins from built-in or listed
`ignore_marketplaces` aren't reported; project-scope installs aren't reported; a harness without a CLI
yields nothing unless a selected plugin targets it; `unmanaged-plugin` alone
exits `0`, `duplicate-plugin` exits `1`.

### D5 — `outdated` and `update` track plugins

**Build:** plugin changes between pin and tip (modified by files or entry,
added, removed, `"*"` selecting both sides), versions at each end, commits
touching selected plugins, `--diff`, and the `--json` additions; `update`
followed by Codex reinstalls (*Tracking plugins upstream*).

**Depends on:** D2.

**Done when:** tests on local git remotes show a file change under a
plugin's directory and an entry-only change as *modified*, a new plugin under
`"*"` as *added*, a dropped one as *removed*, unselected plugins ignored,
versions from `plugin.json` and from the entry, the commit list, a diff
limited to the plugin, the `--json` shape, and a Codex reinstall after
`update`.

### D6 — `add --plugin`

**Build:** `--plugin P…`, writing `plugins` and (without `--skill`)
`skills = []`, and its refusals: a plugin the catalog lacks, one tack can't
deploy, one another source already selects (DEC-11), and a source with
neither skills nor `--plugin`, whose message lists the catalog's plugins
(*Adding and removing sources*).

**Depends on:** D2.

Notes from the P0001-C08 cut: until D8, `add` refuses a plugin from another
repository as `sync` reports it; the TUI's add form takes plugins in this
item, since *The TUI* has it take what `tack add` takes.

**Done when:** each refusal exits `2` with nothing written and a fresh clone
removed; a dry run writes nothing; the appended table round-trips through the
manifest parser and the following `sync` installs the plugin; the agent
skill's argument-parser test accepts the new flag.

### D7 — The TUI's Plugins tab

**Build:** the Plugins tab after Skills, tabs keyed `1`–`4`, grouping,
folding and sorting as on Skills with the plugin state order, the detail
pane, changed plugins in the Sources detail, and plugin commands in `s`'s
preview (*The TUI*).

Note from the P0001-C05 review: the TUI's worker calls `status.status` and
`doctor.run` together, and from D4 both list the agents' plugins, so each
refresh runs every `list` command twice; the Plugins tab's worker reads
each agent once and shares it.

**Depends on:** D3, D5.

**Done when:** pilot tests show the tab order and keys, the app still
opening on Skills, every state rendered, the plugin column sort order,
grouping and folding held through a refresh, the detail for a plugin inside a
source and for a broken one, changed plugins in the Sources detail, and the
sync preview listing plugin commands.

### D8 — Plugins from other repositories

**Build:** clones in `$XDG_DATA_HOME/tack/plugins/<source>/<plugin>/` at the
catalog's commit, `git-subdir`'s path, fetching a new commit after an
`update`, refusing a clone with local changes, re-cloning a missing one,
`remove` deleting a source's clones, `outdated --diff` between commits,
`status` and the TUI detail naming repository and commit, and `add`
accepting such plugins (*Plugins from other repositories*; DEC-4). The
catalog fixes in [#29](https://github.com/chocs-cat/tack/issues/29) land
here.

**Depends on:** D2, D5, D6, D7.

Notes from the P0001-C10 cut: *Plugins from other repositories* is pinned
(DEC-21), and D8 is split. P0001-C10 builds the clones unwired, as C01 built
tack's marketplace, with #29. The wiring follows as one chunk, since the
plan's directory for such a plugin changes `sync`, `status`, `doctor`, the
TUI's problems and `add` at once (DEC-19 holds only if they move together);
its cut rewrites the passages that still call such a plugin undeployable
(*`doctor` checks*' *A source* and *Leftovers*, *The TUI*'s problem list,
README, the skill). `status --json` and the TUI's detail naming the
repository and commit, and `outdated --diff` between commits, are pinned at
their own cut.

Notes from the P0001-C11 cut: C10 was accepted, and C11 wires the clones,
with #54 (DEC-22) first. What remains of D8 after it: `status --json` and
the TUI's detail naming the repository and commit, and `outdated --diff`
between commits.

Notes from the P0001-C12 cut: C11 was accepted. C12 is the rest of D8,
pinned at this cut: `status --json`'s `repository` and the TUI's detail
lines for it, and `outdated --diff` between a plugin's commits (DEC-23).

Notes from the P0001-C13 cut: C12 was accepted, and D8 is done. C13
gathers §6's evidence; what remains after it is `/relay-project`'s
closeout.

**Done when:** tests with local git remotes show an entry with a commit
deployed at that commit, a `git-subdir` entry deploying only its path, an
`update` that changes the commit fetching it and reinstalling in Codex, a
clone with local changes refused (and its plugin left as it was), a missing
clone re-cloned, `remove` deleting the clones, and `outdated --diff` showing
the diff between the two commits.

## 6. Project completion

- **Real agents.** In a scratch `HOME`, never the maintainer's, `tack sync`
  with a source for a local clone of `anthropics/claude-plugins-official`
  selecting `skill-creator` and one git-entry plugin installs both in the real
  Claude Code and Codex: `claude plugin list --json` shows them `@tack`,
  loaded from tack's marketplace, and `codex plugin list --json` lists them;
  a pin move reaches Codex's copy; `tack remove` uninstalls both and
  unregisters the marketplace. The run is recorded in a chunk report with the
  agents' versions, and *Harness facts* is corrected if anything differs.
- **Compatibility.** The existing test suite passes unchanged apart from tab
  keys; with a manifest without `plugins`, `sync` and `status` make no
  agent CLI call (DEC-18); a pre-project
  `state.json` loads, and the new one keeps `version: 1`.
- **A real setup.** `tack doctor` on a machine with hand-installed plugins
  reports them as `unmanaged-plugin` and stays quiet about the agents' own;
  the run records the agents' own marketplace names that
  `ignore_marketplaces` defaults to in *Harness facts*, with the versions
  (#42: a fresh scratch `HOME` has none to check).
- **Docs.** `README.md` and `skills/tack/SKILL.md` describe plugins;
  design.md's *(P0001)* marks and the header note are removed.

## 7. Chunk ledger

| Chunk | Delivery items | State | Review | Integrated identity |
|---|---|---|---|---|
| [P0001-C01](../chunks/P0001-C01.md) | D1 (catalogs), D2 (tack's marketplace, the agents' CLIs, stand-ins): unwired groundwork | accepted with follow-ups (#29; C02-a) | 2026-10-05 | #28, `4c3bcac` |
| [P0001-C02](../chunks/P0001-C02.md) | D1 (the `plugins` selection, unwired; the plan); C01 review follow-up | accepted with follow-ups (DEC-11 as C03-a; #31) | 2026-10-05 | #30, `3d4bcf5` |
| [P0001-C03](../chunks/P0001-C03.md) | D2 (`sync`'s plugin steps and the record, not yet reachable); C02 review follow-up (DEC-11) | accepted with follow-ups (#33 as C04-a) | 2026-10-06 | #32, `91feded` |
| [P0001-C04](../chunks/P0001-C04.md) | D2 (#33; DEC-12's held sources; `remove`; docs), D1 (`skills = []`; the `plugins` field): D1 and D2 done | accepted with follow-ups (#35 as C05-a) | 2026-10-07 | #34, `5f4cd60` |
| [P0001-C05](../chunks/P0001-C05.md) | D3 (`status` reports plugins); C04 review follow-up (#35): D3 done | accepted with follow-ups (#40 as C06-a) | 2026-10-07 | #37, `0b78ae1` |
| [P0001-C06](../chunks/P0001-C06.md) | D4 (`doctor` audits plugins, `ignore_marketplaces`); C05 review follow-up (#40): D4 done | accepted with follow-ups (#44 as C07-a; #42) | 2026-10-07 | #41, `32ca329` |
| [P0001-C07](../chunks/P0001-C07.md) | D5 (`outdated` tracks plugins, `update` reinstalls in Codex); C06 review follow-up (#44): D5 done | accepted with follow-ups (#46, #47 as C08-a; brief-checklist §7) | 2026-10-07 | #45, `5998bac` |
| [P0001-C08](../chunks/P0001-C08.md) | D6 (`add --plugin`, the TUI's add form); C07 review follow-ups (#46, #47): D6 done | accepted with follow-ups (#49 as C09-a) | 2026-10-08 | #48, `d51ff10` |
| [P0001-C09](../chunks/P0001-C09.md) | D7 (the TUI's Plugins tab, its details, one read per refresh); #49 (C08's follow-up), #43: D7 done | accepted with follow-ups (review-checklist §3, a Plugins-tab test, #51 as C10-a; #52) | 2026-10-08 | #50, `d0d10e6` |
| [P0001-C10](../chunks/P0001-C10.md) | D8 (#29; plugins' clones and `remove` deleting them: unwired groundwork); C09 review follow-ups (#51) | accepted with follow-ups (#54 as C11-a) | 2026-10-08 | #53, `8ef8036` |
| [P0001-C11](../chunks/P0001-C11.md) | D8 (the clones wired into `sync`, `status`, `doctor`, the TUI and `add`); C10 review follow-up (#54) | accepted with follow-ups (#56) | 2026-10-09 | #55, `c954779` |
| [P0001-C12](../chunks/P0001-C12.md) | D8 (`status --json` and the TUI naming a plugin's repository, commit and clone; `outdated --diff` between commits): D8 done | accepted | 2026-10-09 | #58 |
| [P0001-C13](../chunks/P0001-C13.md) | §6's completion evidence: the real agents, a real setup (#42), compatibility, design.md's marks removed | ready for an executor | — | — |

## 8. Closeout

Fill this only when completing or abandoning the project.

- **Outcome:** —
- **Accepted chunks:** —
- **Changelog entries:** —
- **Derived release effect:** —
- **Unfinished or deliberately excluded:** —
- **Decisions added or reopened:** —

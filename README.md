# tack

Keep your coding agents' skills deployed identically to Claude Code and Codex
from one manifest of sources — your own skill repos and pinned third-party
ones — and audit your projects so either agent sees the same instructions,
skills, and hooks.

**Status: phase 5 of [the design](docs/design.md).** `tack sync` deploys
skills from the manifest's sources, `tack status` shows what is where,
`tack outdated` and `tack update` track upstream, `tack add` and `tack remove`
edit the manifest, and `tack doctor` audits. A `path` source with
`autocommit = true` (and `autopush`) has its skill edits committed, and
pushed, whenever `sync`, `update`, `add` or `remove` runs. Scaffolding the
fixes `doctor` suggests comes next.

```sh
uv tool install -e .      # or: uv run tack ...
tack add https://github.com/cloudflare/skills.git --skill wrangler
tack sync --dry-run       # what would change
tack sync                 # fetch pinned sources, link skills into every harness
tack status               # sources, pins, and which skills are linked where
tack outdated --diff      # what upstream changed in the skills you deploy
tack update cloudflare    # take it: move the pin, then sync
tack remove cloudflare    # its table, pin, links and checkout
tack doctor               # audit the harnesses and the projects under projects.roots
tack doctor --json        # for scripts; exit 1 when there is an error or warning
```

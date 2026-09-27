# tack

Keep your coding agents' skills deployed identically to Claude Code and Codex
from one manifest of sources — your own skill repos and pinned third-party
ones — and audit your projects so either agent sees the same instructions,
skills, and hooks.

**Status: phase 3 of [the design](docs/design.md).** `tack sync` deploys
skills from the manifest's sources, `tack status` shows what is where, and
`tack doctor` audits; tracking upstream (`outdated`, `update`) comes next.

```sh
uv tool install -e .      # or: uv run tack ...
tack sync --dry-run       # what would change
tack sync                 # fetch pinned sources, link skills into every harness
tack status               # sources, pins, and which skills are linked where
tack doctor               # audit the harnesses and the projects under projects.roots
tack doctor --json        # for scripts; exit 1 when there is an error or warning
```

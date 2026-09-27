# tack

Keep your coding agents' skills deployed identically to Claude Code and Codex
from one manifest of sources — your own skill repos and pinned third-party
ones — and audit your projects so either agent sees the same instructions,
skills, and hooks.

**Status: phase 2 of [the design](docs/design.md).** `tack doctor`, the
read-only audit, works; deploying skills (`tack sync` and the rest) comes next.

```sh
uv tool install -e .      # or: uv run tack ...
tack doctor               # audit the harnesses and the projects under projects.roots
tack doctor ~/Code/app    # audit one project
tack doctor --json        # for scripts; exit 1 when there is an error or warning
```

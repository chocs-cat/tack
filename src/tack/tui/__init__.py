"""The TUI: a Textual app over the same operations as the CLI.

Textual is imported only when the app runs, so the CLI starts as fast as it
did without it.
"""

from __future__ import annotations

from pathlib import Path


def run(config_dir: Path | None = None) -> int:
    """Run the app until it quits."""
    from tack.tui.app import TackApp

    TackApp(config_dir).run()
    return 0

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warn", "info"]
SEVERITIES: tuple[Severity, ...] = ("error", "warn", "info")


@dataclass(frozen=True)
class Finding:
    id: str  # stable: scripts match on it
    severity: Severity
    message: str
    path: Path | None = None  # the file or directory it is about
    harness: str | None = None
    project: Path | None = None  # None for global findings
    fix: str | None = None  # the `tack scaffold` fix, where one exists

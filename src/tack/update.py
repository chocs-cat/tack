"""`tack update`: move git sources' pins to the tip of their refs, then sync.

A source whose manifest entry changed since it was pinned is re-pinned for
the entry as it is now. A pin already at the tip is left alone, its `locked`
time included.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from tack import config, sources, sync
from tack.config import Config
from tack.sources import SourceError
from tack.sync import Change, Problem, Result


def update(
    cfg: Config,
    names: Sequence[str] = (),
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> Result:
    """Re-pin the named git sources (every one if none are named) and sync."""
    now = now or datetime.now(UTC)
    targets = sources.git_sources(cfg, names)
    lock = config.load_lock(cfg.paths)
    pins = dict(lock)
    result = Result(dry_run)
    for src in targets:
        try:
            new = sources.pin(src, now)
        except SourceError as e:
            result.problems.append(Problem("source", str(e), source=src.name))
            continue
        old = lock.get(src.name)
        if old is not None and old.matches(src) and old.commit == new.commit:
            continue
        pins[src.name] = new
        where = sources.root(src, cfg.paths)
        if old is None:
            change = Change("pin", sources.pin_detail(new), src.name, path=where)
        elif not old.matches(src):
            detail = f"{sources.pin_detail(new)} (the manifest's git or ref changed)"
            change = Change("update", detail, src.name, path=where)
        else:
            on = new.ref or "the default branch"
            detail = f"{old.commit[:12]} -> {new.commit[:12]} on {on}"
            change = Change("update", detail, src.name, path=where)
        result.changes.append(change)

    return result.extend(sync.sync(cfg, dry_run=dry_run, now=now, lock=pins))

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tack import sources
from tack.config import Config, LockEntry
from tack.sources import SourceError
from tests.helpers import commit, git, load, upstream, write

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)


def cfg_for(home: Path, url: Path | str, ref: str | None = None) -> Config:
    ref_line = f'ref = "{ref}"\n' if ref else ""
    return load(home, f'[[source]]\nname = "up"\ngit = "{url}"\n{ref_line}')


def test_remote_tip(tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    first = git(up, "rev-parse", "HEAD").strip()
    git(up, "tag", "-a", "v1", "-m", "v1")
    git(up, "tag", "light")
    git(up, "branch", "stable")
    second = commit(up, {"skills/a/notes.md": "x"})
    assert sources.remote_tip(str(up), None) == second
    assert sources.remote_tip(str(up), "master") == second
    assert sources.remote_tip(str(up), "stable") == first
    assert sources.remote_tip(str(up), "v1") == first  # the commit, not the tag object
    assert sources.remote_tip(str(up), "light") == first
    with pytest.raises(SourceError, match="has no branch or tag 'nope'"):
        sources.remote_tip(str(up), "nope")
    with pytest.raises(SourceError, match="can't read"):
        sources.remote_tip(str(tmp_path / "missing"), None)


def test_first_sync_clones_and_pins_the_tip(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a", "b")
    tip = git(up, "rev-parse", "HEAD").strip()
    cfg = cfg_for(home, up)
    (src,) = cfg.sources
    out = sources.sync_git(src, cfg.paths, None, now=WHEN)
    d = cfg.paths.sources_dir / "up"
    assert out.entry == LockEntry(str(up), None, tip, WHEN)
    assert [a for a, _ in out.steps] == ["pin", "clone", "checkout"]
    assert (d / "skills" / "a" / "SKILL.md").is_file()
    assert sources.head(d) == tip
    assert sources.offered(src, cfg.paths) == {"a": d / "skills" / "a", "b": d / "skills" / "b"}

    # Upstream moves on; the pin doesn't.
    commit(up, {"skills/c/SKILL.md": "new"})
    again = sources.sync_git(src, cfg.paths, out.entry)
    assert (again.entry, again.steps) == (out.entry, [])
    assert not (d / "skills" / "c").exists()


def test_checkout_follows_the_pin(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    old = git(up, "rev-parse", "HEAD").strip()
    new = commit(up, {"skills/b/SKILL.md": "b"})
    cfg = cfg_for(home, up)
    (src,) = cfg.sources
    sources.sync_git(src, cfg.paths, LockEntry(str(up), None, new, WHEN))
    d = cfg.paths.sources_dir / "up"
    out = sources.sync_git(src, cfg.paths, LockEntry(str(up), None, old, WHEN))
    assert out.steps == [("checkout", old[:12])]
    assert not (d / "skills" / "b").exists()

    shutil.rmtree(d)  # a checkout that went missing is cloned again at its pin
    out = sources.sync_git(src, cfg.paths, LockEntry(str(up), None, old, WHEN))
    assert [a for a, _ in out.steps] == ["clone", "checkout"]
    assert sources.head(d) == old


def test_pin_a_new_commit_fetches_it(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    cfg = cfg_for(home, up)
    (src,) = cfg.sources
    first = sources.sync_git(src, cfg.paths, None, now=WHEN).entry
    new = commit(up, {"skills/b/SKILL.md": "b"})
    out = sources.sync_git(src, cfg.paths, LockEntry(first.git, None, new, WHEN))
    assert out.steps == [("checkout", new[:12])]


def test_refusals(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    cfg = cfg_for(home, up, ref="master")
    (src,) = cfg.sources
    with pytest.raises(SourceError, match="changed since it was pinned; `tack update up`"):
        sources.sync_git(src, cfg.paths, LockEntry(str(up), None, "0" * 40, WHEN))

    entry = sources.sync_git(src, cfg.paths, None).entry
    d = cfg.paths.sources_dir / "up"
    write(d / ".DS_Store", "untracked files don't count")
    assert sources.sync_git(src, cfg.paths, entry).steps == []
    write(d / "skills" / "a" / "SKILL.md", "edited")
    with pytest.raises(SourceError, match="has local changes"):
        sources.sync_git(src, cfg.paths, entry)

    shutil.rmtree(d)
    write(d / "stray.txt")
    with pytest.raises(SourceError, match="isn't a git checkout"):
        sources.sync_git(src, cfg.paths, entry)

    shutil.rmtree(d)
    with pytest.raises(SourceError, match="pinned commit 000000000000 isn't in"):
        sources.sync_git(src, cfg.paths, LockEntry(str(up), "master", "0" * 40, WHEN))

    other = load(home, '[[source]]\nname = "gone"\ngit = "/nowhere/repo.git"\n')
    with pytest.raises(SourceError, match=r"can.t read /nowhere/repo\.git"):
        sources.sync_git(other.sources[0], other.paths, None)


def test_dry_run_changes_nothing(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    tip = git(up, "rev-parse", "HEAD").strip()
    cfg = cfg_for(home, up)
    (src,) = cfg.sources
    out = sources.sync_git(src, cfg.paths, None, dry_run=True)
    assert out.entry.commit == tip
    assert [a for a, _ in out.steps] == ["pin", "clone", "checkout"]
    assert not cfg.paths.data_dir.exists()

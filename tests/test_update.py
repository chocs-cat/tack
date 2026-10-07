from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tack import config, deploy, plugins, sources, sync, update
from tack.config import Config, UsageError
from tests.helpers import commit, git, load, repo, skill_md, tree, upstream
from tests.standin import Standins

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 1, 9, 30, 0, tzinfo=UTC)


def source(up: Path, name: str = "up", extra: str = "") -> str:
    return f'[[source]]\nname = "{name}"\ngit = "{up}"\n{extra}'


def pinned(home: Path, manifest: str) -> Config:
    cfg = load(home, manifest)
    assert sync.sync(cfg, now=WHEN).problems == []
    return cfg


def actions(result: sync.Result) -> list[tuple[str, str | None]]:
    return [(c.action, c.harness or c.source) for c in result.changes]


def test_update_moves_the_pin_and_syncs(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    cfg = pinned(home, source(up))
    old = config.load_lock(cfg.paths)["up"].commit
    new = commit(up, {"skills/b/SKILL.md": skill_md("b")})

    result = update.update(cfg, now=LATER)
    assert result.problems == []
    assert actions(result) == [
        ("update", "up"),
        ("checkout", "up"),
        ("write", None),
        ("link", "claude-code"),
        ("link", "codex"),
    ]
    assert result.changes[0].detail == f"{old[:12]} -> {new[:12]} on the default branch"
    entry = config.load_lock(cfg.paths)["up"]
    assert (entry.commit, entry.locked) == (new, LATER)
    assert sources.head(cfg.paths.sources_dir / "up") == new
    assert (home / ".claude" / "skills" / "b").is_symlink()

    # At the tip already: nothing changes, not even the `locked` time.
    again = update.update(cfg, now=datetime(2027, 1, 1, tzinfo=UTC))
    assert (again.changes, again.problems) == ([], [])
    assert config.load_lock(cfg.paths)["up"].locked == LATER


def test_update_only_the_named_sources(home: Path, tmp_path: Path) -> None:
    one, two = upstream(tmp_path / "one", "a"), upstream(tmp_path / "two", "b")
    cfg = pinned(home, source(one, "one") + source(two, "two"))
    before = config.load_lock(cfg.paths)
    commit(one, {"skills/a/x": "1"})
    new_two = commit(two, {"skills/b/x": "2"})
    update.update(cfg, ["two"], now=LATER)
    after = config.load_lock(cfg.paths)
    assert after["one"] == before["one"]
    assert after["two"].commit == new_two


def test_update_repins_a_changed_or_new_source(home: Path, tmp_path: Path) -> None:
    up, other = upstream(tmp_path / "up", "a"), upstream(tmp_path / "other", "b")
    pinned(home, source(up))
    git(up, "branch", "stable")
    changed = source(up, extra='ref = "stable"\n')
    assert [p.kind for p in sync.sync(load(home, changed)).problems] == ["source"]  # refused
    cfg = load(home, changed + source(other, "fresh"))

    result = update.update(cfg, now=LATER)
    assert result.problems == []
    assert actions(result)[:2] == [("update", "up"), ("pin", "fresh")]
    assert result.changes[0].detail.endswith("(the manifest's git or ref changed)")
    lock = config.load_lock(cfg.paths)
    assert (lock["up"].ref, lock["fresh"].ref) == ("stable", None)


def test_dry_run_changes_nothing(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    cfg = pinned(home, source(up))
    commit(up, {"skills/b/SKILL.md": skill_md("b")})
    before = tree(home)
    result = update.update(cfg, dry_run=True, now=LATER)
    assert tree(home) == before
    assert actions(result)[:3] == [("update", "up"), ("checkout", "up"), ("write", None)]


def test_an_unreachable_source_is_reported(home: Path, tmp_path: Path) -> None:
    gone, up = upstream(tmp_path / "gone", "a"), upstream(tmp_path / "up", "b")
    cfg = pinned(home, source(gone, "gone") + source(up))
    shutil.rmtree(gone)
    new = commit(up, {"skills/b/x": "1"})
    result = update.update(cfg, now=LATER)
    assert [(p.kind, p.source) for p in result.problems] == [("source", "gone")]
    assert config.load_lock(cfg.paths)["up"].commit == new


def test_usage_errors(home: Path, tmp_path: Path) -> None:
    (home / "mine" / "skills").mkdir(parents=True)
    cfg = load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')
    with pytest.raises(UsageError, match="only git sources are pinned"):
        update.update(cfg, ["mine"])
    with pytest.raises(UsageError, match="no source named 'nope'"):
        update.update(cfg, ["nope"])


def test_update_carries_a_plugin_change_to_codex(
    home: Path, tmp_path: Path, standins: Standins
) -> None:
    """A changed plugin file is copied and reinstalled in Codex, whose copy
    is its own; Claude Code loads tack's copy in place, so nothing runs
    there but the two lists (design.md *Deploying*, step 3)."""
    catalog = json.dumps({"plugins": [{"name": "a", "source": "./plugins/a"}]})
    up = repo(
        tmp_path / "up",
        {".claude-plugin/marketplace.json": catalog, "plugins/a/README.md": "a\n"},
    )
    cfg = pinned(home, source(up, extra='skills = []\nplugins = ["a"]\n'))
    before = deploy.load_record(cfg.paths).plugins
    claude = len(standins.calls("claude"))
    commit(up, {"plugins/a/README.md": "changed\n"})

    result = update.update(cfg, now=LATER)
    assert result.problems == []
    assert [(c.action, c.harness, c.detail) for c in result.changes[3:]] == [
        ("copy", None, "a from ~/.local/share/tack/sources/up/plugins/a"),
        ("reinstall", "codex", "codex plugin add a@tack --json"),
    ]
    assert [c.action for c in result.changes[:3]] == ["update", "checkout", "write"]
    after = deploy.load_record(cfg.paths).plugins
    copy = cfg.paths.marketplace_dir / "plugins" / "a"
    assert after["codex"]["a"].hash == plugins.tree_hash(copy) != before["codex"]["a"].hash
    assert after["claude-code"]["a"] == before["claude-code"]["a"]
    assert sorted(" ".join(c.args) for c in standins.calls("claude")[claude:]) == [
        "plugin list --json",
        "plugin marketplace list --json",
    ]

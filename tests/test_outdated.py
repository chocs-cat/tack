from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tack import outdated, sources, sync
from tack.config import Config, UsageError
from tack.outdated import ChangedSkill
from tests.helpers import commit, git, load, skill_md, upstream

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)


def source(up: Path, extra: str = "", name: str = "up") -> str:
    return f'[[source]]\nname = "{name}"\ngit = "{up}"\n{extra}'


def pinned(home: Path, manifest: str) -> Config:
    cfg = load(home, manifest)
    assert sync.sync(cfg, now=WHEN).problems == []
    return cfg


def only(cfg: Config, **kw) -> outdated.SourceReport:
    (report,) = outdated.outdated(cfg, **kw).sources
    return report


def test_up_to_date(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    cfg = pinned(home, source(up))
    report = outdated.outdated(cfg)
    (r,) = report.sources
    assert (r.state, r.pin, r.tip, r.behind) == ("current", r.tip, r.pin, 0)
    assert not report.failed


def test_behind(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a", "b", "c")
    cfg = pinned(home, source(up))
    pin = git(up, "rev-parse", "HEAD").strip()
    commit(up, {"skills/a/SKILL.md": skill_md("a") + "More.\n"}, "Change a")
    commit(up, {"skills/d/SKILL.md": skill_md("d")}, "Add d")
    git(up, "rm", "-rq", "skills/c")
    git(up, "commit", "-qm", "Drop c")
    tip = commit(up, {"README.md": "docs"}, "Docs")

    report = outdated.outdated(cfg)
    (r,) = report.sources
    assert report.failed
    assert (r.state, r.pin, r.tip, r.behind, r.rewritten) == ("behind", pin, tip, 4, False)
    assert r.skills == [
        ChangedSkill("a", "modified"),
        ChangedSkill("c", "removed"),
        ChangedSkill("d", "added"),
    ]
    assert [(c.subject, c.skills) for c in r.commits] == [
        ("Drop c", ["c"]),
        ("Add d", ["d"]),
        ("Change a", ["a"]),
    ]
    assert r.diff is None
    checkout = cfg.paths.sources_dir / "up"
    assert sources.head(checkout) == pin  # fetched, not moved

    diff = only(cfg, diff=True).diff
    assert diff is not None
    for text in ("+More.", "b/skills/d/SKILL.md", "a/skills/c/SKILL.md"):
        assert text in diff
    assert "README" not in diff


def test_only_selected_skills_count(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a", "b")
    cfg = pinned(home, source(up, 'skills = ["b"]\n'))
    commit(up, {"skills/a/SKILL.md": "changed"}, "Change a")
    commit(up, {"skills/new/SKILL.md": "new"}, "Add new")
    r = only(cfg)
    assert (r.state, r.behind, r.skills, r.commits) == ("behind", 2, [], [])


def test_subdir_at_the_root(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up")
    commit(up, {"a/SKILL.md": skill_md("a"), ".github/x.yml": "", "README.md": ""})
    cfg = pinned(home, source(up, 'subdir = "."\n'))
    commit(up, {"a/SKILL.md": "changed", ".github/x.yml": "y", "README.md": "z"}, "Many")
    r = only(cfg)
    assert r.skills == [ChangedSkill("a", "modified")]


def test_rewritten_history(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    commit(up, {"skills/a/SKILL.md": "second"})
    cfg = pinned(home, source(up))
    git(up, "reset", "-q", "--hard", "HEAD~1")
    commit(up, {"skills/a/SKILL.md": "rewritten"}, "Rewrite")
    r = only(cfg)
    assert (r.state, r.behind, r.rewritten) == ("behind", 1, True)
    assert r.skills == [ChangedSkill("a", "modified")]


def test_sources_that_cant_be_compared(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    manifest = source(up)
    cfg = load(home, manifest)
    assert (only(cfg).state, only(cfg).message) == (
        "not pinned",
        "not pinned yet; `tack sync` pins it",
    )
    sync.sync(cfg, now=WHEN)
    changed = load(home, manifest + 'ref = "master"\n')
    assert only(changed).state == "manifest changed"
    assert "`tack update up` re-pins it" in (only(changed).message or "")

    shutil.rmtree(tmp_path / "up")
    r = only(cfg)
    assert r.state == "error"
    assert (r.message or "").startswith("can't read")

    shutil.rmtree(cfg.paths.sources_dir / "up")
    assert only(cfg).state == "not checked out"
    assert outdated.outdated(cfg).failed


def test_which_sources(home: Path, tmp_path: Path) -> None:
    one, two = upstream(tmp_path / "one", "a"), upstream(tmp_path / "two", "b")
    (home / "mine" / "skills").mkdir(parents=True)
    cfg = pinned(
        home,
        source(one, name="one")
        + source(two, name="two")
        + '[[source]]\nname = "mine"\npath = "~/mine"\n',
    )
    assert [s.name for s in outdated.outdated(cfg).sources] == ["one", "two"]
    assert [s.name for s in outdated.outdated(cfg, ["two"]).sources] == ["two"]
    with pytest.raises(UsageError, match="'mine' is a path source"):
        outdated.outdated(cfg, ["mine"])
    with pytest.raises(UsageError, match="no source named 'nope'"):
        outdated.outdated(cfg, ["nope"])

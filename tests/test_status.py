from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from tack import status, sync
from tests.helpers import git, link, load, repo, skill, upstream, write

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)


def test_status(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    tip = git(up, "rev-parse", "HEAD").strip()
    mine = repo(home / "mine", {"skills/a/SKILL.md": "---\ndescription: a\n---\n"})
    skill(mine / "skills", "b")  # uncommitted
    manifest = (
        '[[source]]\nname = "mine"\npath = "~/mine"\n'
        f'[[source]]\nname = "up"\ngit = "{up}"\nref = "master"\n'
        '[[source]]\nname = "gone"\npath = "~/gone"\n'
    )
    cfg = load(home, manifest)
    sync.sync(cfg, now=WHEN)
    (home / ".agents" / "skills" / "b").unlink()
    link(home / ".agents" / "skills" / "c", home)  # not a selected skill: not listed

    st = status.status(cfg)
    by_name = {s.name: s for s in st.sources}
    assert by_name["mine"].state == "ok"
    assert by_name["mine"].uncommitted == ["b"]
    assert by_name["gone"].state == "missing"
    up_status = by_name["up"]
    assert (up_status.state, up_status.commit, up_status.locked) == ("ok", tip, WHEN)
    assert up_status.skills == ["x"]
    assert [(k.name, k.source, k.harnesses) for k in st.skills] == [
        ("a", "mine", {"claude-code": "linked", "codex": "linked"}),
        ("b", "mine", {"claude-code": "linked", "codex": "missing"}),
        ("x", "up", {"claude-code": "linked", "codex": "linked"}),
    ]


def test_git_source_states(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    manifest = f'[[source]]\nname = "up"\ngit = "{up}"\n'
    cfg = load(home, manifest)

    def state() -> str:
        return status.status(cfg).sources[0].state

    assert state() == "not pinned"
    sync.sync(cfg, now=WHEN)
    assert state() == "ok"
    checkout = cfg.paths.sources_dir / "up"
    write(checkout / "skills" / "x" / "SKILL.md", "edited")
    assert state() == "local changes"
    git(checkout, "checkout", "-q", "--", ".")
    git(up, "commit", "-q", "--allow-empty", "-m", "later")
    git(checkout, "fetch", "-q")
    git(checkout, "checkout", "-q", "--detach", "origin/master")
    assert state() == "off its pin"
    shutil.rmtree(checkout)
    assert state() == "not checked out"
    cfg = load(home, manifest + 'ref = "master"\n')
    assert status.status(cfg).sources[0].state == "manifest changed"


def test_collisions_and_conflicts(home: Path) -> None:
    skill(home / "one" / "skills", "dup")
    skill(home / "two" / "skills", "dup")
    skill(home / "one" / "skills", "solo")
    skill(home / ".claude" / "skills", "solo")  # a real directory in the way
    cfg = load(
        home,
        '[[source]]\nname = "one"\npath = "~/one"\n'
        '[[source]]\nname = "two"\npath = "~/two"\nharnesses = ["codex"]\n',
    )
    st = status.status(cfg)
    assert [(k.name, k.source, k.harnesses) for k in st.skills] == [
        ("dup", "one", {"claude-code": "missing", "codex": "collision"}),
        ("dup", "two", {"codex": "collision"}),
        ("solo", "one", {"claude-code": "conflict", "codex": "missing"}),
    ]

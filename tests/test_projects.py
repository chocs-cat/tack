from __future__ import annotations

from pathlib import Path

import pytest

from tack.doctor.projects import discover, is_clone, url_owner
from tests.helpers import git, repo, write


def test_discover(tmp_path: Path) -> None:
    root = tmp_path / "Code"
    for rel in (
        "app",
        "app/vendored",  # inside a repository: not descended into
        "group/one",
        "group/two",
        "Archive/old",  # excluded
        ".hidden/repo",
        "web/node_modules/pkg",
        "deep/a/b/c",
    ):
        (root / rel / ".git").mkdir(parents=True)
    write(root / "worktree" / ".git", "gitdir: /elsewhere\n")  # a worktree's .git is a file
    (root / "plain").mkdir()
    (root / "link").symlink_to(root / "group")  # not followed
    assert discover([root], [root / "Archive"]) == [
        root / "app",
        root / "deep" / "a" / "b" / "c",
        root / "group" / "one",
        root / "group" / "two",
        root / "worktree",
    ]


def test_a_start_that_is_a_repository_is_one_project(tmp_path: Path) -> None:
    (tmp_path / "r" / ".git").mkdir(parents=True)
    (tmp_path / "r" / "sub" / ".git").mkdir(parents=True)
    assert discover([tmp_path / "r", tmp_path / "r"]) == [tmp_path / "r"]
    assert discover([tmp_path / "missing"]) == []


@pytest.mark.parametrize(
    ("url", "owner"),
    [
        ("https://github.com/johnfoland/corral.git", "johnfoland"),
        ("https://github.com/millsymills-com/gandi-mcp", "millsymills-com"),
        ("git@github.com:cruzainet/specs.git", "cruzainet"),
        ("ssh://git@gitlab.example.com:2222/group/sub/repo.git", "group"),
        ("github.com:someone/repo", "someone"),
        ("https://github.com/lonely", None),
        ("/srv/git/repo.git", None),
        ("../relative/repo", None),
        ("file:///srv/git/owner/repo.git", None),
    ],
)
def test_url_owner(url: str, owner: str | None) -> None:
    assert url_owner(url) == owner


def test_is_clone(tmp_path: Path) -> None:
    theirs = repo(tmp_path / "theirs")
    git(theirs, "remote", "add", "origin", "https://github.com/someone/theirs.git")
    mine = repo(tmp_path / "mine")
    git(mine, "remote", "add", "origin", "git@github.com:Me/mine.git")
    local = repo(tmp_path / "local")
    assert is_clone(theirs, ["me"])
    assert not is_clone(mine, ["me"])  # owners compare case-insensitively
    assert not is_clone(local, ["me"])
    assert not is_clone(theirs, [])  # no owners configured: everything is yours

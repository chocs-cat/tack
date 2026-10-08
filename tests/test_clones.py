"""Plugins' clones of other repositories (design.md *Plugins from other
repositories*, DEC-21): kept at their catalog's commit by the code that
keeps a source's checkout at its pin.

Every remote is a `file://` URL: `git clone` of a plain path copies every
object, so a commit no branch or tag reaches would arrive without a fetch by
its id, and the test would prove nothing."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tack import sources
from tack.catalog import InRepository
from tack.config import LockEntry, Paths
from tack.sources import Clone, CloneState, SourceError
from tack.text import tilde
from tests.helpers import commit, git, load, repo, tree, write

WHEN = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
MISSING = "0123456789abcdef0123456789abcdef01234567"


def remote(path: Path) -> tuple[Path, str, str]:
    """A repository with two commits on master, the plugin under `plug/`;
    it, and the two commits, oldest first."""
    r = repo(path, {"plug/README.md": "one\n"})
    first = git(r, "rev-parse", "HEAD").strip()
    second = commit(r, {"plug/README.md": "two\n"})
    return r, first, second


def url(r: Path) -> str:
    return r.as_uri()


def clone_of(r: Path, commit: str, path: str | None = None) -> Clone:
    return Clone.of(Paths.from_env(), "src", "p", InRepository(url(r), path, commit))


def gone(r: Path) -> None:
    """Take the remote away, so a test that says nothing is fetched fails if
    anything is (review-checklist §1)."""
    shutil.rmtree(r)


def made(state: CloneState, tmp_path: Path) -> Clone:
    """A clone in `state`, of a remote whose second commit it targets."""
    r, first, second = remote(tmp_path / "up")
    c = clone_of(r, second)
    if state == "in the way":
        write(c.path / "stray.txt", "not a checkout\n")
    elif state == "local changes":
        sources.sync_clone(c)
        write(c.path / "plug" / "README.md", "edited\n")
    elif state == "off its commit":
        sources.sync_clone(clone_of(r, first))
    elif state == "ok":
        sources.sync_clone(c)
    assert c.state() == state
    return c


STATES: tuple[CloneState, ...] = (
    "in the way",
    "not cloned",
    "local changes",
    "off its commit",
    "ok",
)


@pytest.mark.parametrize("state", STATES)
def test_each_state(home: Path, tmp_path: Path, state: CloneState) -> None:
    made(state, tmp_path)


def test_where_a_clone_is_and_its_plugin_directory(home: Path, tmp_path: Path) -> None:
    data = home / ".local" / "share" / "tack"
    whole = clone_of(tmp_path / "r", MISSING)
    assert whole.path == data / "plugins" / "src" / "p"
    assert whole.directory == whole.path
    assert clone_of(tmp_path / "r", MISSING, "a/b").directory == whole.path / "a" / "b"


def test_untracked_files_are_no_local_changes(home: Path, tmp_path: Path) -> None:
    c = made("ok", tmp_path)
    write(c.path / ".DS_Store", "untracked\n")
    assert c.state() == "ok"


def test_not_cloned_is_cloned_at_its_commit(home: Path, tmp_path: Path) -> None:
    r, first, _ = remote(tmp_path / "up")
    c = clone_of(r, first, "plug")
    assert sources.sync_clone(c) == [("clone", url(r)), ("checkout", first[:12])]
    assert sources.head(c.path) == first
    assert (c.directory / "README.md").read_text() == "one\n"
    assert c.state() == "ok"


def test_off_its_commit_with_the_commit_only_checks_out(home: Path, tmp_path: Path) -> None:
    r, first, second = remote(tmp_path / "up")
    sources.sync_clone(clone_of(r, second))
    gone(r)
    c = clone_of(r, first)
    assert sources.sync_clone(c) == [("checkout", first[:12])]
    assert sources.head(c.path) == first


def test_off_its_commit_without_it_fetches_it(home: Path, tmp_path: Path) -> None:
    r, first, _ = remote(tmp_path / "up")
    sources.sync_clone(clone_of(r, first))
    third = commit(r, {"plug/README.md": "three\n"})
    c = clone_of(r, third)
    assert sources.sync_clone(c) == [("checkout", third[:12])]
    assert sources.head(c.path) == third


def test_ok_takes_no_step(home: Path, tmp_path: Path) -> None:
    c = made("ok", tmp_path)
    gone(tmp_path / "up")
    assert sources.sync_clone(c) == []


def pinned_off_the_branches(r: Path) -> str:
    """A commit on `r` that only `refs/pins/x` reaches."""
    git(r, "checkout", "-q", "-b", "side")
    off = commit(r, {"plug/README.md": "off\n"})
    git(r, "update-ref", "refs/pins/x", off)
    git(r, "checkout", "-q", "master")
    git(r, "branch", "-q", "-D", "side")
    return off


@pytest.mark.parametrize("cloned", [False, True])
def test_a_commit_no_branch_or_tag_reaches_is_fetched_by_id(
    home: Path, tmp_path: Path, cloned: bool
) -> None:
    r, first, _ = remote(tmp_path / "up")
    off = pinned_off_the_branches(r)
    if cloned:
        sources.sync_clone(clone_of(r, first))
    c = clone_of(r, off)
    steps = sources.sync_clone(c)
    assert [s for s, _ in steps] == ([] if cloned else ["clone"]) + ["checkout"]
    assert sources.head(c.path) == off
    assert (c.path / "plug" / "README.md").read_text() == "off\n"


def test_a_commit_the_remote_lacks_fails_as_a_pin_does(home: Path, tmp_path: Path) -> None:
    """The message a source's checkout gives for a pin its remote doesn't
    have, from the same code."""
    r, _, _ = remote(tmp_path / "up")
    cfg = load(home, f'[[source]]\nname = "up"\ngit = "{url(r)}"\n')
    with pytest.raises(SourceError) as checkout:
        sources.sync_git(cfg.sources[0], cfg.paths, LockEntry(url(r), None, MISSING, WHEN))
    with pytest.raises(SourceError) as clone:
        sources.sync_clone(clone_of(r, MISSING))
    assert (
        str(clone.value) == str(checkout.value) == f"pinned commit {MISSING[:12]} isn't in {url(r)}"
    )


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ("local changes", "tack's checkout at {} has local changes; discard or move them"),
        ("in the way", "{} is in the way and isn't a git checkout"),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_a_clone_it_cant_move_fails_untouched(
    home: Path, tmp_path: Path, state: CloneState, message: str, dry_run: bool
) -> None:
    c = made(state, tmp_path)
    before = tree(c.path)
    with pytest.raises(SourceError) as e:
        sources.sync_clone(c, dry_run=dry_run)
    assert str(e.value) == message.format(tilde(c.path))
    assert tree(c.path) == before


def test_origin_follows_the_url(home: Path, tmp_path: Path) -> None:
    r, first, _ = remote(tmp_path / "up")
    sources.sync_clone(clone_of(r, first))
    moved = tmp_path / "moved"
    git(tmp_path, "clone", "-q", url(r), str(moved))
    new = commit(moved, {"plug/README.md": "moved\n"})
    gone(r)
    c = clone_of(moved, new)
    assert sources.sync_clone(c) == [("checkout", new[:12])]
    assert sources.head(c.path) == new
    assert git(c.path, "remote", "get-url", "origin").strip() == url(moved)


def test_a_dry_run_from_not_cloned_writes_nothing(home: Path, tmp_path: Path) -> None:
    r, first, _ = remote(tmp_path / "up")
    before = tree(home)
    c = clone_of(r, first)
    assert sources.sync_clone(c, dry_run=True) == [("clone", url(r)), ("checkout", first[:12])]
    assert tree(home) == before


def test_a_dry_run_fetches_nothing(home: Path, tmp_path: Path) -> None:
    r, first, _ = remote(tmp_path / "up")
    sources.sync_clone(clone_of(r, first))
    third = commit(r, {"plug/README.md": "three\n"})
    c = clone_of(r, third)
    before = tree(c.path)
    assert sources.sync_clone(c, dry_run=True) == [("checkout", third[:12])]
    assert tree(c.path) == before
    assert not sources.has_commit(c.path, third)


@pytest.mark.parametrize("state", STATES)
def test_the_state_and_a_dry_run_agree(home: Path, tmp_path: Path, state: CloneState) -> None:
    """What a dry run lists is what the state says `sync` does first
    (brief-checklist §5)."""
    c = made(state, tmp_path)
    expected = {"ok": [], "not cloned": ["clone", "checkout"], "off its commit": ["checkout"]}
    if state in expected:
        assert [s for s, _ in sources.sync_clone(c, dry_run=True)] == expected[state]
    else:
        with pytest.raises(SourceError):
            sources.sync_clone(c, dry_run=True)

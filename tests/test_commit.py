from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tack import commit, sources
from tack.config import Config
from tests.helpers import git, load, repo, skill_md, write

MINE = '[[source]]\nname = "mine"\npath = "~/mine"\nautocommit = true\n'
PUSHED = MINE + "autopush = true\n"


def mine(home: Path, tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """~/mine: a skills repository tracking a bare remote, pushed."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    r = repo(home / "mine", files or {"skills/a/SKILL.md": skill_md("a")})
    git(r, "remote", "add", "origin", str(remote))
    git(r, "push", "-q", "-u", "origin", "master")
    return r


def head(r: Path, rev: str = "HEAD") -> str:
    return git(r, "rev-parse", rev).strip()


def status(r: Path) -> list[str]:
    return git(r, "status", "--porcelain", "--untracked-files=all").splitlines()


def top(r: Path) -> Path:
    return Path(git(r, "rev-parse", "--show-toplevel").strip())


def run(
    cfg: Config, *, dry_run: bool = False
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """The changes, problems and notes an auto-commit makes."""
    result = commit.autocommit(cfg, dry_run=dry_run)
    assert all(c.source == "mine" for c in result.changes)
    return (
        [(c.action, c.detail) for c in result.changes],
        [p.message for p in result.problems],
        [n.message for n in result.notes],
    )


def test_commits_only_the_skill_directories(home: Path, tmp_path: Path) -> None:
    r = mine(
        home,
        tmp_path,
        {
            "skills/a/SKILL.md": skill_md("a"),
            "skills/old/SKILL.md": skill_md("old"),
            "skills/NOTES.md": "notes\n",
            "README.md": "hi\n",
        },
    )
    write(r / "skills" / "a" / "SKILL.md", skill_md("a") + "edited\n")
    shutil.rmtree(r / "skills" / "old")
    write(r / "skills" / "new" / "SKILL.md", skill_md("new"))
    write(r / "skills" / "NOTES.md", "a loose file beside the skills\n")
    write(r / "README.md", "unrelated\n")
    write(r / "other.txt", "staged by hand\n")
    git(r, "add", "other.txt")

    changes, problems, notes = run(load(home, PUSHED))
    assert changes == [
        ("commit", f'"Add new; update a; remove old" ({head(r)[:12]})'),
        ("push", "master to origin/master"),
    ]
    assert (problems, notes) == ([], [])
    assert git(r, "show", "--name-status", "--format=%s", "HEAD").split() == [
        "Add", "new;", "update", "a;", "remove", "old",
        "M", "skills/a/SKILL.md", "A", "skills/new/SKILL.md", "D", "skills/old/SKILL.md",
    ]  # fmt: skip
    assert status(r) == [" M README.md", "A  other.txt", " M skills/NOTES.md"]
    assert head(r, "origin/master") == head(tmp_path / "remote.git", "master") == head(r)


def test_nothing_pending(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    write(r / "README.md", "outside the skills\n")
    assert run(load(home, PUSHED)) == ([], [], [])


def test_dry_run_changes_nothing(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    write(r / "skills" / "a" / "SKILL.md", "edited\n")
    before = head(r)
    changes, _, _ = run(load(home, PUSHED), dry_run=True)
    assert changes == [("commit", '"Update a"'), ("push", "master to origin/master")]
    assert (head(r), status(r)) == (before, [" M skills/a/SKILL.md"])


def test_off_unless_asked(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    write(r / "skills" / "a" / "SKILL.md", "edited\n")
    assert run(load(home, MINE.replace("autocommit = true\n", ""))) == ([], [], [])
    changes, _, _ = run(load(home, MINE))
    assert [a for a, _ in changes] == ["commit"]  # committed, not pushed
    assert head(r, "origin/master") != head(r)


def test_skips_a_repository_in_the_middle_of_something(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    cfg = load(home, PUSHED)
    edited = r / "skills" / "a" / "SKILL.md"

    git(r, "checkout", "-q", "--detach")
    write(edited, "edited\n")
    assert run(cfg) == ([], [], ["not auto-committed: ~/mine is on a detached HEAD"])
    git(r, "checkout", "-q", "master")

    (r / ".git" / "rebase-merge").mkdir()
    assert run(cfg)[2] == ["not auto-committed: ~/mine is mid-rebase"]
    (r / ".git" / "rebase-merge").rmdir()

    git(r, "checkout", "-q", "--", ".")
    git(r, "checkout", "-q", "-b", "other")
    write(edited, "theirs\n")
    git(r, "commit", "-q", "-am", "theirs")
    git(r, "checkout", "-q", "master")
    write(edited, "ours\n")
    git(r, "commit", "-q", "-am", "ours")
    with pytest.raises(subprocess.CalledProcessError):
        git(r, "merge", "-q", "other")
    before = head(r)
    assert run(cfg) == ([], [], ["not auto-committed: ~/mine is mid-merge"])
    assert head(r) == before


def test_not_a_repository(home: Path) -> None:
    write(home / "mine" / "skills" / "a" / "SKILL.md", skill_md("a"))
    assert run(load(home, PUSHED)) == (
        [],
        [],
        ["not auto-committed: ~/mine/skills isn't in a git repository"],
    )


def test_a_failed_push_is_tried_again_next_run(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    cfg = load(home, PUSHED)
    remote = tmp_path / "remote.git"
    git(r, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    write(r / "skills" / "a" / "SKILL.md", "edited\n")
    changes, problems, _ = run(cfg)
    assert [a for a, _ in changes] == ["commit"]
    assert len(problems) == 1
    assert problems[0].startswith("can't push to origin/master: ")
    assert sources.edits(cfg.sources[0], cfg.paths) == ([], ["a"])

    git(r, "remote", "set-url", "origin", str(remote))
    assert run(cfg) == ([("push", "master to origin/master")], [], [])
    assert head(remote, "master") == head(r)
    assert run(cfg) == ([], [], [])


def test_a_rejected_push_is_left_to_the_user(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    remote = tmp_path / "remote.git"
    elsewhere = tmp_path / "elsewhere"
    git(tmp_path, "clone", "-q", str(remote), str(elsewhere))
    git(elsewhere, "commit", "-q", "--allow-empty", "-m", "from another machine")
    git(elsewhere, "push", "-q")
    theirs = head(elsewhere)

    write(r / "skills" / "a" / "SKILL.md", "edited\n")
    changes, problems, _ = run(load(home, PUSHED))
    assert [a for a, _ in changes] == ["commit"]
    assert problems == [
        "can't push to origin/master: origin/master has commits master doesn't; "
        "pull, then push by hand"
    ]
    assert head(remote, "master") == theirs


def test_no_upstream(home: Path) -> None:
    r = repo(home / "mine", {"skills/a/SKILL.md": skill_md("a")})
    write(r / "skills" / "a" / "SKILL.md", "edited\n")
    changes, problems, _ = run(load(home, PUSHED))
    assert [a for a, _ in changes] == ["commit"]
    assert problems == ["can't push: master has no upstream branch; `git push -u` sets one"]


def test_a_failed_commit_leaves_the_edits_staged(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    hook = write(r / "hooks" / "pre-commit", "#!/bin/sh\necho 'not today' >&2\nexit 1\n")
    hook.chmod(0o755)
    git(r, "config", "core.hooksPath", "hooks")
    write(r / "skills" / "b" / "SKILL.md", skill_md("b"))
    before = head(r)
    assert run(load(home, PUSHED)) == (
        [],
        ["can't commit b: not today; the edits are left staged"],
        [],
    )
    assert head(r) == before
    assert "A  skills/b/SKILL.md" in status(r)


def test_skills_at_the_repository_root(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path, {"a/SKILL.md": skill_md("a"), "README.md": "hi\n"})
    write(r / "a" / "SKILL.md", "edited\n")
    write(r / "README.md", "edited\n")
    write(r / ".github" / "workflow.yml", "hidden, so not a skill\n")
    changes, _, _ = run(load(home, MINE + 'subdir = "."\n'))
    assert changes == [("commit", f'"Update a" ({head(r)[:12]})')]
    assert status(r) == [" M README.md", "?? .github/workflow.yml"]


def test_pending_edits_are_what_auto_commit_takes(home: Path) -> None:
    """A skills directory no commit has seen yet counts, and a loose file in it doesn't."""
    r = repo(home / "mine", {"README.md": "hi\n"})
    write(r / "skills" / "a" / "SKILL.md", skill_md("a"))
    write(r / "skills" / "NOTES.md", "loose\n")
    cfg = load(home, MINE)
    assert sources.edits(cfg.sources[0], cfg.paths) == (["a"], [])
    changes, _, _ = run(cfg)
    assert changes == [("commit", f'"Add a" ({head(r)[:12]})')]
    assert status(r) == ["?? skills/NOTES.md"]


def test_message() -> None:
    assert commit.message([], ["a"], []) == "Update a"
    assert commit.message(["n"], ["a", "b"], ["o"]) == "Add n; update a, b; remove o"
    assert commit.message([], [], ["o"]) == "Remove o"


def test_paths_are_the_repository(home: Path, tmp_path: Path) -> None:
    r = mine(home, tmp_path)
    write(r / "skills" / "a" / "SKILL.md", "edited\n")
    result = commit.autocommit(load(home, PUSHED))
    assert {c.path for c in result.changes} == {top(r)}

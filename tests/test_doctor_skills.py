from __future__ import annotations

from pathlib import Path

import pytest

from tack.doctor import skills
from tack.doctor.findings import Finding
from tests.helpers import git, link, load, repo, skill, write


def findings(home: Path, manifest: str | None = None) -> list[Finding]:
    return list(skills.check(load(home, manifest)))


def by_path(fs: list[Finding]) -> dict[tuple[str, Path | None], Finding]:
    return {(f.id, f.path): f for f in fs}


MINE = '[[source]]\nname = "mine"\npath = "~/mine"\n'


def test_clean_deployment_has_no_findings(home: Path) -> None:
    a = skill(home / "mine" / "skills", "a")
    link(home / ".claude" / "skills" / "a", a)
    link(home / ".agents" / "skills" / "a", a)
    assert findings(home, MINE) == []


def test_unmanaged_and_ignored_entries(home: Path) -> None:
    claude = home / ".claude" / "skills"
    skill(claude, "hand-made")
    skill(claude, "synced")  # Claude Code's own: ignored by default
    skill(claude, "installer")  # ignored in the manifest
    write(claude / ".DS_Store")
    link(claude / "chezmoi-made", skill(home / "lib", "chezmoi-made"))
    fs = findings(home, '[harness.claude-code]\nignore = ["installer"]\n')
    assert [(f.id, f.path, f.harness) for f in fs] == [
        ("unmanaged-skill", claude / "chezmoi-made", "claude-code"),
        ("unmanaged-skill", claude / "hand-made", "claude-code"),
    ]
    assert "links to ~/lib/chezmoi-made" in fs[0].message
    assert fs[1].message == "a real directory, outside tack"


def test_dangling_link(home: Path) -> None:
    entry = link(home / ".agents" / "skills" / "gone", home / "nowhere")
    (f,) = findings(home)
    assert (f.id, f.severity, f.path, f.harness) == ("dangling-link", "error", entry, "codex")


def test_not_synced_cases(home: Path) -> None:
    for name in ("a", "b", "c"):
        skill(home / "mine" / "skills", name)
    claude, codex = home / ".claude" / "skills", home / ".agents" / "skills"
    link(claude / "a", skill(home / "old-copy", "a"))  # points elsewhere
    skill(codex, "a")  # a real directory in the way
    link(claude / "b", home / "mine" / "skills" / "b")
    link(codex / "b", home / "mine" / "skills" / "b")
    link(claude / "c", home / "mine" / "skills" / "c")
    # codex/c is missing
    fs = by_path(findings(home, MINE))
    assert set(fs) == {
        ("not-synced", claude / "a"),
        ("not-synced", codex / "a"),
        ("not-synced", codex / "c"),
    }
    assert "links to ~/old-copy/a; the manifest deploys it from mine" in (
        fs["not-synced", claude / "a"].message
    )
    assert fs["not-synced", codex / "a"].message == (
        "a real directory; the manifest deploys it from mine (~/mine/skills/a); "
        "`tack sync --adopt` replaces it"
    )
    assert fs["not-synced", codex / "c"].message.startswith("missing;")


def test_stale_tack_link_is_not_synced(home: Path) -> None:
    skill(home / "mine" / "skills", "keep")
    skill(home / "mine" / "skills", "drop")
    entry = link(home / ".claude" / "skills" / "drop", home / "mine" / "skills" / "drop")
    link(home / ".claude" / "skills" / "keep", home / "mine" / "skills" / "keep")
    link(home / ".agents" / "skills" / "keep", home / "mine" / "skills" / "keep")
    (f,) = findings(home, MINE.replace('path = "~/mine"', 'path = "~/mine"\nskills = ["keep"]'))
    assert (f.id, f.path) == ("not-synced", entry)
    assert "a tack link the manifest no longer deploys to claude-code" in f.message


def test_listed_skill_missing_from_source(home: Path) -> None:
    skill(home / "mine" / "skills", "a")
    fs = findings(home, MINE + 'skills = ["nope"]\n')
    (f,) = fs
    assert (f.id, f.path) == ("not-synced", home / "mine" / "skills" / "nope")
    assert "which has no such skill" in f.message


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        (MINE, "has no directory at ~/mine"),
        ('[[source]]\nname = "g"\ngit = "https://example.com/g.git"\n', "not checked out yet"),
    ],
)
def test_absent_source(home: Path, manifest: str, message: str) -> None:
    (f,) = findings(home, manifest)
    assert f.id == "not-synced"
    assert message in f.message


def test_source_without_skills_dir(home: Path) -> None:
    (home / "mine").mkdir()
    (f,) = findings(home, MINE)
    assert "has no skills directory at ~/mine/skills" in f.message


@pytest.mark.parametrize("selection", ["[]", '"*"'])
def test_path_source_presence_without_a_skills_directory(home: Path, selection: str) -> None:
    root = home / "mine"
    root.mkdir()
    manifest = MINE + f"skills = {selection}\n"

    fs = findings(home, manifest)

    if selection == "[]":
        assert fs == []
    else:
        (finding,) = fs
        assert (finding.id, finding.message) == (
            "not-synced",
            "source 'mine' has no skills directory at ~/mine/skills",
        )
    root.rmdir()
    (finding,) = findings(home, manifest)
    assert (finding.id, finding.message) == (
        "not-synced",
        "source 'mine' has no directory at ~/mine",
    )


def test_name_collision(home: Path) -> None:
    skill(home / "one" / "skills", "dup")
    skill(home / "two" / "skills", "dup")
    fs = findings(
        home,
        '[[source]]\nname = "one"\npath = "~/one"\n[[source]]\nname = "two"\npath = "~/two"\n',
    )
    collisions = [f for f in fs if f.id == "name-collision"]
    assert len(collisions) == 1
    assert collisions[0].severity == "error"
    assert "'dup' is selected from sources one, two for claude-code, codex" in (
        collisions[0].message
    )
    # Neither is deployed, so nothing is reported missing for it.
    assert [f.id for f in fs if f.id != "name-collision"] == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (None, "no SKILL.md"),
        ("# Just a heading\n", "SKILL.md has no frontmatter"),
        ("---\nname: s\ndescription: never closed\n", "SKILL.md has no frontmatter"),
        ("---\nname: s\n---\n", "SKILL.md frontmatter has no description"),
        ("---\nname: s\ndescription: ''\n---\n", "SKILL.md frontmatter has no description"),
        ("---\nname: other\ndescription: x\n---\n", "SKILL.md names the skill 'other'"),
        ("---\ndescription: x\n---\n", None),  # the name is optional
        ("---\nname: 's'\ndescription: >\n  Folded\n  text.\n---\n", None),
        ('---\nname: "s"\ndescription: |\n  Literal.\nmetadata:\n  a: b\n---\n', None),
    ],
)
def test_bad_skill(home: Path, text: str | None, problem: str | None) -> None:
    d = home / "mine" / "skills" / "s"
    d.mkdir(parents=True)
    if text is not None:
        write(d / "SKILL.md", text)
    got = skills.skill_problem(d)
    if problem is None:
        assert got is None
    else:
        assert got
        assert got.startswith(problem)


def test_bad_skill_is_reported_for_selected_skills_only(home: Path) -> None:
    (home / "mine" / "skills" / "broken").mkdir(parents=True)
    (home / "mine" / "skills" / "ignored-broken").mkdir(parents=True)
    fs = findings(home, MINE + 'skills = ["broken"]\n')
    bad = [f for f in fs if f.id == "bad-skill"]
    assert [(f.path, f.message) for f in bad] == [
        (home / "mine" / "skills" / "broken", "no SKILL.md")
    ]


def test_frontmatter_reader() -> None:
    text = "---\nname: x\ndescription: >-\n  one\n  two\nnested:\n  key: v\n---\nbody: no\n"
    assert skills.frontmatter(text) == {"name": "x", "description": "one two", "nested": "key: v"}
    assert skills.frontmatter("﻿---\ndescription: 'quoted'\n---\n") == {"description": "quoted"}


def test_dirty_source(home: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare", "-b", "master")
    mine = repo(
        home / "mine",
        {
            "skills/a/SKILL.md": "---\ndescription: a\n---\n",
            "skills/b/SKILL.md": "---\ndescription: b\n---\n",
            "README.md": "hi\n",
        },
    )
    git(mine, "remote", "add", "origin", str(remote))
    git(mine, "push", "-q", "-u", "origin", "master")
    for name in ("a", "b"):
        link(home / ".claude" / "skills" / name, mine / "skills" / name)
        link(home / ".agents" / "skills" / name, mine / "skills" / name)
    assert findings(home, MINE) == []

    write(mine / "README.md", "unrelated edit\n")  # outside the skills dir: not reported
    assert findings(home, MINE) == []

    write(mine / "skills" / "a" / "SKILL.md", "---\ndescription: edited\n---\n")
    write(mine / "skills" / "new" / "notes.md", "untracked\n")
    (f,) = [f for f in findings(home, MINE) if f.id == "dirty-source"]
    assert f.severity == "info"
    assert f.message == "source 'mine' has uncommitted edits to a, new"

    git(mine, "add", "skills/a")
    git(mine, "commit", "-q", "-m", "edit a")
    git(mine, "mv", "skills/b", "skills/b2")
    (f,) = [f for f in findings(home, MINE) if f.id == "dirty-source"]
    assert f.message == (
        "source 'mine' has uncommitted edits to b, b2, new; unpushed commits touching a"
    )


def test_dirty_source_ignores_non_git_paths(home: Path) -> None:
    skill(home / "mine" / "skills", "a")
    assert [f for f in findings(home, MINE) if f.id == "dirty-source"] == []

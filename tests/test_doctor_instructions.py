from __future__ import annotations

from pathlib import Path

import pytest

from tack.doctor import instructions
from tests.helpers import git, ids, load, repo, write


def test_imports_follow_claude_code_rules(home: Path) -> None:
    d = home / "p"
    f = write(
        d / "CLAUDE.md",
        "@AGENTS.md\n"
        "See @docs/more.md for details.\n"
        "Mail me at me@example.com, not an import.\n"
        "`@in-a-span.md` and <!-- @in-a-comment.md -->\n"
        "```\n@in-a-fence.md\n```\n"
        "@~/global.md\n"
        "@/abs/file.md\n",
    )
    write(d / "docs" / "more.md")
    assert instructions.imports(f) == [
        d / "AGENTS.md",
        d / "docs" / "more.md",
        home / "global.md",
        Path("/abs/file.md"),
    ]


def test_trailing_punctuation_is_dropped_when_the_path_needs_it(home: Path) -> None:
    f = write(home / "CLAUDE.md", "Read @AGENTS.md.\n")
    assert instructions.imports(f) == [home / "AGENTS.md."]
    write(home / "AGENTS.md")
    assert instructions.imports(f) == [home / "AGENTS.md"]


def test_reads_is_transitive_and_counts_symlinks(home: Path) -> None:
    agents = write(home / "AGENTS.md", "shared\n")
    write(home / "mid.md", "@AGENTS.md\n")
    top = write(home / "CLAUDE.md", "@mid.md\n")
    assert instructions.reads(top, agents)
    assert not instructions.reads(agents, top)
    alias = home / "alias.md"
    alias.symlink_to(agents)
    assert instructions.reads(alias, agents)
    assert not instructions.reads(top, home / "missing.md")
    # Imports are followed at most five hops.
    for i in range(6):
        write(home / f"hop{i}.md", f"@hop{i + 1}.md\n")
    write(home / "hop6.md", "@AGENTS.md\n")
    assert not instructions.reads(home / "hop0.md", agents)
    assert instructions.reads(home / "hop2.md", agents)


@pytest.mark.parametrize(
    ("claude", "codex", "split"),
    [
        (None, None, False),
        ("<!-- Claude-only notes below -->\n@~/.codex/AGENTS.md\n", "shared\n", False),
        ("same text\n", "same text\n\n", False),
        ("claude's own\n", "codex's own\n", True),
        ("instructions\n", None, True),
        (None, "instructions\n", True),
        ("", None, False),
    ],
)
def test_global_instructions_split(
    home: Path, claude: str | None, codex: str | None, split: bool
) -> None:
    if claude is not None:
        write(home / ".claude" / "CLAUDE.md", claude)
    if codex is not None:
        write(home / ".codex" / "AGENTS.md", codex)
    fs = list(instructions.check_global(load(home)))
    assert ids(fs) == (["instructions-split"] if split else [])


def test_global_symlink_is_not_a_split(home: Path) -> None:
    write(home / ".codex" / "AGENTS.md", "shared\n")
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").symlink_to(home / ".codex" / "AGENTS.md")
    assert list(instructions.check_global(load(home))) == []


def test_only_a_harness_that_follows_imports_counts_them(home: Path) -> None:
    # Codex doesn't follow imports, so its file importing Claude's doesn't help.
    write(home / ".claude" / "CLAUDE.md", "claude\n")
    write(home / ".codex" / "AGENTS.md", "@~/.claude/CLAUDE.md\n")
    assert ids(instructions.check_global(load(home))) == ["instructions-split"]


def project_ids(home: Path, project: Path) -> list[str]:
    return ids(instructions.check_project(load(home), project))


def test_project_conventional_layout_is_clean(home: Path) -> None:
    p = repo(home / "p", {"AGENTS.md": "shared\n", "CLAUDE.md": "@AGENTS.md\n"})
    write(p / "CLAUDE.local.md", "personal, and CLAUDE.md already imports AGENTS.md\n")
    assert project_ids(home, p) == []


def test_agents_md_missing(home: Path) -> None:
    p = repo(home / "p", {"CLAUDE.md": "instructions\n"})
    (f,) = instructions.check_project(load(home), p)
    assert (f.id, f.severity, f.fix, f.project) == ("agents-md-missing", "error", "agents-md", p)
    empty = repo(home / "empty", {"CLAUDE.md": "\n"})
    assert project_ids(home, empty) == []


def test_claude_md_no_import(home: Path) -> None:
    p = repo(home / "p", {"AGENTS.md": "shared\n", "CLAUDE.md": "a copy\n"})
    assert project_ids(home, p) == ["claude-md-no-import"]
    (p / "CLAUDE.md").unlink()
    (p / "CLAUDE.md").symlink_to("AGENTS.md")
    assert project_ids(home, p) == []


def test_instructions_untracked(home: Path) -> None:
    p = repo(home / "p", {"AGENTS.md": "shared\n"})
    write(p / "CLAUDE.md", "@AGENTS.md\n")
    (f,) = instructions.check_project(load(home), p)
    assert f.id == "instructions-untracked"
    assert f.message == "AGENTS.md is committed but CLAUDE.md isn't"
    git(p, "add", "CLAUDE.md")
    assert project_ids(home, p) == []


def test_untracked_check_needs_a_repository(home: Path) -> None:
    p = home / "plain"
    write(p / "AGENTS.md", "shared\n")
    write(p / "CLAUDE.md", "@AGENTS.md\n")
    assert project_ids(home, p) == []


def test_local_md_suppresses_agents(home: Path) -> None:
    p = repo(home / "p", {"AGENTS.md": "shared\n"})
    write(p / "CLAUDE.local.md", "personal notes\n")
    assert project_ids(home, p) == ["local-md-suppresses-agents"]
    write(p / "CLAUDE.local.md", "@AGENTS.md\npersonal notes\n")
    assert project_ids(home, p) == []


def test_local_md_without_agents_md_is_fine(home: Path) -> None:
    p = repo(home / "p")
    write(p / "CLAUDE.local.md", "personal notes\n")
    assert project_ids(home, p) == []

from __future__ import annotations

from pathlib import Path

from tack.doctor import project_skills
from tests.helpers import ids, load, skill, write


def check(home: Path, project: Path) -> list[str]:
    return ids(project_skills.check(load(home), project))


def test_symlinked_claude_skills_is_the_convention(home: Path) -> None:
    p = home / "p"
    skill(p / ".agents" / "skills", "deploy")
    (p / ".claude").mkdir()
    (p / ".claude" / "skills").symlink_to("../.agents/skills")
    assert check(home, p) == []


def test_no_skills_anywhere(home: Path) -> None:
    p = home / "p"
    write(p / ".claude" / "skills" / ".DS_Store")  # an empty skills dir
    (p / ".codex" / "skills").mkdir(parents=True)
    assert check(home, p) == []


def test_codex_skills_dir(home: Path) -> None:
    p = home / "p"
    skill(p / ".codex" / "skills", "a")
    (f,) = project_skills.check(load(home), p)
    assert (f.id, f.severity, f.fix) == ("codex-skills-dir", "error", "skills-dir")
    assert f.message.endswith("skills there: a")


def test_codex_skills_dir_linked_to_agents_is_harmless(home: Path) -> None:
    p = home / "p"
    skill(p / ".agents" / "skills", "a")
    for d in (".codex", ".claude"):
        (p / d).mkdir()
        (p / d / "skills").symlink_to("../.agents/skills")
    assert check(home, p) == []


def test_codex_only_skills(home: Path) -> None:
    p = home / "p"
    skill(p / ".agents" / "skills", "a")
    skill(p / ".agents" / "skills", "b")
    skill(p / ".claude" / "skills", "a")
    (f, dup) = project_skills.check(load(home), p)
    assert (f.id, f.severity, f.fix) == ("codex-only-skills", "error", "skills-dir")
    assert (
        f.message
        == "Claude Code can't see skills in .agents/skills that aren't in .claude/skills: b"
    )
    assert dup.id == "duplicate-skill-copies"


def test_claude_only_skills(home: Path) -> None:
    p = home / "p"
    skill(p / ".claude" / "skills", "a")
    skill(p / ".claude" / "skills", "b")
    (f,) = project_skills.check(load(home), p)
    assert (f.id, f.severity) == ("claude-only-skills", "error")
    assert f.message.endswith("a, b")


def test_duplicate_copies(home: Path) -> None:
    p = home / "p"
    skill(p / ".claude" / "skills", "a")
    skill(p / ".claude" / "skills", "only-claude")
    skill(p / ".agents" / "skills", "a")
    assert check(home, p) == ["claude-only-skills", "duplicate-skill-copies"]


def test_per_skill_links_are_not_copies(home: Path) -> None:
    p = home / "p"
    skill(p / ".agents" / "skills", "a")
    (p / ".claude" / "skills").mkdir(parents=True)
    (p / ".claude" / "skills" / "a").symlink_to("../../.agents/skills/a")
    assert check(home, p) == []

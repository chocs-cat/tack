from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tack import doctor
from tack.config import Config, UsageError
from tack.scaffold import scaffold
from tests.helpers import git, load, repo, skill, write


def fixes(cfg: Config, project: Path) -> list[str]:
    """The ids of the project's findings that have a fix."""
    return [f.id for f in doctor.check_project(cfg, project) if f.fix]


def staged(project: Path) -> list[str]:
    return git(project, "diff", "--cached", "--name-status", "--no-renames").splitlines()


def run(
    cfg: Config, fix: str, project: Path, **kw: Any
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    result = scaffold(cfg, fix, project, **kw)
    return (
        [(c.action, c.detail) for c in result.changes],
        [p.message for p in result.problems],
        [n.message for n in result.notes],
    )


# --- agents-md --------------------------------------------------------------------


CLAUDE = """\
# Project

Build with `make`.
Ask Claude to run the tests.

@docs/style.md
"""


def test_agents_md_moves_claude_md(home: Path) -> None:
    p = repo(home / "p", {"CLAUDE.md": CLAUDE, "docs/style.md": "style\n"})
    cfg = load(home)
    assert fixes(cfg, p) == ["agents-md-missing"]
    changes, problems, notes = run(cfg, "agents-md", p)
    assert changes == [("move", "CLAUDE.md -> AGENTS.md"), ("write", "CLAUDE.md")]
    assert problems == []
    assert notes == [
        "AGENTS.md:4 names one agent: Ask Claude to run the tests.",
        "AGENTS.md:6 imports docs/style.md, which Codex doesn't follow",
    ]
    assert (p / "AGENTS.md").read_text() == CLAUDE
    assert (p / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert staged(p) == ["A\tAGENTS.md", "M\tCLAUDE.md"]
    assert fixes(cfg, p) == []

    git(p, "commit", "-q", "-m", "move")
    assert git(p, "log", "--follow", "--format=%s", "--", "AGENTS.md").split() == ["move", "init"]


def test_agents_md_keeps_what_only_claude_md_has(home: Path) -> None:
    shared = "# Project\n\nBuild with `make`.\n"
    fence = "```sh\nmake\n\nmake test\n```\n"
    p = repo(
        home / "p",
        {
            "AGENTS.md": shared + "\n" + fence,
            "CLAUDE.md": shared + "\nUse the AskUserQuestion tool.\n\n" + fence,
        },
    )
    cfg = load(home)
    assert fixes(cfg, p) == ["claude-md-no-import"]
    changes, _, notes = run(cfg, "agents-md", p)
    assert changes == [("write", "CLAUDE.md")]
    assert (p / "CLAUDE.md").read_text() == "@AGENTS.md\n\nUse the AskUserQuestion tool.\n"
    assert notes == [
        "CLAUDE.md:3 is for Claude Code only; move what Codex needs to AGENTS.md",
    ]
    assert staged(p) == ["M\tCLAUDE.md"]
    assert fixes(cfg, p) == []


def test_agents_md_beside_a_local_file(home: Path) -> None:
    p = repo(home / "p", {"AGENTS.md": "shared\n", ".gitignore": "CLAUDE.local.md\n"})
    write(p / "CLAUDE.local.md", "mine\n")
    cfg = load(home)
    assert fixes(cfg, p) == ["local-md-suppresses-agents"]
    changes, _, _ = run(cfg, "agents-md", p)
    assert changes == [("write", "CLAUDE.md")]
    assert (p / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert staged(p) == ["A\tCLAUDE.md"]
    assert fixes(cfg, p) == []


def test_agents_md_drops_a_redundant_local_import(home: Path) -> None:
    p = repo(home / "p", {"AGENTS.md": "shared\n", "CLAUDE.md": "shared\n"})
    write(p / "CLAUDE.local.md", "mine\n@AGENTS.md\n")  # untracked: stays so
    cfg = load(home)
    changes, _, _ = run(cfg, "agents-md", p)
    assert changes == [("write", "CLAUDE.md"), ("write", "CLAUDE.local.md")]
    assert (p / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert (p / "CLAUDE.local.md").read_text() == "mine\n"
    assert staged(p) == ["M\tCLAUDE.md"]


def test_dry_run_shows_diffs_and_changes_nothing(home: Path) -> None:
    p = repo(home / "p", {"CLAUDE.md": "rules\n"})
    result = scaffold(load(home), "agents-md", p, dry_run=True)
    assert [(c.action, c.detail) for c in result.changes] == [
        ("move", "CLAUDE.md -> AGENTS.md"),
        ("write", "CLAUDE.md"),
    ]
    assert result.changes[1].diff == "--- /dev/null\n+++ b/CLAUDE.md\n@@ -0,0 +1 @@\n+@AGENTS.md\n"
    assert not (p / "AGENTS.md").exists()
    assert (staged(p), (p / "CLAUDE.md").read_text()) == ([], "rules\n")


def test_nothing_to_fix(home: Path) -> None:
    p = repo(home / "p", {"AGENTS.md": "x\n", "CLAUDE.md": "@AGENTS.md\n"})
    assert run(load(home), "agents-md", p) == ([], [], [])


def test_usage(home: Path) -> None:
    cfg = load(home)
    with pytest.raises(UsageError, match="no fix named"):
        scaffold(cfg, "tidy", home)
    with pytest.raises(UsageError, match="--from applies to the hooks fix"):
        scaffold(cfg, "agents-md", home, source="codex")
    with pytest.raises(UsageError, match="no harness named"):
        scaffold(cfg, "hooks", home, source="pi")
    with pytest.raises(UsageError, match="no directory"):
        scaffold(cfg, "hooks", home / "nowhere")


# --- skills-dir -------------------------------------------------------------------


def test_skills_dir(home: Path) -> None:
    p = repo(home / "p", {".gitignore": ".DS_Store\n"})
    skill(p / ".claude" / "skills", "a")
    skill(p / ".agents" / "skills", "a")  # an identical copy
    skill(p / ".codex" / "skills", "c")
    git(p, "add", "-A")
    git(p, "commit", "-q", "-m", "skills")
    skill(p / ".claude" / "skills", "b")  # untracked: stays so
    write(p / ".claude" / "skills" / ".DS_Store", "junk")
    cfg = load(home)
    assert fixes(cfg, p) == ["codex-skills-dir", "claude-only-skills", "duplicate-skill-copies"]

    changes, problems, _ = run(cfg, "skills-dir", p)
    assert problems == []
    assert changes == [
        ("move", ".claude/skills/b -> .agents/skills/b"),
        ("move", ".codex/skills/c -> .agents/skills/c"),
        ("delete", ".claude/skills/a"),
        ("delete", ".claude/skills"),
        ("delete", ".codex/skills"),
        ("link", ".claude/skills -> ../.agents/skills"),
    ]
    assert sorted(e.name for e in (p / ".agents" / "skills").iterdir()) == ["a", "b", "c"]
    assert (p / ".claude" / "skills").readlink() == Path("../.agents/skills")
    assert not (p / ".codex" / "skills").exists()
    assert staged(p) == [
        "A\t.agents/skills/c/SKILL.md",
        "A\t.claude/skills",
        "D\t.claude/skills/a/SKILL.md",
        "D\t.codex/skills/c/SKILL.md",
    ]
    assert "?? .agents/skills/b/" in git(p, "status", "--porcelain")
    assert fixes(cfg, p) == []


def test_skills_dir_refuses_differing_copies(home: Path) -> None:
    p = repo(home / "p")
    skill(p / ".claude" / "skills", "a", description="Mine.")
    skill(p / ".agents" / "skills", "a", description="Theirs.")
    changes, problems, _ = run(load(home), "skills-dir", p)
    assert changes == []
    assert problems == [
        "these differ from their namesakes, so tack can't tell which to keep: "
        ".claude/skills/a (and .agents/skills/a); reconcile them by hand"
    ]
    assert (p / ".claude" / "skills" / "a").is_dir()


def test_skills_only_codex_sees(home: Path) -> None:
    p = repo(home / "p")
    skill(p / ".agents" / "skills", "a")
    cfg = load(home)
    assert fixes(cfg, p) == ["codex-only-skills"]
    changes, _, _ = run(cfg, "skills-dir", p)
    assert changes == [("link", ".claude/skills -> ../.agents/skills")]
    assert fixes(cfg, p) == []


def test_a_linked_skill_keeps_pointing_where_it_did(home: Path) -> None:
    p = repo(home / "p")
    skill(p / "vendor", "x")
    (p / ".claude" / "skills").mkdir(parents=True)
    (p / ".claude" / "skills" / "x").symlink_to("../../vendor/x")
    run(load(home), "skills-dir", p)
    moved = p / ".agents" / "skills" / "x"
    assert moved.readlink() == Path("../../vendor/x")
    assert moved.resolve() == (p / "vendor" / "x").resolve()


# --- hooks ------------------------------------------------------------------------


def hooks_json(*entries: tuple[str, str, dict[str, Any]], **extra: Any) -> str:
    out: dict[str, list[Any]] = {}
    for event, matcher, hook in entries:
        out.setdefault(event, []).append({"matcher": matcher, "hooks": [hook]})
    return json.dumps({**extra, "hooks": out}, indent=2)


def command(cmd: str, **extra: Any) -> dict[str, Any]:
    return {"type": "command", "command": cmd, **extra}


def test_hooks_copies_to_codex(home: Path) -> None:
    gate = {
        "type": "command",
        "command": "python3",
        "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/check.py"],
        "timeout": 5,
    }
    p = repo(home / "p", {".claude/settings.json": hooks_json(("PreToolUse", "Bash", gate))})
    write(p / ".claude" / "hooks" / "check.py", "json.load(sys.stdin)['tool_input']['command']")
    cfg = load(home)
    assert fixes(cfg, p) == ["hook-one-harness"]
    changes, problems, notes = run(cfg, "hooks", p)
    assert (changes, problems) == ([("write", ".codex/hooks.json")], [])
    assert notes == ["Codex asks you to trust new or changed hooks: run /hooks in Codex here"]
    assert json.loads((p / ".codex" / "hooks.json").read_text()) == {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        command(
                            'python3 "$(git rev-parse --show-toplevel)"/.claude/hooks/check.py',
                            timeout=5,
                        )
                    ],
                }
            ]
        }
    }
    assert staged(p) == ["A\t.codex/hooks.json"]
    assert [f.id for f in doctor.check_project(cfg, p)] == []


def test_hooks_copies_to_claude_code(home: Path) -> None:
    p = repo(
        home / "p",
        {
            ".claude/settings.json": json.dumps({"permissions": {"allow": ["Bash(ls)"]}}),
            ".codex/hooks.json": hooks_json(
                ("PostToolUse", "apply_patch", command("jq .tool_input.command | fmt")),
                ("SessionStart", "startup", command("./hooks/hello", statusMessage="hi")),
            ),
        },
    )
    cfg = load(home)
    changes, _, notes = run(cfg, "hooks", p)
    assert changes == [("write", ".claude/settings.json")]
    settings = json.loads((p / ".claude" / "settings.json").read_text())
    assert settings == {
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {
            "PostToolUse": [
                {"matcher": "Edit|Write", "hooks": [command("jq .tool_input.command | fmt")]}
            ],
            "SessionStart": [
                {"matcher": "startup", "hooks": [command("./hooks/hello", statusMessage="hi")]}
            ],
        },
    }
    assert notes == [
        "codex's PostToolUse [apply_patch] `jq .tool_input.command | fmt` reads the tool "
        "payload, and the harnesses describe edits differently (Claude Code sends file_path, "
        "Codex a patch in tool_input.command); check that it works for claude-code"
    ]
    assert [f.id for f in doctor.check_project(cfg, p)] == []


def test_hooks_warn_about_what_does_not_carry_over(home: Path) -> None:
    p = repo(
        home / "p",
        {
            ".claude/settings.json": hooks_json(
                ("PreToolUse", "Grep|Glob|Bash", command("gate", once=True)),
                ("Stop", "", {"type": "prompt", "prompt": "Done?"}),
            )
        },
    )
    changes, _, notes = run(load(home), "hooks", p)
    assert changes == [("write", ".codex/hooks.json")]
    assert notes == [
        "claude-code's PreToolUse [Grep|Glob|Bash] `gate`: its once isn't copied to codex",
        "claude-code's PreToolUse [Grep|Glob|Bash] `gate`: Codex has no Grep, Glob tool, so "
        "that part of the matcher never fires there",
        """claude-code's Stop `{"prompt": "Done?", "type": "prompt"}` isn't a command hook, """
        "so tack can't copy it to codex",
        "Codex asks you to trust new or changed hooks: run /hooks in Codex here",
    ]
    doc = json.loads((p / ".codex" / "hooks.json").read_text())
    assert doc == {
        "hooks": {"PreToolUse": [{"matcher": "Grep|Glob|Bash", "hooks": [command("gate")]}]}
    }


def test_hooks_mismatch_needs_from(home: Path) -> None:
    p = repo(
        home / "p",
        {
            ".claude/settings.json": hooks_json(("PreToolUse", "Bash", command("./gate --strict"))),
            ".codex/hooks.json": hooks_json(
                ("PreToolUse", "Bash", command("./gate --strict", timeout=9)),
                ("PostToolUse", "Bash", command("./gate --strict")),
                ("Stop", "", command("./done")),
            ),
        },
    )
    cfg = load(home)
    assert fixes(cfg, p) == ["hook-mismatch", "hook-one-harness"]
    before = (p / ".codex" / "hooks.json").read_text()
    changes, problems, _ = run(cfg, "hooks", p)
    assert changes == []
    assert problems == [
        "counterpart hooks differ -- claude-code: PreToolUse [Bash] `./gate --strict`; "
        "codex: PreToolUse [Bash] `./gate --strict`, PostToolUse [Bash] `./gate --strict`; "
        "`--from HARNESS` says whose version to keep"
    ]
    assert (p / ".codex" / "hooks.json").read_text() == before

    changes, problems, _ = run(cfg, "hooks", p, source="claude-code")
    assert (changes, problems) == (
        [("write", ".codex/hooks.json"), ("write", ".claude/settings.json")],
        [],
    )
    doc = json.loads((p / ".codex" / "hooks.json").read_text())
    assert doc["hooks"] == {
        "Stop": [{"matcher": "", "hooks": [command("./done")]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [command("./gate --strict")]}],
    }
    assert [f.id for f in doctor.check_project(cfg, p)] == []


def test_hooks_leave_codex_config_toml_alone(home: Path) -> None:
    toml = '[[hooks.PreToolUse]]\nmatcher = "Bash"\n\n[[hooks.PreToolUse.hooks]]\n'
    toml += 'type = "command"\ncommand = "./gate"\n'
    p = repo(
        home / "p",
        {
            ".claude/settings.json": hooks_json(("PreToolUse", "Edit", command("./gate"))),
            ".codex/config.toml": toml,
        },
    )
    _, problems, _ = run(load(home), "hooks", p, source="claude-code")
    assert problems == [
        "PreToolUse [Bash] `./gate` would have to change in .codex/config.toml, which tack "
        "doesn't edit; change it by hand"
    ]

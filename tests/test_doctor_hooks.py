from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tack.doctor import hooks
from tests.helpers import ids, load, write


def settings(*entries: tuple[str, str, str], **extra: Any) -> str:
    """A hooks JSON file from (event, matcher, command) triples."""
    out: dict[str, list] = {}
    for event, matcher, command in entries:
        out.setdefault(event, []).append(
            {"matcher": matcher, "hooks": [{"type": "command", "command": command, **extra}]}
        )
    return json.dumps({"hooks": out})


def codex_toml(*entries: tuple[str, str, str]) -> str:
    lines = ['model = "gpt"\n']
    for event, matcher, command in entries:
        lines.append(f'[[hooks.{event}]]\nmatcher = "{matcher}"\n')
        lines.append(f"[[hooks.{event}.hooks]]\ntype = \"command\"\ncommand = '{command}'\n")
    lines.append('[hooks.state."x"]\ntrusted_hash = "sha256:0"\n')
    return "\n".join(lines)


def test_read_json_and_toml(home: Path) -> None:
    j = write(home / "s.json", settings(("PreToolUse", "Bash", "check"), timeout=5))
    t = write(home / "c.toml", codex_toml(("SessionStart", "startup|resume", "/x/reminder")))
    assert hooks.read(j) == [hooks.Hook("PreToolUse", "Bash", "check", j)]
    assert hooks.read(t) == [hooks.Hook("SessionStart", "startup|resume", "/x/reminder", t)]
    assert hooks.read(home / "missing.json") == []
    assert hooks.read(write(home / "no-hooks.json", '{"model": "x"}')) == []
    with pytest.raises(hooks.HookFileError):
        hooks.read(write(home / "bad.json", "{"))


def test_command_args_and_non_command_hooks(home: Path) -> None:
    f = write(
        home / "s.json",
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "python3", "args": ["a b.py"]},
                                {"type": "prompt", "prompt": "Is this safe?", "timeout": 3},
                            ],
                        }
                    ]
                }
            }
        ),
    )
    a, b = hooks.read(f)
    assert a.command == "python3 'a b.py'"
    assert b.command == '{"prompt": "Is this safe?", "type": "prompt"}'


def test_signature_ignores_where_scripts_live(home: Path) -> None:
    def sig(command: str) -> str:
        return hooks.Hook("E", "", command, home).signature

    assert sig("~/.claude/hooks/gate") == sig("'/Users/someone/.codex/hooks/gate'") == "gate"
    assert sig("bash '/a/state.sh' session") == sig("bash /b/state.sh session")
    assert sig("bash /a/state.sh session") != sig("bash /a/state.sh end")
    assert sig("unbalanced 'quote") == "unbalanced 'quote"


def test_matcher_alternatives() -> None:
    def alts(matcher: str) -> frozenset[str]:
        return hooks.Hook("E", matcher, "c", Path()).alternatives

    assert alts("startup | resume") == {"startup", "resume"}
    assert alts("") == alts("*") == {"*"}


def test_global_counterparts_across_file_formats(home: Path) -> None:
    write(
        home / ".claude" / "settings.json",
        settings(
            ("SessionStart", "startup", "~/.claude/hooks/reminder"),
            ("SessionStart", "resume", "~/.claude/hooks/reminder"),
            ("PreToolUse", "Grep|Glob", "~/.claude/hooks/gate"),
            ("Stop", "", "notify-me"),
        ),
    )
    write(
        home / ".codex" / "config.toml",
        codex_toml(
            ("SessionStart", "startup|resume", f"{home}/.codex/hooks/reminder"),
            ("PostToolUse", "Grep|Glob", f"{home}/.codex/hooks/gate"),
        ),
    )
    fs = list(hooks.check_global(load(home)))
    assert [(f.id, f.severity, f.harness) for f in fs] == [
        ("hook-one-harness", "info", "claude-code"),  # PreToolUse gate
        ("hook-one-harness", "info", "claude-code"),  # Stop notify-me
        ("hook-one-harness", "info", "codex"),  # PostToolUse gate
    ]
    assert "Stop `notify-me` is registered for claude-code, not codex" in fs[1].message


def test_global_unreadable_hook_file(home: Path) -> None:
    f = write(home / ".codex" / "hooks.json", "not json")
    (finding,) = hooks.check_global(load(home))
    assert (finding.id, finding.severity, finding.path) == ("unreadable-file", "error", f)


def project_findings(home: Path, p: Path) -> list:
    return list(hooks.check_project(load(home), p))


def test_project_identical_hooks_are_clean(home: Path) -> None:
    p = home / "p"
    body = settings(("PostToolUse", "Edit|Write", 'node "$(git rev-parse --show-toplevel)/s.mjs"'))
    write(p / ".claude" / "settings.json", body)
    write(p / ".codex" / "hooks.json", body)
    assert project_findings(home, p) == []


def test_project_hook_one_harness(home: Path) -> None:
    p = home / "p"
    write(p / ".claude" / "settings.json", settings(("PreToolUse", "Bash", "./check.py")))
    (f,) = project_findings(home, p)
    assert (f.id, f.severity, f.fix, f.project) == ("hook-one-harness", "warn", "hooks", p)
    assert f.message == "PreToolUse [Bash] `./check.py` has no counterpart for codex"


def test_claude_only_hook_with_args(home: Path) -> None:
    """The shape found in a real project: a Claude Code hook running a script
    through `args`, with nothing registered for Codex."""
    p = home / "p"
    write(
        p / ".claude" / "settings.json",
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3",
                                    "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/check.py"],
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    )
    (f,) = project_findings(home, p)
    assert (f.id, f.severity, f.fix) == ("hook-one-harness", "warn", "hooks")
    assert f.message == (
        "PreToolUse [Bash] `python3 '${CLAUDE_PROJECT_DIR}/.claude/hooks/check.py'` "
        "has no counterpart for codex"
    )
    # The same script registered for Codex, however it is spelled, pairs up.
    write(
        p / ".codex" / "hooks.json",
        settings(("PreToolUse", "Bash", "python3 ./.claude/hooks/check.py")),
    )
    (f,) = project_findings(home, p)
    assert f.id == "hook-mismatch"


@pytest.mark.parametrize(
    ("claude", "codex"),
    [
        (("PostToolUse", "Edit|Write", "./fmt"), ("PostToolUse", "Edit", "./fmt")),
        (("PostToolUse", "Edit", "./fmt"), ("PreToolUse", "Edit", "./fmt")),
        (("PostToolUse", "Edit", "./fmt"), ("PostToolUse", "Edit", "scripts/fmt")),
    ],
)
def test_project_hook_mismatch(
    home: Path, claude: tuple[str, str, str], codex: tuple[str, str, str]
) -> None:
    p = home / "p"
    write(p / ".claude" / "settings.json", settings(claude))
    write(p / ".codex" / "hooks.json", settings(codex))
    (f,) = project_findings(home, p)
    assert f.id == "hook-mismatch"
    assert f.message.startswith("counterpart hooks differ -- claude-code: ")


def test_project_matchers_merge_across_entries(home: Path) -> None:
    p = home / "p"
    write(
        p / ".claude" / "settings.json",
        settings(("PostToolUse", "Edit", "./fmt"), ("PostToolUse", "Write", "./fmt")),
    )
    write(p / ".codex" / "config.toml", codex_toml(("PostToolUse", "Write|Edit", "./fmt")))
    assert project_findings(home, p) == []


def test_project_hardcoded_home(home: Path) -> None:
    p = home / "p"
    body = settings(("Stop", "", f"{home}/bin/notify"), ("Stop", "", "/Users/else/bin/x"))
    write(p / ".claude" / "settings.json", body)
    write(p / ".codex" / "hooks.json", body)
    fs = project_findings(home, p)
    assert ids(fs) == ["hook-hardcoded-home"] * 4  # two commands in each of two files
    assert {f.severity for f in fs} == {"info"}


def test_project_unreadable_hook_file(home: Path) -> None:
    p = home / "p"
    write(p / ".codex" / "config.toml", "[[hooks")
    (f,) = project_findings(home, p)
    assert (f.id, f.project, f.harness) == ("unreadable-file", p, "codex")

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tack import doctor
from tack.doctor import project_plugins
from tack.doctor.findings import Finding
from tests.helpers import ids, load, repo, write

CLAUDE = ".claude/settings.json"
CODEX = ".codex/config.toml"

# Only the codex harness lists a hook file, and not the plugin settings files.
NO_SETTINGS_HOOKS = """
[harness.claude-code]
project_hooks = []

[harness.codex]
project_hooks = [".codex/hooks.json"]
"""


def claude(p: Path, enabled: object) -> Path:
    return write(p / CLAUDE, json.dumps({"enabledPlugins": enabled}))


def codex(p: Path, *tables: tuple[str, str]) -> Path:
    """`.codex/config.toml` with a `[plugins."<key>"]` table per (key, body)."""
    body = "".join(f'[plugins."{key}"]\n{rest}\n' for key, rest in tables)
    return write(p / CODEX, 'model = "gpt"\n\n' + body)


def check(home: Path, p: Path, manifest: str | None = None) -> list[Finding]:
    return list(project_plugins.check(load(home, manifest), p))


def test_on_in_claude_unset_in_codex(home: Path) -> None:
    p = home / "p"
    f = claude(p, {"foo@mk": True})
    (finding,) = check(home, p)
    assert finding == Finding(
        "plugin-one-harness",
        "warn",
        "plugin 'foo' is on for claude-code (`foo@mk = true` in .claude/settings.json) "
        'and unset for codex; add `[plugins."foo@<marketplace>"] enabled = true` '
        "to .codex/config.toml",
        path=f,
        harness="claude-code",
        project=p,
        fix=None,
    )


def test_on_in_codex_unset_in_claude(home: Path) -> None:
    p = home / "p"
    f = codex(p, ("foo@openai", "enabled = true"))
    (finding,) = check(home, p)
    assert finding == Finding(
        "plugin-one-harness",
        "warn",
        "plugin 'foo' is on for codex (`foo@openai = true` in .codex/config.toml) "
        'and unset for claude-code; add `"enabledPlugins": {"foo@<marketplace>": true}` '
        "to .claude/settings.json",
        path=f,
        harness="codex",
        project=p,
        fix=None,
    )


def test_on_against_off(home: Path) -> None:
    p = home / "p"
    c = claude(p, {"foo@mk": True})
    codex(p, ("foo@mk", "enabled = false"))
    (finding,) = check(home, p)
    assert (finding.path, finding.harness, finding.project) == (c, "claude-code", p)
    assert finding.message == (
        "plugin 'foo' is on for claude-code (`foo@mk = true` in .claude/settings.json) "
        'and off for codex; add `[plugins."foo@<marketplace>"] enabled = true` '
        "to .codex/config.toml"
    )

    q = home / "q"
    claude(q, {"foo@mk": False})
    x = codex(q, ("foo@mk", "enabled = true"))
    (finding,) = check(home, q)
    assert (finding.path, finding.harness, finding.project) == (x, "codex", q)
    assert "is on for codex (`foo@mk = true` in .codex/config.toml)" in finding.message
    assert "and off for claude-code;" in finding.message
    assert '`"enabledPlugins": {"foo@<marketplace>": true}`' in finding.message


def test_off_against_unset(home: Path) -> None:
    p = home / "p"
    c = claude(p, {"foo@mk": False})
    (finding,) = check(home, p)
    assert (finding.path, finding.harness, finding.project) == (c, "claude-code", p)
    assert finding.message == (
        "plugin 'foo' is off for claude-code (`foo@mk = false` in .claude/settings.json) "
        'and unset for codex; add `[plugins."foo@<marketplace>"] enabled = false` '
        "to .codex/config.toml"
    )

    q = home / "q"
    x = codex(q, ("foo@mk", "enabled = false"))
    (finding,) = check(home, q)
    assert (finding.path, finding.harness, finding.project) == (x, "codex", q)
    assert "is off for codex (`foo@mk = false` in .codex/config.toml)" in finding.message
    assert "and unset for claude-code;" in finding.message
    assert '`"enabledPlugins": {"foo@<marketplace>": false}`' in finding.message


def test_matches_by_name_across_marketplaces(home: Path) -> None:
    p = home / "p"
    claude(p, {"foo@a": True, "bar": False})
    codex(p, ("foo@b", "enabled = true"), ("bar@c", "enabled = false"))
    assert check(home, p) == []


def test_several_keys_for_one_name(home: Path) -> None:
    for order in ({"foo@a": False, "foo@b": True}, {"foo@b": True, "foo@a": False}):
        p = home / "p"
        claude(p, order)
        (finding,) = check(home, p)
        assert "is on for claude-code (`foo@b = true`" in finding.message

    p = home / "p"
    claude(p, {"foo@a": False, "foo@b": False})
    (finding,) = check(home, p)
    assert "is off for claude-code (`foo@a = false`" in finding.message

    p = home / "codex-order"
    codex(p, ("foo@a", "enabled = false"), ("foo@b", "enabled = true"), ("foo@c", "enabled = true"))
    (finding,) = check(home, p)
    assert "is on for codex (`foo@b = true`" in finding.message


@pytest.mark.parametrize("value", [1, "true", None])
def test_non_bool_claude_value_sets_nothing(home: Path, value: object) -> None:
    p = home / "p"
    claude(p, {"foo@mk": value})
    codex(p, ("foo@mk", "enabled = true"))
    (finding,) = check(home, p)
    assert (finding.harness, "and unset for claude-code;" in finding.message) == ("codex", True)


@pytest.mark.parametrize(
    "text", ['{"enabledPlugins": ["foo@mk"]}', '[{"enabledPlugins": {"foo@mk": true}}]', "null"]
)
def test_malformed_claude_file_sets_nothing(home: Path, text: str) -> None:
    p = home / "p"
    write(p / CLAUDE, text)
    codex(p, ("foo@mk", "enabled = true"))
    (finding,) = check(home, p)
    assert (finding.harness, "and unset for claude-code;" in finding.message) == ("codex", True)


@pytest.mark.parametrize(
    "toml",
    [
        'plugins = "foo@mk"\n',  # not a table
        'plugins = { "foo@mk" = true }\n',  # an entry that isn't a table
        '[plugins."foo@mk"]\npath = "x"\n',  # no `enabled`
        '[plugins."foo@mk"]\nenabled = "true"\n',  # not a boolean
        '[plugins."foo@mk"]\nenabled = 1\n',
    ],
)
def test_malformed_codex_file_sets_nothing(home: Path, toml: str) -> None:
    p = home / "p"
    write(p / CODEX, toml)
    claude(p, {"foo@mk": True})
    (finding,) = check(home, p)
    assert (finding.harness, "and unset for codex;" in finding.message) == ("claude-code", True)


def test_equal_settings_are_clean(home: Path) -> None:
    assert check(home, home / "empty") == []  # both files missing
    p = home / "p"
    claude(p, {"on@mk": True, "off@mk": False})
    codex(p, ("on@mk", "enabled = true"), ("off@mk", "enabled = false"))
    assert check(home, p) == []
    q = home / "q"
    write(q / CLAUDE, '{"model": "opus"}')
    write(q / CODEX, 'model = "gpt"\n')
    assert check(home, q) == []


def test_local_settings_are_not_read(home: Path) -> None:
    p = home / "p"
    write(p / ".claude/settings.local.json", json.dumps({"enabledPlugins": {"foo@mk": True}}))
    assert check(home, p) == []


def test_findings_in_name_order(home: Path) -> None:
    p = home / "p"
    claude(p, {"zed@mk": True, "alpha@mk": True})
    codex(p, ("mid@mk", "enabled = false"))
    assert [f.message.split("'")[1] for f in check(home, p)] == ["alpha", "mid", "zed"]


def unreadable(p: Path, which: str) -> Path:
    path = p / which
    path.parent.mkdir(parents=True, exist_ok=True)
    if which == CLAUDE:
        path.write_text("{")  # invalid JSON
    else:
        path.write_bytes(b'model = "\xff"\n')  # not UTF-8
    return path


@pytest.mark.parametrize("which", [CLAUDE, CODEX])
def test_unreadable_reported_once_by_the_hooks_check(home: Path, which: str) -> None:
    p = home / "p"
    bad = unreadable(p, which)
    if which == CLAUDE:
        codex(p, ("foo@mk", "enabled = true"))
    else:
        claude(p, {"foo@mk": True})
    findings = doctor.check_project(load(home), p)
    (finding,) = [f for f in findings if f.id == "unreadable-file"]
    assert finding.path == bad
    assert "can't parse hook file" in finding.message
    assert "plugin-one-harness" not in ids(findings)


@pytest.mark.parametrize(
    ("which", "text", "harness"),
    [(CLAUDE, "{", "claude-code"), (CODEX, "[plugins", "codex"), (CODEX, None, "codex")],
)
def test_unreadable_reported_once_by_this_check(
    home: Path, which: str, text: str | None, harness: str
) -> None:
    p = home / "p"
    bad = write(p / which, text) if text is not None else unreadable(p, which)
    if which == CLAUDE:
        codex(p, ("foo@mk", "enabled = true"))
    else:
        claude(p, {"foo@mk": True})
    findings = doctor.check_project(load(home, NO_SETTINGS_HOOKS), p)
    (finding,) = [f for f in findings if f.id == "unreadable-file"]
    assert (finding.severity, finding.path, finding.harness, finding.project) == (
        "error",
        bad,
        harness,
        p,
    )
    assert finding.message.startswith("can't parse plugin settings file: ")
    assert finding.fix is None
    assert "plugin-one-harness" not in ids(findings)


def test_unreadable_listed_by_the_other_harness(home: Path) -> None:
    """Codex's `project_hooks` lists Claude Code's settings file: the hooks
    check reports it, for codex, and this check doesn't."""
    p = home / "p"
    bad = write(p / CLAUDE, "{")
    codex(p, ("foo@mk", "enabled = true"))
    manifest = NO_SETTINGS_HOOKS.replace(".codex/hooks.json", CLAUDE)
    findings = doctor.check_project(load(home, manifest), p)
    (finding,) = [f for f in findings if f.id == "unreadable-file"]
    assert (finding.path, finding.harness) == (bad, "codex")
    assert "can't parse hook file" in finding.message
    assert "plugin-one-harness" not in ids(findings)


def test_reported_with_projects_only(home: Path) -> None:
    p = repo(home / "p")
    claude(p, {"foo@mk": True})
    report = doctor.run(load(home), [p], global_checks=False)
    (finding,) = [f for f in report.findings if f.id == "plugin-one-harness"]
    assert (finding.project, finding.fix) == (p, None)

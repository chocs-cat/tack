from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tack import __version__
from tack.cli import main
from tests.helpers import commit, git, link, market, repo, skill, skill_md, upstream, write


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def manifest(home: Path, text: str) -> None:
    write(home / ".config" / "tack" / "tack.toml", text)


@pytest.fixture
def machine(home: Path) -> Path:
    """One source deployed to both harnesses, and a project root with one clean
    project and one whose CLAUDE.md has no AGENTS.md."""
    a = skill(home / "mine" / "skills", "a")
    link(home / ".claude" / "skills" / "a", a)
    link(home / ".agents" / "skills" / "a", a)
    repo(home / "Code" / "good", {"AGENTS.md": "x\n", "CLAUDE.md": "@AGENTS.md\n"})
    repo(home / "Code" / "bad", {"CLAUDE.md": "x\n"})
    manifest(
        home,
        '[projects]\nroots = ["~/Code"]\n[[source]]\nname = "mine"\npath = "~/mine"\n',
    )
    return home


def test_doctor_json(machine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "doctor", "--json")
    data = json.loads(out)
    assert code == 1
    assert data["manifest"] == str(machine / ".config" / "tack" / "tack.toml")
    assert data["projects"] == [str(machine / "Code" / "bad"), str(machine / "Code" / "good")]
    assert data["counts"] == {"error": 1, "warn": 0, "info": 0}
    assert data["findings"] == [
        {
            "id": "agents-md-missing",
            "severity": "error",
            "message": "CLAUDE.md has instructions but there is no AGENTS.md: "
            "Codex gets none of them",
            "path": str(machine / "Code" / "bad" / "CLAUDE.md"),
            "harness": None,
            "project": str(machine / "Code" / "bad"),
            "fix": "agents-md",
        }
    ]


def test_doctor_text(machine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "doctor")
    assert code == 1
    assert out.splitlines() == [
        "manifest: ~/.config/tack/tack.toml",
        "",
        "~/Code/bad",
        "  error  agents-md-missing  CLAUDE.md  (fix: agents-md)",
        "         "
        + " " * len("agents-md-missing")
        + "  CLAUDE.md has instructions but there is no AGENTS.md: Codex gets none of them",
        "",
        "1 error -- checked 2 harnesses, 2 projects",
    ]


def test_doctor_scopes_and_paths(machine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "doctor", "--global-only")
    assert (code, out.splitlines()[-1]) == (0, "no findings -- checked 2 harnesses, 0 projects")

    link(machine / ".claude" / "skills" / "stray", machine / "nowhere")
    code, out, _ = run(capsys, "doctor", "--projects-only", "--json")
    assert code == 1
    assert [f["id"] for f in json.loads(out)["findings"]] == ["agents-md-missing"]

    code, out, _ = run(capsys, "doctor", "--projects-only", str(machine / "Code" / "good"))
    assert (code, out.splitlines()[-1]) == (0, "no findings -- checked 1 project")


def test_clones_are_skipped_unless_named(machine: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clone = repo(machine / "Code" / "vendor" / "tool", {"CLAUDE.md": "theirs\n"})
    git(clone, "remote", "add", "origin", "https://github.com/someone/tool.git")
    mine = machine / "Code" / "good"
    git(mine, "remote", "add", "origin", "https://github.com/me/good.git")
    text = (machine / ".config" / "tack" / "tack.toml").read_text()
    manifest(machine, text.replace("[projects]\n", '[projects]\nowners = ["me"]\n'))

    code, out, _ = run(capsys, "doctor", "--projects-only", "--json")
    data = json.loads(out)
    assert data["clones"] == [str(clone)]
    assert str(clone) not in data["projects"]
    assert [f["project"] for f in data["findings"]] == [str(machine / "Code" / "bad")]

    code, out, _ = run(capsys, "doctor", "--projects-only")
    assert out.splitlines()[-1] == (
        "1 error -- checked 2 projects (1 clone of others' projects skipped)"
    )

    code, out, _ = run(capsys, "doctor", "--projects-only", "--json", str(clone))
    data = json.loads(out)
    assert code == 1
    assert (data["projects"], data["clones"]) == ([str(clone)], [])
    assert [f["id"] for f in data["findings"]] == ["agents-md-missing"]


def test_sync_and_status(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("a", "b"):
        skill(home / "mine" / "skills", name)
    skill(home / ".claude" / "skills", "b")  # a conflict
    manifest(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')

    code, out, _ = run(capsys, "sync", "--dry-run")
    assert code == 1
    assert out.splitlines() == [
        "claude-code  would link a -> ~/mine/skills/a",
        "codex        would link a -> ~/mine/skills/a",
        "codex        would link b -> ~/mine/skills/b",
        "conflict: mine claude-code: b: a real directory is in the way; "
        "`tack sync --adopt` takes it over",
        "",
        "would make 3 changes, 1 problem",
    ]
    assert not (home / ".agents" / "skills").exists()

    code, out, _ = run(capsys, "sync", "--json")
    data = json.loads(out)
    assert code == 1
    assert data["dry_run"] is False
    assert [c["action"] for c in data["changes"]] == ["link", "link", "link"]
    assert data["problems"][0]["kind"] == "conflict"
    assert data["problems"][0]["path"] == str(home / ".claude" / "skills" / "b")

    code, out, _ = run(capsys, "sync", "--adopt")
    assert code == 0
    assert out.splitlines()[-1] == "1 change"
    code, out, _ = run(capsys, "sync")
    assert (code, out.strip()) == (0, "already in sync")

    code, out, _ = run(capsys, "status")
    assert code == 0
    assert out.splitlines() == [
        "sources",
        "  mine  ~/mine",
        "        2 skills",
        "",
        "skill  source  claude-code  codex",
        "a      mine    linked       linked",
        "b      mine    linked       linked",
    ]
    code, out, _ = run(capsys, "status", "--json")
    data = json.loads(out)
    assert data["sources"][0]["name"] == "mine"
    assert data["skills"][1] == {
        "name": "b",
        "source": "mine",
        "harnesses": {"claude-code": "linked", "codex": "linked"},
        "path": str(home / "mine" / "skills" / "b"),
    }


def test_status_shows_plugins(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skill(home / "mine" / "skills", "a")
    for name in ("p", "q"):
        write(home / "plugs" / "plugins" / name / "plugin.json", json.dumps({"name": name}))
    market(home / "plugs", "p", "q")
    manifest(
        home,
        '[[source]]\nname = "mine"\npath = "~/mine"\n'
        '[[source]]\nname = "plugs"\npath = "~/plugs"\nskills = []\n'
        'plugins = ["p", { name = "q", harnesses = ["codex"] }]\n',
    )
    assert run(capsys, "sync")[0] == 0
    (home / ".agents" / "skills" / "a").unlink()

    code, out, _ = run(capsys, "status")
    assert code == 0
    assert out.splitlines() == [
        "sources",
        "  mine   ~/mine",
        "         1 skill",
        "  plugs  ~/plugs",
        "         0 skills; 2 plugins",
        "",
        "skill  source  claude-code  codex",
        "a      mine    linked       missing",
        "",
        "plugin  source  claude-code  codex",
        "p       plugs   installed    installed",
        "q       plugs   -            installed",
    ]


def test_status_shows_plugins_in_place_of_skills(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    market(home / "plugs", {"name": "x", "source": {"source": "npm", "package": "x"}})
    manifest(home, '[[source]]\nname = "plugs"\npath = "~/plugs"\nskills = []\nplugins = "*"\n')

    code, out, _ = run(capsys, "status")
    assert code == 0
    assert out.splitlines() == [
        "sources",
        "  plugs  ~/plugs",
        "         0 skills; 1 plugin",
        "",
        "plugin  source  claude-code  codex",
        "x       plugs   missing      missing",
    ]


@pytest.mark.parametrize(
    ("selection", "root", "note"),
    [
        ("[]", False, "its directory isn't there"),
        ('"*"', False, "its directory isn't there"),
        ('"*"', True, "its skills directory isn't there"),
    ],
)
def test_status_says_which_directory_a_missing_source_lacks(
    home: Path, capsys: pytest.CaptureFixture[str], selection: str, root: bool, note: str
) -> None:
    """A `path` source whose root is gone says so; one with a root but no
    skills directory says that, as `doctor` tells them apart (#40)."""
    if root:
        (home / "gone").mkdir()
    manifest(home, f'[[source]]\nname = "gone"\npath = "~/gone"\nskills = {selection}\n')

    code, out, _ = run(capsys, "status")
    assert code == 0
    assert out.splitlines() == ["sources", "  gone  ~/gone", f"        {note}; 0 skills"]
    assert json.loads(run(capsys, "status", "--json")[1])["sources"][0]["state"] == "missing"


def test_tracking(home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    up = upstream(tmp_path / "up", "a")
    pin = git(up, "rev-parse", "HEAD").strip()
    code, out, _ = run(capsys, "add", f"file://{up}", "--json")
    assert code == 0
    assert [c["action"] for c in json.loads(out)["changes"]] == [
        "pin", "clone", "checkout", "write", "write", "link", "link",
    ]  # fmt: skip

    tip = commit(up, {"skills/a/SKILL.md": "changed\n"}, "Change a")
    code, out, _ = run(capsys, "outdated")
    assert code == 1
    assert out.splitlines() == [
        f"up  1 commit behind on the default branch ({pin[:12]} -> {tip[:12]})",
        "    modified: a",
        f"    {tip[:12]} Change a",
        "",
        "1 of 1 git source behind; `tack update` moves the pins",
    ]
    code, out, _ = run(capsys, "outdated", "up", "--diff", "--json")
    (data,) = json.loads(out)["sources"]
    assert (data["state"], data["skills"]) == ("behind", [{"name": "a", "change": "modified"}])
    assert "+changed" in data["diff"]

    code, out, _ = run(capsys, "update")
    assert code == 0
    assert out.splitlines()[0] == f"up  updated {pin[:12]} -> {tip[:12]} on the default branch"
    code, out, _ = run(capsys, "update")
    assert (code, out.strip()) == (0, "already up to date")
    code, out, _ = run(capsys, "outdated")
    assert (code, out.splitlines()[-1]) == (0, "1 git source, all up to date")

    code, out, _ = run(capsys, "remove", "up")
    assert code == 0
    assert out.splitlines()[-1] == "5 changes"
    code, out, _ = run(capsys, "outdated")
    assert (code, out.strip()) == (0, "no git sources")


def test_add_takes_skills_in_any_grouping(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("a", "b", "c", "d"):
        skill(home / "mine" / "skills", name)
    code, _, _ = run(capsys, "add", str(home / "mine"), "--skill", "a", "b", "--skill", "c")
    assert code == 0
    assert sorted(p.name for p in (home / ".agents" / "skills").iterdir()) == ["a", "b", "c"]


def test_add_takes_plugins_in_any_grouping(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("a", "b", "c", "d"):
        write(home / "mine" / "plugins" / name / "README.md", f"{name}\n")
    market(home / "mine", "a", "b", "c", "d")
    code, _, err = run(capsys, "add", str(home / "mine"), "--plugin", "a", "b", "--plugin", "c")
    assert (code, err) == (0, "")
    with (home / ".config" / "tack" / "tack.toml").open("rb") as f:
        (table,) = tomllib.load(f)["source"]
    assert (table["skills"], table["plugins"]) == ([], ["a", "b", "c"])


def test_usage_errors_exit_two(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "remove", "nope", "--json")
    assert code == 2
    assert json.loads(out) == {
        "error": "usage",
        "message": "no source named 'nope' in ~/.config/tack/tack.toml or its lockfile",
    }
    code, _, err = run(capsys, "outdated", "nope")
    assert code == 2
    assert err.strip() == "tack: no source named 'nope'"


def test_status_without_sources(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "status")
    assert (code, out.strip()) == (0, "no sources in ~/.config/tack/tack.toml")


def test_corrupt_state_is_a_config_error(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(home / ".local" / "state" / "tack" / "state.json", "{")
    code, _, err = run(capsys, "sync")
    assert code == 2
    assert "state.json" in err


def test_info_findings_alone_exit_zero(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(
        home / ".claude" / "settings.json", '{"hooks": {"Stop": [{"hooks": [{"command": "x"}]}]}}'
    )
    code, out, _ = run(capsys, "doctor", "--json")
    assert code == 0
    assert json.loads(out)["counts"] == {"error": 0, "warn": 0, "info": 1}


def test_no_manifest(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "doctor")
    assert code == 0
    assert out.splitlines()[0] == (
        "no manifest at ~/.config/tack/tack.toml: built-in harnesses, no sources, no project roots"
    )
    code, out, _ = run(capsys, "doctor", "--json")
    assert json.loads(out)["manifest"] is None


def test_config_errors_exit_two(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest(home, "bogus = true\n")
    code, _, err = run(capsys, "doctor")
    assert code == 2
    assert "unknown key 'bogus'" in err
    code, out, _ = run(capsys, "doctor", "--json")
    assert code == 2
    assert json.loads(out)["error"] == "config"

    write(tmp_path / "other" / "tack.toml", "")
    code, out, _ = run(capsys, "doctor", "--config", str(tmp_path / "other"), "--json")
    assert (code, json.loads(out)["manifest"]) == (0, str(tmp_path / "other" / "tack.toml"))


def test_changing_commands_auto_commit(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    mine = repo(home / "mine", {"skills/a/SKILL.md": skill_md("a")})
    git(mine, "remote", "add", "origin", str(remote))
    git(mine, "push", "-q", "-u", "origin", "master")
    manifest(
        home, '[[source]]\nname = "mine"\npath = "~/mine"\nautocommit = true\nautopush = true\n'
    )
    assert run(capsys, "sync")[0] == 0
    write(mine / "skills" / "a" / "SKILL.md", "edited\n")
    before = git(mine, "rev-parse", "HEAD")

    # Read-only commands, a usage error, and runs told not to commit leave the edit alone.
    for argv in (
        ["status"], ["doctor"], ["outdated"], ["remove", "nosuch"], ["sync", "--no-commit"],
    ):  # fmt: skip
        run(capsys, *argv)
    monkeypatch.setenv("TACK_NO_COMMIT", "1")
    run(capsys, "sync")
    monkeypatch.delenv("TACK_NO_COMMIT")
    code, out, _ = run(capsys, "sync", "--dry-run")
    assert (code, out.splitlines()) == (
        0,
        [
            'mine  would commit "Update a"',
            "mine  would push master to origin/master",
            "",
            "would make 2 changes",
        ],
    )
    assert git(mine, "rev-parse", "HEAD") == before

    code, out, _ = run(capsys, "sync")
    commit = git(mine, "rev-parse", "HEAD").strip()
    assert (code, out.splitlines()) == (
        0,
        [
            f'mine  committed "Update a" ({commit[:12]})',
            "mine  pushed master to origin/master",
            "",
            "2 changes",
        ],
    )
    assert git(remote, "rev-parse", "master").strip() == commit

    git(mine, "checkout", "-q", "--detach")
    write(mine / "skills" / "a" / "SKILL.md", "again\n")
    code, out, _ = run(capsys, "sync")
    assert (code, out.splitlines()) == (
        0,
        ["note: mine: not auto-committed: ~/mine is on a detached HEAD", "", "already in sync"],
    )
    code, out, _ = run(capsys, "sync", "--json")
    assert json.loads(out)["notes"] == [
        {
            "message": "not auto-committed: ~/mine is on a detached HEAD",
            "source": "mine",
            "path": str(mine),
        }
    ]


def test_scaffold(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = repo(home / "p", {"CLAUDE.md": "Ask Claude.\n"})
    code, out, _ = run(capsys, "scaffold", "agents-md", str(project), "--dry-run")
    assert (code, out.splitlines()) == (
        0,
        [
            "would move CLAUDE.md -> AGENTS.md",
            "would write CLAUDE.md",
            "--- /dev/null",
            "+++ b/CLAUDE.md",
            "@@ -0,0 +1 @@",
            "+@AGENTS.md",
            "note: AGENTS.md:1 names one agent: Ask Claude.",
            "",
            "would make 2 changes",
        ],
    )
    code, out, _ = run(capsys, "scaffold", "agents-md", str(project))
    assert (code, out.splitlines()[:2]) == (0, ["moved CLAUDE.md -> AGENTS.md", "wrote CLAUDE.md"])
    code, out, _ = run(capsys, "scaffold", "agents-md", str(project))
    assert (code, out.strip()) == (0, "nothing to fix")

    skill(project / ".claude" / "skills", "a", description="Mine.")
    skill(project / ".agents" / "skills", "a", description="Theirs.")
    code, out, _ = run(capsys, "scaffold", "skills-dir", str(project), "--json")
    data = json.loads(out)
    assert code == 1
    assert (data["changes"], [p["kind"] for p in data["problems"]]) == ([], ["refused"])

    with pytest.raises(SystemExit) as e:
        main(["scaffold", "tidy", str(project)])
    assert e.value.code == 2
    assert "invalid choice: 'tidy'" in capsys.readouterr().err
    code, _, err = run(capsys, "scaffold", "agents-md", str(project), "--from", "codex")
    assert (code, err.strip()) == (2, "tack: --from applies to the hooks fix")


def test_usage(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys)
    assert code == 2
    assert "doctor" in err
    with pytest.raises(SystemExit) as e:
        main(["doctor", "--global-only", "--projects-only"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"tack {__version__}"


def test_module_entry_point(home: Path) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "tack", "doctor", "--json"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["findings"] == []

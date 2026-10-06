from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tack import config, deploy, sync
from tack.config import Config
from tests.helpers import commit, git, link, load, skill, tree, upstream, write

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
MINE = '[[source]]\nname = "mine"\npath = "~/mine"\n'


def run(cfg: Config, **kw) -> sync.Result:
    return sync.sync(cfg, now=WHEN, **kw)


def actions(result: sync.Result) -> list[tuple[str, str | None, str]]:
    return [(c.action, c.harness or c.source, c.detail.split(" ", 1)[0]) for c in result.changes]


@pytest.fixture
def mine(home: Path) -> Path:
    for name in ("a", "b"):
        skill(home / "mine" / "skills", name)
    return home / "mine" / "skills"


def test_path_source_links_every_harness(home: Path, mine: Path) -> None:
    cfg = load(home, MINE)
    result = run(cfg)
    assert result.problems == []
    assert actions(result) == [
        ("link", "claude-code", "a"),
        ("link", "claude-code", "b"),
        ("link", "codex", "a"),
        ("link", "codex", "b"),
    ]
    for h in (".claude", ".agents"):
        assert (home / h / "skills" / "a").readlink() == mine / "a"
    record = deploy.load_record(cfg.paths)
    assert record.links[str(home / ".claude" / "skills" / "a")] == str(mine / "a")
    # Idempotent.
    again = run(cfg)
    assert (again.changes, again.problems) == ([], [])


def test_deselected_and_removed_skills_are_unlinked(home: Path, mine: Path) -> None:
    run(load(home, MINE))
    result = run(load(home, MINE + 'skills = ["a"]\n'))
    assert actions(result) == [("unlink", "claude-code", "b"), ("unlink", "codex", "b")]
    assert not (home / ".claude" / "skills" / "b").is_symlink()

    shutil.rmtree(mine / "a")  # a skill deleted from its source: its dangling links go
    result = run(load(home, MINE))
    assert [a for a, *_ in actions(result)] == ["link", "unlink", "link", "unlink"]


def test_dropping_a_path_source_removes_its_links(home: Path, mine: Path) -> None:
    run(load(home, MINE))
    foreign = link(home / ".claude" / "skills" / "hand-made", mine / "b")  # not tack's
    del foreign
    result = run(load(home, ""))
    # The record says a and b are tack's, though ~/mine is no longer a source.
    assert sorted(actions(result)) == [
        ("unlink", "claude-code", "a"),
        ("unlink", "claude-code", "b"),
        ("unlink", "codex", "a"),
        ("unlink", "codex", "b"),
    ]
    assert (home / ".claude" / "skills" / "hand-made").is_symlink()
    assert deploy.load_record(load(home).paths).links == {}


def test_ignored_and_foreign_entries_are_left_alone(home: Path, mine: Path) -> None:
    claude = home / ".claude" / "skills"
    skill(claude, "synced")
    skill(claude, "installer")
    link(claude / "elsewhere", home / "lib" / "x")
    before = tree(claude)
    run(load(home, MINE + '[harness.claude-code]\nignore = ["installer"]\n'))
    after = tree(claude)
    assert all(after[k] == v for k, v in before.items())


def test_ignored_name_selected_is_a_conflict(home: Path, mine: Path) -> None:
    result = run(load(home, MINE + '[harness.codex]\nignore = ["a"]\n'))
    (p,) = result.problems
    assert (p.kind, p.harness) == ("conflict", "codex")
    assert "in codex's ignore list" in p.message


def test_stale_link_is_relinked(home: Path, mine: Path) -> None:
    skill(home / "mine" / "old", "a")
    entry = link(home / ".claude" / "skills" / "a", home / "mine" / "old" / "a")  # into the source
    result = run(load(home, MINE + 'skills = ["a"]\nharnesses = ["claude-code"]\n'))
    assert actions(result) == [("relink", "claude-code", "a")]
    assert "(was ~/mine/old/a)" in result.changes[0].detail
    assert entry.readlink() == mine / "a"


def test_conflicts_are_reported_then_adopted(home: Path, mine: Path) -> None:
    claude = home / ".claude" / "skills"
    real = skill(claude, "a", description="A hand-installed copy.")
    link(claude / "b", home / "chezmoi-lib" / "b")
    cfg = load(home, MINE + 'harnesses = ["claude-code"]\n')

    result = run(cfg)
    assert [(p.kind, p.path) for p in result.problems] == [
        ("conflict", claude / "a"),
        ("conflict", claude / "b"),
    ]
    assert "a real directory is in the way; `tack sync --adopt`" in result.problems[0].message
    assert "a link to ~/chezmoi-lib/b is in the way" in result.problems[1].message
    assert result.changes == []
    assert (real / "SKILL.md").is_file()

    result = run(cfg, adopt=True)
    assert result.problems == []
    assert actions(result) == [("adopt", "claude-code", "a"), ("adopt", "claude-code", "b")]
    moved = cfg.paths.state_dir / "adopted" / "20260927T120000Z" / "claude-code" / "a"
    assert (moved / "SKILL.md").read_text().endswith("A hand-installed copy.\n---\n\nBody.\n")
    assert f"moved a real directory to {moved.relative_to(home).as_posix()}" in (
        result.changes[0].detail.replace("~/", "")
    )
    assert "replaced a link to ~/chezmoi-lib/b" in result.changes[1].detail
    assert (claude / "a").readlink() == mine / "a"
    assert (claude / "b").readlink() == mine / "b"


def test_collisions_deploy_neither(home: Path, mine: Path) -> None:
    skill(home / "two" / "skills", "a")
    existing = link(home / ".claude" / "skills" / "a", mine / "a")
    result = run(load(home, MINE + '[[source]]\nname = "two"\npath = "~/two"\n'))
    assert [p.kind for p in result.problems] == ["collision"]
    assert "'a' is selected from sources mine, two" in result.problems[0].message
    assert existing.readlink() == mine / "a"  # left alone, not removed
    assert not (home / ".agents" / "skills" / "a").exists()
    assert (home / ".agents" / "skills" / "b").is_symlink()


def test_git_source(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x", "y", "z")
    tip = git(up, "rev-parse", "HEAD").strip()
    manifest = f'[[source]]\nname = "up"\ngit = "{up}"\nskills = ["x", "y"]\n'
    cfg = load(home, manifest)
    result = run(cfg)
    assert result.problems == []
    assert [c.action for c in result.changes] == [
        "pin", "clone", "checkout", "write", "link", "link", "link", "link",
    ]  # fmt: skip
    checkout = cfg.paths.sources_dir / "up"
    assert (home / ".agents" / "skills" / "x").readlink() == checkout / "skills" / "x"
    assert not (home / ".agents" / "skills" / "z").exists()
    assert config.load_lock(cfg.paths)["up"].commit == tip

    # Upstream moves; sync keeps the pin and changes nothing.
    commit(up, {"skills/x/SKILL.md": "changed upstream"})
    again = run(cfg)
    assert (again.changes, again.problems) == ([], [])
    assert config.load_lock(cfg.paths)["up"].commit == tip


def test_manifest_change_refuses_the_source_and_holds_its_links(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    run(load(home, f'[[source]]\nname = "up"\ngit = "{up}"\n'))
    lock_before = load(home).paths.lockfile.read_text()
    cfg = load(home, f'[[source]]\nname = "up"\ngit = "{up}"\nref = "master"\n')
    result = run(cfg)
    assert [(p.kind, p.source) for p in result.problems] == [("source", "up")]
    assert "`tack update up` re-pins it" in result.problems[0].message
    assert result.changes == []
    assert (home / ".agents" / "skills" / "x").is_symlink()
    assert cfg.paths.lockfile.read_text() == lock_before


def test_unreachable_source_holds_its_links(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    run(load(home, f'[[source]]\nname = "up"\ngit = "{up}"\n'))
    shutil.rmtree(load(home).paths.sources_dir / "up")
    shutil.rmtree(up)
    result = run(load(home, f'[[source]]\nname = "up"\ngit = "{up}"\n'))
    assert [p.kind for p in result.problems] == ["source"]
    assert result.changes == []
    assert (home / ".claude" / "skills" / "x").is_symlink()  # dangling, but not removed


def test_missing_path_source_holds_its_links(home: Path, mine: Path) -> None:
    run(load(home, MINE))
    shutil.move(home / "mine", home / "mine-moved")
    result = run(load(home, MINE))
    assert [(p.kind, p.source) for p in result.problems] == [("source", "mine")]
    assert "no skills directory at ~/mine/skills" in result.problems[0].message
    assert result.changes == []
    assert (home / ".claude" / "skills" / "a").is_symlink()


@pytest.mark.parametrize("selection", ["[]", '"*"'])
def test_path_source_presence_without_a_skills_directory(home: Path, selection: str) -> None:
    (home / "mine").mkdir()
    cfg = load(home, MINE + f"skills = {selection}\n")

    result = run(cfg)

    assert deploy.plan(cfg).sources[0].present == (selection == "[]")
    if selection == "[]":
        assert result.problems == []
    else:
        (problem,) = result.problems
        assert (problem.kind, problem.message) == (
            "source",
            "no skills directory at ~/mine/skills",
        )


def test_empty_skills_selection_unlinks_old_skills_without_a_skills_directory(
    home: Path, mine: Path
) -> None:
    assert run(load(home, MINE)).problems == []
    shutil.rmtree(mine)

    result = run(load(home, MINE + "skills = []\n"))

    assert result.problems == []
    assert sorted(actions(result)) == [
        ("unlink", "claude-code", "a"),
        ("unlink", "claude-code", "b"),
        ("unlink", "codex", "a"),
        ("unlink", "codex", "b"),
    ]
    for harness in (".claude", ".agents"):
        for name in ("a", "b"):
            assert not (home / harness / "skills" / name).is_symlink()


def test_missing_path_with_empty_skills_selection_holds_its_links(home: Path, mine: Path) -> None:
    assert run(load(home, MINE)).problems == []
    (home / "mine").rename(home / "mine-moved")
    cfg = load(home, MINE + "skills = []\n")

    result = run(cfg)

    assert not deploy.plan(cfg).sources[0].present
    assert [(p.kind, p.source, p.message) for p in result.problems] == [
        ("source", "mine", "no directory at ~/mine"),
    ]
    assert result.changes == []
    for harness in (".claude", ".agents"):
        assert (home / harness / "skills" / "a").is_symlink()


def test_lock_keeps_entries_for_sources_left_out(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    run(load(home, f'[[source]]\nname = "up"\ngit = "{up}"\n'))
    run(load(home, ""))
    assert list(config.load_lock(load(home).paths)) == ["up"]


def test_after_save_runs_when_the_lock_changes(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    log = home / "saved.log"
    source = f'[[source]]\nname = "up"\ngit = "{up}"\n'
    cfg = load(home, f'after_save = "echo {{path}} >> {log}"\n' + source)
    assert run(cfg).problems == []
    assert log.read_text() == f"{cfg.paths.lockfile}\n"
    run(cfg)  # the lock doesn't change: nothing runs
    assert log.read_text() == f"{cfg.paths.lockfile}\n"

    cfg = load(home, 'after_save = "exit 1"\n' + source.replace('"up"', '"up2"', 1))
    result = run(cfg)
    assert [p.kind for p in result.problems] == ["after-save"]
    assert "up2" in config.load_lock(cfg.paths)  # written all the same


def test_dry_run_changes_nothing(home: Path, tmp_path: Path, mine: Path) -> None:
    claude = home / ".claude" / "skills"
    skill(claude, "a")  # a conflict
    up = upstream(tmp_path / "up", "x")
    everything = upstream(tmp_path / "all", "y")
    write(home / "marker")
    manifest = (
        MINE
        + f'[[source]]\nname = "up"\ngit = "{up}"\nskills = ["x"]\n'
        + f'[[source]]\nname = "all"\ngit = "{everything}"\n'
    )
    cfg = load(home, manifest)
    before = tree(home)
    result = run(cfg, dry_run=True, adopt=True)
    assert tree(home) == before
    assert result.dry_run
    done = {(c.action, c.harness or c.source) for c in result.changes}
    assert {("pin", "up"), ("clone", "up"), ("pin", "all"), ("write", None)} <= done
    assert ("adopt", "claude-code") in done
    linked = {c.detail.split(" ")[0] for c in result.changes if c.action == "link"}
    assert linked == {"a", "b", "x"}  # y is unknown until `all` is fetched

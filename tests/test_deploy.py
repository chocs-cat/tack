from __future__ import annotations

from pathlib import Path

from tack import deploy
from tests.helpers import link, load, skill, write


def test_plan_selects_every_skill_or_a_list(home: Path) -> None:
    for name in ("a", "b", ".hidden"):
        skill(home / "mine" / "skills", name)
    write(home / "mine" / "skills" / "README.md")  # not a directory: not a skill
    skill(home / "vendor" / "skills", "x")
    skill(home / "vendor" / "skills", "y")
    cfg = load(
        home,
        """
[[source]]
name = "mine"
path = "~/mine"

[[source]]
name = "vendor"
path = "~/vendor"
skills = [{ name = "x", harnesses = ["codex"] }, "gone"]
""",
    )
    plan = deploy.plan(cfg)
    mine, vendor = plan.sources
    assert [s.name for s in mine.selected] == ["a", "b"]
    assert mine.selected[0].harnesses == ("claude-code", "codex")
    assert [s.name for s in vendor.selected] == ["x"]
    assert vendor.missing == ["gone"]
    assert set(plan.links["claude-code"]) == {"a", "b"}
    assert set(plan.links["codex"]) == {"a", "b", "x"}
    assert plan.links["codex"]["x"].path == home / "vendor" / "skills" / "x"
    assert not plan.collisions


def test_absent_source_still_plans_its_listed_skills(home: Path) -> None:
    cfg = load(
        home,
        """
[[source]]
name = "cf"
git = "https://example.com/cf.git"
skills = ["wrangler"]

[[source]]
name = "all"
git = "https://example.com/all.git"
""",
    )
    cf, everything = deploy.plan(cfg).sources
    assert not cf.present
    assert cf.root == cfg.paths.data_dir / "sources" / "cf"
    assert [s.path for s in cf.selected] == [cf.root / "skills" / "wrangler"]
    assert cf.missing == []
    assert everything.selected == []


def test_collisions_only_where_harnesses_overlap(home: Path) -> None:
    skill(home / "one" / "skills", "dup")
    skill(home / "two" / "skills", "dup")
    skill(home / "three" / "skills", "dup")
    cfg = load(
        home,
        """
[[source]]
name = "one"
path = "~/one"
harnesses = ["claude-code"]

[[source]]
name = "two"
path = "~/two"
harnesses = ["codex"]
""",
    )
    plan = deploy.plan(cfg)
    assert not plan.collisions
    assert plan.links["claude-code"]["dup"].source.name == "one"
    assert plan.links["codex"]["dup"].source.name == "two"

    cfg = load(
        home,
        '[[source]]\nname = "one"\npath = "~/one"\n'
        '[[source]]\nname = "three"\npath = "~/three"\nharnesses = ["codex"]\n',
    )
    plan = deploy.plan(cfg)
    assert plan.collisions == {"dup": (["codex"], ["one", "three"])}
    assert "dup" not in plan.links["codex"]
    assert plan.links["claude-code"]["dup"].source.name == "one"


def test_ownership(home: Path) -> None:
    skill(home / "mine" / "skills", "a")
    cfg = load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')
    d = home / "d"
    into_source = link(d / "a", home / "mine" / "skills" / "a")
    into_data = link(d / "b", cfg.paths.data_dir / "sources" / "x" / "skills" / "b")
    elsewhere = link(d / "c", home / "other" / "c")
    relative = link(d / "e", Path("../mine/skills/a"))
    (d / "real").mkdir()
    assert deploy.is_owned(into_source, cfg)
    assert deploy.is_owned(into_data, cfg)  # even dangling
    assert deploy.is_owned(relative, cfg)
    assert not deploy.is_owned(elsewhere, cfg)
    assert not deploy.is_owned(d / "real", cfg)
    assert deploy.link_target(relative) == home / "mine" / "skills" / "a"
    assert deploy.within(home / "mine" / "skills", home / "mine")
    assert not deploy.within(home / "mine-other", home / "mine")

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tack import deploy
from tack.config import ConfigError
from tack.deploy import Install
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
    record = deploy.Record()
    assert deploy.is_owned(into_source, cfg, record)
    assert deploy.is_owned(into_data, cfg, record)  # even dangling
    assert deploy.is_owned(relative, cfg, record)
    assert not deploy.is_owned(elsewhere, cfg, record)
    assert not deploy.is_owned(d / "real", cfg, record)
    # The record makes a link tack's while it still points where it did.
    record.links[str(elsewhere)] = str(home / "other" / "c")
    assert deploy.is_owned(elsewhere, cfg, record)
    record.links[str(elsewhere)] = str(home / "other" / "moved")
    assert not deploy.is_owned(elsewhere, cfg, record)
    assert deploy.link_target(relative) == home / "mine" / "skills" / "a"
    assert deploy.within(home / "mine" / "skills", home / "mine")
    assert not deploy.within(home / "mine-other", home / "mine")


def test_record_round_trip(home: Path) -> None:
    cfg = load(home)
    assert deploy.load_record(cfg.paths).links == {}
    deploy.save_record(cfg.paths, deploy.Record({"/a": "/b"}))
    assert deploy.load_record(cfg.paths).links == {"/a": "/b"}
    (cfg.paths.state_dir / "state.json").write_text("[]")
    with pytest.raises(ConfigError, match="not a version 1 ownership record"):
        deploy.load_record(cfg.paths)


def test_a_record_with_plugins_round_trips(home: Path) -> None:
    paths = load(home).paths
    record = deploy.Record(
        {"/a": "/b"},
        {
            "codex": {"y": Install("two", "h2"), "x": Install("one", "h1")},
            "claude-code": {"x": Install("one", "h0")},
        },
    )
    deploy.save_record(paths, record)
    assert deploy.load_record(paths) == record
    data = json.loads((paths.state_dir / "state.json").read_text())
    assert data == {
        "version": 1,
        "links": {"/a": "/b"},
        "plugins": {
            "claude-code": {"x": {"source": "one", "hash": "h0"}},
            "codex": {"x": {"source": "one", "hash": "h1"}, "y": {"source": "two", "hash": "h2"}},
        },
    }
    assert list(data["plugins"]) == ["claude-code", "codex"]
    assert list(data["plugins"]["codex"]) == ["x", "y"]


def test_a_record_with_links_only_is_written_as_before(home: Path) -> None:
    paths = load(home).paths
    file = paths.state_dir / "state.json"
    old = '{\n  "version": 1,\n  "links": {\n    "/a": "/b",\n    "/c": "/d"\n  }\n}\n'
    write(file, old)
    record = deploy.load_record(paths)
    assert record == deploy.Record({"/a": "/b", "/c": "/d"}, {})
    file.unlink()
    deploy.save_record(paths, record)
    assert file.read_text() == old


def test_a_harness_with_no_plugins_left_is_dropped(home: Path) -> None:
    paths = load(home).paths
    file = paths.state_dir / "state.json"
    deploy.save_record(
        paths, deploy.Record({}, {"claude-code": {}, "codex": {"x": Install("s", "h")}})
    )
    assert json.loads(file.read_text())["plugins"] == {"codex": {"x": {"source": "s", "hash": "h"}}}
    deploy.save_record(paths, deploy.Record({}, {"claude-code": {}, "codex": {}}))
    assert json.loads(file.read_text()) == {"version": 1, "links": {}}


@pytest.mark.parametrize(
    "plugins",
    [
        None,
        [],
        "x",
        {"codex": []},
        {"codex": {"x": "s"}},
        {"codex": {"x": {"source": "s"}}},
        {"codex": {"x": {"hash": "h"}}},
        {"codex": {"x": {"source": 1, "hash": "h"}}},
        {"codex": {"x": {"source": "s", "hash": None}}},
    ],
)
def test_a_malformed_plugins_record_is_rejected(home: Path, plugins: object) -> None:
    paths = load(home).paths
    write(
        paths.state_dir / "state.json", json.dumps({"version": 1, "links": {}, "plugins": plugins})
    )
    with pytest.raises(ConfigError, match="not a version 1 ownership record"):
        deploy.load_record(paths)


def test_state(home: Path) -> None:
    a = skill(home / "mine" / "skills", "a")
    skill(home / "mine" / "skills", "b")
    cfg = load(home, '[[source]]\nname = "mine"\npath = "~/mine"\nskills = ["a"]\n')
    sel = deploy.plan(cfg).links["codex"]["a"]
    record = deploy.Record()
    d = home / "d"
    assert deploy.state(d / "a", sel, cfg, record) == "absent"
    assert deploy.state(link(d / "ok", a), sel, cfg, record) == "ok"
    assert (
        deploy.state(link(d / "stale", home / "mine" / "skills" / "b"), sel, cfg, record) == "stale"
    )
    assert deploy.state(link(d / "other", home / "x"), sel, cfg, record) == "conflict"
    (d / "real").mkdir()
    assert deploy.state(d / "real", sel, cfg, record) == "conflict"
    assert deploy.state(d / "stale", None, cfg, record) == "owned"
    assert deploy.state(d / "other", None, cfg, record) == "foreign"


def test_make_link_replaces_a_link_atomically(home: Path) -> None:
    entry = home / "skills" / "a"
    deploy.make_link(entry, home / "one")
    deploy.make_link(entry, home / "two")
    assert deploy.link_target(entry) == home / "two"
    assert sorted(p.name for p in entry.parent.iterdir()) == ["a"]

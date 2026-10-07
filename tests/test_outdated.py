from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tack import catalog, cli, outdated, sources, sync
from tack.config import Config, UsageError
from tack.outdated import ChangedSkill
from tests.helpers import commit, git, load, repo, skill_md, upstream

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)


def source(up: Path, extra: str = "", name: str = "up") -> str:
    return f'[[source]]\nname = "{name}"\ngit = "{up}"\n{extra}'


def pinned(home: Path, manifest: str) -> Config:
    cfg = load(home, manifest)
    assert sync.sync(cfg, now=WHEN).problems == []
    return cfg


def only(cfg: Config, **kw) -> outdated.SourceReport:
    (report,) = outdated.outdated(cfg, **kw).sources
    return report


def test_up_to_date(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    cfg = pinned(home, source(up))
    report = outdated.outdated(cfg)
    (r,) = report.sources
    assert (r.state, r.pin, r.tip, r.behind) == ("current", r.tip, r.pin, 0)
    assert not report.failed


def test_behind(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a", "b", "c")
    cfg = pinned(home, source(up))
    pin = git(up, "rev-parse", "HEAD").strip()
    commit(up, {"skills/a/SKILL.md": skill_md("a") + "More.\n"}, "Change a")
    commit(up, {"skills/d/SKILL.md": skill_md("d")}, "Add d")
    git(up, "rm", "-rq", "skills/c")
    git(up, "commit", "-qm", "Drop c")
    tip = commit(up, {"README.md": "docs"}, "Docs")

    report = outdated.outdated(cfg)
    (r,) = report.sources
    assert report.failed
    assert (r.state, r.pin, r.tip, r.behind, r.rewritten) == ("behind", pin, tip, 4, False)
    assert r.skills == [
        ChangedSkill("a", "modified"),
        ChangedSkill("c", "removed"),
        ChangedSkill("d", "added"),
    ]
    assert [(c.subject, c.skills) for c in r.commits] == [
        ("Drop c", ["c"]),
        ("Add d", ["d"]),
        ("Change a", ["a"]),
    ]
    assert r.diff is None
    checkout = cfg.paths.sources_dir / "up"
    assert sources.head(checkout) == pin  # fetched, not moved

    diff = only(cfg, diff=True).diff
    assert diff is not None
    for text in ("+More.", "b/skills/d/SKILL.md", "a/skills/c/SKILL.md"):
        assert text in diff
    assert "README" not in diff


def test_only_selected_skills_count(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a", "b")
    cfg = pinned(home, source(up, 'skills = ["b"]\n'))
    commit(up, {"skills/a/SKILL.md": "changed"}, "Change a")
    commit(up, {"skills/new/SKILL.md": "new"}, "Add new")
    r = only(cfg)
    assert (r.state, r.behind, r.skills, r.commits) == ("behind", 2, [], [])


def test_subdir_at_the_root(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up")
    commit(up, {"a/SKILL.md": skill_md("a"), ".github/x.yml": "", "README.md": ""})
    cfg = pinned(home, source(up, 'subdir = "."\n'))
    commit(up, {"a/SKILL.md": "changed", ".github/x.yml": "y", "README.md": "z"}, "Many")
    r = only(cfg)
    assert r.skills == [ChangedSkill("a", "modified")]


def test_rewritten_history(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    commit(up, {"skills/a/SKILL.md": "second"})
    cfg = pinned(home, source(up))
    git(up, "reset", "-q", "--hard", "HEAD~1")
    commit(up, {"skills/a/SKILL.md": "rewritten"}, "Rewrite")
    r = only(cfg)
    assert (r.state, r.behind, r.rewritten) == ("behind", 1, True)
    assert r.skills == [ChangedSkill("a", "modified")]


def test_sources_that_cant_be_compared(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "a")
    manifest = source(up)
    cfg = load(home, manifest)
    assert (only(cfg).state, only(cfg).message) == (
        "not pinned",
        "not pinned yet; `tack sync` pins it",
    )
    sync.sync(cfg, now=WHEN)
    changed = load(home, manifest + 'ref = "master"\n')
    assert only(changed).state == "manifest changed"
    assert "`tack update up` re-pins it" in (only(changed).message or "")

    shutil.rmtree(tmp_path / "up")
    r = only(cfg)
    assert r.state == "error"
    assert (r.message or "").startswith("can't read")

    shutil.rmtree(cfg.paths.sources_dir / "up")
    assert only(cfg).state == "not checked out"
    assert outdated.outdated(cfg).failed


def test_which_sources(home: Path, tmp_path: Path) -> None:
    one, two = upstream(tmp_path / "one", "a"), upstream(tmp_path / "two", "b")
    (home / "mine" / "skills").mkdir(parents=True)
    cfg = pinned(
        home,
        source(one, name="one")
        + source(two, name="two")
        + '[[source]]\nname = "mine"\npath = "~/mine"\n',
    )
    assert [s.name for s in outdated.outdated(cfg).sources] == ["one", "two"]
    assert [s.name for s in outdated.outdated(cfg, ["two"]).sources] == ["two"]
    with pytest.raises(UsageError, match="'mine' is a path source"):
        outdated.outdated(cfg, ["mine"])
    with pytest.raises(UsageError, match="no source named 'nope'"):
        outdated.outdated(cfg, ["nope"])


# --- plugins (design.md *Tracking plugins upstream*) --------------------------------------

CATALOG = ".claude-plugin/marketplace.json"
CODEX_CATALOG = ".agents/plugins/marketplace.json"
SHA = "a" * 40
NPM_SOURCE = {"source": "npm", "package": "@acme/x"}


def catalog_json(*entries: Any) -> str:
    """A catalog listing `entries`: a name `n` is `./plugins/n` at version
    1.0 in its entry, anything else is the entry itself."""
    listed = [
        {"name": e, "source": f"./plugins/{e}", "version": "1.0"} if isinstance(e, str) else e
        for e in entries
    ]
    return json.dumps({"name": "up", "owner": {"name": "up"}, "plugins": listed}, indent=2)


def plugin_files(name: str, version: str | None = None, directory: str = "") -> dict[str, str]:
    """A plugin's files under `plugins/<name>` (or `directory`), its
    `plugin.json` giving `version` when there is one."""
    d = directory or f"plugins/{name}"
    doc: dict[str, str] = {"name": name} | ({"version": version} if version else {})
    return {f"{d}/.claude-plugin/plugin.json": json.dumps(doc), f"{d}/README.md": f"{name}\n"}


def plugin_upstream(path: Path, *names: str, skills: tuple[str, ...] = ()) -> Path:
    files = {CATALOG: catalog_json(*names)}
    for n in names:
        files |= plugin_files(n)
    for s in skills:
        files[f"skills/{s}/SKILL.md"] = skill_md(s)
    return repo(path, files)


def tracking(home: Path, up: Path, selection: str = '"*"', skills: str = "[]") -> Config:
    """`up` as a source selecting `selection`, pinned by a sync that selects
    no plugins (so no agent runs, and a catalog it can't deploy from is no
    problem); a pin is for the source's git and ref, whatever it selects."""
    pinned(home, source(up, f"skills = {skills}\n"))
    return load(home, source(up, f"skills = {skills}\nplugins = {selection}\n"))


def plugin_changes(r: outdated.SourceReport) -> list[tuple[str, str, str | None, str | None]]:
    return [(p.name, p.change, p.version["from"], p.version["to"]) for p in r.plugins]


def test_plugins_modified_added_removed(home: Path, tmp_path: Path) -> None:
    up = plugin_upstream(tmp_path / "up", "files", "entry", "moved", "dropped", "same")
    cfg = tracking(home, up)
    commit(up, {"plugins/files/README.md": "changed\n"}, "Change files")
    entries: list[Any] = [
        "files",
        {"name": "entry", "source": "./plugins/entry", "version": "1.0", "description": "New."},
        {"name": "moved", "source": "./elsewhere/moved", "version": "1.0"},
        "same",
        "new",
    ]
    git(up, "mv", "plugins/moved", "elsewhere")
    commit(up, {CATALOG: catalog_json(*entries), **plugin_files("new", "3.0")}, "Catalog")

    r = only(cfg)
    assert (r.state, r.skills, r.plugins_error) == ("behind", [], None)
    assert plugin_changes(r) == [
        ("dropped", "removed", "1.0", None),
        ("entry", "modified", "1.0", "1.0"),
        ("files", "modified", "1.0", "1.0"),
        ("moved", "modified", "1.0", "1.0"),
        ("new", "added", None, "3.0"),
    ]


@pytest.mark.parametrize("end", ["pin", "tip"])
def test_a_file_change_under_the_directory_at_either_end(
    home: Path, tmp_path: Path, end: str
) -> None:
    """A new `pluginRoot` moves a plugin without changing its entry: a change
    under its directory at the pin, or at the tip, modifies it."""

    def listing(root: str) -> str:
        return json.dumps(
            {"metadata": {"pluginRoot": root}, "plugins": [{"name": "b", "source": "b"}]}
        )

    up = repo(
        tmp_path / "up",
        {
            CATALOG: listing("./old"),
            **plugin_files("b", directory="old/b"),
            **plugin_files("b", directory="new/b"),
        },
    )
    cfg = tracking(home, up)
    commit(up, {CATALOG: listing("./new")}, "Move b")
    assert only(cfg).plugins == []  # the same entry, and the same files at both ends

    commit(up, {f"{'old' if end == 'pin' else 'new'}/b/README.md": "changed\n"})
    assert plugin_changes(only(cfg)) == [("b", "modified", None, None)]


def test_a_file_moved_out_of_a_plugin(home: Path, tmp_path: Path) -> None:
    """A rename counts at both its paths: the plugin it leaves changed."""
    up = plugin_upstream(tmp_path / "up", "a")
    cfg = tracking(home, up)
    git(up, "mv", "plugins/a/README.md", "README.md")
    git(up, "commit", "-qm", "Move a file out")
    assert plugin_changes(only(cfg)) == [("a", "modified", "1.0", "1.0")]


def test_a_plugin_that_is_the_whole_repository(home: Path, tmp_path: Path) -> None:
    """Any file in the repository is under its directory."""
    entry = {"name": "w", "source": "./"}
    up = repo(tmp_path / "up", {CATALOG: catalog_json(entry), **plugin_files("w", "1.0", ".")})
    cfg = tracking(home, up)
    commit(up, {"docs/x.md": "new\n"})
    assert plugin_changes(only(cfg)) == [("w", "modified", "1.0", "1.0")]


def test_a_listed_selection(home: Path, tmp_path: Path) -> None:
    """Only the names it lists: a new plugin it doesn't name isn't added, an
    unselected plugin's change is ignored, and a name in neither catalog is
    left out."""
    up = plugin_upstream(tmp_path / "up", "a", "b")
    cfg = tracking(home, up, '["a", "gone"]')
    commit(up, {"plugins/b/README.md": "changed\n"}, "Change b")
    commit(up, {CATALOG: catalog_json("a", "b", "new"), **plugin_files("new")}, "Add new")

    r = only(cfg)
    assert (r.state, r.plugins, r.plugins_error) == ("behind", [], None)

    commit(up, {"plugins/a/README.md": "changed\n"}, "Change a")
    assert plugin_changes(only(cfg)) == [("a", "modified", "1.0", "1.0")]


def test_a_plugin_from_another_repository(home: Path, tmp_path: Path) -> None:
    """Modified by its entry (a new commit), never by files in the source."""
    entry = {"name": "r", "source": {"source": "github", "repo": "acme/r", "sha": SHA}}
    up = repo(tmp_path / "up", {CATALOG: catalog_json(entry), "plugins/r/README.md": "r\n"})
    cfg = tracking(home, up)
    commit(up, {"plugins/r/README.md": "changed\n"})
    assert only(cfg).plugins == []

    moved = {**entry, "source": {**entry["source"], "sha": "b" * 40}}
    commit(up, {CATALOG: catalog_json(moved)}, "Bump r")
    assert plugin_changes(only(cfg)) == [("r", "modified", None, None)]


def test_a_name_listed_twice_is_all_its_entries(home: Path, tmp_path: Path) -> None:
    twice = ({"name": "t", "source": "./plugins/t"}, {"name": "t", "source": "./plugins/u"})
    up = repo(tmp_path / "up", {CATALOG: catalog_json(*twice), **plugin_files("t")})
    cfg = tracking(home, up)
    commit(up, {"plugins/t/README.md": "changed\n"})
    assert only(cfg).plugins == []  # it can't be deployed: only its entries count

    commit(up, {CATALOG: catalog_json(twice[0], {**twice[1], "version": "2"})})
    assert plugin_changes(only(cfg)) == [("t", "modified", None, None)]


def test_entries_compare_as_json(home: Path, tmp_path: Path) -> None:
    """Reordered keys and reformatted text aren't a change; a number that
    becomes a string is."""
    entry = {"name": "a", "source": "./plugins/a", "tags": [1]}
    up = repo(tmp_path / "up", {CATALOG: catalog_json(entry), **plugin_files("a")})
    cfg = tracking(home, up)
    reordered = {"tags": [1], "source": "./plugins/a", "name": "a"}
    commit(up, {CATALOG: json.dumps({"plugins": [reordered], "name": "up"})})
    assert only(cfg).plugins == []

    commit(up, {CATALOG: json.dumps({"plugins": [{**reordered, "tags": ["1"]}]})})
    assert plugin_changes(only(cfg)) == [("a", "modified", None, None)]


def test_versions(home: Path, tmp_path: Path) -> None:
    """From `plugin.json` at each end, else the entry; none at the end
    without the plugin."""
    from_entry = {"name": "e", "source": "./plugins/e", "version": "2.0"}
    up = repo(
        tmp_path / "up",
        {
            CATALOG: catalog_json("j", from_entry, "gone", "same"),
            **plugin_files("j", "1.0"),
            **plugin_files("e"),
            **plugin_files("gone", "0.9"),
            **plugin_files("same", "4.0"),
        },
    )
    cfg = tracking(home, up)
    commit(
        up,
        {
            CATALOG: catalog_json("j", {**from_entry, "version": "2.1"}, "same", "new"),
            **plugin_files("j", "1.1"),
            **plugin_files("new", "5.0"),
            "plugins/same/README.md": "changed\n",
        },
    )
    git(up, "rm", "-rq", "plugins/gone")
    git(up, "commit", "-qm", "Drop gone")

    assert plugin_changes(only(cfg)) == [
        ("e", "modified", "2.0", "2.1"),
        ("gone", "removed", "0.9", None),
        ("j", "modified", "1.0", "1.1"),
        ("new", "added", None, "5.0"),
        ("same", "modified", "4.0", "4.0"),
    ]


@pytest.mark.parametrize("end", ["tip", "pin"])
def test_a_broken_catalog(home: Path, tmp_path: Path, end: str) -> None:
    """No plugin changes, `plugins_error` saying why, and the skills still
    compared (DEC-20)."""
    up = plugin_upstream(tmp_path / "up", "a", skills=("s",))
    if end == "pin":
        commit(up, {CATALOG: "{"}, "Break")
    pin = git(up, "rev-parse", "HEAD").strip()
    cfg = tracking(home, up, skills='"*"')
    tip = commit(
        up,
        {
            CATALOG: "{" if end == "tip" else catalog_json("a", "new"),
            "skills/s/SKILL.md": "changed\n",
            **plugin_files("new"),
        },
    )

    r = only(cfg)
    assert (r.skills, r.plugins) == ([ChangedSkill("s", "modified")], [])
    at = pin if end == "pin" else tip
    assert r.plugins_error == (
        f"plugins not compared: the catalog at the {end} ({at[:12]}) is broken: "
        f"{CATALOG}: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
    )


def test_a_source_selecting_no_plugins_reads_no_catalog(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    up = plugin_upstream(tmp_path / "up", "a", skills=("s",))
    cfg = pinned(home, source(up))
    commit(up, {CATALOG: "{", "plugins/a/README.md": "changed\n"}, "Break")

    r = only(cfg)
    assert (r.state, r.skills, r.plugins, r.plugins_error) == ("behind", [], [], None)

    def unread(*args: object) -> None:
        raise AssertionError("read a catalog")

    monkeypatch.setattr(catalog, "read_at", unread)
    assert only(cfg).plugins_error is None


def test_a_source_at_its_tip_reads_no_catalog(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    up = plugin_upstream(tmp_path / "up", "a")
    cfg = tracking(home, up)

    def unread(*args: object) -> None:
        raise AssertionError("read a catalog")

    monkeypatch.setattr(catalog, "read_at", unread)
    assert (only(cfg).state, only(cfg).plugins) == ("current", [])


# The reader at a commit, against the one on disk.

_READS: dict[str, dict[str, str]] = {
    "claude code's": {CATALOG: catalog_json("a", {"name": "x", "source": NPM_SOURCE})},
    "codex's": {
        CODEX_CATALOG: catalog_json({"name": "c", "source": {"source": "local", "path": "./c"}})
    },
    "both": {CATALOG: catalog_json("a"), CODEX_CATALOG: catalog_json("c")},
    "none": {"README.md": "no catalog\n"},
    "ignored entries": {
        CATALOG: json.dumps({"plugins": [1, {"name": "Bad name"}, {"name": "ok"}]})
    },
    "plugin root": {
        CATALOG: json.dumps(
            {"metadata": {"pluginRoot": "./ps"}, "plugins": [{"name": "b", "source": "b"}]}
        )
    },
    "a link to the catalog": {"catalogs/real.json": catalog_json("a")},
}


@pytest.mark.parametrize("case", _READS)
def test_reading_at_a_commit_is_reading_the_checkout(tmp_path: Path, case: str) -> None:
    up = repo(tmp_path / "up", _READS[case], commit=False)
    if case == "a link to the catalog":
        (up / ".claude-plugin").mkdir()
        (up / CATALOG).symlink_to("../catalogs/real.json")
    git(up, "add", "-A")
    git(up, "commit", "-qm", "init")

    disk, at = catalog.read(up), catalog.read_at(up, "HEAD")
    if disk is None:
        assert at is None
        return
    assert at is not None
    assert (at.plugins, at.ignored) == (disk.plugins, disk.ignored)
    assert str(up / at.file) == disk.file


@pytest.mark.parametrize(
    "files",
    [
        {CATALOG: "{", CODEX_CATALOG: catalog_json("c")},  # not passed over for Codex's
        {CODEX_CATALOG: "[]"},
        {CATALOG: json.dumps({"plugins": {}})},
        {CATALOG: "\udcff"},
    ],
    ids=["invalid json", "not an object", "no plugins list", "not utf-8"],
)
def test_a_broken_catalog_at_a_commit_is_broken_on_disk(
    tmp_path: Path, files: dict[str, str]
) -> None:
    up = repo(tmp_path / "up", commit=False)
    for rel, text in files.items():
        (up / rel).parent.mkdir(parents=True, exist_ok=True)
        (up / rel).write_bytes(text.encode("utf-8", "surrogateescape"))
    git(up, "add", "-A")
    git(up, "commit", "-qm", "init")

    with pytest.raises(catalog.CatalogError) as on_disk:
        catalog.read(up)
    with pytest.raises(catalog.CatalogError) as at_commit:
        catalog.read_at(up, "HEAD")
    assert str(on_disk.value) == f"{up}/{at_commit.value}"


def test_a_catalog_at_a_commit_thats_a_directory(tmp_path: Path) -> None:
    up = repo(tmp_path / "up", {f"{CATALOG}/x": "", CODEX_CATALOG: catalog_json("c")})
    with pytest.raises(catalog.CatalogError, match="a directory, not a file"):
        catalog.read_at(up, "HEAD")
    with pytest.raises(catalog.CatalogError):
        catalog.read(up)


@pytest.mark.parametrize(
    ("files", "entry", "expected"),
    [
        (plugin_files("p", "1.0", "d"), {}, "1.0"),
        ({"d/plugin.json": json.dumps({"version": "2.0"})}, {"version": "9"}, "2.0"),
        ({"d/.codex-plugin/plugin.json": json.dumps({"version": "3.0"})}, {}, "3.0"),
        ({"d/.claude-plugin/plugin.json": "{", "d/plugin.json": '{"version": "4.0"}'}, {}, "4.0"),
        ({"d/.claude-plugin/plugin.json": json.dumps({"name": "p"})}, {"version": "5.0"}, "5.0"),
        ({"d/README.md": ""}, {}, None),
    ],
    ids=["claude code's", "root", "codex's", "the next file", "the entry's", "none"],
)
def test_a_version_at_a_commit_is_the_checkouts(
    tmp_path: Path, files: dict[str, str], entry: dict[str, str], expected: str | None
) -> None:
    """In a plugin's directory, and in a plugin that is the whole repository."""
    up = repo(tmp_path / "up", files)
    whole = repo(tmp_path / "whole", {k.removeprefix("d/"): v for k, v in files.items()})
    at_commit = catalog.version(entry, catalog.files_at(up, "HEAD", "d"))
    assert at_commit == catalog.version(entry, catalog.files(up / "d")) == expected
    at_commit = catalog.version(entry, catalog.files_at(whole, "HEAD", "."))
    assert at_commit == catalog.version(entry, catalog.files(whole)) == expected


def test_outdated_json_gives_plugins(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    up = plugin_upstream(tmp_path / "up", "a", "b")
    tracking(home, up)
    commit(up, {CATALOG: catalog_json("a", "c"), **plugin_files("a", "1.1"), **plugin_files("c")})

    assert cli.main(["outdated", "--json"]) == 1
    (data,) = json.loads(capsys.readouterr().out)["sources"]
    assert data["plugins"] == [
        {"name": "a", "change": "modified", "version": {"from": "1.0", "to": "1.1"}},
        {"name": "b", "change": "removed", "version": {"from": "1.0", "to": None}},
        {"name": "c", "change": "added", "version": {"from": None, "to": "1.0"}},
    ]
    assert data["plugins_error"] is None
    assert list(data)[list(data).index("skills") :][:3] == ["skills", "plugins", "plugins_error"]

    commit(up, {CATALOG: "{"})
    assert cli.main(["outdated", "--json"]) == 1
    (data,) = json.loads(capsys.readouterr().out)["sources"]
    assert data["plugins"] == []
    assert data["plugins_error"].startswith("plugins not compared: the catalog at the tip (")


def _report(*plugins: outdated.ChangedPlugin, **kw: Any) -> outdated.Report:
    pin, tip = "1" * 40, "2" * 40
    report = outdated.SourceReport("up", "u", None, "behind", pin=pin, tip=tip, behind=1, **kw)
    report.plugins = list(plugins)
    return outdated.Report([report])


def _changed(
    name: str, change: outdated.SkillChange, was: str | None, now: str | None
) -> outdated.ChangedPlugin:
    return outdated.ChangedPlugin(name, change, {"from": was, "to": now})


def test_outdated_text_for_plugins() -> None:
    report = _report(
        _changed("a", "modified", "1.0", "1.1"),
        _changed("b", "modified", None, None),
        _changed("c", "modified", "2.0", "2.0"),
        _changed("d", "modified", None, "3.0"),
        _changed("e", "modified", "4.0", None),
        _changed("f", "added", None, "5.0"),
        _changed("g", "added", None, None),
        _changed("h", "removed", "6.0", None),
        _changed("i", "removed", None, None),
    )
    assert cli._outdated_text(report, {"up"}).splitlines()[1:4] == [
        "    plugins modified: a (1.0 -> 1.1), b, c (2.0), d (none -> 3.0), e (4.0 -> none)",
        "    plugins added: f (5.0), g",
        "    plugins removed: h (6.0), i",
    ]


def test_outdated_text_when_nothing_selected_changed() -> None:
    def said(selects_plugins: bool, **kw: Any) -> list[str]:
        text = cli._outdated_text(_report(**kw), {"up"} if selects_plugins else set())
        return text.splitlines()[1:-2]

    assert said(False) == ["    no selected skill changed"]
    assert said(True) == ["    no selected skill or plugin changed"]
    assert said(True, plugins_error="plugins not compared: why") == [
        "    plugins not compared: why",
        "    no selected skill changed",
    ]
    assert said(True, skills=[ChangedSkill("s", "added")], plugins_error="why") == [
        "    added: s",
        "    why",
    ]


# --- commits touching plugins, and `--diff` ---------------------------------------------


def listed(r: outdated.SourceReport) -> dict[str, tuple[list[str], list[str]]]:
    return {c.subject: (c.skills, c.plugins) for c in r.commits}


def test_commits_touching_plugins(home: Path, tmp_path: Path) -> None:
    """A file under a plugin's directory, or its entry changed in a catalog
    file (one that can't be read having no entries); only selected plugins."""
    up = plugin_upstream(tmp_path / "up", "a", "b", "c", skills=("s",))
    cfg = tracking(home, up, '["a", "b"]', skills='"*"')
    described = {"name": "b", "source": "./plugins/b", "version": "1.0", "description": "B."}
    commit(up, {"plugins/a/README.md": "changed\n"}, "File a")
    commit(up, {CATALOG: catalog_json("a", described, "c")}, "Entry b")
    commit(up, {CATALOG: catalog_json("a", described, {"name": "c", "source": "./c"})}, "Entry c")
    commit(up, {CATALOG: "{"}, "Break")
    commit(up, {CATALOG: catalog_json("a", described, "c")}, "Fix")
    commit(up, {"skills/s/SKILL.md": "changed\n", "plugins/a/README.md": "again\n"}, "Both")
    commit(up, {"plugins/c/README.md": "changed\n", "README.md": "docs\n"}, "Neither")

    r = only(cfg)
    assert r.plugins_error is None
    assert [(c.subject, c.skills, c.plugins) for c in r.commits] == [
        ("Both", ["s"], ["a"]),
        ("Fix", [], ["a", "b"]),
        ("Break", [], ["a", "b"]),
        ("Entry b", [], ["b"]),
        ("File a", [], ["a"]),
    ]


def test_a_merge_touches_no_plugin(home: Path, tmp_path: Path) -> None:
    up = plugin_upstream(tmp_path / "up", "a", "b")
    cfg = tracking(home, up)
    git(up, "checkout", "-qb", "side")
    commit(up, {"plugins/b/README.md": "side\n"}, "Side b")
    git(up, "checkout", "-q", "master")
    commit(up, {"plugins/a/README.md": "main\n"}, "Main a")
    git(up, "merge", "-q", "--no-ff", "-m", "Merge side", "side")

    r = only(cfg)
    assert listed(r) == {"Side b": ([], ["b"]), "Main a": ([], ["a"])}
    assert [p.name for p in r.plugins] == ["a", "b"]


def test_no_commit_is_attributed_to_plugins_not_compared(home: Path, tmp_path: Path) -> None:
    up = plugin_upstream(tmp_path / "up", "a", skills=("s",))
    cfg = tracking(home, up, skills='"*"')
    commit(up, {"plugins/a/README.md": "changed\n"}, "File a")
    commit(up, {"skills/s/SKILL.md": "changed\n", "plugins/a/README.md": "x\n"}, "Both")
    commit(up, {CATALOG: "{"}, "Break")

    r = only(cfg)
    assert r.plugins_error is not None
    assert listed(r) == {"Both": (["s"], [])}


def test_a_source_selecting_no_plugins_lists_its_commits_as_before(
    home: Path, tmp_path: Path
) -> None:
    up = plugin_upstream(tmp_path / "up", "a", skills=("s",))
    cfg = pinned(home, source(up))
    commit(up, {"plugins/a/README.md": "changed\n"}, "File a")
    commit(up, {"skills/s/SKILL.md": "changed\n"}, "Skill s")
    assert listed(only(cfg)) == {"Skill s": (["s"], [])}


def test_diff_adds_each_changed_plugin(home: Path, tmp_path: Path) -> None:
    """After the skills' diff, each changed plugin's in name order: its files
    at either end, then its entry's, JSON in the catalog's key order."""
    up = plugin_upstream(tmp_path / "up", "a", "b", "gone", "same", "other", skills=("s",))
    cfg = tracking(home, up, '["a", "b", "gone", "same", "new"]', skills='"*"')
    described = {"name": "b", "source": "./plugins/b", "version": "1.0", "description": "B."}
    new = {"source": "./plugins/new", "name": "new"}
    git(up, "rm", "-rq", "plugins/gone")
    commit(
        up,
        {
            CATALOG: catalog_json("a", described, "same", "other", new),
            "skills/s/SKILL.md": "changed\n",
            "plugins/a/README.md": "changed a\n",
            "plugins/other/README.md": "changed other\n",
            **plugin_files("new"),
        },
    )

    r = only(cfg, diff=True)
    assert [p.name for p in r.plugins] == ["a", "b", "gone", "new"]
    diff = r.diff
    assert diff is not None
    heads = [
        "diff --git a/skills/s/SKILL.md b/skills/s/SKILL.md",
        "diff --git a/plugins/a/README.md b/plugins/a/README.md",
        "--- a/.claude-plugin/marketplace.json#b\n+++ b/.claude-plugin/marketplace.json#b\n",
        "diff --git a/plugins/gone/README.md b/plugins/gone/README.md\ndeleted file",
        "--- a/.claude-plugin/marketplace.json#gone\n+++ /dev/null\n",
        "diff --git a/plugins/new/README.md b/plugins/new/README.md\nnew file",
        "--- /dev/null\n+++ b/.claude-plugin/marketplace.json#new\n",
    ]
    at = [diff.index(h) for h in heads]
    assert at == sorted(at)
    assert '+  "description": "B."\n' in diff
    assert (
        "--- /dev/null\n"
        "+++ b/.claude-plugin/marketplace.json#new\n"
        "@@ -0,0 +1,4 @@\n"
        "+{\n"
        '+  "source": "./plugins/new",\n'
        '+  "name": "new"\n'
        "+}\n"
    ) in diff
    for unchanged in ("plugins/same", "plugins/other", "marketplace.json#a", "#same"):
        assert unchanged not in diff
    assert only(cfg).diff is None


def test_diff_of_plugins_alone(home: Path, tmp_path: Path) -> None:
    up = plugin_upstream(tmp_path / "up", "a")
    cfg = tracking(home, up)
    commit(up, {"plugins/a/README.md": "changed\n"})
    diff = only(cfg, diff=True).diff
    assert diff is not None
    assert diff.startswith("diff --git a/plugins/a/README.md b/plugins/a/README.md\n")
    assert "+changed" in diff

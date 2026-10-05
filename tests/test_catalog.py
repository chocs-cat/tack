from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tack import catalog
from tack.catalog import CatalogError, Ignored, InRepository, InSource, Undeployable
from tests.helpers import write

SHA = "0123456789abcdef0123456789abcdef01234567"


def one(source: Any, *, root: Any = None, **entry: Any) -> catalog.Where:
    """How the catalog classifies a single entry with `source`."""
    data: dict[str, Any] = {"plugins": [{"name": "x", "source": source, **entry}]}
    if root is not None:
        data["metadata"] = {"pluginRoot": root}
    (plugin,) = catalog.parse(data, "test").plugins
    return plugin.where


def undeployable(where: catalog.Where, *words: str) -> None:
    assert isinstance(where, Undeployable), where
    for w in words:
        assert w in where.reason, where.reason


# --- find and read ------------------------------------------------------------


def _catalog(root: Path, rel: str, *names: str) -> None:
    write(root / rel, json.dumps({"plugins": [{"name": n, "source": f"./{n}"} for n in names]}))


def test_find_prefers_claude_code_catalog(tmp_path: Path) -> None:
    claude, codex = ".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"
    only_claude, only_codex, both, neither = (tmp_path / d for d in ("a", "b", "c", "d"))
    _catalog(only_claude, claude, "one")
    _catalog(only_codex, codex, "two")
    _catalog(both, claude, "three")
    _catalog(both, codex, "four")
    neither.mkdir()

    assert catalog.find(only_claude) == only_claude / claude
    assert catalog.find(only_codex) == only_codex / codex
    assert catalog.find(both) == both / claude
    assert catalog.find(neither) is None
    assert catalog.read(neither) is None
    read = catalog.read(both)
    assert read is not None
    assert read.file == str(both / claude)
    assert [p.name for p in read.plugins] == ["three"]
    read = catalog.read(only_codex)
    assert read is not None
    assert [p.name for p in read.plugins] == ["two"]


@pytest.mark.parametrize("text", ["{not json", '{"plugins": 3}', "[]"])
def test_read_of_broken_claude_code_catalog_does_not_fall_back(tmp_path: Path, text: str) -> None:
    write(tmp_path / ".claude-plugin" / "marketplace.json", text)
    _catalog(tmp_path, ".agents/plugins/marketplace.json", "good")
    with pytest.raises(CatalogError, match=r"\.claude-plugin/marketplace\.json"):
        catalog.read(tmp_path)


def test_read_of_undecodable_catalog(tmp_path: Path) -> None:
    file = tmp_path / ".claude-plugin" / "marketplace.json"
    file.parent.mkdir()
    file.write_bytes(b'{"plugins": ["\xff"]}')
    with pytest.raises(CatalogError, match=r"marketplace\.json"):
        catalog.read(tmp_path)


# --- parse: plugins in the source ---------------------------------------------


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("./plugins/x", "plugins/x"),
        ("./", "."),
        (".", "."),
        ("./plugins/x/", "plugins/x"),
        ("./plugins//x/./", "plugins/x"),
        ({"source": "local", "path": "./plugins/x"}, "plugins/x"),
        ({"source": "local", "path": "."}, "."),
    ],
)
def test_paths_in_the_source(source: Any, path: str) -> None:
    assert one(source) == InSource(path)


@pytest.mark.parametrize("root", ["./plugins", "plugins", "./plugins/", "plugins/./"])
def test_bare_name_under_plugin_root(root: str) -> None:
    assert one("x", root=root) == InSource("plugins/x")
    assert one({"source": "local", "path": "x"}, root=root) == InSource("plugins/x")


def test_bare_name_under_root_plugin_root() -> None:
    assert one("x", root=".") == InSource("x")


def test_bare_name_without_plugin_root() -> None:
    undeployable(one("x"), "'x'", "bare name", "metadata.pluginRoot")
    data = {"metadata": "plugins", "plugins": [{"name": "x", "source": "x"}]}
    undeployable(catalog.parse(data, "test").plugins[0].where, "bare name")


@pytest.mark.parametrize("root", ["../elsewhere", "/abs/plugins", "plugins/../..", "", 3])
def test_bare_name_under_plugin_root_leaving_the_source(root: Any) -> None:
    undeployable(one("x", root=root), "bare name", "metadata.pluginRoot")


@pytest.mark.parametrize(
    ("source", "words"),
    [
        ("plugins/x", ["'plugins/x'", "./"]),
        ("/abs/plugins/x", ["'/abs/plugins/x'", "./"]),
        ("", ["''"]),
        ("../x", ["`..`"]),
        ("./plugins/../x", ["`..`"]),  # would land back inside: still refused
        ("./plugins/x/..", ["`..`"]),
        ("..", ["`..`"]),
        ({"source": "local", "path": "../x"}, ["`path`", "`..`"]),
        ({"source": "local", "path": "plugins/x"}, ["`path`", "./"]),
        ({"source": "local"}, ["`local`", "`path`"]),
    ],
)
def test_paths_that_cannot_be_deployed(source: Any, words: list[str]) -> None:
    undeployable(one(source), *words)


def test_dotdot_wins_over_plugin_root() -> None:
    undeployable(one("..", root="plugins"), "`..`")


# --- parse: plugins in other repositories -------------------------------------


@pytest.mark.parametrize(
    ("source", "where"),
    [
        (
            {"source": "url", "url": "https://example.com/p.git", "sha": SHA},
            InRepository("https://example.com/p.git", None, SHA),
        ),
        (
            {"source": "github", "repo": "owner/repo", "sha": SHA},
            InRepository("https://github.com/owner/repo.git", None, SHA),
        ),
        (
            {"source": "git-subdir", "url": "https://example.com/m.git", "path": "a/b", "sha": SHA},
            InRepository("https://example.com/m.git", "a/b", SHA),
        ),
        (
            {"source": "git-subdir", "url": "owner/repo", "path": "./a/b/", "sha": SHA},
            InRepository("https://github.com/owner/repo.git", "a/b", SHA),
        ),
        (
            {"source": "git-subdir", "url": "git@example.com:m.git", "path": "./", "sha": SHA},
            InRepository("git@example.com:m.git", ".", SHA),
        ),
        (
            {"source": "url", "url": "https://example.com/p.git", "ref": "main", "sha": SHA},
            InRepository("https://example.com/p.git", None, SHA),
        ),
    ],
)
def test_other_repositories_pinned_by_sha(source: Any, where: InRepository) -> None:
    assert one(source) == where


@pytest.mark.parametrize(
    "base",
    [
        {"source": "url", "url": "https://example.com/p.git"},
        {"source": "github", "repo": "owner/repo"},
        {"source": "git-subdir", "url": "owner/repo", "path": "a"},
    ],
)
def test_other_repositories_need_a_full_lowercase_sha(base: dict[str, Any]) -> None:
    kind = base["source"]
    undeployable(one({**base, "ref": "main"}), f"`{kind}`", "only to a `ref`", "`sha`")
    undeployable(one(base), f"`{kind}`", "no `sha`")
    undeployable(one({**base, "sha": SHA.upper()}), "`sha`", "lowercase")
    undeployable(one({**base, "sha": SHA[:12]}), f"{SHA[:12]!r}", "40")
    undeployable(one({**base, "sha": 7}), "`sha`")


@pytest.mark.parametrize(
    ("source", "words"),
    [
        ({"source": "git-subdir", "url": "owner/repo", "path": "../a", "sha": SHA}, ["`..`"]),
        ({"source": "git-subdir", "url": "owner/repo", "path": "a/../b", "sha": SHA}, ["`..`"]),
        ({"source": "git-subdir", "url": "owner/repo", "path": "/a", "sha": SHA}, ["'/a'"]),
        ({"source": "git-subdir", "url": "owner/repo", "sha": SHA}, ["`git-subdir`", "`path`"]),
        ({"source": "git-subdir", "path": "a", "sha": SHA}, ["`git-subdir`", "`url`"]),
        ({"source": "url", "sha": SHA}, ["`url`", "needs a `url`"]),
        ({"source": "url", "url": "", "sha": SHA}, ["needs a `url`"]),
        ({"source": "github", "sha": SHA}, ["`github`", "`repo`"]),
        ({"source": "github", "repo": "https://github.com/o/r", "sha": SHA}, ["owner/repo"]),
        ({"source": "npm", "package": "x"}, ["`npm`", "pinned"]),
        ({"source": "archive", "url": "https://example.com/x.tgz"}, ["`archive`", "pinned"]),
        ({"source": "command", "command": "make"}, ["`command`", "pinned"]),
        ({"source": "svn", "url": "x"}, ["unknown", "'svn'"]),
        ({"url": "https://example.com/p.git", "sha": SHA}, ["no `source` type"]),
        (["./x"], ["neither a path nor an object"]),
        (None, ["neither a path nor an object"]),
    ],
)
def test_sources_that_cannot_be_deployed(source: Any, words: list[str]) -> None:
    undeployable(one(source), *words)


def test_entry_without_source() -> None:
    (plugin,) = catalog.parse({"plugins": [{"name": "x"}]}, "test").plugins
    undeployable(plugin.where, "no `source`")


# --- parse: the catalog as a whole --------------------------------------------


def test_ignored_entries_are_listed_with_their_index() -> None:
    data = {
        "plugins": [
            "x",
            {"name": "good", "source": "./good"},
            {"source": "./anonymous"},
            {"name": "bad/name", "source": "./bad"},
            {"name": 3, "source": "./three"},
            None,
        ]
    }
    parsed = catalog.parse(data, "test")
    assert [p.name for p in parsed.plugins] == ["good"]
    assert [i.index for i in parsed.ignored] == [0, 2, 3, 4, 5]
    assert parsed.ignored[0] == Ignored(0, "not an object")
    assert "no `name`" in parsed.ignored[1].reason
    assert "'bad/name'" in parsed.ignored[2].reason
    assert "3" in parsed.ignored[3].reason


def test_name_listed_twice_is_not_deployable() -> None:
    data = {
        "plugins": [
            {"name": "x", "source": "./a"},
            {"name": "y", "source": "./y"},
            {"name": "x", "source": "./b"},
        ]
    }
    x1, y, x2 = catalog.parse(data, "test").plugins
    assert y.where == InSource("y")
    for x, src in ((x1, "./a"), (x2, "./b")):
        assert x.name == "x"
        undeployable(x.where, "'x'", "more than once")
        assert x.entry["source"] == src


@pytest.mark.parametrize(
    "data",
    [
        [{"name": "x", "source": "./x"}],
        "plugins",
        {"name": "m"},
        {"plugins": {"x": "./x"}},
        None,
    ],
)
def test_not_a_catalog(data: Any) -> None:
    with pytest.raises(CatalogError, match=r"^label: .*`plugins` list"):
        catalog.parse(data, "label")


def test_upstream_entry_is_kept_unchanged() -> None:
    entry = {
        "name": "x",
        "source": {"source": "local", "path": "./plugins/x"},
        "description": "The x plugin",
        "version": "1.2.0",
        "author": {"name": "Someone"},
        "headers": {"Authorization": "secret"},
        "category": "development",
    }
    data: dict[str, Any] = {"name": "m", "metadata": {"pluginRoot": "plugins"}, "plugins": [entry]}
    before = copy.deepcopy(data)
    (plugin,) = catalog.parse(data, "test").plugins
    assert plugin.entry == before["plugins"][0]
    assert data == before


def test_parse_is_codex_and_claude_code_alike() -> None:
    claude = {"plugins": [{"name": "x", "source": "./plugins/x"}]}
    codex = {"plugins": [{"name": "x", "source": {"source": "local", "path": "./plugins/x"}}]}
    assert catalog.parse(claude, "a").plugins[0].where == InSource("plugins/x")
    assert catalog.parse(codex, "b").plugins[0].where == InSource("plugins/x")


# --- version ------------------------------------------------------------------


def _reader(files: Mapping[str, str | bytes]) -> Any:
    def read(rel: str) -> bytes | None:
        v = files.get(rel)
        return v.encode() if isinstance(v, str) else v

    return read


def _v(version: str) -> str:
    return json.dumps({"name": "x", "version": version})


def test_version_precedence() -> None:
    entry = {"name": "x", "version": "0.0.1-entry"}
    claude, root, codex = catalog.PLUGIN_JSONS
    every = {claude: _v("1-claude"), root: _v("2-root"), codex: _v("3-codex")}
    assert catalog.version(entry, _reader(every)) == "1-claude"
    assert catalog.version(entry, _reader({root: _v("2"), codex: _v("3")})) == "2"
    assert catalog.version(entry, _reader({codex: _v("3")})) == "3"
    assert catalog.version(entry, _reader({})) == "0.0.1-entry"
    assert catalog.version({"name": "x"}, _reader({})) is None
    assert catalog.version({"name": "x", "version": 2}, _reader({})) is None


@pytest.mark.parametrize(
    "bad",
    [
        "{not json",
        b"\xff\xfe",
        json.dumps({"name": "x"}),
        json.dumps({"version": 3}),
        json.dumps(["version", "9"]),
    ],
)
def test_version_skips_unusable_plugin_json(bad: str | bytes) -> None:
    claude, root, _ = catalog.PLUGIN_JSONS
    assert catalog.version({"version": "e"}, _reader({claude: bad, root: _v("2")})) == "2"
    assert catalog.version({"version": "e"}, _reader({claude: bad})) == "e"


def test_version_from_a_directory(tmp_path: Path) -> None:
    write(tmp_path / "plugin.json", _v("2.0.0"))
    write(tmp_path / ".codex-plugin" / "plugin.json", _v("3.0.0"))
    assert catalog.version({"version": "1"}, catalog.files(tmp_path)) == "2.0.0"
    (tmp_path / ".claude-plugin" / "plugin.json").mkdir(parents=True)  # unreadable: passed over
    assert catalog.version({"version": "1"}, catalog.files(tmp_path)) == "2.0.0"
    assert catalog.version({"version": "1"}, catalog.files(tmp_path / "gone")) == "1"

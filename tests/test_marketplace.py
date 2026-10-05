from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tack import plugins
from tack.config import Paths
from tack.plugins import Wanted
from tests.helpers import link, tree, write


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "config", tmp_path / "data", tmp_path / "state")


def plugin(root: Path, name: str, files: dict[str, str] | None = None) -> Path:
    d = root / name
    for rel, text in (files or {f"skills/{name}/SKILL.md": f"The {name} skill.\n"}).items():
        write(d / rel, text)
    return d


def wanted(directory: Path, **entry: Any) -> Wanted:
    name = directory.name
    return Wanted(name, directory, {"name": name, "source": f"./plugins/{name}", **entry})


def catalog(paths: Paths) -> Any:
    return json.loads((paths.marketplace_dir / plugins.CATALOG).read_text())


def actions(update: plugins.Update) -> list[tuple[str, str | None]]:
    return [(c.action, c.plugin) for c in update.changes]


def snapshot(root: Path, *skip: Path) -> dict[str, tuple[str, int]]:
    """Every path under `root` but those under `skip`: what it is and its mtime."""
    out: dict[str, tuple[str, int]] = {}
    for p in sorted(root.rglob("*")):
        if any(p == s or s in p.parents for s in skip):
            continue
        st = p.lstat()
        kind = "link" if p.is_symlink() else "dir" if p.is_dir() else p.read_bytes().hex()
        out[str(p.relative_to(root))] = (kind, st.st_mtime_ns)
    return out


# --- updating -----------------------------------------------------------------


def test_first_update_copies_every_plugin_and_writes_the_catalog(
    tmp_path: Path, paths: Paths
) -> None:
    src = tmp_path / "src"
    bar = plugin(src, "bar")
    foo = plugin(src, "foo", {"plugin.json": '{"name": "foo"}', "hooks/run.sh": "echo\n"})
    (foo / "hooks" / "run.sh").chmod(0o755)
    foo_entry = {
        "name": "foo",
        "description": "The foo plugin",
        "source": {"source": "local", "path": "./plugins/foo"},
        "version": "1.2.0",
        "author": {"name": "Someone", "email": "someone@example.com"},
        "homepage": "https://example.com/foo",
        "category": "development",
        "headers": {"Authorization": "Bearer x"},
        "headersHelper": "./helper.sh",
        "commands": ["./commands/a.md"],
        "strict": False,
    }
    before = snapshot(tmp_path)

    up = plugins.update(paths, [Wanted("foo", foo, foo_entry), wanted(bar, description="Bar")])

    assert not up.failures
    assert actions(up) == [("copy", "bar"), ("copy", "foo"), ("write", None)]
    market = paths.marketplace_dir
    assert up.changes[0].path == market / "plugins" / "bar"
    assert up.changes[2].path == market / ".claude-plugin" / "marketplace.json"
    assert tree(market / "plugins" / "foo") == tree(foo)
    assert os.access(market / "plugins" / "foo" / "hooks" / "run.sh", os.X_OK)
    assert catalog(paths) == {
        "name": "tack",
        "owner": {"name": "tack"},
        "plugins": [
            {"name": "bar", "source": "./plugins/bar", "description": "Bar"},
            {
                "name": "foo",
                "description": "The foo plugin",
                "source": "./plugins/foo",
                "version": "1.2.0",
                "author": {"name": "Someone", "email": "someone@example.com"},
                "homepage": "https://example.com/foo",
                "category": "development",
                "commands": ["./commands/a.md"],
                "strict": False,
            },
        ],
    }
    assert list(catalog(paths)["plugins"][1]) == [
        "name", "description", "source", "version", "author", "homepage", "category",
        "commands", "strict",
    ]  # fmt: skip
    # Nothing outside tack's marketplace was written, but the data directory holding it.
    after = snapshot(tmp_path, paths.marketplace_dir)
    assert after.pop("data")[0] == "dir"
    assert after == before
    assert not [p.name for p in (market / "plugins").iterdir() if p.name.startswith(".")]


def test_second_update_changes_nothing(tmp_path: Path, paths: Paths) -> None:
    foo = plugin(tmp_path / "src", "foo")
    plugins.update(paths, [wanted(foo)])
    before = snapshot(tmp_path)
    up = plugins.update(paths, [wanted(foo)])
    assert not up.changes
    assert not up.failures
    assert snapshot(tmp_path) == before


def test_an_edited_file_brings_one_copy(tmp_path: Path, paths: Paths) -> None:
    src = tmp_path / "src"
    foo, bar = plugin(src, "foo"), plugin(src, "bar")
    plugins.update(paths, [wanted(foo), wanted(bar)])
    catalog_file = paths.marketplace_dir / plugins.CATALOG
    written = catalog_file.stat().st_mtime_ns
    write(foo / "skills" / "foo" / "SKILL.md", "Changed.\n")

    up = plugins.update(paths, [wanted(foo), wanted(bar)])

    assert actions(up) == [("copy", "foo")]
    assert (paths.marketplace_dir / "plugins/foo/skills/foo/SKILL.md").read_text() == "Changed.\n"
    assert catalog_file.stat().st_mtime_ns == written


def test_an_entry_only_change_rewrites_the_catalog(tmp_path: Path, paths: Paths) -> None:
    foo = plugin(tmp_path / "src", "foo")
    plugins.update(paths, [wanted(foo, description="old")])
    copy = paths.marketplace_dir / "plugins" / "foo"
    before = snapshot(copy)
    up = plugins.update(paths, [wanted(foo, description="new")])
    assert actions(up) == [("write", None)]
    assert catalog(paths)["plugins"][0]["description"] == "new"
    assert snapshot(copy) == before


def test_catalog_lists_only_wanted_plugins_with_a_copy(tmp_path: Path, paths: Paths) -> None:
    src = tmp_path / "src"
    foo, bar = plugin(src, "foo"), plugin(src, "bar")
    plugins.update(paths, [wanted(foo), wanted(bar)])
    up = plugins.update(paths, [wanted(foo), wanted(src / "gone")])
    assert actions(up) == [("write", None)]
    assert [p["name"] for p in catalog(paths)["plugins"]] == ["foo"]
    assert set(plugins.copies(paths)) == {"bar", "foo"}  # bar's copy stays until dropped


# --- what a copy holds ----------------------------------------------------------


def test_git_is_left_out_at_any_depth(tmp_path: Path, paths: Paths) -> None:
    foo = plugin(
        tmp_path / "src",
        "foo",
        {
            "README.md": "hi\n",
            ".git/HEAD": "ref: refs/heads/master\n",
            "vendor/lib/.git": "gitdir: ../../.git/modules/lib\n",
            "vendor/lib/x.py": "x = 1\n",
            ".github/workflows/ci.yml": "on: push\n",
            ".gitignore": "*.pyc\n",
        },
    )
    plugins.update(paths, [wanted(foo)])
    copy = paths.marketplace_dir / "plugins" / "foo"
    assert sorted(tree(copy)) == [
        ".github", ".github/workflows", ".github/workflows/ci.yml", ".gitignore", "README.md",
        "vendor", "vendor/lib", "vendor/lib/x.py",
    ]  # fmt: skip


def test_symlinks_are_copied_as_what_they_point_to(tmp_path: Path, paths: Paths) -> None:
    shared = plugin(tmp_path, "shared", {"skills/common/SKILL.md": "Common.\n", "notes.md": "N\n"})
    foo = plugin(tmp_path / "src", "foo", {"README.md": "hi\n"})
    link(foo / "skills" / "common", shared / "skills" / "common")
    link(foo / "NOTES.md", Path("..") / ".." / "shared" / "notes.md")
    link(foo / "same", Path("README.md"))

    up = plugins.update(paths, [wanted(foo)])

    assert not up.failures
    copy = paths.marketplace_dir / "plugins" / "foo"
    assert tree(copy) == {
        "NOTES.md": "N\n",
        "README.md": "hi\n",
        "same": "hi\n",
        "skills": "/",
        "skills/common": "/",
        "skills/common/SKILL.md": "Common.\n",
    }
    assert not any(p.is_symlink() for p in copy.rglob("*"))


# --- failures -------------------------------------------------------------------


def _break(kind: str, d: Path) -> None:
    if kind == "dangling":
        link(d / "skills" / "gone", d / "nowhere")
    elif kind == "loop":
        link(d / "skills" / "up", Path(".."))
    elif kind == "self-loop":
        link(d / "skills" / "me", Path("me"))
    else:
        assert kind == "missing"
        d.rename(d.with_name(d.name + "-moved"))


@pytest.mark.parametrize(
    ("kind", "words"),
    [
        ("dangling", ["skills/gone", "nowhere"]),
        ("loop", ["skills/up", "contains it"]),
        ("self-loop", ["skills/me", "loop"]),
        ("missing", ["no plugin directory", "foo"]),
    ],
)
def test_a_broken_plugin_fails_alone_and_keeps_its_copy(
    tmp_path: Path, paths: Paths, kind: str, words: list[str]
) -> None:
    src = tmp_path / "src"
    foo, bar = plugin(src, "foo"), plugin(src, "bar")
    plugins.update(paths, [wanted(foo, description="v1")])
    copy = paths.marketplace_dir / "plugins" / "foo"
    kept = tree(copy)
    write(foo / "skills" / "foo" / "SKILL.md", "Changed.\n")
    _break(kind, foo)

    up = plugins.update(paths, [wanted(foo, description="v2"), wanted(bar)])

    (failure,) = up.failures
    assert failure.plugin == "foo"
    assert failure.path == foo
    for w in words:
        assert w in failure.message, failure.message
    assert actions(up) == [("copy", "bar"), ("write", None)]
    assert tree(copy) == kept
    assert [(p["name"], p.get("description")) for p in catalog(paths)["plugins"]] == [
        ("bar", None),
        ("foo", "v2"),
    ]
    assert not [p for p in (paths.marketplace_dir / "plugins").iterdir() if p.name[0] == "."]


def test_a_broken_plugin_without_a_copy_is_left_out(tmp_path: Path, paths: Paths) -> None:
    foo = plugin(tmp_path / "src", "foo")
    _break("dangling", foo)
    up = plugins.update(paths, [wanted(foo)])
    assert [f.plugin for f in up.failures] == ["foo"]
    assert actions(up) == [("write", None)]
    assert catalog(paths)["plugins"] == []
    assert plugins.copies(paths) == {}


def test_an_unreadable_file_fails_its_plugin(tmp_path: Path, paths: Paths) -> None:
    foo = plugin(tmp_path / "src", "foo")
    secret = write(foo / "secret.txt", "s\n")
    secret.chmod(0)
    if os.access(secret, os.R_OK):
        pytest.skip("running as a user who reads everything")
    up = plugins.update(paths, [wanted(foo)])
    (failure,) = up.failures
    assert "secret.txt" in failure.message
    assert plugins.copies(paths) == {}


def test_a_copy_is_built_beside_the_old_one_and_swapped_in(
    tmp_path: Path, paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    foo = plugin(tmp_path / "src", "foo", {"a.md": "a\n", "b.md": "b\n"})
    plugins.update(paths, [wanted(foo)])
    copy = paths.marketplace_dir / "plugins" / "foo"
    old_inode = copy.stat().st_ino
    write(foo / "a.md", "A\n")
    write(foo / "b.md", "B\n")

    real = plugins.shutil.copy2

    def failing(src: Path, dst: Path) -> object:
        if Path(src).name == "b.md":
            raise OSError(5, "Input/output error", str(src))
        return real(src, dst)

    monkeypatch.setattr(plugins.shutil, "copy2", failing)
    up = plugins.update(paths, [wanted(foo)])
    (failure,) = up.failures
    assert "b.md" in failure.message
    assert "Input/output error" in failure.message
    assert tree(copy) == {"a.md": "a\n", "b.md": "b\n"}  # untouched, not half-updated
    assert sorted(p.name for p in copy.parent.iterdir()) == ["foo"]

    monkeypatch.setattr(plugins.shutil, "copy2", real)
    assert actions(plugins.update(paths, [wanted(foo)])) == [("copy", "foo")]
    assert tree(copy) == {"a.md": "A\n", "b.md": "B\n"}
    assert copy.stat().st_ino != old_inode
    assert sorted(p.name for p in copy.parent.iterdir()) == ["foo"]


def test_a_copy_left_half_built_is_cleared(tmp_path: Path, paths: Paths) -> None:
    foo = plugin(tmp_path / "src", "foo")
    write(paths.marketplace_dir / "plugins" / ".foo.abc123" / "half", "x")
    plugins.update(paths, [wanted(foo)])
    assert sorted(p.name for p in (paths.marketplace_dir / "plugins").iterdir()) == ["foo"]


# --- dropping, removing, dry runs -------------------------------------------------


def test_drop_and_remove(tmp_path: Path, paths: Paths) -> None:
    src = tmp_path / "src"
    foo, bar = plugin(src, "foo"), plugin(src, "bar")
    plugins.update(paths, [wanted(foo), wanted(bar)])
    assert set(plugins.copies(paths)) == {"bar", "foo"}

    assert plugins.drop(paths, "foo")
    assert not plugins.drop(paths, "foo")
    assert set(plugins.copies(paths)) == {"bar"}
    assert foo.is_dir()

    assert plugins.remove(paths)
    assert not paths.marketplace_dir.exists()
    assert not plugins.remove(paths)
    assert plugins.copies(paths) == {}
    assert tree(src)  # the plugins themselves are untouched


def test_dry_run_reports_the_same_and_writes_nothing(tmp_path: Path, paths: Paths) -> None:
    src = tmp_path / "src"
    foo, bar = plugin(src, "foo"), plugin(src, "bar")
    write(paths.marketplace_dir / "plugins" / ".foo.leftover" / "x", "x")
    before = snapshot(tmp_path)

    dry = plugins.update(paths, [wanted(foo), wanted(bar)], dry_run=True)

    assert actions(dry) == [("copy", "bar"), ("copy", "foo"), ("write", None)]
    assert snapshot(tmp_path) == before

    plugins.update(paths, [wanted(foo), wanted(bar)])
    write(foo / "skills" / "foo" / "SKILL.md", "Changed.\n")
    before = snapshot(tmp_path)
    dry = plugins.update(paths, [wanted(foo, description="new"), wanted(bar)], dry_run=True)
    assert actions(dry) == [("copy", "foo"), ("write", None)]
    assert snapshot(tmp_path) == before
    _break("dangling", bar)
    before = snapshot(tmp_path)
    dry = plugins.update(paths, [wanted(foo), wanted(bar)], dry_run=True)
    assert [f.plugin for f in dry.failures] == ["bar"]
    assert actions(dry) == [("copy", "foo")]
    assert snapshot(tmp_path) == before


# --- the hash ---------------------------------------------------------------------


def test_a_plugin_and_its_copy_hash_the_same(tmp_path: Path, paths: Paths) -> None:
    shared = plugin(tmp_path, "shared", {"x.md": "x\n"})
    foo = plugin(tmp_path / "src", "foo", {"README.md": "hi\n", ".git/HEAD": "ref\n"})
    link(foo / "linked", shared)
    link(foo / "linked.md", shared / "x.md")
    plugins.update(paths, [wanted(foo)])
    copy = paths.marketplace_dir / "plugins" / "foo"
    assert plugins.tree_hash(foo) == plugins.tree_hash(copy)


def test_the_hash_follows_contents_mode_and_names(tmp_path: Path) -> None:
    foo = plugin(tmp_path, "foo", {"a/run.sh": "echo\n", "b.md": "b\n"})
    start = plugins.tree_hash(foo)
    assert plugins.tree_hash(foo) == start

    (foo / "empty" / "deeper").mkdir(parents=True)
    assert plugins.tree_hash(foo) == start  # directories count only through their files

    (foo / "a" / "run.sh").chmod(0o755)
    executable = plugins.tree_hash(foo)
    assert executable != start
    (foo / "a" / "run.sh").chmod(0o644)
    assert plugins.tree_hash(foo) == start

    write(foo / "b.md", "B\n")
    assert plugins.tree_hash(foo) not in (start, executable)
    write(foo / "b.md", "b\n")
    assert plugins.tree_hash(foo) == start

    (foo / "b.md").rename(foo / "c.md")
    assert plugins.tree_hash(foo) != start


def test_the_hash_tells_where_a_file_ends(tmp_path: Path) -> None:
    one = plugin(tmp_path, "one", {"a": "b\0c"})
    two = plugin(tmp_path, "two", {"a": "b", "c": ""})
    assert plugins.tree_hash(one) != plugins.tree_hash(two)


@pytest.mark.parametrize("kind", ["dangling", "loop", "self-loop", "missing"])
def test_the_hash_of_a_broken_plugin_is_an_error(tmp_path: Path, kind: str) -> None:
    foo = plugin(tmp_path, "foo")
    _break(kind, foo)
    with pytest.raises(plugins.PluginError):
        plugins.tree_hash(foo)

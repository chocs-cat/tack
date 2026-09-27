from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tack import config, deploy, edit, sync
from tack.config import Config, ConfigError, UsageError
from tack.sync import Result
from tests.helpers import git, load, skill, tree, upstream, write

WHEN = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)

MANIFEST = """\
# Run after tack changes this file.
after_save = "true"

[projects]
roots = ["~/Code"]

[[source]]
name = "mine"
path = "~/mine"   # my own
autocommit = true

# Cloudflare's, pinned.
[[source]]
name = "cloudflare"
git = "https://github.com/cloudflare/skills.git"
skills = [
  "a", "b",
]
# A note inside the table.

# ---- vendors ----

# Vercel's.
[[source]]
name = "vercel"
git = "https://github.com/vercel-labs/skills.git"

[harness.codex]
ignore = ["x"]
"""

NEW = '[[source]]\nname = "new"\ngit = "u"\n'


def lines_of(text: str) -> list[str]:
    return text.splitlines()


# --- the text edits ------------------------------------------------------------------


def test_cut_keeps_every_other_line_and_comment() -> None:
    cut = edit.cut_source(MANIFEST, 1)
    assert cut is not None
    assert "cloudflare" not in cut
    assert "# Cloudflare's" not in cut
    assert "A note inside" not in cut
    assert lines_of(cut)[6:] == [
        "[[source]]",
        'name = "mine"',
        'path = "~/mine"   # my own',
        "autocommit = true",
        "",
        "# ---- vendors ----",
        "",
        "# Vercel's.",
        "[[source]]",
        'name = "vercel"',
        'git = "https://github.com/vercel-labs/skills.git"',
        "",
        "[harness.codex]",
        'ignore = ["x"]',
    ]


def test_cut_the_last_source_before_another_table() -> None:
    cut = edit.cut_source(MANIFEST, 2)
    assert cut is not None
    assert lines_of(cut)[-8:] == [
        '  "a", "b",',
        "]",
        "# A note inside the table.",
        "",
        "# ---- vendors ----",
        "",
        "[harness.codex]",
        'ignore = ["x"]',
    ]


def test_cut_the_first_and_only_sources() -> None:
    text = '[[source]]\nname = "a"\npath = "x"\n\n# b\n[[source]]\nname = "b"\npath = "y"\n'
    assert edit.cut_source(text, 0) == '# b\n[[source]]\nname = "b"\npath = "y"\n'
    assert edit.cut_source(text, 1) == '[[source]]\nname = "a"\npath = "x"\n'
    assert edit.cut_source('x = 1\n[[source]]\nname = "a"\n\n[t]\n', 0) == "x = 1\n\n[t]\n"
    assert edit.cut_source(text, 2) is None


def test_append_after_the_last_source() -> None:
    added = edit.append_source(MANIFEST, NEW)
    assert lines_of(added)[-10:] == [
        "[[source]]",
        'name = "vercel"',
        'git = "https://github.com/vercel-labs/skills.git"',
        "",
        "[[source]]",
        'name = "new"',
        'git = "u"',
        "",
        "[harness.codex]",
        'ignore = ["x"]',
    ]
    assert added.replace(NEW + "\n", "", 1) == MANIFEST


def test_append_elsewhere() -> None:
    assert edit.append_source("", NEW) == NEW
    assert edit.append_source('after_save = "x"', NEW) == 'after_save = "x"\n\n' + NEW
    # The comment directly below the last source's keys stays with it.
    text = '[[source]]\nname = "a"\n# about a\n# [t]\n'
    assert edit.append_source(text, NEW) == text + "\n" + NEW


def test_table_rendering() -> None:
    short = edit._table({"name": "x", "git": 'a"b', "skills": ["one", "two"]})
    assert short == '[[source]]\nname = "x"\ngit = "a\\"b"\nskills = ["one", "two"]\n'
    long = edit._table({"name": "x", "skills": [f"skill-number-{i}" for i in range(8)]})
    assert long.splitlines()[2:5] == ["skills = [", '  "skill-number-0",', '  "skill-number-1",']
    assert tomllib.loads(long)["source"][0]["skills"][7] == "skill-number-7"


def test_urls_and_names() -> None:
    for url in ("https://github.com/o/r.git", "file:///x/r", "git@github.com:o/r.git", "h:r"):
        assert edit.is_url(url), url
    for path in ("~/Code/skills", "./a:b", "/abs/path", "rel"):
        assert not edit.is_url(path), path
    assert edit.default_name("https://github.com/cloudflare/skills.git") == "cloudflare"
    assert edit.default_name("git@github.com:vercel-labs/skills") == "vercel-labs"
    assert edit.default_name("https://github.com/johnfoland/corral.git/") == "corral"


# --- add ------------------------------------------------------------------------------


def run_add(cfg: Config, spec: str | Path, **kw) -> Result:
    return edit.add(cfg, str(spec), now=WHEN, **kw)


def url(repo: Path) -> str:
    return f"file://{repo}"


def manifest_text(home: Path) -> str:
    return (home / ".config" / "tack" / "tack.toml").read_text()


def test_add_a_path_source(home: Path) -> None:
    for name in ("a", "b"):
        skill(home / "mine" / "skills", name)
    cfg = load(home, "# my manifest\n")
    result = run_add(cfg, home / "mine" / ".." / "mine", skills=["a", "a"])
    assert result.problems == []
    assert [(c.action, c.harness or c.source) for c in result.changes] == [
        ("write", None),
        ("link", "claude-code"),
        ("link", "codex"),
    ]
    assert manifest_text(home) == (
        '# my manifest\n\n[[source]]\nname = "mine"\npath = "~/mine"\nskills = ["a"]\n'
    )
    assert (home / ".claude" / "skills" / "a").readlink() == home / "mine" / "skills" / "a"
    assert not (home / ".claude" / "skills" / "b").exists()


def test_add_without_a_manifest_creates_one(home: Path, tmp_path: Path) -> None:
    skill(tmp_path / "elsewhere" / "skills", "a")
    run_add(load(home), tmp_path / "elsewhere", name="other")
    assert manifest_text(home) == f'[[source]]\nname = "other"\npath = "{tmp_path}/elsewhere"\n'


def test_add_a_git_source(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "o" / "skills", "x", "y")
    tip = git(up, "rev-parse", "HEAD").strip()
    log = home / "saved.log"
    cfg = load(home, f'after_save = "echo {{path}} >> {log}"\n')
    # A stale lock entry under the same name is replaced by a fresh pin.
    stale = config.LockEntry("https://elsewhere", None, "0" * 40, WHEN)
    config.save_lock(cfg.paths, {"o": stale})

    result = run_add(cfg, url(up), ref="master", skills=["x"])
    assert result.problems == []
    assert [c.action for c in result.changes] == [
        "pin", "clone", "checkout", "write", "write", "link", "link",
    ]  # fmt: skip
    assert tomllib.loads(manifest_text(home))["source"] == [
        {"name": "o", "git": url(up), "ref": "master", "skills": ["x"]}
    ]
    assert config.load_lock(cfg.paths)["o"] == config.LockEntry(url(up), "master", tip, WHEN)
    checkout = cfg.paths.sources_dir / "o"
    assert (home / ".agents" / "skills" / "x").readlink() == checkout / "skills" / "x"
    assert log.read_text().splitlines() == [str(cfg.paths.manifest), str(cfg.paths.lockfile)]


def test_add_refusals_write_nothing(home: Path, tmp_path: Path) -> None:
    skill(home / "mine" / "skills", "a")
    skill(home / "two" / "skills", "a")
    (home / "empty" / "skills").mkdir(parents=True)
    (home / "bare").mkdir()
    up = upstream(tmp_path / "up", "x")
    cfg = load(home, '[[source]]\nname = "mine"\npath = "~/mine"\n')
    cfg.paths.sources_dir.mkdir(parents=True)
    before = tree(home)

    cases = [
        (home / "nowhere", {}, "there is no directory at"),
        (home / "two", {"ref": "main"}, "--ref applies to git sources"),
        (home / "two", {"name": "mine"}, "already a source named 'mine'; pass --name"),
        (home / "mine" / "skills" / "..", {"name": "again"}, "is already source 'mine'"),
        (home / "two", {"name": "bad name"}, "'bad name' can't name a source"),
        (home / "bare", {}, "no skills directory at ~/bare/skills; --subdir"),
        (home / "empty", {}, "there are no skills in ~/empty/skills"),
        (home / "two", {"skills": ["a", "b", "c"]}, "has no skills 'b', 'c'"),
        (home / "two", {}, "skill 'a' already deployed by mine; --skill takes only"),
        (url(up), {"skills": ["nope"]}, "has no skill 'nope'"),
    ]
    for spec, kw, message in cases:
        with pytest.raises(UsageError, match=message):
            run_add(cfg, spec, **kw)
        assert tree(home) == before, spec  # a fresh clone is removed again

    with pytest.raises(ConfigError, match="subdir must be inside the source"):
        run_add(cfg, home / "two", subdir="../mine/skills")
    result = run_add(cfg, url(tmp_path / "missing.git"))
    assert [(p.kind, p.source) for p in result.problems] == [("source", "missing")]
    assert tree(home) == before


def test_add_to_a_manifest_it_cant_edit_cleanly(home: Path) -> None:
    skill(home / "two" / "skills", "b")
    cfg = load(home, 'source = [{ name = "mine", path = "~/mine" }]\n')
    with pytest.raises(UsageError, match="without disturbing the rest of it; edit it by hand"):
        run_add(cfg, home / "two")


def test_add_dry_run(home: Path, tmp_path: Path) -> None:
    skill(home / "mine" / "skills", "a")
    up = upstream(tmp_path / "up", "x")
    cfg = load(home, "")
    before = tree(home)
    result = run_add(cfg, home / "mine", dry_run=True)
    assert [c.action for c in result.changes] == ["write", "link", "link"]
    result = run_add(cfg, url(up), skills=["nope"], dry_run=True)  # unchecked: not cloned
    assert [c.action for c in result.changes][:5] == ["pin", "write", "clone", "checkout", "write"]
    assert tree(home) == before


# --- remove ---------------------------------------------------------------------------


def test_remove_a_path_source(home: Path) -> None:
    skill(home / "mine" / "skills", "a")
    skill(home / "two" / "skills", "b")
    cfg = load(home, "")
    run_add(cfg, home / "mine")
    cfg = load(home)
    run_add(cfg, home / "two")
    result = edit.remove(load(home), "mine", now=WHEN)
    assert result.problems == []
    assert [c.action for c in result.changes] == ["write", "unlink", "unlink"]
    assert manifest_text(home) == '[[source]]\nname = "two"\npath = "~/two"\n'
    assert not (home / ".claude" / "skills" / "a").is_symlink()
    assert (home / "mine" / "skills" / "a" / "SKILL.md").is_file()  # never touched


def test_remove_from_a_commented_manifest(home: Path, tmp_path: Path) -> None:
    cloudflare = upstream(tmp_path / "cf", "a", "b")
    vercel = upstream(tmp_path / "vc", "v")
    skill(home / "mine" / "skills", "m")
    text = MANIFEST.replace("https://github.com/cloudflare/skills.git", url(cloudflare))
    text = text.replace("https://github.com/vercel-labs/skills.git", url(vercel))
    sync.sync(load(home, text), now=WHEN)
    before = tree(home)

    result = edit.remove(load(home), "cloudflare", dry_run=True)
    assert tree(home) == before
    assert [c.action for c in result.changes] == ["write", "write", *["unlink"] * 4, "delete"]

    edit.remove(load(home), "cloudflare")
    assert manifest_text(home) == edit.cut_source(text, 1)


def test_remove_a_git_source(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    other = upstream(tmp_path / "other", "y")
    run_add(load(home, ""), url(up))
    run_add(load(home), url(other))
    cfg = load(home)
    checkout = cfg.paths.sources_dir / "up"
    assert checkout.is_dir()

    result = edit.remove(cfg, "up", now=WHEN)
    assert result.problems == []
    assert [c.action for c in result.changes] == ["write", "write", "unlink", "unlink", "delete"]
    assert [s["name"] for s in tomllib.loads(manifest_text(home))["source"]] == ["other"]
    assert list(config.load_lock(cfg.paths)) == ["other"]
    assert not checkout.exists()
    assert not (home / ".claude" / "skills" / "x").is_symlink()
    assert (home / ".claude" / "skills" / "y").is_symlink()
    assert deploy.load_record(cfg.paths).links.keys() == {
        str(home / ".claude" / "skills" / "y"),
        str(home / ".agents" / "skills" / "y"),
    }


def test_remove_keeps_a_checkout_with_local_changes(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    run_add(load(home, ""), url(up))
    cfg = load(home)
    checkout = cfg.paths.sources_dir / "up"
    write(checkout / "skills" / "x" / "SKILL.md", "edited")
    result = edit.remove(cfg, "up", now=WHEN)
    assert [(p.kind, p.source) for p in result.problems] == [("source", "up")]
    assert "has local changes, so it is left where it is" in result.problems[0].message
    assert checkout.is_dir()
    assert "source" not in tomllib.loads(manifest_text(home))


def test_remove_a_name_only_the_lockfile_has(home: Path, tmp_path: Path) -> None:
    up = upstream(tmp_path / "up", "x")
    run_add(load(home, ""), url(up))
    cfg = load(home, "# commented out:\n# [[source]]\n")
    result = edit.remove(cfg, "up", now=WHEN)
    assert [c.action for c in result.changes] == ["write", "unlink", "unlink", "delete"]
    assert manifest_text(home) == "# commented out:\n# [[source]]\n"
    assert config.load_lock(cfg.paths) == {}
    assert not (cfg.paths.sources_dir / "up").exists()

    with pytest.raises(UsageError, match=r"no source named 'up' in ~/\.config/tack/tack\.toml"):
        edit.remove(cfg, "up")

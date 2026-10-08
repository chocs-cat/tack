from __future__ import annotations

import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tack import config, deploy, edit, sync
from tack.config import Config, ConfigError, SkillSpec, Source, UsageError
from tack.sync import Result
from tests.helpers import git, load, market, repo, skill, tree, upstream, write
from tests.standin import Standins

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


# --- add --plugin (design.md *Adding and removing sources*) --------------------------

NPM = {"name": "u", "source": {"source": "npm", "package": "@acme/u"}}
ELSEWHERE = {"name": "r", "source": {"source": "github", "repo": "acme/r", "sha": "0" * 40}}


def offering(root: Path, *skills: str) -> Path:
    """A source at `root` whose catalog offers plugins `a` and `good`, with
    their files; `u`, from npm, which tack can't deploy; `r`, from another
    repository; and `gone`, whose directory isn't there. Its `skills` are in
    `skills/`, which isn't there without them."""
    for p in ("a", "good"):
        write(root / "plugins" / p / ".claude-plugin" / "plugin.json", json.dumps({"name": p}))
    for s in skills:
        skill(root / "skills", s)
    return market(root, "a", "good", NPM, ELSEWHERE, "gone")


def plugins_of(home: Path) -> Source:
    (src,) = load(home).sources
    return src


@pytest.mark.parametrize(("kw", "table", "selected"), [
    ({}, 'skills = []\nplugins = ["a", "good"]\n', ()),
    ({"skills": ["s"]}, 'skills = ["s"]\nplugins = ["a", "good"]\n', (SkillSpec("s"),)),
    ({"subdir": "lib"}, 'subdir = "lib"\nskills = []\nplugins = ["a", "good"]\n', ()),
])  # fmt: skip
def test_add_plugins_writes_them_after_the_skills(
    home: Path, kw: dict[str, object], table: str, selected: tuple[SkillSpec, ...]
) -> None:
    """`--plugin a --plugin a good`: each name once, in the order given; with
    no `--skill`, `skills = []`."""
    offering(home / "full", "s")
    (home / "full" / "lib").mkdir()
    cfg = load(home, "")
    result = run_add(cfg, home / "full", plugins=["a", "a", "good"], **kw)
    assert result.problems == []
    assert manifest_text(home) == '[[source]]\nname = "full"\npath = "~/full"\n' + table
    assert plugins_of(home) == Source(
        "full",
        path=home / "full",
        subdir=str(kw.get("subdir", "skills")),
        skills=selected,
        plugins=(SkillSpec("a"), SkillSpec("good")),
    )


def test_add_without_plugins_writes_the_table_as_before(home: Path) -> None:
    offering(home / "full", "s")
    run_add(load(home, ""), home / "full")
    assert manifest_text(home) == '[[source]]\nname = "full"\npath = "~/full"\n'


def test_add_plugins_installs_them(home: Path, tmp_path: Path, standins: Standins) -> None:
    """A source with no skills directory, path or git, is accepted with
    `--plugin`: its skills aren't checked. The plugin goes to both agents."""
    offering(home / "full")
    up = repo(offering(tmp_path / "git" / "up"))
    cfg = load(home, "")
    assert run_add(cfg, home / "full", plugins=["good"]).problems == []
    cfg = load(home)
    assert run_add(cfg, url(up), plugins=["a"]).problems == []
    assert [(s.name, s.skills, s.plugins) for s in load(home).sources] == [
        ("full", (), (SkillSpec("good"),)),
        ("up", (), (SkillSpec("a"),)),
    ]
    for cli_name in ("claude", "codex"):
        assert set(standins.state()[cli_name]["plugins"]) == {"good@tack", "a@tack"}
    calls = [" ".join(c.args[:3]) for c in standins.calls() if c.args[1] in ("install", "add")]
    assert calls == [
        "plugin install good@tack",
        "plugin add good@tack",
        "plugin install a@tack",
        "plugin add a@tack",
    ]


def plugin_refusal_cases(home: Path, tmp_path: Path) -> list[tuple[str, list[str], str]]:
    """Each refusal for a path source and for a fresh git clone: the source,
    `--plugin`, and the refusal."""
    out: list[tuple[str, list[str], str]] = []
    for kind in ("path", "git"):
        base = home if kind == "path" else tmp_path / "git"
        full, bare, broken = offering(base / "full"), base / "bare", base / "broken"
        write(bare / "README.md", "no catalog\n")
        write(broken / ".claude-plugin" / "marketplace.json", "{}")
        if kind == "git":
            full, bare, broken = (url(repo(r)) for r in (full, bare, broken))
        root = "~/" if kind == "path" else "~/.local/share/tack/sources/"
        catalog = f"{root}full/.claude-plugin/marketplace.json"
        out += [
            (str(bare), ["x"], f"there is no plugin catalog in {root}bare "
                "(.claude-plugin/marketplace.json or .agents/plugins/marketplace.json)"),
            (str(full), ["good", "nope", "nah"], f"{catalog} has no plugins 'nope', 'nah'"),
            (str(broken), ["x"], "marketplace.json: not a catalog: it needs a `plugins` list"),
            (str(full), ["u"], "plugin 'u' can't be deployed: "),
            (str(full), ["r"], "plugin 'r' is in another repository (https://github.com/acme/r.git)"),
            (str(full), ["gone"], f"plugin 'gone': no plugin directory at {root}full/plugins/gone"),
            (str(full), ["a"], "plugin 'a' already selected by taken"),
        ]  # fmt: skip
    return out


def test_add_plugin_refusals_write_nothing(home: Path, tmp_path: Path) -> None:
    offering(home / "taken")
    cfg = load(home, '[[source]]\nname = "taken"\npath = "~/taken"\nskills = []\nplugins = ["a"]\n')
    cases = plugin_refusal_cases(home, tmp_path)
    cfg.paths.sources_dir.mkdir(parents=True)
    before = tree(home)
    for spec, names, message in cases:
        with pytest.raises(UsageError, match=re.escape(message)):
            run_add(cfg, spec, plugins=names)
        assert tree(home) == before, (spec, names)  # a fresh clone is removed again


def test_add_plugin_refusals_come_in_order(home: Path) -> None:
    """The skills', then a broken catalog or the names it lacks, then each
    plugin `sync` couldn't deploy, then each another source selects."""
    offering(home / "taken")
    cfg = load(home, '[[source]]\nname = "taken"\npath = "~/taken"\nskills = []\nplugins = ["a"]\n')
    offering(home / "full")
    with pytest.raises(UsageError) as refused:
        run_add(cfg, home / "full", skills=["s"], plugins=["a", "nope", "gone", "r", "u"])
    assert str(refused.value).removeprefix("can't add full: ").split("; ") == [
        "there is no skills directory at ~/full/skills",
        "--subdir says where they are",  # the skills refusal's own "; "
        "~/full/.claude-plugin/marketplace.json has no plugin 'nope'",
        "plugin 'gone': no plugin directory at ~/full/plugins/gone",
        "plugin 'r' is in another repository (https://github.com/acme/r.git), "
        "and tack doesn't deploy those yet",
        "plugin 'u' can't be deployed: `npm` sources can't be pinned",
        "plugin 'a' already selected by taken",
    ]


def test_a_source_with_no_skills_lists_its_plugins(home: Path) -> None:
    """Without `--plugin`, the refusal of a source with no skills lists the
    plugins `--plugin` would accept: sorted, deployable, and selected by no
    other source. Each of them is then accepted."""
    offering(home / "full")
    write(home / "full" / "plugins" / "b" / "README.md", "b\n")
    market(home / "full", "good", "a", NPM, ELSEWHERE, "gone", "b")
    (home / "empty" / "skills").mkdir(parents=True)
    write(home / "empty" / "plugins" / "e" / "README.md", "e\n")
    market(home / "empty", "e")
    cfg = load(home, '[[source]]\nname = "taken"\npath = "~/taken"\nskills = []\nplugins = ["a"]\n')
    offering(home / "taken")

    with pytest.raises(UsageError) as refused:
        run_add(cfg, home / "full")
    assert str(refused.value) == (
        "can't add full: there is no skills directory at ~/full/skills; --subdir says where "
        "they are; --plugin selects its plugins 'b', 'good'"
    )
    with pytest.raises(UsageError) as refused:
        run_add(cfg, home / "empty")
    assert str(refused.value) == (
        "can't add empty: there are no skills in ~/empty/skills; --plugin selects its plugin 'e'"
    )
    # With --plugin, the refusal is as before.
    with pytest.raises(UsageError, match=r"--subdir says where they are; plugin 'u' can't"):
        run_add(cfg, home / "full", skills=["s"], plugins=["u"])

    assert run_add(cfg, home / "full", plugins=["b", "good"]).problems == []
    assert [(s.name, s.plugins) for s in load(home).sources][-1] == (
        "full",
        (SkillSpec("b"), SkillSpec("good")),
    )


def test_a_source_with_no_skills_and_no_plugins_to_offer(home: Path) -> None:
    """No catalog, a broken one, or none `--plugin` would accept: the refusal
    is as before."""
    (home / "bare").mkdir()
    write(home / "broken" / ".claude-plugin" / "marketplace.json", "{")
    market(home / "only-npm", NPM)
    cfg = load(home, "")
    for name in ("bare", "broken", "only-npm"):
        with pytest.raises(UsageError) as refused:
            run_add(cfg, home / name)
        assert str(refused.value) == (
            f"can't add {name}: there is no skills directory at ~/{name}/skills; "
            "--subdir says where they are"
        )


@pytest.mark.parametrize("plugin", ["u", "r", "gone"])
def test_a_plugin_refusal_gives_the_reason_sync_gives(home: Path, plugin: str) -> None:
    """The same words as the `source` problem a `sync` dry run reports for
    the source already in the manifest selecting the plugin."""
    offering(home / "full")
    with pytest.raises(UsageError) as refused:
        run_add(load(home, ""), home / "full", plugins=[plugin])
    selecting = load(
        home, f'[[source]]\nname = "full"\npath = "~/full"\nskills = []\nplugins = ["{plugin}"]\n'
    )
    result = sync.sync(selecting, dry_run=True, now=WHEN)
    (problem,) = result.problems
    assert (problem.kind, problem.source) == ("source", "full")
    assert str(refused.value) == f"can't add full: {problem.message}"


def test_add_plugins_dry_run(home: Path, tmp_path: Path) -> None:
    """A git source's dry run can't check its plugins, not having cloned it;
    a path source's checks them."""
    offering(home / "full")
    up = repo(offering(tmp_path / "up"))
    cfg = load(home, "")
    before = tree(home)
    result = run_add(cfg, url(up), plugins=["nope"], dry_run=True)
    assert [c.action for c in result.changes][:2] == ["pin", "write"]
    with pytest.raises(UsageError, match="has no plugin 'nope'"):
        run_add(cfg, home / "full", plugins=["nope"], dry_run=True)
    assert tree(home) == before


@pytest.mark.parametrize("kw", [{"skills": ["nope"]}, {"plugins": ["nope"]}])
@pytest.mark.parametrize("skills", [(), ("x",)])
def test_a_git_dry_run_ignores_a_leftover_checkout(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kw: dict[str, list[str]],
    skills: tuple[str, ...],
) -> None:
    """A dry run doesn't clone, so it checks neither a git source's skills
    nor its plugins, even with tack's checkout of an earlier source by that
    name still there (#49): here one with no catalog, and no skills
    directory or one without `nope`."""
    # The leftover's commit would start git's auto-maintenance in the
    # background, whose lock in its .git can come and go mid-test.
    for var, value in (("COUNT", "1"), ("KEY_0", "maintenance.auto"), ("VALUE_0", "false")):
        monkeypatch.setenv(f"GIT_CONFIG_{var}", value)
    up = repo(offering(tmp_path / "up"))
    cfg = load(home, "")
    upstream(cfg.paths.sources_dir / "up", *skills)
    before = tree(home)
    run_add(cfg, url(up), dry_run=True, **kw)
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


# --- settings ---------------------------------------------------------------------

SETTINGS = """\
# My skills.
after_save = "chezmoi re-add {path}"

[projects]
roots = ["~/Code"]
owners = [
  "me",
  "you",
]

# Built-in harnesses need no table.
[harness.claude-code]
ignore = ["codebase-memory"]   # owned by its installer

# Mine.
[[source]]
name = "mine"
path = "~/mine"

[[source]]
name = "up"
git = "https://example.com/up.git"
"""


def _set(changes: dict[edit.Key, object], text: str = SETTINGS) -> str:
    new = edit.set_values(text, changes)
    assert new is not None
    expected = tomllib.loads(text)
    for key, value in changes.items():
        edit._put(expected, key, value)
    assert tomllib.loads(new) == expected
    return new


def test_set_replaces_a_value_in_place() -> None:
    new = _set({("projects", "owners"): ["me"], ("after_save",): "true"})
    assert new == SETTINGS.replace('"chezmoi re-add {path}"', '"true"').replace(
        'owners = [\n  "me",\n  "you",\n]', 'owners = ["me"]'
    )


def test_set_keeps_a_comment_on_the_same_line() -> None:
    new = _set({("harness", "claude-code", "ignore"): ["a", "b"]})
    assert 'ignore = ["a", "b"]   # owned by its installer\n' in new


def test_set_adds_a_key_after_the_last_in_its_table() -> None:
    new = _set({("projects", "exclude"): ["~/Code/old"], ("source", 1, "ref"): "main"})
    assert 'owners = [\n  "me",\n  "you",\n]\nexclude = ["~/Code/old"]\n\n# Built-in' in new
    assert new.endswith('git = "https://example.com/up.git"\nref = "main"\n')


def test_set_removes_a_key() -> None:
    new = _set({("after_save",): None, ("projects", "owners"): None})
    assert new == SETTINGS.replace('after_save = "chezmoi re-add {path}"\n', "").replace(
        'owners = [\n  "me",\n  "you",\n]\n', ""
    )


def test_set_adds_a_table_before_the_sources() -> None:
    new = _set({("tui", "group_by_source"): False, ("harness", "codex", "ignore"): ["x"]})
    tables = '\n[tui]\ngroup_by_source = false\n\n[harness.codex]\nignore = ["x"]\n\n# Mine.\n'
    assert tables in new


def test_set_top_level_keys_go_above_the_first_table() -> None:
    text = "# Header.\n\n# Projects.\n[projects]\nroots = []\n"
    assert _set({("after_save",): "x"}, text) == (
        '# Header.\n\nafter_save = "x"\n\n# Projects.\n[projects]\nroots = []\n'
    )
    assert _set({("after_save",): "x"}, "") == 'after_save = "x"\n'
    assert _set({("tui", "group_by_source"): False}, "") == "[tui]\ngroup_by_source = false\n"


def test_set_refuses_what_it_cant_edit_as_text(home: Path) -> None:
    assert edit.set_values("", {("source", 0, "ref"): "main"}) is None
    cfg = load(home, "projects.roots = ['~/a']\n")  # a dotted key, not a [projects] table
    with pytest.raises(UsageError, match="edit it by hand"):
        edit.settings(cfg, {("projects", "roots"): ["~/b"]})


def test_settings_writes_with_a_diff_and_runs_after_save(home: Path) -> None:
    cfg = load(home, SETTINGS.replace("chezmoi re-add {path}", "touch {path}.saved"))
    file = home / ".config" / "tack" / "tack.toml"
    before = file.read_text()
    dry = edit.settings(cfg, {("tui", "group_by_source"): False}, dry_run=True)
    assert file.read_text() == before
    (change,) = dry.changes
    assert change.diff is not None
    assert "+[tui]\n+group_by_source = false\n" in change.diff
    result = edit.settings(cfg, {("tui", "group_by_source"): False})
    assert not result.problems
    assert not config.load().tui.group_by_source
    assert (file.parent / "tack.toml.saved").exists()
    assert edit.settings(config.load(), {("tui", "group_by_source"): False}).changes == []


def test_settings_refuses_an_invalid_manifest(home: Path) -> None:
    cfg = load(home, SETTINGS)
    with pytest.raises(ConfigError, match="autopush"):
        edit.settings(cfg, {("source", 0, "autopush"): True})

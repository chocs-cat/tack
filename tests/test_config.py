from __future__ import annotations

import re
from pathlib import Path

import pytest

from tack import config
from tack.config import ConfigError, Paths, SkillSpec
from tests.helpers import load, write

DESIGN = Path(__file__).parent.parent / "docs" / "design.md"


def test_no_manifest_means_builtin_harnesses_and_nothing_else(home: Path) -> None:
    cfg = load(home)
    assert cfg.manifest is None
    assert cfg.sources == ()
    assert cfg.roots == ()
    assert list(cfg.harnesses) == ["claude-code", "codex"]
    claude, codex = cfg.harnesses["claude-code"], cfg.harnesses["codex"]
    assert claude.skills_dir == home / ".claude" / "skills"
    assert claude.hooks == (home / ".claude" / "settings.json",)
    assert claude.imports
    assert claude.ignores("synced")
    assert claude.ignores(".DS_Store")
    assert not claude.ignores("interview")
    assert codex.skills_dir == home / ".agents" / "skills"
    assert codex.instructions == home / ".codex" / "AGENTS.md"
    assert codex.hooks == (home / ".codex" / "hooks.json", home / ".codex" / "config.toml")
    assert codex.project_hooks == (".codex/hooks.json", ".codex/config.toml")
    assert not codex.imports
    assert not codex.ignores("synced")


def test_locations_follow_xdg_then_tack_overrides(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = Paths.from_env()
    assert p.config_dir == home / ".config" / "tack"
    assert p.data_dir == home / ".local" / "share" / "tack"
    assert p.state_dir == home / ".local" / "state" / "tack"
    assert p.sources_dir == p.data_dir / "sources"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xc"))
    monkeypatch.setenv("XDG_DATA_HOME", "relative/is/ignored")
    p = Paths.from_env()
    assert p.config_dir == tmp_path / "xc" / "tack"
    assert p.data_dir == home / ".local" / "share" / "tack"

    monkeypatch.setenv("TACK_CONFIG", str(tmp_path / "tc"))
    monkeypatch.setenv("TACK_DATA", "~/data")
    monkeypatch.setenv("TACK_STATE", str(tmp_path / "ts"))
    p = Paths.from_env()
    assert p.config_dir == tmp_path / "tc"
    assert p.data_dir == home / "data"
    assert p.state_dir == tmp_path / "ts"
    assert Paths.from_env(tmp_path / "flag").config_dir == tmp_path / "flag"


def test_design_example_manifest_parses(home: Path) -> None:
    example = re.search(
        r"## The manifest: `tack.toml`\n\n```toml\n(.*?)```", DESIGN.read_text(), re.S
    )
    assert example
    cfg = load(home, example.group(1))
    assert cfg.after_save == "chezmoi re-add {path}"
    assert cfg.roots == (home / "Code",)
    assert cfg.exclude == (home / "Code" / "Archive", home / "Code" / "cruzainet")
    assert cfg.owners == ("johnfoland", "cruzainet")
    assert [s.name for s in cfg.sources] == ["mine", "cloudflare", "vercel", "corral"]
    mine, cloudflare, vercel, _ = cfg.sources
    assert mine.path == home / "Code" / "skills"
    assert mine.autocommit
    assert mine.autopush
    assert mine.skills is None
    assert cloudflare.git == "https://github.com/cloudflare/skills.git"
    assert cloudflare.ref == "main"
    assert cloudflare.skills
    assert SkillSpec("wrangler") in cloudflare.skills
    assert vercel.ref is None
    # A built-in's `ignore` adds to its own.
    assert cfg.harnesses["claude-code"].ignore == {"synced", "codebase-memory"}
    assert cfg.harnesses["codex"].ignore == {"codebase-memory"}


def test_source_details(home: Path) -> None:
    cfg = load(
        home,
        """
[[source]]
name = "local"
path = "rel/skills-repo"
subdir = "."
harnesses = ["claude-code", "codex"]
skills = ["a", { name = "b", harnesses = ["codex"] }]
""",
    )
    (src,) = cfg.sources
    assert src.path == home / ".config" / "tack" / "rel" / "skills-repo"
    assert src.subdir == "."
    assert src.skills == (SkillSpec("a"), SkillSpec("b", ("codex",)))


def test_new_harness_needs_every_field(home: Path) -> None:
    table = """
[harness.pi]
skills_dir = "~/.pi/skills"
project_skills_dir = ".pi/skills"
instructions = "~/.pi/AGENTS.md"
project_instructions = "AGENTS.md"
hooks = "~/.pi/hooks.json"
project_hooks = [".pi/hooks.json"]
"""
    cfg = load(home, table)
    pi = cfg.harnesses["pi"]
    assert list(cfg.harnesses) == ["claude-code", "codex", "pi"]
    assert pi.hooks == (home / ".pi" / "hooks.json",)
    assert not pi.imports
    assert pi.ignore == frozenset()
    with pytest.raises(ConfigError, match="new harness and needs project_hooks"):
        load(home, table.replace('project_hooks = [".pi/hooks.json"]', ""))


def test_builtin_harness_override(home: Path) -> None:
    cfg = load(home, '[harness.codex]\nskills_dir = "~/elsewhere"\nhooks = "~/h.json"\n')
    codex = cfg.harnesses["codex"]
    assert codex.skills_dir == home / "elsewhere"
    assert codex.hooks == (home / "h.json",)
    assert codex.instructions == home / ".codex" / "AGENTS.md"


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ("nonsense = 1", "unknown key 'nonsense'"),
        ("[projects]\nroot = []", r"unknown key 'root' in \[projects\]"),
        ("[projects]\nroots = '~/Code'", "roots must be a list"),
        ("[projects]\nowners = 'me'", "owners must be a list"),
        ("after_save = 1", "after_save must be a string"),
        ("[[source]]\npath = '/x'", "needs a `name`"),
        ("[[source]]\nname = '../x'\npath = '/x'", "needs a `name`"),
        ("[[source]]\nname = 'x'", "exactly one of `path` or `git`"),
        ("[[source]]\nname = 'x'\npath = '/x'\ngit = 'u'", "exactly one of `path` or `git`"),
        ("[[source]]\nname = 'x'\npath = '/x'\nref = 'main'", "`ref` applies to git"),
        ("[[source]]\nname = 'x'\ngit = 'u'\nautocommit = true", "auto-commit applies to path"),
        ("[[source]]\nname = 'x'\npath = '/x'\nautopush = 'yes'", "autopush must be true"),
        ("[[source]]\nname = 'x'\npath = '/x'\nautopush = true", "it needs autocommit"),
        ("[[source]]\nname = 'x'\npath = '/x'\nsubdir = '../up'", "subdir must be inside"),
        ("[[source]]\nname = 'x'\npath = '/x'\nskills = 'all'", 'skills must be "\\*" or a list'),
        ("[[source]]\nname = 'x'\npath = '/x'\nskills = ['a', 'a']", "lists skill 'a' twice"),
        ("[[source]]\nname = 'x'\npath = '/x'\nharnesses = ['pi']", "no harness named 'pi'"),
        ("[[source]]\nname = 'x'\npath = '/x'\nbranch = 'b'", "unknown key 'branch'"),
        (
            "[[source]]\nname = 'x'\npath = '/x'\nharnesses = ['codex']\n"
            "skills = [{ name = 'a', harnesses = ['claude-code'] }]",
            "isn't among the source's harnesses",
        ),
        (
            "[[source]]\nname = 'x'\npath = '/a'\n[[source]]\nname = 'x'\npath = '/b'",
            "two sources are named 'x'",
        ),
        ("[harness.codex]\nimports = 'no'", "imports must be true or false"),
        ("[harness.codex]\nproject_skills_dir = '/abs'", "relative to a project"),
        ("[harness.codex]\nskill_dir = '~/x'", "unknown key 'skill_dir'"),
        ("[harness.codex]\nignore = 'synced'", "ignore must be a list"),
        ("[[source]\n", "tack.toml"),  # invalid TOML
    ],
)
def test_manifest_errors(home: Path, manifest: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load(home, manifest)


def test_config_dir_argument(home: Path, tmp_path: Path) -> None:
    write(tmp_path / "cfg" / "tack.toml", "[projects]\nroots = ['~/src']\n")
    cfg = config.load(tmp_path / "cfg")
    assert cfg.manifest == tmp_path / "cfg" / "tack.toml"
    assert cfg.roots == (home / "src",)

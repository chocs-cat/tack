from __future__ import annotations

import re
from pathlib import Path

import pytest

from tack import agents, config
from tack.config import ConfigError, Harness, Paths, SkillSpec, Source
from tests.helpers import load, write

DESIGN = Path(__file__).parent.parent / "docs" / "design.md"


def test_no_manifest_means_builtin_harnesses_and_nothing_else(home: Path) -> None:
    cfg = load(home)
    assert cfg.manifest is None
    assert cfg.sources == ()
    assert cfg.roots == ()
    assert cfg.tui.group_by_source
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
    assert cfg.owners == ("johnfoland", "cruzainet", "chocs-cat")
    assert [s.name for s in cfg.sources] == [
        "mine",
        "cloudflare",
        "vercel",
        "corral",
        "claude-plugins-official",
    ]
    mine, cloudflare, vercel, _, official = cfg.sources
    assert mine.path == home / "Code" / "skills"
    assert mine.autocommit
    assert mine.autopush
    assert mine.skills is None
    assert cloudflare.git == "https://github.com/cloudflare/skills.git"
    assert cloudflare.ref == "main"
    assert cloudflare.skills
    assert SkillSpec("wrangler") in cloudflare.skills
    assert vercel.ref is None
    assert official.skills == ()
    assert official.plugins == (SkillSpec("skill-creator"),)
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
    assert src.plugins == ()


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


# --- `ignore_marketplaces` (design.md *Harness fields*) -----------------------------

CLAUDE_MARKETS = {"builtin", "inline", "skills-dir", "synced"}
CODEX_MARKETS = {"openai-bundled", "openai-curated-remote", "openai-primary-runtime"}


def test_builtin_ignore_marketplaces(home: Path) -> None:
    for cfg in (load(home), load(home, "[harness.codex]\nimports = false\n")):
        assert cfg.harnesses["claude-code"].ignore_marketplaces == CLAUDE_MARKETS
        assert cfg.harnesses["codex"].ignore_marketplaces == CODEX_MARKETS


@pytest.mark.parametrize(
    ("harness", "builtin"), [("claude-code", CLAUDE_MARKETS), ("codex", CODEX_MARKETS)]
)
def test_ignore_marketplaces_adds_to_the_builtin_list(
    home: Path, harness: str, builtin: set[str]
) -> None:
    cfg = load(home, f'[harness.{harness}]\nignore_marketplaces = ["mine", "theirs"]\n')
    assert cfg.harnesses[harness].ignore_marketplaces == builtin | {"mine", "theirs"}
    other = "codex" if harness == "claude-code" else "claude-code"
    assert cfg.harnesses[other].ignore_marketplaces == (
        CODEX_MARKETS if other == "codex" else CLAUDE_MARKETS
    )


NEW_HARNESS = """
[harness.pi]
skills_dir = "~/.pi/skills"
project_skills_dir = ".pi/skills"
instructions = "~/.pi/AGENTS.md"
project_instructions = "AGENTS.md"
hooks = "~/.pi/hooks.json"
project_hooks = [".pi/hooks.json"]
"""


def test_a_manifest_defined_harness_takes_no_ignore_marketplaces(home: Path) -> None:
    assert load(home, NEW_HARNESS).harnesses["pi"].ignore_marketplaces == frozenset()
    with pytest.raises(
        ConfigError, match=r"\[harness.pi\] ignore_marketplaces: only the built-in harnesses"
    ):
        load(home, NEW_HARNESS + 'ignore_marketplaces = ["x"]\n')


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
        (
            "[harness.codex]\nignore_marketplaces = 'mine'",
            r"\[harness.codex\] ignore_marketplaces must be a list of strings",
        ),
        (
            "[harness.claude-code]\nignore_marketplaces = ['ok', 1]",
            r"\[harness.claude-code\] ignore_marketplaces must be a list of strings",
        ),
        ("[tui]\ngroup_by_source = 'yes'", "group_by_source must be true or false"),
        ("[tui]\ngroup = true", "unknown key 'group' in \\[tui\\]"),
        ("[[source]\n", "tack.toml"),  # invalid TOML
    ],
)
def test_manifest_errors(home: Path, manifest: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load(home, manifest)


def test_tui_defaults(home: Path) -> None:
    assert load(home, "[tui]\n").tui.group_by_source
    assert not load(home, "[tui]\ngroup_by_source = false\n").tui.group_by_source


def test_config_dir_argument(home: Path, tmp_path: Path) -> None:
    write(tmp_path / "cfg" / "tack.toml", "[projects]\nroots = ['~/src']\n")
    cfg = config.load(tmp_path / "cfg")
    assert cfg.manifest == tmp_path / "cfg" / "tack.toml"
    assert cfg.roots == (home / "src",)


# --- the `plugins` field ------------------------------------------------------------

PI = """
[harness.pi]
skills_dir = "~/.pi/skills"
project_skills_dir = ".pi/skills"
instructions = "~/.pi/AGENTS.md"
project_instructions = "AGENTS.md"
hooks = ["~/.pi/hooks.json"]
project_hooks = [".pi/hooks.json"]
"""


@pytest.fixture
def harnesses(home: Path) -> dict[str, Harness]:
    """The built-in harnesses and `pi`, one the manifest defines."""
    return load(home, PI).harnesses


def plugins(
    harnesses: dict[str, Harness], value: object, source: tuple[str, ...] | None = None
) -> tuple[SkillSpec, ...] | None:
    return config.parse_plugins(value, source, harnesses, Path("tack.toml"), "source 'x'")


def test_plugins_values(harnesses: dict[str, Harness]) -> None:
    assert plugins(harnesses, "*") is None
    assert plugins(harnesses, []) == ()
    assert plugins(harnesses, ["a", "b"]) == (SkillSpec("a"), SkillSpec("b"))
    value = ["a", {"name": "b", "harnesses": ["codex"]}]
    assert plugins(harnesses, value) == (SkillSpec("a"), SkillSpec("b", ("codex",)))
    value = [{"name": "b", "harnesses": ["claude-code"]}]
    assert plugins(harnesses, value, ("claude-code", "pi")) == (SkillSpec("b", ("claude-code",)),)


@pytest.mark.parametrize(
    ("value", "source", "message"),
    [
        ("all", None, "source 'x' plugins must be \"\\*\" or a list"),
        ({"name": "a"}, None, 'plugins must be "\\*" or a list'),
        ([1], None, "plugins entries are names or tables"),
        ([{"harnesses": ["codex"]}], None, "plugins: a table entry needs a `name`"),
        ([{"name": "a", "version": "1"}], None, "unknown key 'version' in source 'x' plugins"),
        (["../a"], None, "plugins: '../a' isn't a plugin name"),
        (["a", {"name": "a"}], None, "lists plugin 'a' twice"),
        ([{"name": "a", "harnesses": ["nope"]}], None, "plugin 'a' harnesses: no harness named"),
        ([{"name": "a", "harnesses": "codex"}], None, "harnesses must be a list"),
        # A harness the manifest defines takes no plugins (DEC-8), even
        # where the source targets it.
        (
            [{"name": "a", "harnesses": ["pi"]}],
            None,
            "plugin 'a' harnesses: only claude-code and codex take plugins, not 'pi'",
        ),
        ([{"name": "a", "harnesses": ["codex", "pi"]}], ("pi", "codex"), "not 'pi'"),
        (
            [{"name": "a", "harnesses": ["claude-code"]}],
            ("codex",),
            "plugin 'a' harnesses: claude-code isn't among the source's harnesses",
        ),
    ],
)
def test_plugins_errors(
    harnesses: dict[str, Harness], value: object, source: tuple[str, ...] | None, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        plugins(harnesses, value, source)


def test_a_source_selecting_plugins_targets_a_harness_that_takes_them(
    harnesses: dict[str, Harness],
) -> None:
    # DEC-10: selecting plugins for `pi` alone is an error ...
    for value in ("*", ["x"]):
        with pytest.raises(ConfigError, match="selects plugins but targets neither claude-code"):
            plugins(harnesses, value, ("pi",))
    # ... selecting none isn't, and a source that also targets a built-in is fine.
    assert plugins(harnesses, [], ("pi",)) == ()
    assert plugins(harnesses, "*", ("pi", "codex")) is None
    assert plugins(harnesses, ["x"], ("pi", "codex")) == (SkillSpec("x"),)
    # A source with no `harnesses` targets every harness, built-ins included.
    assert plugins(harnesses, ["x"]) == (SkillSpec("x"),)


def test_skills_and_plugins_messages_name_their_own_field(
    home: Path, harnesses: dict[str, Harness]
) -> None:
    with pytest.raises(ConfigError, match="lists plugin 'a' twice"):
        plugins(harnesses, ["a", "a"])
    with pytest.raises(ConfigError, match="lists skill 'a' twice"):
        load(home, "[[source]]\nname = 'x'\npath = '/x'\nskills = ['a', 'a']")


def test_a_source_selects_no_plugins_by_default() -> None:
    assert Source("x").plugins == ()  # DEC-3
    assert Source("x").skills is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"*"', None),
        ("[]", ()),
        ('["a"]', (SkillSpec("a"),)),
        (
            '["a", { name = "b", harnesses = ["codex"] }]',
            (SkillSpec("a"), SkillSpec("b", ("codex",))),
        ),
    ],
)
def test_the_manifest_accepts_plugins(
    home: Path, value: str, expected: tuple[SkillSpec, ...] | None
) -> None:
    cfg = load(home, f"[[source]]\nname = 'x'\npath = '/x'\nplugins = {value}\n")
    assert cfg.sources[0].plugins == expected


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            'plugins = [{ name = "a", harnesses = ["pi"] }]',
            "only claude-code and codex take plugins",
        ),
        ('harnesses = ["pi"]\nplugins = "*"', "selects plugins but targets neither"),
        ('plugins = ["a", { name = "a" }]', "lists plugin 'a' twice"),
    ],
)
def test_manifest_plugin_errors_name_the_manifest(home: Path, fields: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message) as exc:
        load(home, PI + "\n[[source]]\nname = 'x'\npath = '/x'\n" + fields)
    assert str(home / ".config" / "tack" / "tack.toml") in str(exc.value)


def test_the_harnesses_that_take_plugins_are_those_with_a_cli() -> None:
    assert set(config.PLUGIN_HARNESSES) == set(agents.CLIS)
    assert set(config.PLUGIN_HARNESSES) == set(config.BUILTIN_HARNESSES)  # DEC-8

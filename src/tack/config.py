"""The manifest (tack.toml), the harnesses tack knows, and where its files live.

Locations follow the XDG base directory spec: the manifest in
$TACK_CONFIG, else $XDG_CONFIG_HOME/tack, else ~/.config/tack; git checkouts
under $TACK_DATA or $XDG_DATA_HOME/tack; the ownership record under
$TACK_STATE or $XDG_STATE_HOME/tack. The XDG paths are used on macOS too.

A missing manifest is valid: no sources, no project roots, and the built-in
harnesses. The lockfile, tack.lock, sits beside the manifest; tack alone
writes it. Anything present is checked strictly -- unknown keys, wrong types
and dangling harness names are errors -- so a typo can't silently deploy
nothing.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

MANIFEST = "tack.toml"
LOCKFILE = "tack.lock"
LOCK_VERSION = 1

BUILTIN_HARNESSES: dict[str, dict[str, Any]] = {
    "claude-code": {
        "skills_dir": "~/.claude/skills",
        "project_skills_dir": ".claude/skills",
        "instructions": "~/.claude/CLAUDE.md",
        "project_instructions": "CLAUDE.md",
        "hooks": ["~/.claude/settings.json"],
        "project_hooks": [".claude/settings.json"],
        "imports": True,
        "ignore": ["synced"],
        # claude.ai's synced plugins and the plugins Claude Code ships with.
        "ignore_marketplaces": ["builtin", "inline", "skills-dir", "synced"],
    },
    "codex": {
        "skills_dir": "~/.agents/skills",
        "project_skills_dir": ".agents/skills",
        "instructions": "~/.codex/AGENTS.md",
        "project_instructions": "AGENTS.md",
        "hooks": ["~/.codex/hooks.json", "~/.codex/config.toml"],
        "project_hooks": [".codex/hooks.json", ".codex/config.toml"],
        "imports": False,
        "ignore": [],
        "ignore_marketplaces": [
            "openai-bundled",
            "openai-curated-remote",
            "openai-primary-runtime",
        ],
    },
}
# The harnesses that take plugins: the built-in ones, whose CLIs tack drives
# (DEC-8). `agents.CLIS` names the CLI of each.
PLUGIN_HARNESSES = tuple(BUILTIN_HARNESSES)

_HARNESS_REQUIRED = (
    "skills_dir",
    "project_skills_dir",
    "instructions",
    "project_instructions",
    "hooks",
    "project_hooks",
)
_HARNESS_KEYS = {*_HARNESS_REQUIRED, "imports", "ignore", "ignore_marketplaces"}
_SOURCE_KEYS = {
    "name",
    "path",
    "git",
    "ref",
    "subdir",
    "skills",
    "plugins",
    "harnesses",
    "autocommit",
    "autopush",
}
_TOP_KEYS = {"after_save", "projects", "harness", "source", "tui"}
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")


class ConfigError(Exception):
    """The manifest can't be read or doesn't make sense (exit code 2)."""


class UsageError(Exception):
    """A command was asked for something it can't do as asked (exit code 2)."""


@dataclass(frozen=True)
class Paths:
    config_dir: Path
    data_dir: Path
    state_dir: Path

    @property
    def manifest(self) -> Path:
        return self.config_dir / MANIFEST

    @property
    def lockfile(self) -> Path:
        return self.config_dir / LOCKFILE

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def marketplace_dir(self) -> Path:
        """tack's marketplace, the one it registers with each agent (DEC-1)."""
        return self.data_dir / "marketplace"

    @classmethod
    def from_env(cls, config_dir: Path | None = None) -> Paths:
        return cls(
            config_dir=config_dir or _env_dir("TACK_CONFIG", "XDG_CONFIG_HOME", "~/.config"),
            data_dir=_env_dir("TACK_DATA", "XDG_DATA_HOME", "~/.local/share"),
            state_dir=_env_dir("TACK_STATE", "XDG_STATE_HOME", "~/.local/state"),
        )


def _env_dir(own: str, xdg: str, fallback: str) -> Path:
    if value := os.environ.get(own):
        return Path(value).expanduser().absolute()
    base = os.environ.get(xdg, "")
    # The spec: a relative XDG path is invalid and should be ignored.
    root = Path(base) if base and Path(base).is_absolute() else Path(fallback).expanduser()
    return root / "tack"


@dataclass(frozen=True)
class Harness:
    name: str
    skills_dir: Path
    project_skills_dir: str
    instructions: Path
    project_instructions: str
    hooks: tuple[Path, ...]
    project_hooks: tuple[str, ...]
    imports: bool
    ignore: frozenset[str]
    # Marketplaces whose plugins aren't reported as unmanaged (design.md
    # *Harness fields*); empty for a harness the manifest defines (DEC-8).
    ignore_marketplaces: frozenset[str]

    def ignores(self, entry: str) -> bool:
        """Whether an entry in `skills_dir` belongs to someone else."""
        return entry.startswith(".") or entry in self.ignore


@dataclass(frozen=True)
class SkillSpec:
    """An entry of a source's `skills` or `plugins`."""

    name: str
    harnesses: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Source:
    name: str
    path: Path | None = None
    git: str | None = None
    ref: str | None = None
    subdir: str = "skills"
    skills: tuple[SkillSpec, ...] | None = None  # None: every skill ("*")
    plugins: tuple[SkillSpec, ...] | None = ()  # None: every plugin ("*"); (): none (DEC-3)
    harnesses: tuple[str, ...] | None = None  # None: every harness
    autocommit: bool = False
    autopush: bool = False


@dataclass(frozen=True)
class Tui:
    """The TUI's defaults, from `[tui]`; the CLI ignores them."""

    group_by_source: bool = True


@dataclass(frozen=True)
class Config:
    paths: Paths
    manifest: Path | None  # None when there is no manifest file
    harnesses: dict[str, Harness]
    sources: tuple[Source, ...] = ()
    roots: tuple[Path, ...] = ()
    exclude: tuple[Path, ...] = ()
    owners: tuple[str, ...] = ()  # empty: every repository is yours
    after_save: str | None = None
    tui: Tui = Tui()


def load(config_dir: Path | None = None) -> Config:
    """Read the manifest from `config_dir` (or the environment's default)."""
    paths = Paths.from_env(config_dir.absolute() if config_dir else None)
    file = paths.manifest
    if not file.is_file():
        return Config(paths=paths, manifest=None, harnesses=_harnesses({}, file))
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{file}: {e}") from e
    return parse(data, file, paths)


def parse(data: dict[str, Any], file: Path, paths: Paths) -> Config:
    """Build a Config from the manifest's parsed TOML."""
    _no_unknown(data, _TOP_KEYS, file, "the top level")
    harnesses = _harnesses(_table(data, "harness", file, "the top level"), file)
    base = file.parent
    projects = _table(data, "projects", file, "the top level")
    _no_unknown(projects, {"roots", "exclude", "owners"}, file, "[projects]")
    roots = _str_list(projects.get("roots", []), file, "[projects] roots")
    exclude = _str_list(projects.get("exclude", []), file, "[projects] exclude")
    owners = _str_list(projects.get("owners", []), file, "[projects] owners")
    after_save = data.get("after_save")
    if after_save is not None and not isinstance(after_save, str):
        raise ConfigError(f"{file}: after_save must be a string")
    tui = _table(data, "tui", file, "the top level")
    _no_unknown(tui, {"group_by_source"}, file, "[tui]")
    group = tui.get("group_by_source", True)
    if not isinstance(group, bool):
        raise ConfigError(f"{file}: [tui] group_by_source must be true or false")

    raw_sources = data.get("source", [])
    if not isinstance(raw_sources, list):
        raise ConfigError(f"{file}: sources are [[source]] tables")
    sources: list[Source] = []
    for i, raw in enumerate(raw_sources, 1):
        source = _source(raw, i, file, base, harnesses)
        if any(s.name == source.name for s in sources):
            raise ConfigError(f"{file}: two sources are named {source.name!r}")
        sources.append(source)

    return Config(
        paths=paths,
        manifest=file,
        harnesses=harnesses,
        sources=tuple(sources),
        roots=tuple(_path(r, base) for r in roots),
        exclude=tuple(_path(e, base) for e in exclude),
        owners=tuple(owners),
        after_save=after_save,
        tui=Tui(group_by_source=group),
    )


def _harnesses(tables: dict[str, Any], file: Path) -> dict[str, Harness]:
    out: dict[str, Harness] = {}
    for name in [*BUILTIN_HARNESSES, *(n for n in tables if n not in BUILTIN_HARNESSES)]:
        where = f"[harness.{name}]"
        table = tables.get(name, {})
        if not isinstance(table, dict):
            raise ConfigError(f"{file}: {where} must be a table")
        _no_unknown(table, _HARNESS_KEYS, file, where)
        builtin = BUILTIN_HARNESSES.get(name)
        if builtin is None:
            if not _NAME.fullmatch(name):
                raise ConfigError(f"{file}: {name!r} isn't a valid harness name")
            if "ignore_marketplaces" in table:
                raise ConfigError(
                    f"{file}: {where} ignore_marketplaces: only the built-in harnesses "
                    f"({' and '.join(PLUGIN_HARNESSES)}) take plugins (DEC-8)"
                )
            missing = [k for k in _HARNESS_REQUIRED if k not in table]
            if missing:
                raise ConfigError(
                    f"{file}: {where} is a new harness and needs {', '.join(missing)}"
                )
            fields = {"imports": False, "ignore": [], "ignore_marketplaces": [], **table}
        else:
            # A built-in's `ignore` and `ignore_marketplaces` add to its own
            # lists rather than replacing them.
            fields = {**builtin, **table}
            for key in ("ignore", "ignore_marketplaces"):
                extra = _str_list(table.get(key, []), file, f"{where} {key}")
                fields[key] = [*builtin[key], *extra]
        out[name] = _harness(name, fields, file, where)
    return out


def _harness(name: str, f: dict[str, Any], file: Path, where: str) -> Harness:
    def string(key: str) -> str:
        v = f[key]
        if not isinstance(v, str) or not v:
            raise ConfigError(f"{file}: {where} {key} must be a non-empty string")
        return v

    def strings(key: str) -> list[str]:
        v = f[key]
        return [v] if isinstance(v, str) else _str_list(v, file, f"{where} {key}")

    def relative(key: str, value: str) -> str:
        if Path(value).expanduser().is_absolute():
            raise ConfigError(f"{file}: {where} {key} is relative to a project: {value!r}")
        return value

    if not isinstance(f["imports"], bool):
        raise ConfigError(f"{file}: {where} imports must be true or false")
    return Harness(
        name=name,
        skills_dir=Path(string("skills_dir")).expanduser(),
        project_skills_dir=relative("project_skills_dir", string("project_skills_dir")),
        instructions=Path(string("instructions")).expanduser(),
        project_instructions=relative("project_instructions", string("project_instructions")),
        hooks=tuple(Path(h).expanduser() for h in strings("hooks")),
        project_hooks=tuple(relative("project_hooks", h) for h in strings("project_hooks")),
        imports=f["imports"],
        ignore=frozenset(_str_list(f["ignore"], file, f"{where} ignore")),
        ignore_marketplaces=frozenset(f["ignore_marketplaces"]),
    )


def _source(raw: Any, i: int, file: Path, base: Path, harnesses: dict[str, Harness]) -> Source:
    if not isinstance(raw, dict):
        raise ConfigError(f"{file}: source #{i} must be a table")
    name = raw.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ConfigError(f"{file}: source #{i} needs a `name` of letters, digits, '.', '_' or '-'")
    where = f"source {name!r}"
    _no_unknown(raw, _SOURCE_KEYS, file, where)

    path, git = raw.get("path"), raw.get("git")
    if (path is None) == (git is None):
        raise ConfigError(f"{file}: {where} needs exactly one of `path` or `git`")
    for key in ("path", "git", "ref", "subdir"):
        if key in raw and (not isinstance(raw[key], str) or not raw[key]):
            raise ConfigError(f"{file}: {where} {key} must be a non-empty string")
    for key in ("autocommit", "autopush"):
        if key in raw and not isinstance(raw[key], bool):
            raise ConfigError(f"{file}: {where} {key} must be true or false")
    if path is not None and "ref" in raw:
        raise ConfigError(f"{file}: {where} is a path source; `ref` applies to git sources")
    if git is not None and (raw.get("autocommit") or raw.get("autopush")):
        raise ConfigError(f"{file}: {where} is a git source; auto-commit applies to path sources")
    if raw.get("autopush") and not raw.get("autocommit"):
        raise ConfigError(f"{file}: {where} autopush pushes auto-commits; it needs autocommit")

    subdir = raw.get("subdir", "skills")
    if Path(subdir).is_absolute() or ".." in Path(subdir).parts:
        raise ConfigError(f"{file}: {where} subdir must be inside the source: {subdir!r}")

    source_harnesses = _harness_names(raw.get("harnesses"), harnesses, file, f"{where} harnesses")
    return Source(
        name=name,
        path=_path(path, base) if path is not None else None,
        git=git,
        ref=raw.get("ref"),
        subdir=subdir,
        skills=_specs("skill", raw.get("skills", "*"), source_harnesses, harnesses, file, where),
        plugins=parse_plugins(raw.get("plugins", []), source_harnesses, harnesses, file, where),
        harnesses=source_harnesses,
        autocommit=raw.get("autocommit", False),
        autopush=raw.get("autopush", False),
    )


def parse_plugins(
    value: Any,
    source_harnesses: tuple[str, ...] | None,
    harnesses: dict[str, Harness],
    file: Path,
    where: str,
) -> tuple[SkillSpec, ...] | None:
    """A source's `plugins` (design.md *Selecting plugins*): read as `skills`
    is, and only the harnesses that take plugins may be named (DEC-8). A
    source that selects any must target one of them (DEC-10)."""
    specs = _specs("plugin", value, source_harnesses, harnesses, file, where)
    for spec in specs or ():
        if others := [h for h in spec.harnesses or () if h not in PLUGIN_HARNESSES]:
            label = f"{where} plugin {spec.name!r} harnesses"
            raise ConfigError(
                f"{file}: {label}: only {' and '.join(PLUGIN_HARNESSES)} take plugins, "
                f"not {', '.join(map(repr, others))}"
            )
    selects = specs is None or bool(specs)
    if selects and source_harnesses and not set(source_harnesses) & set(PLUGIN_HARNESSES):
        raise ConfigError(
            f"{file}: {where} selects plugins but targets neither "
            f"{' nor '.join(PLUGIN_HARNESSES)}, the harnesses that take them"
        )
    return specs


def _specs(
    kind: Literal["skill", "plugin"],
    value: Any,
    source_harnesses: tuple[str, ...] | None,
    harnesses: dict[str, Harness],
    file: Path,
    where: str,
) -> tuple[SkillSpec, ...] | None:
    """A source's `skills` or `plugins`, as `kind` ("skill", "plugin") says:
    "*" (None), or a list of names and `{ name, harnesses }` tables."""
    key = f"{kind}s"
    if value == "*":
        return None
    if not isinstance(value, list):
        raise ConfigError(f'{file}: {where} {key} must be "*" or a list')
    specs: list[SkillSpec] = []
    for item in value:
        if isinstance(item, str):
            spec = SkillSpec(item)
        elif isinstance(item, dict):
            _no_unknown(item, {"name", "harnesses"}, file, f"{where} {key}")
            if not isinstance(item.get("name"), str):
                raise ConfigError(f"{file}: {where} {key}: a table entry needs a `name`")
            label = f"{where} {kind} {item['name']!r} harnesses"
            names = _harness_names(item.get("harnesses"), harnesses, file, label)
            outside = [h for h in names or () if source_harnesses and h not in source_harnesses]
            if outside:
                raise ConfigError(
                    f"{file}: {label}: {', '.join(outside)} isn't among the source's harnesses"
                )
            spec = SkillSpec(item["name"], names)
        else:
            raise ConfigError(f"{file}: {where} {key} entries are names or tables")
        if not _NAME.fullmatch(spec.name):
            raise ConfigError(f"{file}: {where} {key}: {spec.name!r} isn't a {kind} name")
        if any(s.name == spec.name for s in specs):
            raise ConfigError(f"{file}: {where} lists {kind} {spec.name!r} twice")
        specs.append(spec)
    return tuple(specs)


def _harness_names(
    value: Any, harnesses: dict[str, Harness], file: Path, where: str
) -> tuple[str, ...] | None:
    if value is None:
        return None
    names = _str_list(value, file, where)
    if unknown := [n for n in names if n not in harnesses]:
        raise ConfigError(f"{file}: {where}: no harness named {', '.join(map(repr, unknown))}")
    return tuple(names)


def _table(data: dict[str, Any], key: str, file: Path, where: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{file}: {key} in {where} must be a table")
    return value


def _str_list(value: Any, file: Path, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{file}: {where} must be a list of strings")
    return value


def valid_name(name: str) -> bool:
    """Whether `name` can name a source, a skill or a harness."""
    return bool(_NAME.fullmatch(name))


def _no_unknown(table: dict[str, Any], allowed: set[str], file: Path, where: str) -> None:
    if unknown := sorted(set(table) - allowed):
        raise ConfigError(f"{file}: unknown key {', '.join(map(repr, unknown))} in {where}")


def _path(value: str, base: Path) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else base / p


# --- the lockfile -----------------------------------------------------------


@dataclass(frozen=True)
class LockEntry:
    git: str
    ref: str | None  # None: the remote's default branch
    commit: str
    locked: datetime

    def matches(self, source: Source) -> bool:
        """Whether this pin was made for the source as the manifest now has it."""
        return self.git == source.git and self.ref == source.ref


def load_lock(paths: Paths) -> dict[str, LockEntry]:
    """The pins by source name; none if there is no lockfile."""
    file = paths.lockfile
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{file}: {e}") from e
    if data.get("version") != LOCK_VERSION:
        raise ConfigError(f"{file}: not a version {LOCK_VERSION} lockfile")
    table = data.get("source", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{file}: sources are [source.<name>] tables")
    out: dict[str, LockEntry] = {}
    for name, entry in table.items():
        git, ref = entry.get("git"), entry.get("ref")
        commit, locked = entry.get("commit"), entry.get("locked")
        if (
            not isinstance(git, str)
            or not (ref is None or isinstance(ref, str))
            or not isinstance(commit, str)
            or not re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", commit)
            or not isinstance(locked, datetime)
        ):
            raise ConfigError(f"{file}: [source.{name}] needs git, commit and locked")
        out[name] = LockEntry(git, ref, commit, locked)
    return out


def dump_lock(entries: dict[str, LockEntry]) -> str:
    lines = [
        "# Generated by tack. Do not edit; use `tack update`.",
        f"version = {LOCK_VERSION}",
    ]
    for name in sorted(entries):
        e = entries[name]
        locked = e.locked.astimezone(UTC).replace(microsecond=0, tzinfo=None).isoformat()
        lines += ["", f"[source.{_key(name)}]", f"git = {toml_str(e.git)}"]
        if e.ref is not None:
            lines.append(f"ref = {toml_str(e.ref)}")
        lines += [f"commit = {toml_str(e.commit)}", f"locked = {locked}Z"]
    return "\n".join(lines) + "\n"


def save_lock(paths: Paths, entries: dict[str, LockEntry]) -> bool:
    """Write the lockfile if its content changes; returns whether it did."""
    text = dump_lock(entries)
    file = paths.lockfile
    try:
        if file.read_text(encoding="utf-8") == text:
            return False
    except FileNotFoundError:
        pass
    write_atomic(file, text)
    return True


def _key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else toml_str(name)


def toml_str(value: str) -> str:
    """`value` as a TOML basic string (a JSON string is one)."""
    return json.dumps(value, ensure_ascii=False)


def write_atomic(file: Path, text: str) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(f".{file.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(file)


def run_after_save(cfg: Config, file: Path) -> str | None:
    """Run the manifest's `after_save` for a file tack wrote; the error, if any."""
    if not cfg.after_save:
        return None
    command = cfg.after_save.replace("{path}", shlex.quote(str(file)))
    r = subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=False)
    if r.returncode == 0:
        return None
    detail = (r.stderr or r.stdout).strip().splitlines()
    return f"after_save `{command}` exited {r.returncode}" + (f": {detail[-1]}" if detail else "")

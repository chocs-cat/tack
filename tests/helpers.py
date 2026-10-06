"""Builders for throwaway harness directories, sources, projects and repos."""

from __future__ import annotations

import dataclasses
import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tack import config
from tack.config import Config
from tack.doctor.findings import Finding


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def skill(
    parent: Path, name: str, *, description: str = "Does a thing.", fm_name: str = ""
) -> Path:
    """A skill directory with a valid SKILL.md (its frontmatter `name` is the
    directory name unless `fm_name` says otherwise)."""
    d = parent / name
    write(
        d / "SKILL.md", f"---\nname: {fm_name or name}\ndescription: {description}\n---\n\nBody.\n"
    )
    return d


def link(entry: Path, target: Path) -> Path:
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.symlink_to(target)
    return entry


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return r.stdout


def repo(path: Path, files: dict[str, str] | None = None, *, commit: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "master")
    for rel, text in (files or {}).items():
        write(path / rel, text)
    if commit:
        git(path, "add", "-A")
        git(path, "commit", "-q", "--allow-empty", "-m", "init")
    return path


def load(home: Path, manifest: str | None = None) -> Config:
    """Config from `manifest` written to the default location (none if None)."""
    if manifest is not None:
        write(home / ".config" / "tack" / "tack.toml", manifest)
    return config.load()


def ids(findings: Iterable[Finding]) -> list[str]:
    return [f.id for f in findings]


def skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: The {name} skill.\n---\n"


def upstream(path: Path, *skills: str) -> Path:
    """A repository standing in for a git source's remote, with `skills/<name>`
    for each skill, committed on master."""
    return repo(path, {f"skills/{s}/SKILL.md": skill_md(s) for s in skills})


def commit(r: Path, files: dict[str, str], message: str = "change") -> str:
    """Commit `files` to `r`; the new commit's SHA."""
    for rel, text in files.items():
        write(r / rel, text)
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", message)
    return git(r, "rev-parse", "HEAD").strip()


def tree(root: Path) -> dict[str, str]:
    """Everything under `root`: each path, and a link's target or a file's text."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = "-> " + str(p.readlink())
        elif p.is_file():
            out[rel] = p.read_bytes().decode(errors="replace")
        else:
            out[rel] = "/"
    return out


def market(root: Path, *entries: Any, **doc: Any) -> Path:
    """A source at `root` whose catalog lists `entries`: a name `n` is
    `{"name": n, "source": "./plugins/n"}`, anything else is the entry itself."""
    listed = [{"name": e, "source": f"./plugins/{e}"} if isinstance(e, str) else e for e in entries]
    write(root / ".claude-plugin" / "marketplace.json", json.dumps({**doc, "plugins": listed}))
    return root


def configure(home: Path, *sources: str, manifest: str = "", **selections: Any) -> Config:
    """A Config whose `path` sources are `~/<name>`, each selecting the
    plugins `selections` gives it (none by default), as `parse_plugins` reads
    them: the manifest doesn't take `plugins` yet. A source written
    `name:h1,h2` targets those harnesses."""
    tables = []
    for s in sources:
        name, _, hs = s.partition(":")
        table = f'[[source]]\nname = "{name}"\npath = "~/{name}"\n'
        if hs:
            table += f"harnesses = {json.dumps(hs.split(','))}\n"
        tables.append(table)
    cfg = load(home, manifest + "\n" + "\n".join(tables))
    assert cfg.manifest is not None
    out = []
    for src in cfg.sources:
        value = selections.get(src.name, [])
        where = f"source {src.name!r}"
        specs = config.parse_plugins(value, src.harnesses, cfg.harnesses, cfg.manifest, where)
        out.append(dataclasses.replace(src, plugins=specs))
    return dataclasses.replace(cfg, sources=tuple(out))

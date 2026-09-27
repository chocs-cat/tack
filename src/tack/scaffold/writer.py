"""The file changes a fix makes, recorded as it makes them (or would, in a dry run).

A tracked path is moved or removed through git, so history follows and the
index keeps up. A file tack writes or links is staged if git tracked it or
tack created it, unless git ignores it; untracked files stay untracked.
"""

from __future__ import annotations

import difflib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tack import git
from tack.sync import Change, Note, Problem, Result


class Refusal(Exception):
    """A fix that can't be applied safely. It is raised before anything changes."""


class Failed(Exception):
    """A change that went wrong partway; it is already reported."""


@dataclass
class Writer:
    project: Path
    result: Result
    in_repo: bool
    gone: set[str] = field(default_factory=set)  # moved or removed during this run

    @classmethod
    def at(cls, project: Path, result: Result) -> Writer:
        return cls(project, result, git.toplevel(project) is not None)

    # --- questions about paths (relative to the project) -------------------------

    def exists(self, rel: str) -> bool:
        return rel not in self.gone and os.path.lexists(self.project / rel)

    def read(self, rel: str) -> str | None:
        """A file's text as this run has left it; None if there is none."""
        if not self.exists(rel):
            return None
        try:
            return (self.project / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def tracked(self, rel: str) -> bool:
        """Whether git tracks `rel`, or anything under it."""
        return self.in_repo and bool(git.tracked(self.project, rel))

    def ignored(self, rel: str) -> bool:
        return self.in_repo and git.run(self.project, "check-ignore", "-q", rel).returncode == 0

    def files(self, rel: str) -> list[str] | None:
        """The files under a directory that git doesn't ignore (every file,
        outside a repository), relative to it; None if it isn't a directory."""
        root = self.project / rel
        if not root.is_dir():
            return None
        if self.in_repo and not root.is_symlink():
            r = git.run(self.project, "ls-files", "-z", "-co", "--exclude-standard", "--", rel)
            if r.returncode == 0:
                found = [f for f in r.stdout.split("\0") if f]
                return sorted(f[len(rel) + 1 :] for f in found if os.path.lexists(self.project / f))
        out = []
        for dirpath, _, filenames in os.walk(root, followlinks=True):
            out += [str((Path(dirpath) / f).relative_to(root)) for f in filenames]
        return sorted(out)

    # --- changes -------------------------------------------------------------

    def note(self, message: str) -> None:
        self.result.notes.append(Note(message))

    def write(self, rel: str, text: str) -> None:
        old = self.read(rel)
        if old == text:
            return
        created = not self.exists(rel)
        stage = self.in_repo and (created or self.tracked(rel)) and not self.ignored(rel)
        diff = "".join(
            difflib.unified_diff(
                (old or "").splitlines(keepends=True),
                text.splitlines(keepends=True),
                "/dev/null" if created else f"a/{rel}",
                f"b/{rel}",
            )
        )
        path = self.project / rel

        def step() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            if stage:
                self._git("add", "--", rel)

        self._do(Change("write", rel, path=path, diff=diff), step)
        self.gone.discard(rel)

    def move(self, src: str, dst: str) -> None:
        tracked = self.tracked(src)
        path = self.project / dst

        def step() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if tracked:
                self._git("mv", "--", src, dst)
            else:
                (self.project / src).rename(path)

        self._do(Change("move", f"{src} -> {dst}", path=path), step)
        self.gone.add(src)
        self.gone.discard(dst)

    def remove(self, rel: str) -> None:
        tracked = self.tracked(rel)
        path = self.project / rel

        def step() -> None:
            if tracked:
                self._git("rm", "-r", "-q", "-f", "--", rel)
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)

        self._do(Change("delete", rel, path=path), step)
        self.gone.add(rel)

    def link(self, rel: str, target: str) -> None:
        path = self.project / rel
        stage = self.in_repo and not self.ignored(rel)

        def step() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
            if stage:
                self._git("add", "--", rel)

        self._do(Change("link", f"{rel} -> {target}", path=path), step)
        self.gone.discard(rel)

    def _do(self, change: Change, step: Callable[[], None]) -> None:
        if not self.result.dry_run:
            try:
                step()
            except OSError as e:
                message = f"{change.action} {change.detail}: {e}"
                self.result.problems.append(Problem("error", message, path=change.path))
                raise Failed from e
        self.result.changes.append(change)

    def _git(self, *args: str) -> None:
        r = git.run(self.project, *args)
        if r.returncode != 0:
            raise OSError(git.error(r))

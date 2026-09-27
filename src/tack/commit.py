"""Auto-commit: commit pending edits to the skills of `path` sources, and push them.

For each path source with `autocommit = true`, `sync`, `update`, `add` and
`remove` finish by committing the changes inside its skill directories --
nothing else in the repository, and nothing else already staged -- as the
user, with a message naming the skills. With `autopush` they then push the
current branch to its upstream while commits touching skills are unpushed, so
a push that failed is tried again on the next run. A repository in the middle
of something (a merge, a rebase, conflicts, a detached HEAD) is skipped with a
note; a failed commit or push is a problem, and is never retried or rebased
within a run.
"""

from __future__ import annotations

from pathlib import Path

from tack import git, sources
from tack.config import Config, Paths, Source
from tack.sync import Change, Note, Problem, Result
from tack.text import tilde

# Files in the git dir that say an operation is under way.
_UNDER_WAY = (
    ("MERGE_HEAD", "mid-merge"),
    ("rebase-merge", "mid-rebase"),
    ("rebase-apply", "mid-rebase"),
    ("CHERRY_PICK_HEAD", "mid-cherry-pick"),
    ("REVERT_HEAD", "mid-revert"),
)


def autocommit(cfg: Config, *, dry_run: bool = False) -> Result:
    """Commit, and push, the pending skill edits of every source that asks."""
    result = Result(dry_run)
    for src in cfg.sources:
        if src.path is not None and src.autocommit:
            _source(src, cfg.paths, result)
    return result


def _source(src: Source, paths: Paths, result: Result) -> None:
    d = sources.skills_dir(src, paths)
    if not d.is_dir():
        return  # sync reports the missing source
    where = sources.work_tree(src, paths)
    if where is None:
        result.notes.append(
            Note(f"not auto-committed: {tilde(d)} isn't in a git repository", src.name, d)
        )
        return
    top, rel = where
    changed = sorted(sources.uncommitted(top, rel))
    if not changed and not (src.autopush and sources.unpushed(top, rel)):
        return
    if why := _busy(top):
        result.notes.append(Note(f"not auto-committed: {tilde(top)} is {why}", src.name, top))
        return
    if changed and not _commit(src, top, rel, changed, result):
        return
    if src.autopush:
        _push(src, top, result)


def _busy(top: Path) -> str | None:
    """Why the repository can't take a commit now, if it can't."""
    r = git.run(top, "rev-parse", "--absolute-git-dir")
    git_dir = Path(r.stdout.strip())
    for name, what in _UNDER_WAY:
        if (git_dir / name).exists():
            return what
    if git.run(top, "symbolic-ref", "--quiet", "HEAD").returncode != 0:
        return "on a detached HEAD"
    if git.run(top, "ls-files", "--unmerged").stdout.strip():
        return "in conflict"
    return None


def _commit(src: Source, top: Path, rel: str, changed: list[str], result: Result) -> bool:
    """Commit the changed skills; whether that worked (or would)."""
    prefix = "" if rel == "." else rel + "/"
    paths = [prefix + name for name in changed]
    text = message(*_kinds(top, rel, changed))
    if result.dry_run:
        result.changes.append(Change("commit", f'"{text}"', src.name, path=top))
        return True
    r = git.run(top, "--literal-pathspecs", "add", "--all", "--", *paths)
    if r.returncode != 0:
        result.problems.append(
            Problem(
                "commit", f"can't stage {', '.join(changed)}: {git.error(r)}", src.name, path=top
            )
        )
        return False
    # Naming the paths commits only them: whatever else is staged stays staged.
    r = git.run(top, "--literal-pathspecs", "commit", "--quiet", "--message", text, "--", *paths)
    if r.returncode != 0:
        result.problems.append(
            Problem(
                "commit",
                f"can't commit {', '.join(changed)}: {git.error(r)}; the edits are left staged",
                src.name,
                path=top,
            )
        )
        return False
    commit = sources.head(top) or ""
    result.changes.append(Change("commit", f'"{text}" ({commit[:12]})', src.name, path=top))
    return True


def _kinds(top: Path, rel: str, changed: list[str]) -> tuple[list[str], list[str], list[str]]:
    """The changed skills that are new, edited and deleted."""
    before = sources.skills_at(top, "HEAD", rel)
    listed = git.run(
        top, "--literal-pathspecs", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
        "--", rel,
    )  # fmt: skip
    deleted = git.run(top, "--literal-pathspecs", "ls-files", "-z", "--deleted", "--", rel)
    files = set(listed.stdout.split("\0")) - set(deleted.stdout.split("\0"))
    after = sources.skills_in(files, rel)  # what the commit will have
    added = [n for n in changed if n not in before and n in after]
    removed = [n for n in changed if n in before and n not in after]
    edited = [n for n in changed if n not in added and n not in removed]
    return added, edited, removed


def message(added: list[str], edited: list[str], removed: list[str]) -> str:
    """`Add foo; update interview, pr-body-md; remove bar`."""
    parts = [
        f"{verb} {', '.join(names)}"
        for verb, names in (("add", added), ("update", edited), ("remove", removed))
        if names
    ]
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


def _push(src: Source, top: Path, result: Result) -> None:
    """Push the current branch, and only it, to its upstream."""
    branch = git.run(top, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    remote = git.run(top, "config", "--get", f"branch.{branch}.remote").stdout.strip()
    merge = git.run(top, "config", "--get", f"branch.{branch}.merge").stdout.strip()
    if not remote or not merge:
        result.problems.append(
            Problem(
                "push",
                f"can't push: {branch} has no upstream branch; `git push -u` sets one",
                src.name,
                path=top,
            )
        )
        return
    upstream = f"{remote}/{merge.removeprefix('refs/heads/')}"
    change = Change("push", f"{branch} to {upstream}", src.name, path=top)
    if result.dry_run:
        result.changes.append(change)
        return
    r = git.run(top, "push", "--quiet", remote, f"HEAD:{merge}")
    if r.returncode == 0:
        result.changes.append(change)
        return
    if "[rejected]" in r.stderr:
        why = f"{upstream} has commits {branch} doesn't; pull, then push by hand"
    else:
        why = git.error(r)
    result.problems.append(Problem("push", f"can't push to {upstream}: {why}", src.name, path=top))

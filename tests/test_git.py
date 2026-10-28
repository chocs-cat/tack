"""Git runs a stop can end (design.md *The TUI*, DEC-29)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import NoReturn

import pytest

from tack import git
from tests.helpers import SlowGit, alive, repo, slow_git

BOUND = 5  # seconds; the stand-in sleeps 30


def _set_later(stop: threading.Event, slow: SlowGit) -> None:
    """Set `stop` from another thread once the slow git has started."""

    def later() -> None:
        slow.wait_for(1)
        stop.set()

    threading.Thread(target=later, daemon=True).start()


def test_a_stop_ends_a_running_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slow = slow_git(tmp_path, monkeypatch, "ls-remote")
    stop = threading.Event()
    _set_later(stop, slow)
    start = time.monotonic()
    with git.stopping(stop), pytest.raises(git.Stopped):
        git.run(None, "ls-remote", "origin")
    assert time.monotonic() - start < BOUND
    [pid] = slow.started()
    assert not alive(pid)


def test_a_stop_ends_a_running_cat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r = repo(tmp_path / "r", {"f": "x"})
    slow = slow_git(tmp_path, monkeypatch, "cat-file")
    stop = threading.Event()
    _set_later(stop, slow)
    start = time.monotonic()
    with git.stopping(stop), pytest.raises(git.Stopped):
        git.cat(r, "HEAD", "f")
    assert time.monotonic() - start < BOUND
    [pid] = slow.started()
    assert not alive(pid)


def test_a_git_ignoring_sigterm_is_killed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slow = slow_git(tmp_path, monkeypatch, "ls-remote", ignore_term=True)
    stop = threading.Event()
    _set_later(stop, slow)
    start = time.monotonic()
    with git.stopping(stop), pytest.raises(git.Stopped):
        git.run(None, "ls-remote", "origin")
    assert time.monotonic() - start < BOUND
    [pid] = slow.started()
    assert not alive(pid)


def test_a_stop_already_set_starts_no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    # A git started and ended at once can be gone before it records itself,
    # so this watches for any process being started at all.
    started: list[object] = []

    def start(*args: object, **kwargs: object) -> NoReturn:
        started.append(args)
        raise AssertionError("started git")

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(subprocess, "run", start)
    stop = threading.Event()
    stop.set()
    with git.stopping(stop), pytest.raises(git.Stopped):
        git.run(None, "ls-remote", "origin")
    with git.stopping(stop), pytest.raises(git.Stopped):
        git.cat(Path(), "HEAD", "f")
    assert started == []


def test_a_stop_ends_only_its_own_threads_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow = slow_git(tmp_path, monkeypatch, "ls-remote")
    stop = threading.Event()
    raised: list[BaseException] = []

    def stopped() -> None:
        try:
            with git.stopping(stop):
                git.run(None, "ls-remote", "origin")
        except git.Stopped as e:
            raised.append(e)

    under = threading.Thread(target=stopped)
    under.start()
    [first] = slow.wait_for(1)
    outside = threading.Thread(target=git.run, args=(None, "ls-remote", "origin"))
    outside.start()
    second = slow.wait_for(2)[1]
    try:
        stop.set()
        under.join(BOUND)
        assert not under.is_alive()
        assert len(raised) == 1
        assert not alive(first)
        time.sleep(0.5)  # longer than the stop's poll: it's still left alone
        assert alive(second)
    finally:
        os.kill(second, signal.SIGKILL)
        outside.join(BOUND)
    assert not outside.is_alive()


def test_outside_a_stop_run_returns_what_git_did(tmp_path: Path) -> None:
    r = git.run(None, "--version")
    assert (r.returncode, r.stderr) == (0, "")
    assert r.stdout.startswith("git version ")
    r = git.run(tmp_path, "rev-parse", "--show-toplevel")
    assert r.returncode == 128
    assert r.stdout == ""
    assert "not a git repository" in r.stderr


def test_under_a_stop_not_set_run_returns_what_git_did(tmp_path: Path) -> None:
    with git.stopping(threading.Event()):
        ok = git.run(None, "--version")
        failed = git.run(tmp_path, "rev-parse", "--show-toplevel")
        found = git.cat(repo(tmp_path / "r", {"f": "x\n"}), "HEAD", "f")
    assert (ok.returncode, ok.stderr) == (0, "")
    assert ok.stdout.startswith("git version ")
    assert (failed.returncode, failed.stdout) == (128, "")
    assert "not a git repository" in failed.stderr
    assert found == git.Object("blob", b"x\n")


@pytest.mark.parametrize("stop", [None, threading.Event()])
def test_a_missing_git_exits_127(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: threading.Event | None
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    if stop is None:
        r = git.run(None, "--version")
    else:
        with git.stopping(stop):
            r = git.run(None, "--version")
    assert r.returncode == 127

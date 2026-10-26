"""The `CI passed` script from `.github/workflows/ci.yml`, run as GitHub runs
it: `bash --noprofile --norc -eo pipefail` (#84)."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
CHECKS = ("LINT", "TEST", "PACKAGE")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _job() -> list[str]:
    """The lines of the job named `CI passed`, from its `name:` line to the
    next job or the end of the file."""
    lines = WORKFLOW.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "name: CI passed"), None)
    assert start is not None, "no job named `CI passed`"
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip() and _indent(lines[i]) <= 2),
        len(lines),
    )
    return lines[start:end]


def _script() -> str:
    """The job's `run: |` block, dedented."""
    job = _job()
    at = next((i for i, line in enumerate(job) if line.strip() == "run: |"), None)
    assert at is not None, "the `CI passed` job has no `run: |` block"
    depth = _indent(job[at])
    block = []
    for line in job[at + 1 :]:
        if line.strip() and _indent(line) <= depth:
            break
        block.append(line)
    script = textwrap.dedent("\n".join(block)).strip()
    assert script
    return script + "\n"


def _run(code: str, **results: str) -> int:
    env = {"PATH": os.environ["PATH"], "CODE": code}
    env |= {name: results.get(name, "success") for name in CHECKS}
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _script()],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    ).returncode


def test_passes_when_every_check_succeeded() -> None:
    assert _run("true") == 0


def test_passes_when_a_docs_only_change_skipped_every_check() -> None:
    assert _run("false", LINT="skipped", TEST="skipped", PACKAGE="skipped") == 0


@pytest.mark.parametrize("check", CHECKS)
@pytest.mark.parametrize("result", ["failure", "cancelled"])
def test_fails_when_a_check_did_not_succeed(check: str, result: str) -> None:
    assert _run("true", **{check: result}) != 0


@pytest.mark.parametrize("check", CHECKS)
@pytest.mark.parametrize("code", ["true", ""])
def test_fails_when_a_check_was_skipped_on_a_code_change(check: str, code: str) -> None:
    """`CODE` is empty when the `changes` job failed: the checks still had to run."""
    assert _run(code, **{check: "skipped"}) != 0


@pytest.mark.parametrize("check", CHECKS)
def test_fails_when_a_check_failed_on_a_docs_only_change(check: str) -> None:
    assert _run("false", **{check: "failure"}) != 0


def test_the_script_reads_the_results_the_workflow_passes() -> None:
    job = _job()
    needs = next(line for line in job if line.strip().startswith("needs:"))
    assert {n.strip() for n in needs.split("[", 1)[1].rstrip("] ").split(",")} == {
        "changes",
        "lint",
        "test",
        "package",
    }
    env = dict(re.findall(r"^\s+([A-Z]+): \$\{\{ (.+?) \}\}$", "\n".join(job), re.M))
    assert env == {
        "CODE": "needs.changes.outputs.code",
        "LINT": "needs.lint.result",
        "TEST": "needs.test.result",
        "PACKAGE": "needs.package.result",
    }

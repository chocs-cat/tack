"""The `CI passed` script from `.github/workflows/ci.yml`, run as GitHub runs
it: `bash --noprofile --norc -eo pipefail` (#84)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
CHECKS = ("lint", "test", "package")


def _jq_dir() -> str | None:
    """The first PATH directory whose jq runs without a home: a version
    manager's shim needs the real one, which no test may hand it."""
    for directory in os.environ["PATH"].split(os.pathsep):
        jq = shutil.which("jq", path=directory)
        if jq and subprocess.run([jq, "--version"], env={}, capture_output=True).returncode == 0:
            return directory
    return None


JQ_DIR = _jq_dir()

# GitHub's runners have jq, so CI can't skip these; there a missing jq fails.
pytestmark = pytest.mark.skipif(
    JQ_DIR is None and "CI" not in os.environ, reason="the gate's script needs jq"
)


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


def _run(code: str | None, **results: str) -> int:
    """The script's exit status for `needs` holding these results, the rest
    successes. `code` is the `changes` job's output, None when that job failed
    and left none. Only a quiet 0 or 1 is jq's verdict: anything else is the
    script breaking, which must not count as the gate failing as it should."""
    outputs = {} if code is None else {"code": code}
    needs = {"changes": {"result": "success", "outputs": outputs}}
    needs |= {name: {"result": results.get(name, "success"), "outputs": {}} for name in CHECKS}
    done = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _script()],
        env={"PATH": f"{JQ_DIR}{os.pathsep}{os.environ['PATH']}", "NEEDS": json.dumps(needs)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert not done.stderr
    assert done.returncode in (0, 1)
    return done.returncode


def test_passes_when_every_check_succeeded() -> None:
    assert _run("true") == 0


def test_passes_when_a_docs_only_change_skipped_every_check() -> None:
    assert _run("false", lint="skipped", test="skipped", package="skipped") == 0


@pytest.mark.parametrize("check", CHECKS)
@pytest.mark.parametrize("result", ["failure", "cancelled"])
def test_fails_when_a_check_did_not_succeed(check: str, result: str) -> None:
    assert _run("true", **{check: result}) != 0


@pytest.mark.parametrize("check", CHECKS)
@pytest.mark.parametrize("code", ["true", None])
def test_fails_when_a_check_was_skipped_on_a_code_change(check: str, code: str | None) -> None:
    """`changes` has no output when it failed: the checks still had to run."""
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
    assert env == {"NEEDS": "toJSON(needs)"}

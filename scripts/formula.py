# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=24"]
# ///
"""Write tack's Homebrew formula for a version published on PyPI.

    uv run scripts/formula.py 0.1.0 > Formula/tack.rb

The formula builds from the PyPI sdist, with a `resource` for each dependency:
`tack-agents==VERSION` is resolved for every platform (`uv pip compile
--universal`) for the formula's Python, and each pin's sdist URL and hash come
from PyPI. A dependency whose markers hold on neither macOS nor Linux is left
out. The release workflow runs this after publishing; `--wait` retries while
PyPI doesn't have the version yet.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PACKAGE = "tack-agents"
PYTHON = "3.14"  # Homebrew's newest; the formula depends on python@PYTHON
PYPI = "https://pypi.org/pypi"

TEMPLATE = """\
class Tack < Formula
  include Language::Python::Virtualenv

  desc "Deploy agent skills to Claude Code and Codex from one manifest"
  homepage "https://github.com/chocs-cat/tack"
  url "{url}"
  sha256 "{sha256}"
  license "MIT"

  depends_on "python@{python}"
{resources}
  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "tack #{{version}}", shell_output("#{{bin}}/tack --version")
    ENV["TACK_CONFIG"] = testpath/"config"
    assert_match '"findings"', shell_output("#{{bin}}/tack doctor --json --global-only")
  end
end
"""

RESOURCE = """
  resource "{name}" do
    url "{url}"
    sha256 "{sha256}"
  end
"""


@dataclass(frozen=True)
class Sdist:
    name: str
    url: str
    sha256: str


def render(package: Sdist, resources: list[Sdist], python: str = PYTHON) -> str:
    """The formula's text; resources in the alphabetical order brew audit wants."""
    blocks = "".join(
        RESOURCE.format(name=r.name, url=r.url, sha256=r.sha256)
        for r in sorted(resources, key=lambda r: r.name)
    )
    return TEMPLATE.format(url=package.url, sha256=package.sha256, python=python, resources=blocks)


def sdist(name: str, version: str, *, wait: float = 0) -> Sdist:
    """A release's sdist on PyPI, retrying for up to `wait` seconds."""
    deadline = time.monotonic() + wait
    while True:
        try:
            with urllib.request.urlopen(f"{PYPI}/{name}/{version}/json", timeout=30) as r:
                release = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code != 404 or time.monotonic() >= deadline:
                raise SystemExit(f"formula.py: {name} {version} isn't on PyPI ({e.code})") from e
            time.sleep(10)
    for f in release["urls"]:
        if f["packagetype"] == "sdist":
            return Sdist(canonicalize_name(name), f["url"], f["digests"]["sha256"])
    raise SystemExit(f"formula.py: {name} {version} has no sdist on PyPI")


def pins(version: str, python: str) -> list[Requirement]:
    """tack's dependencies at `version`, resolved for every platform."""
    r = subprocess.run(
        ["uv", "pip", "compile", "--universal", "--python-version", python,
         "--no-header", "--no-annotate", "--quiet", "-"],
        input=f"{PACKAGE}=={version}\n", capture_output=True, text=True, check=False,
    )  # fmt: skip
    if r.returncode != 0:
        raise SystemExit(f"formula.py: can't resolve {PACKAGE}=={version}:\n{r.stderr}")
    return [Requirement(line) for line in r.stdout.splitlines() if line.strip()]


def needed(req: Requirement, python: str) -> bool:
    """Whether a pin applies on macOS or Linux under the formula's Python."""
    if req.marker is None:
        return True
    return any(
        Marker(str(req.marker)).evaluate(
            {
                "sys_platform": platform,
                "platform_system": system,
                "python_version": python,
                "python_full_version": f"{python}.0",
            }
        )
        for platform, system in (("darwin", "Darwin"), ("linux", "Linux"))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write tack's Homebrew formula.")
    parser.add_argument("version", help="a version of tack-agents published on PyPI")
    parser.add_argument("--python", default=PYTHON, help=f"the formula's Python (default {PYTHON})")
    parser.add_argument("--wait", type=float, default=0, help="seconds to wait for PyPI")
    args = parser.parse_args(argv)

    package = sdist(PACKAGE, args.version, wait=args.wait)
    resources = []
    for req in pins(args.version, args.python):
        if canonicalize_name(req.name) == PACKAGE or not needed(req, args.python):
            continue
        (spec,) = req.specifier
        resources.append(sdist(req.name, spec.version))
    sys.stdout.write(render(package, resources, args.python))
    return 0


if __name__ == "__main__":
    sys.exit(main())

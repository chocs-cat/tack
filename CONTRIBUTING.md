# Contributing

tack is developed with [uv](https://docs.astral.sh/uv/). `uv run tack …`
runs the checkout; the checks, all of which must pass:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

[docs/design.md](docs/design.md) is the spec: change it first when a decision
changes.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/). The
version and the changelog are generated from them:

- `feat: …` → minor bump
- `fix: …` and `perf: …` → patch bump
- `feat!: …` or a `BREAKING CHANGE:` footer → major bump (minor while below 1.0)
- `docs:`, `refactor:`, `test:`, `ci:`, `build:`, `chore:` → no release on
  their own, and not listed in the changelog

Pull request titles are checked for this format in CI, because a squash merge
makes the title the commit release-please reads.

## Releasing

Releases are automated with
[release-please](https://github.com/googleapis/release-please):

1. Merge Conventional Commits to `master`.
2. release-please opens or updates a **release pull request** that bumps the
   version (in `pyproject.toml`, `src/tack/__init__.py` and `uv.lock`) and
   adds a section to `CHANGELOG.md`.
3. Merging it tags `vX.Y.Z` and creates the GitHub release. The `publish` job
   then builds the package and uploads it to PyPI, and the `formula` workflow
   writes the Homebrew formula, pushes it to
   [chocs-cat/homebrew-tap](https://github.com/chocs-cat/homebrew-tap), and
   installs it from there on macOS to check it.

Don't edit versions or `CHANGELOG.md` by hand. To force a version, add a
`Release-As: X.Y.Z` footer to a commit. Never move or delete a pushed release
tag; fix a bad release forward. To redo a version's formula, run the
**Formula** workflow by hand with that version, or locally:
`uv run --script scripts/formula.py X.Y.Z > tack.rb`.

### One-time setup

- **PyPI trusted publishing:** on pypi.org, add a pending publisher for
  project `tack-agents`: owner `chocs-cat`, repository `tack`, workflow
  `release.yml`, environment `pypi`.
- **GitHub environment:** an environment named `pypi` in the repository
  settings. Optionally require approval there.
- **Actions permissions:** in the repository's (and the organization's)
  Settings → Actions → General, allow GitHub Actions to create pull requests.
- **Homebrew tap:** a `TAP_TOKEN` secret, a fine-grained personal access token
  for `chocs-cat/homebrew-tap` only, with **Contents** read/write.
- **CI on release pull requests (optional):** a pull request opened with the
  built-in `GITHUB_TOKEN` waits for a maintainer to approve its CI run. The
  release workflow uses a `RELEASE_PLEASE_TOKEN` secret instead when it
  exists: a fine-grained token for this repository only, with **Contents** and
  **Pull requests** read/write. Renew it before it expires.

# Working on tack

Instructions for coding agents. Claude Code reads this through `CLAUDE.md`'s
`@AGENTS.md` import.

[docs/design.md](docs/design.md) is the spec and the source of truth: read it
before any change, and change it first when a decision changes. tack was
built in ten phases, all done; new features are planned as projects through
the [relay workflow](#relay-workflow). Don't write implementation code for a
project until the maintainer has approved its design and it is active.

Checks, all of which must pass: `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run ty check`. Tests build everything in a
temporary directory with a scratch `HOME` (see `tests/conftest.py`); never
let one touch the real home directory.

tack is meant to be publishable: nothing in it may assume the maintainer's
setup (a dotfiles tool, a home-directory path, a particular agent beyond the
built-in harness defaults).

## Roadmap: GitHub Issues

Ideas, bugs, and follow-ups are issues on `chocs-cat/tack`. The design and
delivery plan for anything bigger than one chunk live in a project file under
`docs/projects/`, and each chunk in its brief; both link the issues they come
from. Check the issue list (`gh issue list`) before starting work, and keep it
current:

- **File ideas as issues, don't just mention them.** When you or the user
  come up with a feature, a follow-up, a bug, or a loose end you won't handle
  now, create an issue without asking first. Unplanned thoughts get the
  `idea` label; add an area label (`cli`, `tui`, `doctor`, `sources`,
  `config`, `release`, `documentation`) and a type label (`bug`,
  `enhancement`, `question`) where one fits.
- **The repo is public, and so are its issues.** Write them for any reader:
  no private paths, hostnames, or personal details.
- Before starting work, look for an existing issue and reference it. Close
  issues from the pull request that resolves them (`Fixes #12` in its body).
- Comment on an issue when you learn something that matters to whoever picks
  it up next.

## Releases

Releases are automated with release-please, from Conventional Commits;
[CONTRIBUTING.md](CONTRIBUTING.md) has the process and the one-time setup.

- **Conventional Commits** for pull request titles (CI checks them): a squash
  merge makes the title the commit release-please reads. Unit commits on a
  chunk branch keep their relay titles (`P0002-C03-a: …`) and never reach
  `master` on their own. The types: `feat:`, `fix:`, `perf:`, `docs:`,
  `refactor:`, `test:`, `ci:`, `build:`, `chore:`, with a scope where useful
  (`fix(tui): …`). The type decides the version bump and the changelog entry,
  so choose it for the user-visible effect: `feat` → minor, `fix` and `perf`
  → patch, `feat!` or a `BREAKING CHANGE:` footer → major (minor while below
  1.0). The other types release nothing on their own.
- Don't edit versions or `CHANGELOG.md`; release-please owns them. It keeps a
  release pull request open, and merging it tags `vX.Y.Z`, creates the GitHub
  release, publishes to PyPI and updates the Homebrew tap. That merge is the
  maintainer's call.
- To force a version, add a `Release-As: X.Y.Z` footer to a commit. Never move
  or delete a pushed release tag. A bad release is fixed forward.

## Relay workflow

Work in this repository is built by fresh agent sessions that hand it to one
another through the files below, using the relay skills:

- `/relay-project` shapes an idea into settled design and an ordered delivery
  plan, and closes the project when its work is accepted.
- `/relay-next` reviews the chunk in flight, records the review, merges
  accepted work, and cuts the next chunk brief.
- `/relay-execute` builds the chunk in flight unit by unit on its own branch
  and draft pull request, then hands it back for review.
- `/relay-release` cuts a version by reviewing and merging release-please's
  release pull request.

Code reaches `master` only through a chunk pull request, so every change gets
the executor's test discipline and a CI run; planning changes arrive through
`plan/<slug>` pull requests. The status file is the handoff between sessions:
run each skill in a fresh session.

When code and an authority doc disagree, one of them is wrong: fix it and say
which. A decided entry in the decision log is not re-litigated; where the docs
genuinely do not cover something, add an entry, update the doc that should have
said it, and cite the entry at the code site.

### Settings

- **Integration branch:** `master`. Chunk and planning pull requests
  squash-merge here.
- **Release branch:** same as the integration branch.
- **Gate:** `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check`,
  which runs the tests, the linter, the format check and the type checker. It
  passes before every unit commit and push. CI runs these same targets.
- **CI:** `.github/workflows/ci.yml` runs the gate on pull requests, including
  drafts, on Linux and macOS across Python 3.11–3.14, and smoke-tests the
  built wheel and sdist; pushes to `master` run it too. `pr-title.yml` checks
  that the pull request title is a Conventional Commit. Branch protection on
  `master` requires both (`CI passed`, `conventional commit title`).
- **Releases:** release-please, as *Releases* describes: a chunk pull
  request's title is a Conventional Commit for the chunk's user-visible
  effect, and nobody edits the changelog by hand. Unit commits on a chunk
  branch keep their relay titles; only the squash commit reaches `master`.
- **Issues:** GitHub Issues, as *Roadmap* describes: review follow-ups and
  ideas are filed as issues, a project or maintenance chunk may start from
  one, and the pull request that finishes it closes it.
- **Authority:** `docs/design.md`, the spec; its contents list gives the
  reading order. `README.md` and `skills/tack/SKILL.md` describe what it
  specifies and follow it.
- **Status:** `docs/status.md`
- **Chunks:** `docs/chunks/<ID>.md`
- **Decision log:** `docs/decisions.md`, entries cited as `(DEC-n)`
- **Review checklist:** `docs/review-checklist.md`
- **Brief checklist:** `docs/brief-checklist.md`
- **Projects:** `docs/projects/` (`index.md`, `template.md`, one
  `P####-slug.md` per project)
- **Tools:** `tools/`, review aids run by hand, outside the gate and the build
- **Review extras:**
  - No test reaches the real home directory: everything builds under the
    temporary directory and scratch `HOME` of `tests/conftest.py`.
  - Nothing assumes the maintainer's setup: no dotfiles tool, home-directory
    path, or agent beyond the built-in harness defaults.
  - A change to a command, flag, `--json` shape, or manifest field updates
    `README.md` and `skills/tack/SKILL.md` in the same chunk.
  - A new or changed assumption about how Claude Code or Codex behaves is
    recorded in design.md's *Harness facts tack relies on*, with the versions
    it was verified against.
- **Environment:** none; `uv run` syncs the environment from `uv.lock`.

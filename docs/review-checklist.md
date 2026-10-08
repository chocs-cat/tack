# The review checklist

Every class of bug a review has missed at least once, kept so the next review
looks for it by default. Each entry is a *shape*, not a rule: the authority
docs remain the authority on what the code must do. This file only records
where a passing test suite has failed to catch a real defect.

**How it is used.** `/relay-next` takes the whole chunk diff through every
entry here, after the per-unit checks against the cited doc sections. A finding
that matches an entry cites it as `review-checklist §N`. `/relay-execute` does
not work the whole list; instead the chunk brief's *Kickoff notes* name the
entries a given chunk is most likely to trip, and the executor reads those
before building.

**How it grows.** When a review finds a *class* of bug rather than an
instance, `/relay-next` adds it here as the next numbered entry, with the
finding that revealed it. The provenance is the point: it is the evidence that
the shape is real. Entries are not renumbered or retired: a shape that has
stopped mattering is cheaper to skim than to re-derive after it bites again.

---

## The catalogue

### §1 A test that holds because the test harness already provides the property

A test asserts a property of how the code runs a process or touches the
environment (stdin closed, a working directory, a variable unset, a program
not on PATH), but the test runner or CI already gives the process that
property, so the test passes with the code's own guarantee removed. Look for
it wherever a test checks something the code *does to its environment*: make
the environment hostile first (hold a pipe open on fd 0, start in another
directory, set the variable, put the program on PATH), or the assertion
checks pytest rather than tack. A mutation that deletes the guarantee is the
quick proof.

*Provenance:* P0001-C01-c. The tests that `agents.run` closes the agents'
stdin passed with `stdin=subprocess.DEVNULL` removed, because fd 0 under
pytest is already `/dev/null`; the executor's mutation check caught it, and
`13c2ca4` made the tests hold a pipe open on fd 0.

### §2 A list of paths parsed from git's output line by line

The code reads file names from `git log --name-only`, `git diff
--name-only`, `git status` or `git ls-files` split on newlines. Without
`-z`, git C-quotes a path holding a double quote, a backslash, a tab, a
newline or another control character (`core.quotePath=false` only stops
the escaping of non-ASCII bytes), so the line starts with `"` and matches
no prefix, and the file silently counts for nothing. Test fixtures use
plain names, so every test passes. Look for any git command whose output
is split into paths without `-z`, and for a test with a name git quotes.
The same commands list a rename as its new path only unless
`--no-renames` is given, which drops the old one the same silent way.

*Provenance:* P0001-C07 review. `outdated._Tracked.commits` parsed `git log
--name-only` without `-z`, so a commit whose only change under a plugin was
to `x"y.md` wasn't listed, though the plugin read *modified* (its diff used
`-z`). The sweep found the same parse in `outdated`'s skills log and
`sources.unpushed` (#47), and #46 is the rename half for skills; both
scheduled as P0001-C08-a.

### §3 A test snapshots a tree holding a repository it just committed to

A test runs git inside a directory it then compares before and after (a
`tree(home)` snapshot, a listing of tack's data directory), and git's
automatic maintenance, which a commit or a fetch (tack's own included)
starts in the background, adds or removes a lock file under that
repository's `.git` between the two snapshots. The test passes locally and fails now and then on CI, with a
`.git` path as the only difference, though nothing tack did changed. Look
for any snapshot taken over a repository a test created; the fix belongs
where the suite configures git (`tests/conftest.py`'s scratch config), not
in each test.

*Provenance:* P0001-C09-a. `test_a_git_dry_run_ignores_a_leftover_checkout`
committed a leftover checkout under the scratch home and snapshotted it;
macOS CI failed on three heads with `objects/maintenance.lock` in the
difference, and the branch carried on red. `42be0cb` turned maintenance
off for that one test. The sweep: every `tree(home)` snapshot in the
suite (`test_edit`, `test_sync`, `test_sync_plugins`, `test_status`,
`test_update`, `test_plugin_plan`) can follow a commit or a fetch under the
scratch home; the scratch config's fix, scheduled as P0001-C10-a, covers
them all.

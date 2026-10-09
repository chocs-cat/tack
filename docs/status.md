# Status

Last updated 2026-10-09 by `relay-next`.
Last review: 2026-10-09 (P0001-C11).

## Where this stands

- The relay workflow was set up on 2026-10-05. Design phases 1–10 are done.
- Project [P0001](projects/P0001-plugins.md), plugins for Claude Code and
  Codex ([#22](https://github.com/chocs-cat/tack/issues/22)), is active:
  its design is in design.md (marked *(P0001)*) and DEC-1 – DEC-23.
- D1–D7 are done: P0001-C01 – C09 (#28, #30, #32, #34, #37, #41, #45,
  #48, #50), accepted 2026-10-05 to 2026-10-08. `sync` deploys the
  manifest's `plugins`, `status` shows each one's state per harness,
  `doctor` audits them and reports every plugin problem `sync` would
  (DEC-18, DEC-19), `outdated` reports changed plugins with their versions,
  commits and diff (DEC-20), `add --plugin` (and the TUI's add form)
  selects plugins, and the TUI has a Plugins tab (tabs keyed `1`–`4`).
- P0001-C10 (#53), accepted 2026-10-08: plugins' clones kept as checkouts
  are (DEC-21), unwired, and `remove` deleting them; #29's catalog URL
  fixes; #51.
- P0001-C11 (#55), accepted 2026-10-09: #54 (DEC-22), and plugins from
  other repositories cloned at the catalog's commit and deployed by `sync`,
  with `status`, `doctor`, the TUI and `add` agreeing; #56 its follow-up.
- P0001-C12, ready for an executor: the rest of D8, pinned at its cut
  (DEC-23): `status --json` and the TUI naming a plugin's repository,
  commit and clone, and `outdated --diff` between its commits.
- Still to come: the project's completion, run against the real agents
  (#42 among them), and design.md's *(P0001)* marks removed.
- **Do next:** `/relay-execute` to build P0001-C12.

## In flight

- **Chunk:** P0001-C12
- **State:** ready for an executor
- **Branch:** —
- **Pull request:** —
- **Units committed:** —

(Fixed shape. `State` ∈ `ready for an executor` · `executing` ·
`awaiting review` · `none`; `Branch`, `Pull request`, and `Units committed` are
`—` until set; the pull request carries `(draft)` or `(ready)`.
`/relay-execute` creates `chunk/<id>` from the integration branch, opens a
draft pull request, sets `executing`, updates `Units committed` per unit, and
sets `awaiting review` when its report lands; `/relay-next` reviews that pull
request on its branch, cuts the next chunk, and squash-merges. While a chunk
pull request is open, the copy of this file on its head branch is the
authoritative handoff.)

## Follow-ups not yet scheduled

Follow-ups are filed as GitHub issues (see *Roadmap* in AGENTS.md), not kept
here.

## Decisions by chunk

One line per chunk: the decision-log IDs it added.

- P0001-C01: DEC-9; its review, DEC-10.
- P0001-C02: none; its review, DEC-11 – DEC-12.
- P0001-C03: DEC-13; its review, none (DEC-12 clarified).
- P0001-C04: DEC-14; its review, none.
- P0001-C05: its cut, DEC-15 – DEC-16; its review, DEC-17.
- P0001-C06: its cut, DEC-18; its review, DEC-19.
- P0001-C07: its cut, DEC-20; its review, none.
- P0001-C08: its cut, none; its review, none.
- P0001-C09: its cut, none; its review, none.
- P0001-C10: its cut, DEC-21; its review, none.
- P0001-C11: its cut, DEC-22; its review, none.
- P0001-C12: its cut, DEC-23.

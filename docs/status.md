# Status

Last updated 2026-10-08 by `relay-next`.
Last review: 2026-10-08 (P0001-C08).

## Where this stands

- The relay workflow was set up on 2026-10-05. Design phases 1–10 are done.
- Project [P0001](projects/P0001-plugins.md), plugins for Claude Code and
  Codex ([#22](https://github.com/chocs-cat/tack/issues/22)), is active:
  its design is in design.md (marked *(P0001)*) and DEC-1 – DEC-20.
- D1–D6 are done: P0001-C01 – C08 (#28, #30, #32, #34, #37, #41, #45,
  #48), accepted 2026-10-05 to 2026-10-08. `sync` deploys the manifest's
  `plugins`, `status` shows each one's state per harness, `doctor` audits
  them and reports every plugin problem `sync` would (DEC-18, DEC-19),
  `outdated` reports changed plugins with their versions, commits and diff
  (DEC-20), and `add --plugin` (and the TUI's add form) selects plugins,
  refusing what `sync` couldn't deploy. The TUI doesn't show plugins yet.
- P0001-C09, ready for an executor: D7, the TUI's Plugins tab (pinned in
  *The TUI* at the cut), and #49, #43 (`add`'s git dry run; `doctor`'s
  message for a root that is a file).
- Still to come: D8, then the project's completion runs against the real
  agents (#42 among them).
- **Do next:** `/relay-execute` to build P0001-C09.

## In flight

- **Chunk:** P0001-C09
- **State:** executing
- **Branch:** `chunk/p0001-c09`
- **Pull request:** pending
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
- P0001-C09: its cut, none.

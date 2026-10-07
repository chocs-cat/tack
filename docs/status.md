# Status

Last updated 2026-10-07 by `relay-next`.
Last review: 2026-10-07 (P0001-C04).

## Where this stands

- The relay workflow was set up on 2026-10-05. Design phases 1–10 are done.
- Project [P0001](projects/P0001-plugins.md), plugins for Claude Code and
  Codex ([#22](https://github.com/chocs-cat/tack/issues/22)), is active:
  its design is in design.md (marked *(P0001)*) and DEC-1 – DEC-16.
- D1 (catalogs and plugin selection) and D2 (`sync` deploys plugins) are
  done: P0001-C01 – C04 (#28, #30, #32, #34), accepted 2026-10-05 to
  2026-10-07. The manifest takes `plugins`; `status`, `doctor`, the TUI and
  `outdated` don't show plugins yet.
- P0001-C05, ready for an executor: D3, `status` reports each selected
  plugin's state (DEC-15, DEC-16 pinned at the cut), and #35, the README's
  and the agent skill's manifest examples tested.
- Still to come: D4–D8.
- **Do next:** `/relay-execute` to build P0001-C05.

## In flight

- **Chunk:** P0001-C05
- **State:** awaiting review
- **Branch:** `chunk/p0001-c05`
- **Pull request:** `#37` (ready)
- **Units committed:** a, b, c

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
- P0001-C05: its cut, DEC-15 – DEC-16.

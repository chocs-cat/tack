# Status

Last updated 2026-10-05 by `relay-next`.
Last review: none yet.

## Where this stands

- The relay workflow was set up on 2026-10-05. Design phases 1–10 are done.
- Project [P0001](projects/P0001-plugins.md), plugins for Claude Code and
  Codex ([#22](https://github.com/chocs-cat/tack/issues/22)), is active:
  its design is in design.md (marked *(P0001)*) and DEC-1 – DEC-8.
- P0001-C01, in flight: catalogs, tack's marketplace and the agents' CLIs,
  with stand-in CLIs for tests; groundwork for D1 and D2, not wired in.
  Still to come in D1–D2: the `plugins` field and the plan, and `sync`
  deploying them (the field is accepted only with `sync`).
- **Do next:** `/relay-execute` to build P0001-C01.

## In flight

- **Chunk:** P0001-C01
- **State:** executing
- **Branch:** `chunk/p0001-c01`
- **Pull request:** `#28` (draft)
- **Units committed:** a, b

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

None yet. One line per chunk: the decision-log IDs it added.

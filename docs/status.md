# Status

Last updated 2026-10-05 by `relay-next`.
Last review: 2026-10-05 (P0001-C01).

## Where this stands

- The relay workflow was set up on 2026-10-05. Design phases 1–10 are done.
- Project [P0001](projects/P0001-plugins.md), plugins for Claude Code and
  Codex ([#22](https://github.com/chocs-cat/tack/issues/22)), is active:
  its design is in design.md (marked *(P0001)*) and DEC-1 – DEC-10.
- P0001-C01, accepted with follow-ups 2026-10-05 (#28): catalogs, tack's
  marketplace and the agents' CLIs, with stand-in CLIs for tests; not wired
  in.
- P0001-C02, ready: the `plugins` field's parser (not wired in) and the
  plan, and a stricter Codex stand-in.
- Still to come in D1–D2: accepting `plugins` and `skills = []`, and `sync`
  deploying plugins (the field is accepted only with `sync`).
- **Do next:** `/relay-execute` to build P0001-C02.

## In flight

- **Chunk:** P0001-C02
- **State:** awaiting review
- **Branch:** `chunk/p0001-c02`
- **Pull request:** `#30` (ready)
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

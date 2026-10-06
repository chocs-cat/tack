# Status

Last updated 2026-10-06 by `relay-execute`.
Last review: 2026-10-06 (P0001-C03).

## Where this stands

- The relay workflow was set up on 2026-10-05. Design phases 1–10 are done.
- Project [P0001](projects/P0001-plugins.md), plugins for Claude Code and
  Codex ([#22](https://github.com/chocs-cat/tack/issues/22)), is active:
  its design is in design.md (marked *(P0001)*) and DEC-1 – DEC-13.
- P0001-C01, accepted with follow-ups 2026-10-05 (#28): catalogs, tack's
  marketplace and the agents' CLIs, with stand-in CLIs for tests; not wired
  in.
- P0001-C02, accepted with follow-ups 2026-10-05 (#30): the `plugins`
  field's parser (not wired in) and the plan; plugin names now collide
  across harnesses (DEC-11, fixed in C03-a).
- P0001-C03, accepted with follow-ups 2026-10-06 (#32): `sync` runs the
  plugin steps and records installs in `state.json`, still unreachable
  from the manifest; DEC-13 (Claude Code stays registered while a kept
  plugin is installed). #33 is fixed in C04-a.
- P0001-C04, awaiting review (#34): tack's marketplace kept up to date
  while it exists (#33), held sources keeping their plugins (DEC-12),
  `skills = []` needing no skills directory, and the manifest taking
  `plugins`, with CLI coverage and docs. DEC-14 covers Codex recovery.
- D1–D2 are built, pending C04's acceptance. Still to come: D3–D8.
- **Do next:** `/relay-next` to review P0001-C04.

## In flight

- **Chunk:** P0001-C04
- **State:** awaiting review
- **Branch:** `chunk/p0001-c04`
- **Pull request:** `#34` (ready)
- **Units committed:** a, b, c, d

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
- P0001-C04: DEC-14.

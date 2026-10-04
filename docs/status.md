# Status

Last updated 2026-10-05 by `relay-setup`.
Last review: none yet.

## Where this stands

- The relay workflow was set up on 2026-10-05. Design phases 1–10 are done;
  no project is active and no chunk is in flight.
- **Do next:** `/relay-project` to shape the first project, plugin support
  for Claude Code and Codex
  ([#22](https://github.com/chocs-cat/tack/issues/22)), or `/relay-next`
  with a request for a small, already-designed fix.

## In flight

- **Chunk:** —
- **State:** none
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

None yet. One line per chunk: the decision-log IDs it added.

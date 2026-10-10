---
name: instructions-setup
description: Set up, or reorganize, a project's agent instructions so every coding agent reads the same ones. Makes AGENTS.md the one instructions file (what the project is, its commands, workflow, conventions and rules), with a CLAUDE.md that imports it, project skills in .agents/skills behind a .claude/skills symlink, a git-ignored CLAUDE.local.md for one machine's notes, and a decision log (docs/decisions.md). Folds .cursorrules, Copilot and Gemini instructions into AGENTS.md, and applies the layout with `tack scaffold` and checks it with `tack doctor` when tack is installed. Use when a project has no AGENTS.md or its instructions are scattered or duplicated, and whenever the user asks to "set up instructions", "write an AGENTS.md", "set up CLAUDE.md", "merge CLAUDE.md into AGENTS.md", "add a decision log", or tidy a project's agent setup.
---

# Set up a project's agent instructions

AGENTS.md is a project's one real instructions file, written for any agent.
CLAUDE.md holds `@AGENTS.md` plus any lines only Claude Code needs, so shared
guidance never lives there. Instructions load into every session, so every line
has to earn its place: write what an agent could not infer from the code and
would get wrong without being told, and leave out what the README, the code,
or a linter already says.

This skill writes the content. The layout around it (AGENTS.md beside a
CLAUDE.md that imports it, `.agents/skills` behind a `.claude/skills` link) is
what `tack doctor` audits, so when `tack` is on `PATH` (`command -v tack`) the
skill applies the layout with `tack scaffold` and checks it with `tack doctor`
rather than making the moves itself.

Release systems, an issue tracker's labels, CI, and other repository
conventions are not instructions and are out of this skill's scope. Where the
project already has one, AGENTS.md says what an agent must do about it (and
links to where it is documented); it sets none up.

## 0. Orient

Read every instruction file the project has: AGENTS.md (including nested
ones), CLAUDE.md, CLAUDE.local.md, `.cursorrules` or `.cursor/rules/`,
`.github/copilot-instructions.md`, GEMINI.md. Read the README,
CONTRIBUTING.md, and any docs index. Then detect:

- **Toolchains and commands:** the setup, build, test, lint, format, and type
  check commands, and whether one command runs all the checks (a Makefile
  `check` target, a `package.json` script, a `justfile` recipe).
- **CI:** the workflows under `.github/workflows/` (or the CI system's
  config), and what they run.
- **Branches and history:** the default branch, whether the project has a
  remote (`git remote -v`), and the commit style in `git log --oneline -30`.
- **Skills and local notes:** project skills in `.agents/skills/`,
  `.claude/skills/` or `.codex/skills/`, and whether `CLAUDE.local.md` is
  ignored (`git check-ignore -q CLAUDE.local.md`).
- **Decisions:** a decision log, ADRs, or settled questions recorded anywhere.

With tack installed, its audit lists what the layout lacks:

```sh
tack doctor --projects-only .
```

If instructions already exist, this is a reorganization. Keep every rule, move
each where it belongs, and show the user what moved. Never drop a rule
silently; if one looks obsolete, ask.

## 1. Interview

Ask what detection cannot settle, with the harness's structured question tool,
leading each question with the detected or conventional answer as the
recommendation. One round usually covers it:

- What the project is and who it is for, if the README does not say.
- The check command to run before every push, and whether CI runs the same.
- Rules every agent must follow here: things never to do, docs to keep in step
  with behavior, where behavior belongs.
- For a reorganization: whether other agents' instruction files are removed
  once folded in, or kept as a one-line pointer to AGENTS.md.

## 2. Lay out the files

Unless the project has no remote, or the user wants the change committed
directly, start a branch for it first (`git switch -c agent-instructions`).

**With tack.** Apply each fix as a dry run first and show the user the diff,
then apply it:

```sh
tack scaffold agents-md . --dry-run
tack scaffold agents-md .
tack scaffold skills-dir . --dry-run
tack scaffold skills-dir .
```

`agents-md` moves a lone CLAUDE.md to AGENTS.md (through `git mv`, so its
history follows), or, when both exist, puts `@AGENTS.md` at the top of
CLAUDE.md and removes the paragraphs AGENTS.md already has; it lists the lines
that name one agent, for you to review. `skills-dir` moves the skills in
`.claude/skills` and `.codex/skills` into `.agents/skills` and makes
`.claude/skills` a relative link to it. Each fix says so and changes nothing
when there is nothing to fix. When one refuses (exit `1`, with what to
reconcile by hand), reconcile that with the user and run it again. `scaffold`
stages what it changes and never commits, so its change joins this skill's
own commit.

**Without tack**, make the same moves by hand:

- Only a CLAUDE.md: `git mv CLAUDE.md AGENTS.md`, then write CLAUDE.md as
  `@AGENTS.md`.
- Both: put `@AGENTS.md` on CLAUDE.md's first line and move everything shared
  into AGENTS.md (§3), leaving in CLAUDE.md only what is for Claude Code
  alone.
- An `@AGENTS.md` line in CLAUDE.local.md is redundant once CLAUDE.md has one:
  remove it.
- Skills: move each entry of `.claude/skills/` and `.codex/skills/` into
  `.agents/skills/` (with `git mv`), drop an entry `.agents/skills` already
  has an identical copy of, and stop to reconcile one that differs. Then
  remove `.codex/skills`, which Codex doesn't read, and link the Claude Code
  directory:

```sh
ln -s ../.agents/skills .claude/skills
```

A project that has no instruction file yet gets its layout in §3, from the
templates.

## 3. Write the instruction files

1. **AGENTS.md.** Fill `templates/AGENTS.md` (or rewrite the AGENTS.md §2
   produced), dropping every section and alternative that does not apply. Add
   *Conventions*, *Testing notes*, and *Rules* sections only when there is
   something real to say, and give each rule its reason: a rule with a reason
   gets followed in cases it did not foresee. Link to docs rather than copying
   them, and point humans to CONTRIBUTING.md rather than duplicating it. Aim
   for a file an agent reads in a minute. In a monorepo, put package-specific
   rules in a nested AGENTS.md in that package.
2. **CLAUDE.md** contains `@AGENTS.md` (`templates/CLAUDE.md`), plus any lines
   only Claude Code needs (its hooks, its tool quirks). Move shared guidance
   left in an existing CLAUDE.md into AGENTS.md. Codex doesn't follow imports,
   so AGENTS.md itself never imports another file for content an agent needs.
3. **Other agents' files.** Fold `.cursorrules`, `.cursor/rules/`, Copilot,
   and Gemini instructions into AGENTS.md, and replace each with a pointer to
   it or remove it, as the user chose.
4. **Project skills.** If the project wants skills and has none yet, create
   `.agents/skills/` and the `.claude/skills` link as §2 shows; a new skill
   goes in `.agents/skills/<name>/SKILL.md`.
5. **CLAUDE.local.md.** Offer one from `templates/CLAUDE.local.md` for notes
   specific to one machine or maintainer (local install paths, tools
   installed by hand, chores done by hand). Make sure it is git-ignored: if
   `git check-ignore` says it is not, add it to `.gitignore`.
6. **Decision log.** Create `docs/decisions.md` from `templates/decisions.md`
   unless the project has one. An existing log whose entries have no IDs gets
   them once (`DEC-1`, `DEC-2`, … in file order), so docs and code can cite
   them; say so in the summary. Move settled questions found in other
   instruction files into it.

## 4. Check and land it

With tack installed, audit the result; the instruction and skills findings
should be gone:

```sh
tack doctor --projects-only .
```

Show the user a summary of the changes. Unless they say otherwise, land them
through the branch and a pull request, with a title in the project's commit
style (`Set up agent instructions`), and merge once CI passes. If the project
has no remote yet, or the user wants it committed directly, commit on the
current branch and say so.

## 5. Hand off

Report the files written, the choices made, anything moved between files or
removed (and where its rules went), what `doctor` still reports, and anything
left for the user to do by hand.

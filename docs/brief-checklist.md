# The brief checklist

Every class of mistake a chunk *brief* has carried at least once, kept so the
next cut looks for it by default. Each entry is a *shape*, not a rule: the
authority docs remain the authority on what the code must do. This file
records only where a planner, holding the right decisions, still handed an
executor a brief that was wrong.

It is the cut-time companion to the review checklist. The division is by
*when* the mistake is made, not by who finds it: a defect in the code an
executor wrote belongs there, a defect in the instructions the planner wrote
belongs here. Most entries are found in review, because that is when a brief's
error becomes visible; the provenance names the chunk whose brief carried it.

**How it is used.** `/relay-next` takes each draft brief through every entry
here before committing it. A fix that matches an entry cites it as
`brief-checklist §N` in the review or the chunk ledger. `/relay-execute` does
not read this file: an executor builds the brief it is given.

**How it grows.** When a review finds that the *brief* was wrong rather than
the code (a decision that reached no unit, an instruction that contradicted
itself, a *Tests* line that invented a condition), `/relay-next` adds it here
as the next numbered entry with the finding that revealed it. Entries are not
renumbered or retired.

The boundary with `/relay-next` itself: the skill keeps the *procedure* (what
to read, decide, and write, in what order). This file keeps the recurring ways
the product of that procedure has come out wrong.

---

## The catalogue

### §1 A *Build* item pins a mechanism where only a property was needed

The brief says *how* to achieve something (drop these directories, link that
program back) when what the doc requires is a property (no real agent can be
found; everything else still resolves). The mechanism was never tried in a
real environment, so the executor finds it wrong and has to log a decision to
deviate. Before committing a brief, read each *Build* item that manipulates
the environment, the filesystem or a process and ask whether it states a
property the tests can check or a recipe; give the property, and offer a
recipe only as a suggestion in *Notes for the executor*.

*Provenance:* P0001-C01-c. The brief had the stand-in fixture drop every
`PATH` directory holding a real agent and link `git` back. On a machine with
the agents installed by Homebrew that dropped every other program there, and
asdf's `uv` shim, which looks further down `PATH`, failed; the executor
replaced it with mirrors of those directories (DEC-9).

### §2 A rule borrowed "as for skills" whose premise doesn't carry over

The brief (or the design it cites) gives a new feature an existing feature's
rule by analogy ("as in `deploy.Plan`", "like a listed skill") without
checking the fact that made the rule right for the original. The executor
builds it faithfully and tests pin it, so nothing fails until a later chunk
needs the premise. Before committing a brief, find each rule it borrows from
another feature and name the premise that rule rests on (a directory per
harness, a link per name, a checkout per source); confirm the new feature has
the same one, or write the rule it needs instead.

*Provenance:* P0001-C02-c. The brief told the plan to compute plugin
collisions per harness, "as in `deploy.Plan`", and to test that per-plugin
harnesses that don't overlap don't collide. Skills collide per harness
because each harness has its own skills directory; every plugin goes through
tack's one marketplace, one copy per name (DEC-1), so the same name from two
sources can't be deployed even to different harnesses. Found while cutting
P0001-C03, whose `sync` needs one copy per name (DEC-11). The sweep found the
same per-harness rule in `add`'s plugin refusal and `doctor`'s
`name-collision`, both fixed in that review.

### §3 An exemption that a step's side effect breaks

The brief exempts something from every step ("kept as it is", "left
alone") and then states a step's condition without crossing it with that
exemption, though a harness fact says the step's command touches the
exempted thing anyway. Each line reads true on its own; together they
contradict, and the executor has to log a decision to say which wins.
Before committing a brief that keeps anything as it is, take each step it
lists, look up what that step's command does beyond its purpose (in *Harness
facts*: a removal that uninstalls, a registration that repoints, a write that
drops entries), and state the exemption in that step's condition too.

*Provenance:* P0001-C03-c. The brief kept collided plugins and those whose
copy failed exactly as they were (DEC-11, DEC-12), and had step 5 unregister
tack's marketplace "when no selected plugin targets the harness". Claude
Code's `marketplace remove` uninstalls the marketplace's plugins, so step 5
would uninstall a kept plugin there; the executor logged DEC-13. The sweep
of P0001-C04's brief checked each step against the wider set of kept
plugins a held source adds: step 4 and the copies skip them, DEC-13 covers
step 5, and the record keeps the directory.

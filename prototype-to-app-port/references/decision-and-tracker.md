# Decision protocol & tracker discipline

Detail behind SKILL.md §4 and §5. Two intertwined skills: knowing when a choice
is yours vs the user's, and keeping a tracker the user can trust at a glance.

## When to ASK vs decide

**Default: match the prototype exactly.** You don't need permission to replicate
what the design already specifies. Reserve questions for genuine decisions:

- **(a) Real divergence with a tradeoff** — "ours" does it differently and there's
  an actual cost/benefit either way (not just style preference).
- **(b) A true product / economy / privacy choice** — defaults that affect users'
  money, data exposure, or core product behavior.
- **(c) A missing backend / infra capability** — the prototype implies something
  the backend can't yet do. Here, **inquire and propose a plan**; don't build
  blindly against a guess.

What is **not** a question for the user: execution order, chunk boundaries, which
wave first, internal naming, how to structure the PR. "Follow the plan / work in
parallel atomic chunks" means *execution is yours*; only genuine product
decisions are theirs. Don't stall decision-free work by asking "which track?"

### How to ask

State, concisely: **what the prototype actually does** (cite the code *and* the
docs, note if they disagree — code wins), then **your recommendation**, then the
choice. Batch related questions into one round (e.g. an AskUserQuestion with up
to ~4 options) rather than drip-feeding. Put your recommended option first and
label it.

### Things that become tracked issues, not code

- **Cross-repo needs** (a capability that belongs to another repo you don't edit
  from here): file an issue in that repo, cross-linked to an issue in this one.
  Don't half-build a shim.
- **Infra-blocked needs** (e.g. no scheduler primitive, no email service): file
  it, link it, move on.
- **Prototype-stubbed "coming soon"**: keep it a stub/placeholder if the
  prototype only stubs it. Don't build the real feature the prototype faked.
- **Absent from the prototype**: skip it. The prototype defines scope.

## The durable tracker

One living `TRACKER.md` per port/version, stored **outside the repo** (so branch
churn and worktrees never disturb it). Start from `assets/tracker-template.md`.

Sections:
- **Chunk table** — every chunk with Status, Triage, PR link, Notes.
- **Decisions log** — each resolved decision and what was chosen.
- **Conflicts log** — cross-chunk API collisions and how they were reconciled.
- **Field reports** — the user's hands-on QA findings, each → its own fix PR.
- **Carry-over / parked** — issues explicitly deferred by the user (track, don't
  touch) and cross-linked cross-repo issues.

### Status vocabulary

`todo` · `analysis` · `in-progress` · `pr-open` · `merged` · `done` · `blocked`
· `deferred` · `skip`. Triage tags: `fe-portable` · `data/backend` · `decision`
· `cross-repo-gated` · `infra-blocked` (adapt names per profile).

### Keeping it honest

- **Move statuses the instant they change.** A row that says `pr-open` after the
  PR merged, or `todo` for something shipped, is worse than no tracker — it
  teaches the user not to trust it. The user *will* ask "is the tracker fully
  updated?" and the only acceptable answer is a verified yes.
- **Reconcile against reality** before claiming "all updated": cross-check
  `gh pr list`, open issues, and merged PRs. **Fold in relevant issues that live
  outside your tracker** — they exist whether or not you wrote them down.
- **Audit findings are hypotheses.** A re-audit that screams "the whole X hub is
  missing!" is often a false positive from a rename/refactor (e.g. a section was
  renamed and moved, not deleted). Verify against the actual app before alarming
  the user or spinning up a "fix."
- **Respect explicit parking.** When the user says "don't fix these for now,"
  track them in the parked section and do **not** spin up agents for them — even
  if they look easy. Acting on parked items erodes trust as fast as a stale row.

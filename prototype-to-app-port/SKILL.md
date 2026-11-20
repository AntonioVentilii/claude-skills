---
name: prototype-to-app-port
description: >-
  Methodology for porting a design prototype (or a new prototype VERSION) into a
  production codebase with high fidelity — replicating styles, layout, spacing,
  copy, animations, flows, and states 1:1. Use this whenever the user wants to
  "port a prototype/design into the app", do a "design-to-code migration",
  "replicate this prototype 1:1", "bring the new version (vX.Y) over", port a
  Figma/HTML/JSX mockup into a real framework, or run a large fidelity-driven
  migration as a series of parallel atomic PRs reviewed by a bot. It covers
  diff-first DELTA ports between prototype versions, orchestrating parallel
  background sub-agents in git worktrees, the ready-for-review → bot-review →
  reply-AND-resolve loop, a decision protocol (prototype is the point of truth,
  ask only on real decisions), a durable living tracker, per-project guardrails,
  and the field-QA fidelity loop. Reach for this even when the user only says
  "make our app match the new design" without naming a process.
  "/prototype-to-app-port help", "prototype-to-app-port help" or "come si usa
  prototype-to-app-port" shows usage with examples.
---

# Prototype → App Port

A battle-tested playbook for turning a **design prototype** (HTML/JSX mockup,
Figma export, throwaway "beta" app, or a new version of one) into faithful,
production-grade code in a real framework — and doing it at scale without the
result drifting from the design.

This skill is **stack-agnostic in its core** and **specialized through a
swappable project profile**. The body below is the universal methodology. The
concrete commands, file paths, framework idioms, and hard guardrails for a
specific repo live in a profile file under `references/` that you load once at
the start of a port and treat as binding.

## Help

Once this skill is invoked, if the request asks for help ("help", "aiuto",
"?", "how do I use it", "come si usa", "esempi"), show `references/help.md`, translated into the
user's language, and stop. Don't start a port.

## How to use this skill

1. **Load the project profile first.** Look in `references/` for a
   `project-profile-*.md` matching the repo you're working in (e.g.
   `project-profile-vici.md`). It carries the stack, the exact quality-gate
   commands, the hard guardrails, and the durable doc locations. If none
   matches, copy `project-profile-TEMPLATE.md`, fill it in *with the user*, and
   save it as the new profile — that one-time investment is what makes every
   future port in that repo fast and safe.
2. **Read the rest of this file** for the workflow, then pull in the deeper
   references as you hit each phase:
   - `references/orchestration.md` — running the work as parallel atomic PRs,
     the bot-review loop, schema/binding serialization, conflict handling.
   - `references/decision-and-tracker.md` — when to ask vs decide, and how to
     keep the living tracker honest.
   - `references/agent-prompt-template.md` — the per-chunk sub-agent brief.
   - `assets/tracker-template.md` and `assets/kickoff-template.md` — copy these
     to start a new port.

## 0. Mission & framing — read this before anything

These five ideas govern every decision. Internalize them; they are *why* the
rest of the playbook is shaped the way it is.

- **Replicate the prototype 1:1.** Styles, layout, spacing, copy, **animations**,
  flows, states, icons, images. "Looks about right" is not the bar — visual and
  behavioral parity is. Animations and micro-interactions are first-class, not
  polish-later.
- **The prototype is the point of truth.** When your instinct says "ours is
  cleaner/better/different," that is *exactly* the moment to stop and **ask the
  user, with a recommendation** — never to quietly decide. Divergences are the
  user's call, not yours.
- **Prototype CODE beats prototype DOCS on conflict.** Changelogs and handover
  notes drift; the running source doesn't. Verify every claim against the actual
  prototype source/CSS, not from memory or a summary.
- **A new VERSION is a DELTA port, not a re-port.** If the prior version already
  shipped in the app, your *first* deliverable is a **diff of old-prototype vs
  new-prototype** → a plan covering only the changed/new surfaces. Re-porting
  unchanged screens is the single biggest waste; refuse to do it. (See
  "Delta ports" below.)
- **Structural-done ≠ fidelity-done.** Getting the component on screen is the
  easy 80%. The last 20% — exact spacing, easing curves, empty/loading/error
  states, edge copy — is where fidelity lives and is best caught by the user's
  hands-on **field-QA loop** (screenshot comparisons, prototype-left/ours-right).
  Expect it, invite it, and triage each report into its own small fix PR.

## 1. Guardrails are prompt constraints, not afterthoughts

Every codebase has a set of rules that, if violated, cause CI failures, broken
conventions, or leaked information. These live in the **project profile** and
must be **copied verbatim into every sub-agent prompt** — a background agent
working in an isolated worktree cannot infer them and will not read your mind.

Common categories the profile should pin down (see the VICI profile for a fully
worked example):

- **Confidentiality of the design source** — often you must *never* reference the
  external prototype in code, comments, commits, PRs, or issues. Justify changes
  from the code's own perspective. The design source is for your eyes only.
- **Terminology** — domain-mandated word choices (e.g. one term is legally or
  product-required and a synonym is banned).
- **Generated/derived files** — never hand-edit; regenerate via the documented
  command and commit the result in the same change.
- **Framework idioms** — the modern API only (e.g. a specific reactivity model),
  import conventions, lint landmines that the linter enforces but are easy to
  trip.
- **i18n / theming / accessibility / motion** — every user-facing string
  translated across all catalogs; colors via tokens (not hard-coded); animations
  gated on reduced-motion; ARIA on interactive controls.
- **Environment posture** — what's staging vs production, whether data loss is
  acceptable, whether migrations are expected.

## 2. Quality gates — run before *every* PR

The profile lists the exact commands. The principle: a chunk isn't "done" until
it passes the same gates CI will run — typically format check, lint (watch for
memory/heap flags large repos need), type/framework check, i18n check, and any
codegen build whose output must be committed. Bake the full gate sequence into
each agent prompt so agents self-verify before opening a PR; you should rarely
be the one to discover a lint failure.

## 3. Run it as parallel atomic PRs — see `references/orchestration.md`

The shape of the work: decompose the port into **atomic chunks** (one coherent
surface or concern each), dispatch them to **background sub-agents in isolated
git worktrees**, each opening a **ready-for-review PR**. You (the orchestrator)
poll the review bot, drive nits to resolution, and the user merges. Then fire
the next wave off fresh `main`.

The two hard-won rules that prevent most pain (full detail in the reference):

- **Serialize anything that touches a single shared generated artifact** (e.g. a
  one-file schema/IDL the build regenerates). Two parallel PRs editing it will
  always conflict. FE-only/independent chunks parallelize freely.
- **With the review bot, reply AND _resolve_ the thread.** Replying to a comment
  without resolving leaves it "unresolved" in the UI and erodes the user's trust
  that the PR is actually clean. Resolve every thread you've addressed.

## 4. Decide like the prototype is the boss — see `references/decision-and-tracker.md`

Default to matching the prototype exactly, and **only ask** when there's a real
decision: (a) your approach genuinely diverges with a real tradeoff, (b) a true
product/economy/privacy choice, or (c) a missing backend/infra capability. When
you ask, first state what the prototype actually does (code *and* docs) and give
a recommendation; batch questions. Execution order and chunking are *your* call
— don't ask "which track first?"; just run the decision-free work. Cross-repo or
infra-blocked needs become **cross-linked tracked issues**, not half-built code.
Prototype-stubbed "coming soon" features stay stubs; features absent from the
prototype are skipped.

## 5. Keep one durable, honest tracker — see `references/decision-and-tracker.md`

Maintain a single living `TRACKER.md` per port (or per version), stored
**outside the repo** so it survives branch churn — a chunk table
(status/triage/PR/notes), plus running logs for decisions, conflicts, and
field-QA reports. **Update statuses the moment they move.** Stale `pr-open`/`todo`
rows after a merge are the fastest way to lose the user's trust — they *will*
ask "is the tracker fully updated?", and the honest answer must be yes. Fold in
any relevant issues that live outside your tracker, and treat audit findings as
*hypotheses* to verify against the real app before raising an alarm (renames and
refactors produce false "it's missing!" positives).

## Delta ports (new version of an already-ported prototype)

When the user says "the design team released vX.Y," do **not** start over:

1. **Diff the two prototype versions** — source, styles, and any changelog (code
   wins on conflict). Produce a list of only the changed/new/removed surfaces.
2. **Triage each delta** into: directly portable · needs data/backend · needs a
   user decision · blocked on another repo/infra (→ tracked issue).
3. **Build the wave plan** from that triage and seed a fresh tracker. Everything
   unchanged is already shipped — leave it alone.
4. Watch for **reworks of things you just ported** — e.g. a component you ported
   last version that the new version redesigns, or a generator whose seed/shape
   changed. Diff carefully rather than assuming additive-only.

## The field-QA fidelity loop

After a surface lands, the user will often test it by hand and send screenshot
comparisons. This is the real fidelity pass and the most valuable signal you
get. For each report: reproduce, find the exact prototype behavior, fix it in a
small dedicated PR, and log it in the tracker's field-report section. Don't
batch unrelated fidelity fixes into one PR — small and traceable beats big.

## Starting a fresh port — quick checklist

1. Load (or create) the project profile.
2. Copy `assets/tracker-template.md` → `<port-dir>/TRACKER.md`.
3. Copy `assets/kickoff-template.md`, fill in paths/scope → use it to brief the
   orchestration (and any fresh agent).
4. If a delta port: run the version diff first and turn it into the wave plan.
5. Foundation pass if new repo: token/style map + triage of every surface.
6. Dispatch wave 1 of atomic chunks; poll the review bot; keep the tracker live.

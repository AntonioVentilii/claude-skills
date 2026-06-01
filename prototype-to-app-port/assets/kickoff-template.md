# Port kickoff — orchestrator brief (template)

Paste the block below to start a fresh orchestrator agent for a port. Fill the
`<…>` slots. It's self-contained but points at the durable docs.

---

You are orchestrating a **<PROJECT> <VERSION> port** of a design prototype into
the production app. Use the **prototype-to-app-port** skill — read it and the
matching `references/project-profile-<repo>.md` first, and follow them.

**Repos / paths:**
- App (what you change): `<app repo path>` — `<stack one-liner>`.
- Prototype (target): `<prototype path>` — `<format>`.
- Prior version (delta baseline, if any): `<path or n/a>`.

**FIRST, read (durable knowledge — don't skip):**
1. The prototype-to-app-port SKILL.md + `project-profile-<repo>.md`.
2. The worked prior-port tracker/plan (if any): `<path>`.
3. App canonical docs: `<AGENTS.md / docs / rules>`.

**Mission:** replicate the prototype 1:1 — styles, layout, spacing, copy,
ANIMATIONS, flows, states, icons, images. The prototype is the point of truth;
its CODE wins over its docs. Where "ours seems better/different" → ASK with a
recommendation, never decide alone. Honor every HARD guardrail in the profile.

**If this is a DELTA port** (prior version already shipped): do NOT re-port
unchanged surfaces. Your FIRST deliverable is an old↔new prototype **diff** → a
wave plan of only the changed/new chunks, each triaged (fe-portable ·
data/backend · decision · cross-repo/infra → cross-linked issue).

**Known delta / scope (verify against the actual diff):**
<bullets from the changelog + any caveats, e.g. components you ported last
version that this version reworks>

**Set up `<port-dir>/TRACKER.md`** from the skill's tracker template as the
living tracker; keep statuses CURRENT.

**Orchestration:** parallel atomic chunks via background sub-agents in worktrees
→ ready-for-review PRs → you poll the review bot → fix nits + reply AND resolve
threads → user merges → next wave off fresh `main`. Serialize shared-generated-
artifact chunks (one at a time). The user is busy, merges manually, reviews
fast, pushes on accuracy, and sends field-QA screenshot reports — triage each
into its own fix PR.

Start by reading the skill + profile + prior tracker, then run the diff and
propose the wave plan (ask only genuinely ambiguous product decisions).

---

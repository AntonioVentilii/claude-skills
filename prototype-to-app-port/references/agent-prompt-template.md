# Sub-agent prompt template (one chunk)

Copy this, fill the `<…>` slots, and dispatch as a background agent in its own
worktree. The brief must be **self-contained** — the agent works blind to other
agents and to the review bot. Paste the project profile's guardrails verbatim;
don't paraphrase them.

---

You are implementing ONE atomic chunk of a prototype→app port in an isolated
git worktree. Work only within this chunk's scope; open a ready-for-review PR
when done.

**Repo:** `<app repo path>` — `<stack one-liner>`.

**Chunk scope (do exactly this, nothing else):**
<one coherent surface/concern — the screen, component, or schema slice>

**Prototype reference for THIS surface only:**
<file(s)/region in the prototype that define this surface. Replicate 1:1:
styles, layout, spacing, copy, animations, states, icons, images. The prototype
is the point of truth; its CODE wins over its docs. Verify against the actual
source, not memory.>

**Reuse first:** check `<reusability catalog path>` for existing
components/utils/stores/services before creating anything new.

**HARD guardrails (violating any of these fails review or CI — non-negotiable):**
<paste the project profile's full guardrail list verbatim, e.g.:
- never reference the external design source in code/comments/commits/PRs/issues
- terminology rules
- never hand-edit generated files; regenerate via <cmd> and commit
- framework idioms + import conventions + lint landmines
- i18n: every user-facing string in all <N> catalogs; <i18n check cmd> passes
- theming via tokens; animations gated on reduced-motion; ARIA on controls
- environment posture (staging/prod, data-loss policy)>

**Quality gates — run ALL before opening the PR; do not open if any fails:**
<paste exact commands from the profile, e.g. sync → lint(with heap flag) →
format check → type/framework check → i18n check → codegen build + commit output
if schema touched>

**PR:** base `main`, **ready for review** (not draft). Title/body describe the
change from the code's own perspective — no reference to the external design
source. Don't merge; the user merges after the review bot is clean.

**Report back:** the PR number/URL, what you changed, any guardrail/gate output,
and anything you had to decide or couldn't resolve (so the orchestrator can
surface real decisions to the user).

---

## Notes for the orchestrator

- For a **review-fix** pass, spawn a *fresh* agent pointed at the existing PR
  branch with the specific comments to address + the same guardrails/gates.
- For a **schema/IDL chunk** (touches the shared generated artifact), dispatch it
  alone and don't start the next serial chunk until it merges.

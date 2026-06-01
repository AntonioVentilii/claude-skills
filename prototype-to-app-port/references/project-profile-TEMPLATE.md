# Project profile — TEMPLATE

Copy this to `project-profile-<repo>.md` and fill it in *with the user* the first
time you port into a repo. This is the swappable layer: the universal core in
SKILL.md stays the same, this file makes it concrete. Everything an agent needs
that it can't infer goes here. Keep it accurate — it's pasted into agent prompts.

## Repo & stack
- **App repo (what you change):** `<path>`
- **Stack:** `<framework + language + key infra in one line>`
- **Related repos you must NOT edit from here:** `<paths>` — consume via `<how>`;
  for changes there, file a cross-linked issue.

## Prototype sources
- **Current prototype (target):** `<path>` — `<format: HTML/JSX/Figma/etc>`
- **Prior version (delta baseline):** `<path or n/a>`
- **Key prototype files:** `<screens, styles, data, etc>`

## Hard guardrails (paste verbatim into every agent prompt)
- **Design-source confidentiality:** `<may you name it in code/PRs? usually NO>`
- **Terminology:** `<mandated words / banned synonyms>`
- **Generated files (never hand-edit):** `<paths>` → regenerate via `<cmd>`,
  commit in same change.
- **Shared generated artifact (serialize chunks that touch it):** `<file>`
- **Collection/enum/config sync points:** `<files that must stay in sync>`
- **Framework idioms:** `<modern API only; reactivity model; import rules>`
- **Lint landmines:** `<the easy-to-trip rules the linter enforces>`
- **i18n:** `<mechanism; N catalogs; check cmd; non-translatable → constants>`
- **Theming:** `<token system; multi-theme constraints>`
- **Motion / a11y:** `<reduced-motion gate; ARIA expectations>`
- **Time/units / other naming conventions:** `<e.g. _ms vs _ns>`
- **Environment posture:** `<staging vs prod; data-loss policy; migration policy;
  warn-first rules>`

## Quality gates (exact commands, in order)
```
<sync>
<lint — include any heap/memory flag the repo needs>
<format check/write>
<type / framework check>
<i18n check>
<codegen build (+ commit generated output) if schema touched>
```
Aggregate shortcut (if any): `<e.g. npm run quality>`

## Orchestration specifics
- **Default branch:** `<main>`
- **Review bot:** `<name / how to poll / how to resolve threads>`
- **Worktree convention:** `<any repo-specific notes>`
- **Rebase hotspots (append-only shared docs):** `<paths>`

## Durable knowledge locations
- **Canonical agent docs:** `<AGENTS.md / docs/ai/** / .claude/rules/*>`
- **Reusability catalog:** `<path>`
- **Tracker home (outside repo):** `<path>`
- **Memory/feedback notes:** `<path>`

## Known divergences from the prototype (logged, intentional)
- `<list any deliberate deltas the user already approved, so agents don't "fix"
  them back to the prototype>`

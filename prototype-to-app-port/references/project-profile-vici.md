# Project profile — VICI (vici-app)

The concrete layer for porting VICI design prototypes into the production app.
Pair with the universal core in `../SKILL.md`. Distilled from the full V1.4 port.

## Repo & stack
- **App repo (what you change):** `/Users/antonio.ventilii/projects/vici-app`
- **Stack:** SvelteKit + Svelte 5 (runes) + Juno satellite (TS canister
  functions via `@junobuild/functions`) + consumes icdc-core clearing/registry
  canisters. Vici registers as engine `eng_0` on the icdc-core registry.
- **Related repos you must NOT edit from here:** `../icdc-core/` (the Rust risk
  engine). Consume its Candid surface via generated bindings (`npm run did`,
  commit `src/declarations/**`). For changes there, open it as its own workspace
  and obey *its* AGENTS.md; file a cross-linked vici-app↔icdc-core issue and wire
  it in a separate PR here.

## Prototype sources
- Prototypes are no-build inline-JSX/vanilla-JS apps: `screens.jsx`, `flow.jsx`,
  `app.jsx`, `data.js`, `flow-artwork.js`, `avatar.jsx`, `*.css`, plus
  `CHANGELOG.md` / `Handover.md` / `docs/explorations/`.
- Paths are version-specific (e.g. `/Users/antonio.ventilii/projects/VICI-Beta-V1.5`,
  baseline `/Users/antonio.ventilii/projects/VICI WebApp beta V1.4`). Confirm the
  current paths with the user per port.

## Hard guardrails (paste verbatim into every agent prompt)
- **NEVER reference the external design source** in code/comments/commits/PRs/
  issues — no "prototype", "V1.x", `*.jsx` design paths, "VICI WebApp", "beta
  Vx". Justify changes from the code's own perspective. The design source is for
  YOUR eyes only.
- **Terminology:** always "prediction"/"call", never "bet" (legal "wagering"
  disclaimer copy is the only exception).
- **Never hand-edit generated files:** `src/declarations/**`, `satellite.did`,
  `satellite_extension.did`, generated `api-schemas`. Regenerate.
- **Juno schema edits → `npm run juno:functions:build`, then `prettier --write`
  the regenerated declarations, and COMMIT them in the same PR.** CI's
  `satellite-schema` job fails on unformatted/missing declarations. (Default-
  value / logic-only changes often produce zero real `.did` change after
  prettier — that's fine.)
- **Shared generated artifact (SERIALIZE schema chunks):** the satellite emits
  ONE `satellite_extension.did`. Two parallel PRs that change the satellite
  schema WILL conflict — do satellite-schema chunks one at a time. FE-only
  chunks parallelize freely.
- **Collection names live in TWO places that must stay in sync:** `juno.config.ts`
  and the `Collection` enum in `src/lib/constants/collections.constants.ts`.
- **`@junobuild/core` is FE-only** — never import from `src/satellite/` (use
  `@junobuild/functions`). Local replica = `juno emulator start` (never
  `dfx start`).
- **Svelte 5 runes only** (`$props`/`$state`/`$derived`/`$effect`; no `export let`
  / `$:`); `interface Props` + destructure. **No hidden reactive captures**: a
  top-level IIFE reading `$props`/`$state` freezes the value at init — use
  `$derived`/`$derived.by`; `svelte-check` won't catch it.
- **ESLint landmines:** no `0n` (use `ZERO` from `$lib/constants/app.constants`);
  no `return undefined;` (bare `return;`); no relative imports across folders
  under `src/**` (use `$lib`); `lucide-svelte/icons` SUBPATH imports (never the
  root `lucide-svelte`).
- **Time vars:** `_ms` (milliseconds, default) / `_ns` (nanoseconds, protocol).
- **Theming:** token-based colors only (no dark-only rgba — must adapt across
  dark/light/peach themes). **Reduced-motion-gate every animation/transition.**
- **i18n:** custom `t({locale,key})`; 7 locale catalogs
  `src/lib/constants/messages/{en,it,es,de,fr,pt,zh-CN}.ts` (+ a TODO toward 10);
  every new user-facing string in all 7; `npm run check:i18n` must pass.
  Non-translatable literals (emails/URLs) → a CONSTANT (e.g.
  `contact.constants.ts`), not a per-locale key.
- **Environment posture:** app + satellite are STAGING — data loss acceptable; no
  migration unless asked, but WARN first. For legacy-data bugs prefer WIPING bad
  docs over carrying compat code. The FE talks to icdc-core **PRODUCTION**.
  (PR #263 wired both networks: `--staging`=icdc-core staging,
  `--production`/`--ic`=production.)

## Quality gates (exact commands, in order)
```
npx svelte-kit sync
NODE_OPTIONS=--max-old-space-size=8192 npx eslint <changed files>   # eslint OOMs without the heap bump
npx prettier --check <changed>      # or --write
npm run check                       # svelte-check, expect 0 errors / 0 warnings
npm run check:i18n
npm run juno:functions:build        # + commit regenerated declarations, if satellite touched
```
Aggregate shortcut: `npm run quality` = format + lint + i18n.

## Orchestration specifics
- **Default branch:** `main`.
- **Review bot:** GitHub Copilot auto-reviews any ready-for-review PR with `main`
  base. Agents can't see it — orchestrator polls
  `gh api repos/AntonioVentilii/vici-app/pulls/N/comments|reviews`, filter
  `user.login | test("opilot")`, ~150–220s after open (slow on big generated/
  `.did` diffs; re-poll). For each nit: fix + reply + **resolve the thread**
  (GraphQL `resolveReviewThread`, matched on the thread's first-comment
  `databaseId`); verify `isResolved:true`.
- **Rebase hotspots:** `docs/ai/frontend/reusability.md` (every chunk appends a
  row → take main's wholesale, re-apply your row, prettier, push). Locale
  catalogs usually auto-merge. Prefer MERGE over rebase; force-with-lease only
  when the user says "rebase".
- **Worktree branch-locked:** reset your branch ref to `origin/<branch>` and push
  `HEAD:<branch>` (fast-forward, no force).

## Durable knowledge locations
- **Canonical agent docs:** `AGENTS.md` (entry) → `docs/ai/**` (source of truth)
  → `.claude/rules/*` (thin Claude pointers). Area READMEs:
  `docs/ai/frontend/README.md`, `docs/ai/satellite/README.md`,
  `docs/ai/backend/README.md`. Engine: `docs/engine-integration.md`.
- **Reusability catalog:** `docs/ai/frontend/reusability.md` — check before
  creating any new component/util/store/service.
- **Tracker home (outside repo):**
  `~/.claude/projects/-Users-antonio-ventilii-projects-vici-app/vNN-port/TRACKER.md`
  (+ the worked `v14-port/` example: `PLAN.md`, `TRACKER.md`, `0.1-token-map.md`,
  `0.3-triage.md`, `FINAL-AUDIT.md`).
- **Memory/feedback notes:**
  `~/.claude/projects/-Users-antonio-ventilii-projects-vici-app/memory/`.

## Known divergences from the prototype (logged, intentional — don't "fix" back)
- **Sign-in provider list:** real II/Passkey/Google/Dev + Apple/email "Soon"
  placeholders (a logged divergence).
- **ViciAvatar generator seeded by `principal`** (`ViciAvatar.svelte` +
  `vici-avatar.utils.ts`) — deliberate; real-user default-avatar wiring exists in
  `profile/Avatar.svelte`.
- **Social → Arena rename:** the social hub lives under `/arena` (ArenaPage,
  ArenaOverviewStrip, FriendsTab, ActivityFeed). An audit may falsely read this
  as "social hub missing" — it's not.
- **Prototype-matching placeholders kept:** CSV export, album download, 2FA,
  worlds top-contributors. **Skipped** (absent from prototype): public league
  directory.
- **Cross-repo/infra issues filed (not half-built):** icdc#56↔#353 (per-window
  stats/rank-delta/league-rank/feed-VXP-delta), icdc#55↔#350 (real VXP credit
  path), icdc#54↔#332 (friends-lean), #351 (school email infra). Parked by user:
  #285, #283, #188.

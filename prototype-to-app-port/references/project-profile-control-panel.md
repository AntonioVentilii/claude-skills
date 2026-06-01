# Project profile — control-panel (dfinity/control-panel)

Concrete layer for porting Cloud Engines design-prototype surfaces into the
control-panel Svelte frontend. Pair with `../SKILL.md`. First port: the
user-management (roles/permissions/people/teams) feature.

## Repo & stack
- **App repo (what you change):** `/Users/antonio.ventilii/projects/control-panel`
- **Stack:** pnpm monorepo. Rust backend (`engine-controller-backend`) +
  **Svelte 5 (runes)** frontend under `src/frontend/src`, SvelteKit routing,
  **Tailwind v4** (semantic tokens), ICP / Internet Identity auth, **orval**-
  generated API client from a **utoipa** OpenAPI schema.
- **Backend is OFF-LIMITS:** `src/backend/`, `src/canisters/` are owned by
  `@dfinity/dre`. Don't modify Rust unless explicitly asked. For backend gaps,
  file a tracked issue — don't half-build.

## Prototype sources
- **Prototype:** `github.com/dfinity/cloudengines-product-explorations`, cloned
  at `/Users/antonio.ventilii/projects/_prototype-cloudengines`. It's a
  **Next.js / React (TSX) + shadcn/ui + Tailwind** app under `prototype-v2/`
  (so every port is a **cross-framework** React→Svelte translation).
- **Specs:** `docs/product/user-management.md`, `docs/product/roles.md`,
  `docs/design/{visual,components,navigation}.md`, `prototype-v2/DESIGN-SYSTEM.md`.
- Code wins over docs on conflict; the spec describes a fuller product than is
  backed by the API today (see "Known backend reality").

## Hard guardrails (paste verbatim into every agent prompt)
- **Design-source confidentiality (DEFAULT):** describe changes from the
  product's own perspective; don't reference the prototype repo / Next.js source
  / `*.tsx` paths in code, comments, commits, or PRs. (Internal dfinity repo —
  relax only if the user says so.)
- **Terminology:** use control-panel's product language — "engine", "Team",
  "member", engine roles **Owner/Admin/Developer**; org roles
  **Owner/Admin/Member**. Match existing in-repo terms over prototype synonyms.
- **Never hand-edit generated files:** `src/frontend/src/lib/schemas/api/**`
  (orval), `src/frontend/src/lib/api/**`, `src/frontend/src/common/types/i18n.d.ts`.
  Regenerate: `pnpm generate:api` (from backend OpenAPI), `pnpm i18n` (from
  `en.json`). CI (`backend.yml`) re-runs `generate:api` and **auto-commits** the
  regenerated api schemas — don't fight it; regen locally and commit, or let CI.
- **Service-flow layering (never skip a layer):** `Component.svelte` →
  `$main/services/<f>.services.ts` (orchestration, toasts, i18n) →
  `$lib/services/<f>.services.ts` (typed, returns `Result<T>` discriminated
  union from `@dfinity/zod-schemas`) → `$lib/api/*` (orval, network boundary).
  Components never call `$lib/api` directly.
- **Svelte 5 runes only:** `$props`/`$state`/`$derived`/`$derived.by`/`$effect`;
  `interface Props` + destructure; **snippets** (`{#snippet}`/`{@render}`) over
  slots. No `export let`, no `$:`, no `on:click` (use `onclick`).
- **TS strict:** no `any`, no `as unknown as X`, no non-null `!` — use
  `isNullish()`/`nonNullish()` from `@dfinity/utils`. **Object params** for
  functions with >1 arg (lint rule `local-rules/prefer-object-params`, NOT
  auto-fixable → fails `lint:no-warnings`). Prefer `import type`.
- **Styling:** Tailwind v4 **semantic tokens only** (`text-foreground`,
  `text-muted-foreground`, `bg-card`, `border-border`, `bg-status-green`, …).
  FORBIDDEN: `text-gray-*`/`bg-zinc-*`, `text-[#hex]`, inline `style=`, raw
  `stroke="#…"` on SVG. Conditional classes via `cn()` from `$ui/utils`.
- **Icons:** named imports from `@lucide/svelte` or `@tabler/icons-svelte` only
  (no deep imports); decorative icons get `aria-hidden="true"`.
- **i18n + a11y:** no hard-coded English — every string in
  `src/frontend/src/common/i18n/en.json`, read via typed `$i18n.<dotted.key>`
  (`pnpm i18n` regenerates `i18n.d.ts`); snake_case dotted keys. No bare
  clickable `<div>`s. **`PageHeader` is required on new pages.**
- **Reuse first** (`docs/ai/frontend/reusability.md`): `$ui/components/ui/*`
  primitives (Table, Button, Input, Select, Dialog, Drawer, Popover, Tooltip,
  Badge), `$main/components/shared/*` (PageHeader, MetricCard, StatusBadge,
  Eyebrow, SeoHead), `$main/components/user/*` (UserAvatar, profile bits),
  `$main/components/auth/sign-in/SignInButtons.svelte`. **No new deps** without
  approval. **No new top-level folders** under `src/frontend/src/`.
- **Commandments:** idiomatic · atomic (one logical change per PR) · small
  (prefer 5 small PRs over 1 big) · typed · i18n+a11y · respect structure ·
  don't overengineer.

## Quality gates (exact commands, in order)
```
pnpm format
pnpm lint:fix
pnpm check                 # svelte-check + tsc, 0 errors
pnpm test:frontend         # or scoped: pnpm -C src/frontend test path/to/file.test.ts
pnpm lint:no-warnings      # REQUIRED — matches CI; catches non-auto-fixable warnings
pnpm check:unused:svelte
pnpm check:unused:i18n
pnpm generate:api          # only if pulling new/changed backend endpoints
pnpm i18n                  # after editing en.json (regenerates i18n.d.ts)
```

## Orchestration specifics
- **Default branch:** `main`. Always branch off fresh `main` and target `main`
  (draft if it depends on something unmerged).
- **PR title (CI-enforced):** conventional commits
  `^(feat|fix|chore|build|ci|docs|style|refactor|perf|test)(\(scope\))!?:` —
  e.g. `feat(frontend): add engine team management`. Scope lowercase.
- **PR body (mandatory template):** `# Motivation` then `# Changes`.
- **Review bot:** GitHub Copilot reviews PRs — poll, fix nits, reply AND resolve
  threads.
- **Shared generated artifact:** the orval-generated `lib/schemas/api/**` and
  `lib/api/**` regenerate from the one backend OpenAPI schema. Chunks that pull
  new endpoints should be sequenced / coordinated so they don't fight over the
  regenerated files; pure-FE chunks parallelize freely.

## Durable knowledge locations
- **Canonical docs:** `AGENTS.md` (entry, "10 commandments") → `CLAUDE.md`
  (Claude addenda) → `docs/ai/**` (frontend/README, structure,
  stack-and-patterns, reusability, i18n-and-a11y, workflows/*, pr-and-ci,
  governance). Truth hierarchy: code > CI > governance > AGENTS > tool layers.
- **Reusability catalog:** `docs/ai/frontend/reusability.md`.
- **Auth/identity:** `@icp-sdk/auth` + II + OpenID. `authStore`
  (`$main/stores/auth.store.ts`); `authSignedIn`/`authIdentity`/`authNotSignedIn`
  (`$main/derived/auth.derived.ts`); `SignInButtons` component (don't roll your
  own auth UI). Identity → `identity.principal()`.
- **Tracker home (outside repo):**
  `~/.claude/projects/-Users-antonio-ventilii-projects-control-panel/usermgmt-port/TRACKER.md`.

## Known backend reality (verified on origin/main — CRITICAL for triage)
The prototype's user-management spec has THREE pillars; the API backs ONE:
- ✅ **Engine Team + engine roles** — `services/rbac::{EngineRole, Permission}`;
  routes `GET/POST/PUT/DELETE /v1/engines/{engine_id}/members[/{user_id}]`
  (`ListMembersResponse`/`MemberDto`, `AddMemberRequest{role}`,
  `UpdateMemberRoleRequest{role}`); `AssignableEngineRole` = Admin|Developer,
  Owner reserved. DB migration `create_engine_members` (2026-05-21). The FE
  schema (`lib/schemas/api/engine-members/`) lands via `pnpm generate:api` /
  the `nim-roles` branch.
- ✅ profile (`/v1/users/me` GET/PUT), quota-by-email (`/v1/quotas` POST,
  `/v1/quotas/me`), platform role (`PlatformRole` = PlatformAdmin|User).
- ❌ **No Organizations / People directory / org roles** (Owner/Admin/Member).
- ❌ **No email invitations / tokens / 7-day expiry / accept-invite flow** —
  members are added **by principal/user_id**, NOT invited by email. The
  prototype's "invite by email → pending → accept (passkey)" has no backend.
- Older `POST /v1/engines/change-membership` = NNS-controller set change, a
  different (lower-level) primitive than the RBAC members API.

## Logged divergences / decisions (append as resolved)
- _(scope decision pending — see tracker)_

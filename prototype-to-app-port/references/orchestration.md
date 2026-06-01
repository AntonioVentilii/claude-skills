# Orchestration playbook — running a port as parallel atomic PRs

How the work actually runs. The orchestrator (you) decomposes, dispatches,
polls the review bot, and keeps the tracker live; background sub-agents each own
one chunk in an isolated worktree; the user merges. This file is the detail
behind SKILL.md §3.

## Table of contents
- Chunking: what makes a good atomic chunk
- The sub-agent contract
- Dispatch: parallel background agents in worktrees
- The review-bot loop (reply AND resolve)
- Serialization: shared generated artifacts
- Rebase hotspots & merge hygiene
- Conflict reconciliation across chunks
- Re-spawning for review fixes
- Waves

## Chunking: what makes a good atomic chunk

A chunk is **one coherent surface or concern** that can be reviewed and merged
on its own: a single screen, a shared component, one foundation analysis, one
backend schema slice. Heuristics:

- Small enough to review in one sitting; large enough to be self-contained.
- Minimizes overlap with other in-flight chunks (shared files = merge pain).
- Has a clear "done" — gates pass, surface matches prototype, PR opens green.
- If a chunk needs a backend/schema change *and* FE wiring, consider splitting:
  schema first (serialized), FE wiring after it merges.

## The sub-agent contract

Every dispatched agent gets a self-contained brief (see
`agent-prompt-template.md`). It must contain: the chunk scope, the prototype
reference for *that surface only*, the full guardrails (copied from the project
profile), the exact quality-gate commands, and the instruction to open a
**ready-for-review** PR based on `main`. Agents work blind to each other and to
the review bot — everything they need is in the prompt.

## Dispatch: parallel background agents in worktrees

- Each agent branches off `origin/main` in its **own git worktree** so parallel
  work never collides on the working tree.
- Run independent chunks **concurrently** (dispatch them in the same turn).
- Don't read an agent's full transcript/JSONL — it overflows context. Read its
  **final report** and your own poll output.
- **Worktree branch-locked** (another worktree already holds the branch): reset
  your branch ref to `origin/<branch>` and push `HEAD:<branch>` — a normal
  fast-forward, no force needed.

## The review-bot loop (reply AND resolve)

If the repo has an automated PR reviewer (e.g. Copilot) that triggers on
ready-for-review PRs targeting `main`:

1. **Agents can't see the bot** — only the orchestrator polls. Query the PR's
   review comments and reviews (e.g. `gh api .../pulls/N/comments` and
   `.../reviews`, filtering for the bot's `user.login`). Big generated/IDL diffs
   make the bot slow — poll ~150–220s after opening, then re-poll.
2. For each nit: **fix it, reply to the comment, AND resolve the review thread.**
   Replying alone leaves the thread "unresolved" in the UI. Resolve via the
   platform's API (e.g. GraphQL `resolveReviewThread`, matched on the thread's
   first-comment id). Verify it shows resolved.
3. When the bot is clean and gates are green, hand to the user to merge.
4. After merge, fire the next wave off fresh `main`.

This reply-AND-resolve discipline was learned the hard way: a PR with a fixed
nit but 9 still-"unresolved" threads reads as not-done to a busy reviewer.

## Serialization: shared generated artifacts

Some builds regenerate a **single shared file** from many inputs — a schema
IDL/`.did`, a generated client, a combined types bundle. Two PRs that both
change that input will both regenerate the file and **always conflict**.

Rule: **serialize every chunk that touches such an artifact** — one at a time,
fire the next when the prior merges. Everything that doesn't touch it
parallelizes freely. Identify these artifacts in the project profile so agents
and you both know which chunks are "serial-only."

## Rebase hotspots & merge hygiene

- **Append-only shared docs** (e.g. a reusability catalog every chunk adds a row
  to) conflict trivially. Resolution: take `main`'s version wholesale, re-apply
  your one row, reformat, push.
- Locale/translation catalogs usually auto-merge.
- **Prefer merge over rebase** to avoid force-pushes. Only `--force-with-lease`,
  and only when the user explicitly asks for a rebase. Don't rewrite shared
  history unprompted.

## Conflict reconciliation across chunks

When two chunks touch the same shared component with diverging APIs (e.g. one
adds an `appearance` prop, the other a `variant` prop for the same thing),
unify into one coherent API at merge time and assign **single-file ownership**
so you don't end up with duplicate "ghost" props. Decide the unified shape, then
reconcile both PRs to it.

## Re-spawning for review fixes

To fix review nits on an existing PR, **spawn a fresh agent pointed at the
existing PR branch** rather than trying to continue (resume/SendMessage to) the
original agent — continuation is unreliable. Give the fresh agent the branch
name, the specific comments to address, and the same guardrails + gates.

## Waves

Group chunks into waves. Within a wave, parallelize the independent ones and
serialize the shared-artifact ones. Close a wave (everything merged, tracker
updated) before opening the next off fresh `main`. This keeps `main` always
releasable and the tracker always a true picture.

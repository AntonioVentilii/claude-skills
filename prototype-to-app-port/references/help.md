# prototype-to-app-port: how to use it

Ports a design prototype (an HTML/JSX mockup, a Figma export, a throwaway
"beta" app) into the real app **1:1**: styles, layout, spacing, copy,
animations, flows and states. The work runs as a series of small PRs done in
parallel by background agents, reviewed by the bot, and merged by you. The
prototype is the point of truth: when the app would differ, Claude asks you,
with a recommendation, instead of deciding.

## Examples

| You say | What happens |
|---|---|
| `/prototype-to-app-port` | Starts a port in the current repo. It loads the repo's project profile (or builds one with you), then plans the work. |
| "porta il prototipo in `~/design/v1.0` nell'app" | First port: maps the design tokens, triages every screen, then dispatches wave 1 of PRs. |
| "è uscita la v1.3 del prototipo, portala" | **Delta port**: diffs v1.2 against v1.3 first, and plans only what changed. Unchanged screens are left alone. |
| "make our app match the new design" | Same thing, without naming the skill. |
| *(screenshot: prototype on the left, app on the right)* "qui lo spacing è diverso" | Field-QA report: it finds the exact prototype behaviour and fixes it in a small dedicated PR, logged in the tracker. |
| "il tracker è aggiornato?" | It checks every row against the real PRs and fixes stale statuses. The answer has to be an honest yes. |
| "riprendi il port da dove eravamo" | It reads the tracker and carries on with the next wave. |
| `/prototype-to-app-port help` | This page. |

## What to give it the first time

- **Where the app is**, and its stack.
- **Where the prototype is**, plus the previous version if this is a delta port.
- **The repo's rules**, so it can fill the **project profile** with you
  (`references/project-profile-<repo>.md`):
  - commands that must pass before every PR;
  - words that are mandatory or banned;
  - generated files;
  - whether the prototype may be named in code or PRs.

  Profiles already exist for `vici` and `control-panel`. For any other repo,
  it copies `project-profile-TEMPLATE.md` and fills it in with you once.

## How a port runs

1. **Profile:** loaded, or written with you.
2. **Tracker:** a `TRACKER.md` copied from `assets/tracker-template.md`, stored
   outside the repo. It is kept current as things move.
3. **Plan.**
   - Delta port: the diff between the two prototype versions, turned into waves.
   - New port: the full triage of every screen.
4. **Waves of atomic PRs**, built by agents in separate worktrees. Each PR
   passes the profile's quality gates before it opens.
5. **Bot review:** every comment gets a reply **and** a resolved thread. Then
   you merge, and the next wave starts off a fresh `main`.
6. **Field QA:** your screenshot reports become small fix PRs.

## What it asks you, and what it doesn't

**It asks you** about real decisions only:
- its approach would genuinely diverge from the prototype;
- a product, pricing or privacy choice;
- a missing backend capability.

Each question comes batched with the others and with a recommendation.

**It decides on its own:**
- the order of the work;
- how to split it into chunks.

Work blocked on another repo becomes a cross-linked issue instead of
half-built code.

## Useful files

| File | Use |
|---|---|
| `assets/kickoff-template.md` | Brief to start a fresh orchestrating agent on a port. |
| `assets/tracker-template.md` | Starting `TRACKER.md`. |
| `references/project-profile-TEMPLATE.md` | Profile for a new repo. |
| `references/orchestration.md` | Parallel PRs, bot-review loop, conflicts. |
| `references/decision-and-tracker.md` | When to ask, how to keep the tracker honest. |
| `references/agent-prompt-template.md` | Brief for each chunk's agent. |

---
name: merge-queue
description: >-
  A merge queue for repos that don't have GitHub's native one (personal repos,
  private repos on Free/Team plans). Walks the open PRs of the current repo
  oldest-first and, for each one, checks the gates (ready for review, Copilot
  review arrived and handled per its green/blue/yellow verdict, required
  approvals, no conflicts, no hold labels), rebases it on the base branch, waits
  for all CI to go green, then merges it via auto-merge (squash by default), one
  at a time so every PR is tested on top of the previous one. Any PR failing a
  gate is skipped with a reason. Release PRs are left out. Ends with a report.
  Use when the user says "merge queue", "/merge-queue", "run the queue", "land /
  merge my open PRs", "mergia le PR", "fai girare la merge queue", "process the
  ready PRs", or asks to rebase-and-merge a batch of PRs. Filters: only my PRs
  (default) or everyone's, or an explicit list of PR numbers.
---

# Merge queue (for repos without one)

You are acting as GitHub's merge queue for the repo in the current working
directory. One PR at a time, in order: check it can go, bring it up to date,
let CI prove it, merge it, move on. A PR that fails a gate is skipped, not fixed.
The user gets a report at the end.

The heavy lifting (reading the GraphQL state, judging each gate, waiting on CI)
is done by `scripts/mq.py` (stdlib Python + an authenticated `gh`). Run it rather
than judging gates by eye: the rules below are encoded there and unit-tested.
`SKILL` below means this skill's directory.

## 0. Parse the invocation

Defaults come from `SKILL/config/repos.json` (`"*"` → `"owner/*"` → `"owner/repo"`),
then whatever the user said overrides them. Map their words to flags:

| User says | Flag | Default |
|---|---|---|
| "mine" / "all" / "@alice,@bob" | `--author me\|all\|alice,bob` | `me` |
| "#12 #15 #9" (explicit PRs, in that order; author filter is ignored) | `--pr 12 15 9` | all open PRs |
| "no copilot" / "copilot required" | `--copilot off\|required` | `auto` (detected from repo history) |
| "don't update" / "update with merge" | `--update none\|merge` | `rebase` |
| "merge commit" / "rebase merge" | `--method merge\|rebase` | `squash` (falls back to what the repo allows) |
| "into develop" | `--base develop` | repo default branch |
| "dry run" / "just check" / "report only" | none: stop after step 2 | off |

If something the user asked for is ambiguous (e.g. "merge the good ones"), use
the defaults and say so in the report; don't stop to ask.

## 1. Preflight

```bash
gh auth status            # must be logged in with write access to the repo
gh repo view --json nameWithOwner -q .nameWithOwner
```

If `gh` is missing or unauthenticated (e.g. a cloud session that only has the
GitHub MCP tools), follow `references/mcp-fallback.md` instead of the script.

## 2. Snapshot and triage

```bash
python3 SKILL/scripts/mq.py status --format table [flags]   # human view
python3 SKILL/scripts/mq.py status [flags] > /tmp/mq.json   # what you act on
```

The JSON has repo-level facts (`merge_method`, `auto_merge_allowed`,
`rules`, `notes`) and the ordered `queue`, each PR with `gates`, `blockers`,
`warnings` and a `next` action. `excluded` lists PRs left out of the queue on
purpose (other authors, release PRs, other base branch).

Read `notes` first. If the viewer has no write permission, stop and report. If
the branch has a native merge queue, say so (the user may prefer it) and carry on:
`gh pr merge --auto` will enqueue there.

**Dry run:** stop here and write the report from the snapshot (section 5),
showing what *would* happen to each PR. Make no changes of any kind.

## 3. The gates (what `mq.py` checks, so you can explain it)

In order, for each PR. Any failure → `next: skip` with the reason in `blockers`.

1. **Not excluded.** Release PRs (release-please / changesets branches,
   `autorelease:` labels, `chore: release x.y.z` titles; patterns in config),
   PRs by other authors under the `me` filter, and PRs targeting another branch
   (stacked PRs) are not part of the queue.
2. **Ready for review.** Drafts, hold labels (`do-not-merge`, `wip`, `hold`,
   `blocked`, …) and `[WIP]` titles are skipped.
3. **Copilot review arrived and handled** (when the repo uses Copilot; `auto`
   detects it from this and recent PRs). The latest Copilot review's verdict
   decides:
   - 🟢 *Approval recommended*: OK once every Copilot thread is resolved.
   - 🔵 *Needs a closer look*: also needs an answering comment from a human
     (or an allow-listed agent bot such as `claude`) posted **after** that
     review. CI bots don't count.
   - 🟡 *Changes recommended*: every Copilot thread resolved; if the review had
     no inline threads, an answering comment after it as well.
   - No verdict (older format): every Copilot thread resolved.
   - Review requested but not arrived → `pending`. Not requested at all in a
     repo that normally gets one → `next: request_copilot`.
4. **Approvals.** If branch rules require reviews and they're missing
   (`reviewDecision: REVIEW_REQUIRED`), skip and say how many are needed and
   whether code owners must approve. An outstanding *changes requested* from a
   human blocks too, even if no rule enforces it. Unresolved non-Copilot
   threads block only when the rules require conversation resolution;
   otherwise they become a warning.
5. **No conflicts** with the base.
6. **Up to date** (`--update rebase` by default): if behind the base,
   `next: update`. Then CI must pass on the new head before merging.

## 4. Run the queue

Process `queue` in order. Keep a running log per PR (result + reason) for the
report. **Re-run `mq.py status --pr N` right before acting on each PR**, because
merging the previous PR moved the base, and act on that fresh `next`:

- `skip`: record the blockers; go to the next PR.
- `request_copilot`: request it (`gh pr edit N --add-reviewer @copilot`; if
  your gh rejects that, use the GitHub MCP `request_copilot_review`), record
  "waiting for Copilot", and go to the next PR. Never wait on it inline.
- `update` → `wait_checks` → `merge`, the head-of-queue loop:

```bash
# a. update (server-side; never rebase/force-push locally)
OLD=$(gh pr view N --json headRefOid -q .headRefOid)
gh pr update-branch N --rebase          # omit --rebase when update=merge
# b. wait for CI on the new head. One call waits up to ~9 min; repeat while it
#    exits 2, until wait_timeout_minutes (config, default 45) is used up.
python3 SKILL/scripts/mq.py wait-checks --pr N --not-sha $OLD --timeout-sec 540
#    (no --not-sha when there was no update)
# c. re-verify everything on the final head
python3 SKILL/scripts/mq.py status --pr N
# d. merge (method from the snapshot's merge_method)
gh pr merge N --auto --squash --match-head-commit <head_sha>
# e. confirm it landed before touching the next PR
python3 SKILL/scripts/mq.py wait-merged --pr N --timeout-sec 180
```

How to read each step:

- **a.** If `update-branch` fails (conflicts the server can't rebase, fork
  without maintainer edits, or a rule rejects it), skip with that reason. If
  it says the branch is already up to date, carry on.
- **b.** `wait-checks` returns 0 when everything is green, or when no CI
  registered within the settle time; it prints JSON. Exit 1 means CI failed:
  skip, naming the failing checks. Don't re-run them and don't fix them. If
  the time budget runs out (exit 2) and auto-merge is available, arm it (d)
  and record "auto-merge armed, CI still running". Otherwise skip with "CI
  still running after N min".
- **c.** It must say `next: merge` again. A Copilot re-review triggered by the
  rebase may have landed (yellow or new threads → skip), stale approvals may
  have been dismissed, or the base may have moved again (`update` → back to
  a; at most 3 cycles per PR, then skip as "base keeps moving").
- **d.** Use the snapshot's method. If `auto_merge_allowed` is false (common
  on private repos on Free plans), drop `--auto` and merge directly, which is
  fine because everything was just verified green. If `--auto` fails with "clean
  status" or similar, the PR is already mergeable, so merge directly. Never
  pass `--admin`. Don't pass `--delete-branch`; the repo's setting decides.
- **e.** Exit 0 means merged: next PR. Exit 2 means it didn't merge (e.g.
  waiting on a required check or review GitHub still enforces). Record "armed,
  waiting on <mergeStateStatus>" and go on.

**Final sweep (once):** if anything merged and some PRs were skipped only for
transient reasons (Copilot pending, CI still running), re-run `status` once and
process any PR whose `next` is now `update`/`wait_checks`/`merge`. One sweep,
not a loop.

### Hard rules

- **Gatekeeper, not fixer.** Don't edit code, resolve threads, answer Copilot,
  approve, or re-run CI to get a PR through. Those belong to the PR's author.
  At the end, offer to do them as a separate task.
- **Never rewrite branches locally.** Updates happen server-side
  (`update-branch`) only. No local rebase, no force-push, especially on other
  people's PRs.
- **Never bypass protections** (`--admin`, disabling rules, dismissing reviews).
- **Strictly serial.** Don't update or merge PR *n+1* until PR *n* has merged
  or been skipped. Updating several at once defeats the point (each must be
  tested on top of what lands before it) and wastes CI.
- **Release PRs are never touched**, even if listed explicitly. If the user
  insists on one, ask first.
- Dry run means no mutations at all, Copilot requests included.

## 5. Report

Write it in the language the user invoked the skill in. Keep it scannable:

```markdown
## Merge queue: owner/repo → main
squash · rebase-update · mine · Copilot: auto (used) · 6 in queue, 2 excluded

| PR | Title | Result | Why / next step |
|---|---|---|---|
| #12 | feat: x | ✅ merged | rebased, 7 checks green |
| #14 | fix: y | ⏭ skipped | 🔵 Copilot "needs a closer look" has no answer |
| #15 | chore: z | ⏭ skipped | needs 1 approving review (has 0) |
| #16 | feat: w | ❌ CI failed | `test (node 20)` failed after rebase ([run](url)) |
| #17 | feat: v | ⏳ armed | auto-merge on; waiting on required check `e2e` |
| #18 | docs: u | 📨 Copilot requested | no review yet; will be ready next run |

Excluded: #10 `chore(main): release 2.3.0` (release PR) · #11 by @bob (filter: mine)

### To unblock
- #14: answer the Copilot review (point by point) on the PR.
- #15: needs an approval from someone other than you.
- #16: `test (node 20)` fails on top of current main. Likely needs a rebase fix.
```

Legend: ✅ merged · ⏳ auto-merge armed · ⏭ skipped (gate) · ❌ CI failed ·
📨 Copilot requested · 🚫 excluded. Include warnings (e.g. unresolved human
threads that aren't enforced) under the PR's row. End by offering the follow-ups
that only need you (address Copilot comments on #14, fix CI on #16, …) as a
separate task, and offering to re-run the queue later.

## Configuration

`SKILL/config/repos.json` holds per-repo defaults so the user doesn't repeat
themselves: e.g. a repo without Copilot (`"copilot": "off"`), one that uses
merge commits (`"method": "merge"`), one that doesn't need updating
(`"update": "none"`), extra release patterns, or bots whose comments count as
answering a Copilot review (`addressing_bots`). When the user states a lasting
preference for a repo ("in this repo we never use Copilot"), offer to save it
there.

Tests for the gate logic: `python3 -m unittest discover -s SKILL/tests`.

---
name: merge-queue
description: >-
  A merge queue for repos that don't have GitHub's native one (personal repos,
  private repos on Free/Team plans). Takes the open PRs into the default branch
  (main/master), oldest first, one at a time: checks the gates (ready for
  review, Copilot review arrived and handled per its green/blue/yellow verdict,
  required approvals, no conflicts, no hold labels), rebases on the default
  branch, waits for all CI to go green, then merges via auto-merge (squash by
  default). Any PR failing a gate is skipped with a reason, never fixed.
  Release PRs are left out. Before touching anything it shows a schematic
  briefing of what it will do and which rules apply, and waits for a go-ahead.
  Ends with a report. Use when the user says "merge queue", "/merge-queue",
  "run the queue", "land / merge my open PRs", "mergia le PR", "fai girare la
  merge queue", "process the ready PRs", or asks to rebase-and-merge a batch
  of PRs. By default only the PRs of the person running it.
---

# Merge queue (for repos without one)

You are acting as GitHub's merge queue for the repo in the current working
directory. One PR at a time, in order: check it can go, bring it up to date,
let CI prove it, merge it, move on. A PR that fails a gate is skipped, not fixed.
The user sees a briefing before anything happens and a report at the end.

The heavy lifting (reading the GraphQL state, judging each gate, waiting on CI)
is done by `scripts/mq.py` (stdlib Python + an authenticated `gh`). Run it rather
than judging gates by eye: the rules below are encoded there and unit-tested.
`SKILL` below means this skill's directory.

## 0. Parse the invocation

Defaults come from `SKILL/config/repos.json` (`"*"` → `"owner/*"` → `"owner/repo"`),
then whatever the user said overrides them. Map their words to flags:

| User says | Flag | Default |
|---|---|---|
| "mine" / "all" / "@alice,@bob" | `--author me\|all\|alice,bob` | `me`: only PRs opened by the person running the skill (the `gh`-authenticated user) |
| "#12 #15 #9" (explicit PRs, in that order) | `--pr 12 15 9` | all open PRs |
| "no copilot" / "copilot required" | `--copilot off\|required` | `auto` (detected from repo history) |
| "don't update" / "update with merge" | `--update none\|merge` | `rebase` |
| "merge commit" / "rebase merge" | `--method merge\|rebase` | `squash` (falls back to what the repo allows) |
| "dry run" / "just check" / "report only" | none: stop after the briefing | off |

Explicit PR numbers skip the author filter, but nothing else: release PRs and
PRs that don't target the default branch stay out.

**Base branch is fixed:** only PRs into the repo's default branch
(`main`/`master`/whatever the repo's default is) are ever queued. PRs into any
other branch (stacked PRs, release branches, `develop`) are listed as excluded.
There is no flag to change this.

## 1. Preflight

```bash
gh auth status            # must be logged in with write access to the repo
gh repo view --json nameWithOwner -q .nameWithOwner
```

If `gh` is missing or unauthenticated (e.g. a cloud session that only has the
GitHub MCP tools), follow `references/mcp-fallback.md` instead of the script.

## 2. Briefing, then wait for the go-ahead

```bash
python3 SKILL/scripts/mq.py status --format brief [flags]   # show this to the user
python3 SKILL/scripts/mq.py status [flags]                  # JSON you act on
```

The `brief` output is a schematic summary: the settings in force (which PRs,
order, Copilot, update, merge method, branch rules found), the gates, and a
table with the plan for each PR. **Present it to the user in their language**,
keeping it schematic and plain. Someone who doesn't know GitHub internals
should understand what will happen. Don't add prose around it.

Then **stop and wait for the user's go-ahead.** Nothing is changed before it.
Skip the wait only if the invocation already said so ("go", "senza chiedere",
"don't ask").

**Blue Copilot reviews (and yellow ones without inline threads)** that have
comments after them come out as `next: confirm`. The skill never assumes those
comments resolve the review. The briefing lists the review link and the links of
the comments posted after it, under "Need your answer". Ask the user which
ones are resolved in the same message as the go-ahead. Re-run `status` with
`--confirmed 14 17` for the PRs they confirm. The PRs they don't confirm are
skipped as "Copilot review not confirmed resolved".

Also read `notes`. If the viewer has no write permission, stop after the
briefing. If the branch has a native merge queue, say so (the user may prefer
it); `gh pr merge --auto` would enqueue there.

**Dry run:** the briefing is the whole output. Make no changes of any kind.

## 3. The gates (what `mq.py` checks, so you can explain it)

In order, for each PR. Any failure → `next: skip` with the reason in `blockers`.

1. **In the queue at all.** It must target the default branch. Release PRs
   (release-please / changesets branches, `autorelease:` labels,
   `chore: release x.y.z` titles; patterns in config) are out, and so are PRs by
   other authors under the default `me` filter.
2. **Ready for review.** Drafts, hold labels (`do-not-merge`, `wip`, `hold`,
   `blocked`, …) and `[WIP]` titles are skipped.
3. **Copilot review arrived and handled** (when the repo uses Copilot; `auto`
   detects it from this and recent PRs). **The skill never requests a Copilot
   review**: if none arrived it only reports it ("none requested" or "requested,
   not arrived yet") and skips. The latest Copilot review's verdict decides:
   - 🟢 *Approval recommended*: OK once every Copilot thread is resolved.
   - 🔵 *Needs a closer look*: every thread resolved, **and** the user confirms it
     is resolved. No comment since the review → skip. Comments since the review →
     ask the user, with links (step 2). CI-bot comments are ignored.
   - 🟡 *Changes recommended*: every Copilot thread resolved. If the review had no
     inline threads, it's treated like blue.
   - No verdict (older format): every Copilot thread resolved.
4. **Approvals.** If branch rules require reviews and they're missing
   (`reviewDecision: REVIEW_REQUIRED`), skip and say how many are needed and
   whether code owners must approve. An outstanding *changes requested* from a
   human blocks too, even if no rule enforces it. Unresolved non-Copilot
   threads block only when the rules require conversation resolution;
   otherwise they become a warning.
5. **No conflicts** with the default branch. Only `MERGEABLE` passes: while
   GitHub is still computing it (`UNKNOWN`) the script retries a few times,
   then skips with "re-run shortly".
6. **Up to date** (`--update rebase` by default): if behind, `next: update`.
   Then CI must pass on the new head before merging: every check green,
   GitHub's aggregate check state not worse, and every check the branch rules
   require actually reported.

The script fails closed: if a PR has more labels or review threads than it can
read in one go (over 100), it skips the PR and asks for a manual check instead
of guessing.

## 4. Run the queue

Process `queue` in order. Keep a running log per PR (result + reason) for the
report. **Re-run `mq.py status --pr N [--confirmed …]` right before acting on
each PR**, because merging the previous PR moved the base, and act on that fresh
`next`:

- `skip`: record the blockers; go to the next PR.
- `confirm`: the user didn't confirm this one → record "Copilot review not
  confirmed resolved", with the links; go to the next PR.
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
python3 SKILL/scripts/mq.py status --pr N [--confirmed N]
# d. merge: --<merge_method> from the snapshot (--squash | --merge | --rebase);
#    --auto only when auto_merge_allowed is true, otherwise leave it out
gh pr merge N [--auto] --<merge_method> --match-head-commit <head_sha>
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
- **c.** It must say `next: merge` again. Things that can change it: a Copilot
  re-review triggered by the rebase may have landed (yellow, new threads, or a
  new blue that needs asking → skip and report it), stale approvals may have
  been dismissed, or the base may have moved again (`update` → back to a; at
  most 3 cycles per PR, then skip as "base keeps moving").
- **d.** Build the flags from the snapshot: `merge_method` gives `--squash`,
  `--merge` or `--rebase`. Pass `--auto` only if `auto_merge_allowed` is true;
  otherwise (common on private repos on Free plans) merge directly, which is
  fine because everything was just verified green. If `--auto` fails with "clean
  status" or similar, the PR is already mergeable, so merge directly. Never
  pass `--admin`. Don't pass `--delete-branch`; the repo's setting decides.
- **e.** Exit 0 means merged: next PR. Exit 2 means it didn't merge (e.g.
  waiting on a required check or review GitHub still enforces). Record "armed,
  waiting on <mergeStateStatus>" and go on.

**Final sweep (once):** if anything merged and some PRs were skipped only for
transient reasons (Copilot not arrived yet, CI still running), re-run `status`
once and process any PR whose `next` is now `update`/`wait_checks`/`merge`. One
sweep, not a loop. A PR that newly needs `confirm` goes in the report as a
question, not a new prompt mid-run.

### Hard rules

- **Briefing first.** No change of any kind before the user has seen the
  briefing and said go (unless the invocation already said not to ask).
- **Gatekeeper, not fixer.** Don't edit code, resolve threads, answer Copilot,
  **request Copilot reviews**, approve, or re-run CI to get a PR through. Those
  belong to the PR's author. At the end, offer to do them as a separate task.
- **Never decide a blue review is resolved yourself.** Show the links and ask.
- **Default branch only.** Never update or merge a PR into any other branch.
- **Never rewrite branches locally.** Updates happen server-side
  (`update-branch`) only. No local rebase, no force-push, especially on other
  people's PRs.
- **Never bypass protections** (`--admin`, disabling rules, dismissing reviews).
- **Strictly serial.** Don't update or merge PR *n+1* until PR *n* has merged
  or been skipped. Updating several at once defeats the point (each must be
  tested on top of what lands before it) and wastes CI.
- **Release PRs are never touched**, even if listed explicitly.
- Dry run means no mutations at all.

## 5. Report

Write it in the language the user invoked the skill in. Keep it scannable:

```markdown
## Merge queue: owner/repo → main
squash · rebase-update · only @you · Copilot: used · 6 in queue, 2 excluded

| PR | Title | Result | Why / next step |
|---|---|---|---|
| #12 | feat: x | ✅ merged | rebased, 7 checks green |
| #14 | fix: y | ❓ not confirmed | 🔵 Copilot [review](url): comment [by @you](url), not confirmed resolved |
| #15 | chore: z | ⏭ skipped | needs 1 approving review (has 0) |
| #16 | feat: w | ❌ CI failed | `test (node 20)` failed after rebase ([run](url)) |
| #17 | feat: v | ⏳ armed | auto-merge on; waiting on required check `e2e` |
| #18 | docs: u | ⏭ skipped | no Copilot review, none requested |

Excluded: #10 `chore(main): release 2.3.0` (release PR) · #11 by @bob (only your PRs) · #13 into `develop` (not the default branch)

### To unblock
- #14: confirm the Copilot review is resolved (or answer it), then re-run.
- #15: needs an approval from someone other than you.
- #16: `test (node 20)` fails on top of current main. Likely needs a rebase fix.
- #18: request a Copilot review if you want it in the queue.
```

Legend: ✅ merged · ⏳ auto-merge armed · ⏭ skipped (gate) · ❌ CI failed ·
❓ needs your confirmation · 🚫 excluded. Include warnings (e.g. unresolved
human threads that aren't enforced) under the PR's row. End by offering the
follow-ups that only need you (address Copilot comments on #14, fix CI on #16, …)
as a separate task, and offering to re-run the queue later.

## Configuration

`SKILL/config/repos.json` holds per-repo defaults so the user doesn't repeat
themselves: e.g. a repo without Copilot (`"copilot": "off"`), one that uses
merge commits (`"method": "merge"`), one that doesn't need updating
(`"update": "none"`), extra release patterns, or bots whose comments are shown
as candidate answers to a Copilot review (`addressing_bots`). When the user
states a lasting preference for a repo ("in this repo we never use Copilot"),
offer to save it there.

Tests for the gate logic: `python3 -m unittest discover -s SKILL/tests`.

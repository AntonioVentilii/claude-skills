---
name: merge-queue
description: >-
  A merge queue for repos that don't have GitHub's native one (personal repos,
  private repos on Free/Team plans). Takes the open PRs into the default branch
  (main/master), oldest first, one at a time: checks the gates (ready for
  review, Copilot review arrived and handled per its green/blue/yellow verdict,
  required approvals, no conflicts, no hold labels), updates it with the
  default branch like GitHub's "Update branch" button (merge commit, GitHub's
  default), waits for all CI to go green, then merges it directly (squash by
  default; GitHub auto-merge only if configured). Any PR failing a gate is skipped with a reason, never fixed.
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
| "don't update" / "update with rebase" | `--update none\|rebase` | `merge`: GitHub's **Update branch** button with its default, *Update with merge commit* |
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
table with the plan for each PR. The script prints it in English: **translate
every line, headings and table included, into the user's language** before
showing it, keeping it schematic and plain. Someone who doesn't know GitHub internals
should understand what will happen. Don't add prose around it.

Then **stop and wait for the user's go-ahead.** Nothing is changed before it.
If the briefing says no PR can go (no open PRs, or every one is skipped or out
of the queue), there is nothing to approve: present it as the final answer,
with what would unblock the skipped ones, and stop.
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

**Approved list.** The go-ahead covers exactly the PRs in the briefing's
queue, nothing else. Write their numbers down (e.g. `APPROVED="100 105 106"`).
From here on, every `status` call is `status --pr $APPROVED_STILL_OPEN`, so a
PR that shows up mid-run can never be merged by this run. That includes PRs
retargeted to the default branch after their base PR merged, or new ones. Such PRs go
in the report as "appeared during the run, not processed".

**Approved heads.** The go-ahead also covers each PR's content as it was in
the briefing. Write down each PR's `head_sha` from the JSON
and pass them to every later `status` call as separate `N=SHA` arguments,
written out (`--approved-heads 102=64ad16b 103=8298b6d`), or as one quoted
string (`--approved-heads "$HEADS"`). Never pass an unquoted `$HEADS`: zsh,
the default shell on macOS, doesn't split it. The script now rejects anything
malformed, and lists under `notes` any approved PR it had no head for: if
that note appears, the check didn't run for that PR, so fix the command. If someone else pushes to a PR during the run:
- if the push is only a merge of the base (someone pressed Update branch, or
  merged `origin/main` locally), the run continues, with a warning that goes
  in the report. A merge counts as "of the base" when one of its parents is in
  the base's history, whatever its commit message says;
- if it adds new commits, or rewrites the branch, the PR is skipped as "not
  what you approved". It goes in the queue of the next run.

After **your own** update in step a, replace that PR's entry with the new head
that `wait-checks` reports, so your own merge commit isn't flagged.

**Stacked PRs.** When a queued PR is the base of other open PRs, the briefing
lists them under "Stacked PRs": merging it makes GitHub retarget them to the
default branch (when the branch is deleted on merge), still carrying the
original commits, which can conflict after a squash. Say this plainly; the
user may prefer to merge differently.

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
   otherwise they become a warning. Branch rules the script doesn't model
   (e.g. `code_quality`, extra-approval or stale-review parameters) are listed
   in the briefing as "Other branch rules": GitHub still enforces them, so a
   merge they block shows up as "not merged" in step e. A `copilot_code_review`
   rule tells the script the repo uses Copilot, and whether Copilot re-reviews
   after every push.
5. **No conflicts** with the default branch. Only `MERGEABLE` passes: while
   GitHub is still computing it (`UNKNOWN`) the script retries a few times,
   then skips with "re-run shortly".
6. **Up to date**: if behind, `next: update`. "Update" means what GitHub's
   **Update branch** button does, with GitHub's default method, *Update with
   merge commit* (`gh pr update-branch N`). GitHub has no repo setting for
   that method (the UI only remembers each user's last pick), so the skill
   uses GitHub's default. *Update with rebase* (`--rebase`) is used only when
   the repo's config says `"update": "rebase"`.
   Then CI must pass on the new head before merging: every check green,
   GitHub's aggregate check state not worse, and every check the branch rules
   require actually reported.
   **With `"update": "rebase"` only — "mergeable" doesn't mean "rebaseable".** GitHub's conflict check is a
   merge. A rebase replays the PR's commits one by one, and it conflicts when
   the PR still carries commits of another PR that was already squash-merged
   (typically a PR that was stacked on it), or when the PR has merge commits.
   The script spots this (`rebase_risk`) and gives each PR an `update_method`:
   `rebase`, or `merge` (the base is merged into the PR) for those PRs. That is
   safe only because the final merge is a squash, so no merge commit reaches
   the base. With another merge method, or `"rebase_fallback": "skip"`, those
   PRs are skipped instead. The briefing states the cause once for all the
   PRs that share it.

The script fails closed: if a PR has more labels or review threads than it can
read in one go (over 100), it skips the PR and asks for a manual check instead
of guessing.

## 4. Run the queue

Process the approved queue in order. Keep a running log per PR (result +
reason) for the report. **Re-run `mq.py status --pr N [--confirmed …]
--approved-heads <N=SHA …>` right
before acting on each PR**, because merging the previous PR moved the base, and
act on that fresh `next`:

- `skip`: record the blockers; go to the next PR.
- `confirm`: the user didn't confirm this one → record "Copilot review not
  confirmed resolved", with the links; go to the next PR.
- `update` → `wait_checks` → `merge`, the head-of-queue loop:

```bash
# a. update (server-side; never rebase/force-push locally)
OLD=$(gh pr view N --json headRefOid -q .headRefOid)
gh pr update-branch N                   # add --rebase only when update_method is "rebase"
# b. wait for CI on the new head. One call waits up to ~9 min; repeat while it
#    exits 2, until wait_timeout_minutes (config, default 45) is used up.
python3 SKILL/scripts/mq.py wait-checks --pr N --not-sha $OLD --timeout-sec 540
#    (no --not-sha when there was no update)
# c. re-verify everything on the final head
python3 SKILL/scripts/mq.py status --pr N [--confirmed N] --approved-heads N=<approved sha>
# d. merge: --<merge_method> from the snapshot (--squash | --merge | --rebase).
#    Direct merge by default; add --auto only when merge_mode is "auto".
gh pr merge N --<merge_method> --match-head-commit <head_sha>
# e. confirm it landed before touching the next PR
python3 SKILL/scripts/mq.py wait-merged --pr N --timeout-sec 180
```

How to read each step:

- **a.** Use the PR's `update_method` from the fresh `status`: no flag for
  `merge` (the default, like the Update branch button), `--rebase` for `rebase`. If a rebase fails with `rebase conflict
  between base and head` that the script didn't predict, and the snapshot has
  `merge_method: squash` and `rebase_fallback: merge`, run
  `gh pr update-branch N` (merge) **once** and say so in the report.
  Otherwise, or if that fails too (a real conflict), skip with the reason. A
  fork without maintainer edits, or a rule that rejects the update, means skip.
  If it says the branch is already up to date, carry on. On success it prints
  "✓ PR branch updated" and exits 0, but the head SHA changes a few seconds
  **later**: that's why b passes `--not-sha $OLD`. Never read the checks right
  after the update without it, or you'd be looking at the old head's CI.
- **b.** `wait-checks` returns 0 when everything is green, or when no CI
  registered within the settle time; it prints JSON. Exit 1 means CI failed:
  skip, naming the failing checks. Don't re-run them and don't fix them. If
  the time budget runs out (exit 2): skip with "CI still running after N min"
  (in `merge_mode: auto` only, arm auto-merge instead and record "auto-merge
  armed, CI still running").
- **c.** It must say `next: merge` again. Things that can change it: a Copilot
  re-review triggered by the update may have landed (yellow, new threads, or a
  new blue that needs asking → skip and report it), stale approvals may have
  been dismissed, or the base may have moved again (`update` → back to a; at
  most 3 cycles per PR, then skip as "base keeps moving"), or someone else
  pushed new commits since the briefing (approved-head check → skip).
- **d.** `merge_method` from the snapshot gives `--squash`, `--merge` or
  `--rebase`. `--match-head-commit` makes GitHub refuse the merge if the head
  moved since c. **Default `merge_mode: direct`**: merge now, no `--auto`.
  Everything was just verified green on this exact head. `--auto` is used only
  when the config sets `"auto_merge": true` and the snapshot says `merge_mode:
  auto`. If `--auto` then fails with "clean status", merge directly. Never pass
  `--admin`. Don't pass `--delete-branch`; the repo's setting decides.
  A direct `gh pr merge` prints **nothing** and exits 0 on success, so don't
  read silence as failure (or success): step e is what confirms it.
- **e.** Exit 0 means merged: next PR. Exit 2 means it didn't merge (e.g. a
  required check or review GitHub still enforces). Record "not merged, waiting
  on <mergeStateStatus>" (or "armed" in auto mode) and go on.

**Final sweep (once):** if anything merged and some **approved** PRs were
skipped only for transient reasons (Copilot not arrived yet, CI still running,
mergeability unknown), re-run `status --pr <those numbers>` once and process any
whose `next` is now `update`/`wait_checks`/`merge`. Only approved PRs, never
the whole repo. One sweep, not a loop. A PR that newly needs `confirm` goes in the report as a
question, not a new prompt mid-run.

### Hard rules

- **The user's own instructions win.** If their CLAUDE.md or settings forbid
  something this skill describes (e.g. `gh pr merge --auto`), follow theirs and
  use the alternative given here (direct merge). Say so in the report.
- **Only the approved PRs.** Never update or merge a PR that wasn't in the
  briefing the user said go to, even if it becomes eligible mid-run.
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
squash · update: merge commit · only @you · Copilot: used · 6 in queue, 2 excluded

| PR | Title | Result | Why / next step |
|---|---|---|---|
| #12 | feat: x | ✅ merged | updated with main, 7 checks green |
| #14 | fix: y | ❓ not confirmed | 🔵 Copilot [review](url): comment [by @you](url), not confirmed resolved |
| #15 | chore: z | ⏭ skipped | needs 1 approving review (has 0) |
| #16 | feat: w | ❌ CI failed | `test (node 20)` failed after the update ([run](url)) |
| #17 | feat: v | ⏸ not merged | merge refused: waiting on required check `e2e` |
| #18 | docs: u | ⏭ skipped | no Copilot review, none requested |

Excluded: #10 `chore(main): release 2.3.0` (release PR) · #11 by @bob (only your PRs) · #13 into `develop` (not the default branch)

### To unblock
- #14: confirm the Copilot review is resolved (or answer it), then re-run.
- #15: needs an approval from someone other than you.
- #16: `test (node 20)` fails on top of current main. Likely needs a fix for the latest main.
- #18: request a Copilot review if you want it in the queue.
```

Legend: ✅ merged · ⏸ not merged (⏳ armed, in auto mode) · ⏭ skipped (gate) ·
❌ CI failed · ❓ needs your confirmation · 🚫 excluded.

- **Fresh numbers.** Take figures like "behind by N" from the `status` you ran
  right before acting on that PR, not from the briefing: they change after
  every merge.
- **Under each row:** its warnings, e.g. unresolved human threads that aren't
  enforced, or "N new commits since the Copilot review" (information, not a
  gate).
- **One shared cause, said once.** When several PRs share one cause (e.g. the
  same rebase conflict), state it once below the table with the fix, and keep
  their rows short ("see below").
- **Changed during the run.** After the table, list anything that changed
  around the queue: stacked PRs retargeted, PRs that appeared, conflicts that
  appeared ("not processed"), and any head that someone else pushed to during
  the run, with what they pushed and whether the PR went ahead or was skipped.

End by offering the follow-ups that only need the user (address Copilot
comments on #14, fix CI on #16, …) as a separate task, and offering to re-run
the queue later.

## Configuration

`SKILL/config/repos.json` holds per-repo defaults so the user doesn't repeat
themselves: e.g. a repo without Copilot (`"copilot": "off"`), one that uses
merge commits (`"method": "merge"`), one that doesn't need updating
(`"update": "none"`), GitHub auto-merge instead of direct merges
(`"auto_merge": true`, off by default), *Update with rebase* instead of GitHub's default
merge commit (`"update": "rebase"`), and with it what to do when a rebase can't work
(`"rebase_fallback": "merge"`, the default, or `"skip"`), extra release patterns, or bots whose comments are shown
as candidate answers to a Copilot review (`addressing_bots`). When the user
states a lasting preference for a repo ("in this repo we never use Copilot"),
offer to save it there.

Tests for the gate logic: `python3 -m unittest discover -s SKILL/tests`.

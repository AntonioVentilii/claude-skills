# merge-queue: how to use it

A merge queue for repos without GitHub's: it takes your open PRs into the
default branch, oldest first, **one at a time**. For each one it checks the
PR can go, brings it up to date with the default branch, waits for CI, then
merges it. It always shows a briefing first and waits for your go-ahead.

Run it **inside the repo's folder** (its clone), in a Claude Code chat.

## Examples

| You type | What happens |
|---|---|
| `/merge-queue` | Your open PRs into `main`, oldest first. Briefing first, then it waits for your go-ahead. |
| `/merge-queue dry run` | Briefing only: what it would do and why. Nothing is changed. |
| `/merge-queue #12 #15` | Only those PRs, in that order. |
| `/merge-queue all` | Everyone's PRs, not only yours. |
| `/merge-queue @alice,@bob` | Only the PRs of those people. |
| `/merge-queue no copilot` | Don't check Copilot reviews in this run. |
| `/merge-queue copilot required` | Every PR must have a Copilot review, even if the repo rarely uses it. |
| `/merge-queue update with rebase` | Bring PRs up to date with *Update with rebase* instead of GitHub's default merge commit. |
| `/merge-queue don't update` | Merge PRs without bringing them up to date first. |
| `/merge-queue merge commit` | Merge with a merge commit instead of squash (if the repo allows it). |
| `/merge-queue go, don't ask` | Skip the wait for your go-ahead after the briefing. |
| `/merge-queue help` | This page. |

You can also just say it in words: "fai girare la merge queue", "mergia le
mie PR", "run the queue on #12 and #15, dry run".

## What a PR needs to go

1. Ready for review: not a draft, no `do-not-merge` / `wip` / `hold` label or `[WIP]` title.
2. Its Copilot review has arrived and is handled (when the repo uses Copilot):
   - 🟢 green: every Copilot thread resolved;
   - 🔵 blue: threads resolved, and **you** confirm the comments after it resolve it (it asks, with links);
   - 🟡 yellow: every Copilot thread resolved.

   The skill never requests a Copilot review for you.
3. The approvals the branch rules require; no open "changes requested".
4. No merge conflicts.
5. After the update, every check green.

A PR that fails any of these is **skipped with the reason**, never fixed.
Release PRs and PRs into other branches are left out.

## During the run

- It only touches the PRs you approved in the briefing, as they were then.
- If someone pushes new code to one of them mid-run, that PR is skipped.
- If someone else merges one, it's reported.
- It never uses `--admin`, never force-pushes, never rebases locally.

At the end you get a report: what was merged, what was skipped and why, what to do to unblock it, and what changed around the queue while it ran.

## Per-repo settings

Lasting preferences for a repo go in `merge-queue/config/repos.json` in the
claude-skills clone (or just tell Claude "in this repo we never use Copilot"
and it offers to save it). Keys:

- `author`: `me` | `all` | list of logins;
- `copilot`: `auto` | `required` | `off`;
- `update`: `merge` | `rebase` | `none`;
- `method`: `squash` | `merge` | `rebase`;
- `auto_merge`: `false` | `true`;
- `rebase_fallback`: `merge` | `skip`;
- `exclude_labels`, release patterns, `wait_timeout_minutes`.

Example, for a repo without Copilot that uses merge commits:

```json
{ "repos": { "owner/repo": { "copilot": "off", "method": "merge" } } }
```

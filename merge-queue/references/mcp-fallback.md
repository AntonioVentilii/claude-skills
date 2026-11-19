# Running the queue without `gh` (GitHub MCP tools only)

Use this only when `gh` is missing or unauthenticated, e.g. in a cloud session
that only exposes the GitHub MCP server. The gate rules in `SKILL.md` section 3
don't change. You apply them yourself from the tool output, because `mq.py`
can't run here.

## Step mapping

| Step | MCP tool |
|---|---|
| list open PRs | `list_pull_requests` (state `open`, sort `created`, direction `asc`) |
| PR details: draft, base, head sha, mergeable / mergeable_state, author, labels | `pull_request_read` method `get` |
| reviews (Copilot verdict in body, approvals, changes requested) | `pull_request_read` method `get_reviews` |
| review threads + resolved state | `pull_request_read` method `get_review_comments` |
| PR conversation comments (answers to a blue review) | `pull_request_read` method `get_comments` |
| CI | `pull_request_read` methods `get_check_runs` **and** `get_status` (both: check runs and commit statuses) |
| update branch | `update_pull_request_branch` with `expectedHeadSha` |
| merge (default) | `merge_pull_request` with `merge_method` and `expectedHeadSha` |
| arm auto-merge (only with `auto_merge: true`) | `enable_pr_auto_merge` (`mergeMethod`: `SQUASH` / `MERGE` / `REBASE`) |

## Differences from the `gh` path

- Same hard rules as `SKILL.md`: briefing and go-ahead first, default branch
  only, only the approved PRs, direct merge unless `auto_merge: true`, never
  request Copilot, ask the user about blue reviews (with links).
- **No rebase update.** `update_pull_request_branch` only merges the base into
  the branch. With `update: rebase` (the default), tell the user the update
  will be a merge commit instead, and proceed only if they agree, or use
  `update: none` for this run.
- **No branch-rules endpoint.** Infer required approvals from
  `mergeable_state == "blocked"` combined with missing approvals in
  `get_reviews`, and say in the report that the requirement was inferred.
- **Copilot detection (`auto`).** Treat the repo as using Copilot if any open PR
  has a review from `copilot-pull-request-reviewer[bot]` (or `Copilot`).
- **Waiting on CI.** Poll `get_check_runs` / `get_status` every ~30 s (a short
  Bash `sleep` between calls is fine) for up to `wait_timeout_minutes`. Confirm
  the head sha changed after an update before trusting the results.
- **Auto-merge on a clean PR.** `enable_pr_auto_merge` fails when the PR is
  already mergeable. Then call `merge_pull_request` directly.
- Allowed merge methods aren't exposed: try the preferred one. If GitHub
  rejects it, try the next in `squash → rebase → merge`, and note the fallback.

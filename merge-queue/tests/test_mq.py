"""Unit tests for the pure gate logic in scripts/mq.py (no network).

Run: python3 -m unittest discover -s merge-queue/tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import mq  # noqa: E402

CP = {"login": "copilot-pull-request-reviewer", "__typename": "Bot"}
ME = {"login": "antonio", "__typename": "User"}
BOB = {"login": "bob", "__typename": "User"}
CODECOV = {"login": "codecov", "__typename": "Bot"}
CLAUDE = {"login": "claude", "__typename": "Bot"}


def conn(*items):
    return {"nodes": list(items)}


def pr(**kw):
    base = {
        "number": 1, "title": "feat: thing", "url": "u", "isDraft": False, "state": "OPEN", "merged": False,
        "author": ME, "baseRefName": "main", "headRefName": "feat/thing", "headRefOid": "abc",
        "isCrossRepository": False, "maintainerCanModify": True, "labels": conn(),
        "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "reviewDecision": None, "autoMergeRequest": None,
        "reviewRequests": conn(), "reviews": conn(), "comments": conn(), "reviewThreads": conn(),
        "commits": conn({"commit": {"oid": "abc", "statusCheckRollup": {"state": "SUCCESS", "contexts": conn(
            {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"})}}}),
    }
    base.update(kw)
    return base


def review(body, at="2026-11-01T10:00:00Z", author=CP, state="COMMENTED", rid="R1"):
    return {"id": rid, "author": author, "state": state, "body": body, "submittedAt": at}


def thread(resolved, rid="R1", replies=()):
    cs = [{"author": CP, "createdAt": "2026-11-01T10:00:00Z", "pullRequestReview": {"id": rid}}]
    cs += [{"author": a, "createdAt": at, "pullRequestReview": None} for a, at in replies]
    return {"isResolved": resolved, "isOutdated": False, "comments": conn(*cs)}


def ctx(**kw):
    c = {"cfg": dict(mq.DEFAULTS), "viewer": "antonio", "base": "main",
         "rules": {"required_approvals": 0, "thread_resolution": False}, "repo_uses_copilot": True,
         "explicit": False, "behind": {1: 0}}
    c.update(kw)
    return c


GREEN = "## Pull request overview\n🟢 **Approval recommended** — small, safe change."
BLUE = "🔵 **Needs a closer look** — touches auth."
YELLOW = "🟡 **Changes recommended** — bug in loop."


class Verdict(unittest.TestCase):
    def test_colors(self):
        self.assertEqual(mq.copilot_verdict(GREEN), "green")
        self.assertEqual(mq.copilot_verdict(BLUE), "blue")
        self.assertEqual(mq.copilot_verdict(YELLOW), "yellow")
        self.assertEqual(mq.copilot_verdict("Copilot reviewed 3 out of 3 changed files"), "none")
        self.assertEqual(mq.copilot_verdict("Approval recommended. No changes recommended."), "green")


class CopilotGate(unittest.TestCase):
    def ev(self, p, mode="auto", uses=True, confirmed=False):
        return mq.eval_copilot(p, mode, uses, mq.DEFAULTS, confirmed=confirmed)

    def test_green_clean(self):
        self.assertEqual(self.ev(pr(reviews=conn(review(GREEN))))["status"], "ok")

    def test_green_with_unresolved_thread(self):
        r = self.ev(pr(reviews=conn(review(GREEN)), reviewThreads=conn(thread(False))))
        self.assertEqual(r["status"], "unhandled")

    def test_blue_without_comment_is_unhandled(self):
        self.assertEqual(self.ev(pr(reviews=conn(review(BLUE))))["status"], "unhandled")

    def test_blue_with_comment_asks_user_with_links(self):
        c = {"url": "https://x/c1", "author": ME, "createdAt": "2026-11-01T11:00:00Z"}
        p = pr(reviews=conn({**review(BLUE), "url": "https://x/r1"}), comments=conn(c))
        r = self.ev(p)
        self.assertEqual(r["status"], "confirm")
        self.assertEqual(r["review_url"], "https://x/r1")
        self.assertEqual([x["url"] for x in r["candidates"]], ["https://x/c1"])
        self.assertEqual(self.ev(p, confirmed=True)["status"], "ok")

    def test_blue_answer_before_review_does_not_count(self):
        p = pr(reviews=conn(review(BLUE)), comments=conn({"author": ME, "createdAt": "2026-11-01T09:00:00Z"}))
        self.assertEqual(self.ev(p)["status"], "unhandled")

    def test_blue_ci_bot_comment_does_not_count_but_claude_does(self):
        p = pr(reviews=conn(review(BLUE)), comments=conn({"author": CODECOV, "createdAt": "2026-11-01T11:00:00Z"}))
        self.assertEqual(self.ev(p)["status"], "unhandled")
        p = pr(reviews=conn(review(BLUE)), comments=conn({"author": CLAUDE, "createdAt": "2026-11-01T11:00:00Z"}))
        self.assertEqual(self.ev(p)["status"], "confirm")

    def test_yellow_threads_must_be_resolved(self):
        p = pr(reviews=conn(review(YELLOW)), reviewThreads=conn(thread(True), thread(False)))
        self.assertEqual(self.ev(p)["status"], "unhandled")
        p = pr(reviews=conn(review(YELLOW)), reviewThreads=conn(thread(True), thread(True)))
        self.assertEqual(self.ev(p)["status"], "ok")

    def test_yellow_without_threads_needs_answer(self):
        self.assertEqual(self.ev(pr(reviews=conn(review(YELLOW))))["status"], "unhandled")
        p = pr(reviews=conn(review(YELLOW)), comments=conn({"author": ME, "createdAt": "2026-11-01T11:00:00Z"}))
        self.assertEqual(self.ev(p)["status"], "confirm")

    def test_blue_with_unresolved_thread_does_not_ask(self):
        p = pr(reviews=conn(review(BLUE)), reviewThreads=conn(thread(False)),
               comments=conn({"author": ME, "createdAt": "2026-11-01T11:00:00Z"}))
        self.assertEqual(self.ev(p)["status"], "unhandled")

    def test_latest_review_wins(self):
        p = pr(reviews=conn(review(BLUE, rid="R1"), review(GREEN, at="2026-11-02T10:00:00Z", rid="R2")))
        r = self.ev(p)
        self.assertEqual((r["status"], r["verdict"]), ("ok", "green"))

    def test_pending_and_missing(self):
        req = conn({"requestedReviewer": {"__typename": "Bot", "login": "copilot-pull-request-reviewer"}})
        self.assertEqual(self.ev(pr(reviewRequests=req))["status"], "pending")
        self.assertEqual(self.ev(pr())["status"], "missing")
        self.assertEqual(self.ev(pr(), uses=False)["status"], "n/a")
        self.assertEqual(self.ev(pr(), mode="required", uses=False)["status"], "missing")
        self.assertEqual(self.ev(pr(), mode="off")["status"], "n/a")


class Evaluate(unittest.TestCase):
    def test_happy_path_merges(self):
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN))), ctx())
        self.assertEqual(r["next"], "merge", r)

    def test_behind_updates(self):
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN))), ctx(behind={1: 3}))
        self.assertEqual(r["next"], "update")

    def test_update_none_skips_rebase(self):
        c = ctx(behind={1: 3})
        c["cfg"]["update"] = "none"
        self.assertEqual(mq.evaluate_pr(pr(reviews=conn(review(GREEN))), c)["next"], "merge")

    def test_draft_and_author_and_release(self):
        self.assertEqual(mq.evaluate_pr(pr(isDraft=True), ctx(repo_uses_copilot=False))["next"], "skip")
        self.assertEqual(mq.evaluate_pr(pr(author=BOB), ctx())["next"], "excluded")
        c = ctx(repo_uses_copilot=False)
        c["cfg"]["author"] = "all"
        self.assertEqual(mq.evaluate_pr(pr(author=BOB), c)["next"], "merge")
        self.assertEqual(mq.evaluate_pr(pr(headRefName="release-please--branches--main"), ctx())["next"], "excluded")
        self.assertEqual(mq.evaluate_pr(pr(title="chore(main): release 1.4.0"), ctx())["next"], "excluded")
        self.assertEqual(mq.evaluate_pr(pr(title="chore: version packages"), ctx())["next"], "excluded")
        self.assertEqual(mq.evaluate_pr(pr(baseRefName="feat/base"), ctx())["next"], "excluded")

    def test_release_heuristics_do_not_overmatch(self):
        for t in ("feat: release notes page", "fix: releases list sorting", "docs: how we release"):
            self.assertIsNone(mq.is_release_pr(pr(title=t), mq.DEFAULTS), t)

    def test_approval_required(self):
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN)), reviewDecision="REVIEW_REQUIRED"),
                           ctx(rules={"required_approvals": 1}))
        self.assertEqual(r["next"], "skip")
        self.assertIn("requires 1 approving", " ".join(r["blockers"]))

    def test_changes_requested_by_human_blocks_even_if_not_enforced(self):
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN), review("pls fix", author=BOB, state="CHANGES_REQUESTED", rid="R9"))), ctx())
        self.assertEqual(r["next"], "skip")
        self.assertIn("@bob", " ".join(r["blockers"]))

    def test_ci_failing_and_pending(self):
        failing = conn({"commit": {"oid": "abc", "statusCheckRollup": {"contexts": conn(
            {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"})}}})
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN)), commits=failing), ctx())
        self.assertEqual(r["next"], "skip")
        pending = conn({"commit": {"oid": "abc", "statusCheckRollup": {"contexts": conn(
            {"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": None},
            {"__typename": "StatusContext", "context": "vercel", "state": "SUCCESS"})}}})
        self.assertEqual(mq.evaluate_pr(pr(reviews=conn(review(GREEN)), commits=pending), ctx())["next"], "wait_checks")

    def test_rerun_check_latest_wins(self):
        rerun = conn({"commit": {"oid": "abc", "statusCheckRollup": {"contexts": conn(
            {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"},
            {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"})}}})
        self.assertEqual(mq.checks_summary(pr(commits=rerun))["state"], "success")

    def test_conflicts_and_hold_label(self):
        self.assertEqual(mq.evaluate_pr(pr(reviews=conn(review(GREEN)), mergeable="CONFLICTING"), ctx())["next"], "skip")
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN)), labels=conn({"name": "do-not-merge"})), ctx())
        self.assertEqual(r["next"], "skip")

    def test_missing_copilot_is_reported_not_requested(self):
        r = mq.evaluate_pr(pr(), ctx())
        self.assertEqual(r["next"], "skip")
        self.assertIn("none requested", " ".join(r["blockers"]))

    def test_blue_confirm_flow(self):
        p = pr(reviews=conn(review(BLUE)), comments=conn({"author": ME, "createdAt": "2026-11-01T11:00:00Z"}))
        self.assertEqual(mq.evaluate_pr(p, ctx())["next"], "confirm")
        self.assertEqual(mq.evaluate_pr(p, ctx(confirmed={1}))["next"], "merge")
        # other blockers win: no point asking about a PR that is skipped anyway
        self.assertEqual(mq.evaluate_pr({**p, "isDraft": True}, ctx())["next"], "skip")

    def test_only_default_branch_even_when_explicit(self):
        r = mq.evaluate_pr(pr(baseRefName="develop", reviews=conn(review(GREEN))), ctx(explicit=True))
        self.assertEqual(r["next"], "excluded")
        self.assertIn("default branch", r["excluded"])


class Method(unittest.TestCase):
    def test_fallback(self):
        meta = {"squashMergeAllowed": False, "rebaseMergeAllowed": True, "mergeCommitAllowed": True}
        self.assertEqual(mq.choose_method(meta, {}, "squash")[0], "rebase")
        self.assertEqual(mq.choose_method(meta, {"allowed_methods": {"merge"}}, "squash")[0], "merge")
        meta = {"squashMergeAllowed": True, "mergeCommitAllowed": True}
        self.assertEqual(mq.choose_method(meta, {"linear_history": True}, "merge")[0], "squash")


class Config(unittest.TestCase):
    def test_layering(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"repos": {"*": {"method": "merge"}, "o/*": {"copilot": "off"}, "o/r": {"update": "none"}}}, f)
        cfg = mq.load_config("o/r", f.name)
        os.unlink(f.name)
        self.assertEqual((cfg["method"], cfg["copilot"], cfg["update"], cfg["author"]), ("merge", "off", "none", "me"))


if __name__ == "__main__":
    unittest.main()


class Brief(unittest.TestCase):
    def test_renders(self):
        import contextlib
        import io
        p = pr(reviews=conn({**review(BLUE), "url": "https://x/r1"}),
               comments=conn({"url": "https://x/c1", "author": ME, "createdAt": "2026-11-01T11:00:00Z"}))
        res = mq.evaluate_pr(p, ctx())
        out = {"repo": "o/r", "viewer": "antonio", "base": "main", "auto_merge_allowed": False,
               "merge_method_note": "squash (preferred)", "copilot_mode": "auto", "repo_uses_copilot": True,
               "config": {"author": "me", "update": "rebase"}, "rules": {"required_approvals": 1},
               "notes": [], "queue": [res], "excluded": [{"number": 2, "title": "chore: release 1.0.0", "reason": "release PR"}]}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mq.print_brief(out)
        text = buf.getvalue()
        for needle in ("only PRs opened by you (@antonio)", "default branch `main`", "https://x/r1", "https://x/c1",
                       "ASK YOU first", "1 approval(s)", "never requested", "not in queue"):
            self.assertIn(needle, text)


class FailClosed(unittest.TestCase):
    def ok_pr(self, **kw):
        return pr(reviews=conn(review(GREEN)), **kw)

    def test_changes_requested_decision_blocks_without_review_node(self):
        r = mq.evaluate_pr(self.ok_pr(reviewDecision="CHANGES_REQUESTED"), ctx())
        self.assertEqual(r["next"], "skip")
        self.assertIn("changes requested", " ".join(r["blockers"]))

    def test_unknown_mergeable_does_not_pass(self):
        r = mq.evaluate_pr(self.ok_pr(mergeable="UNKNOWN"), ctx())
        self.assertEqual(r["next"], "skip")
        self.assertIn("UNKNOWN", " ".join(r["blockers"]))

    def test_aggregate_state_wins_over_fetched_page(self):
        commits = conn({"commit": {"oid": "abc", "statusCheckRollup": {"state": "FAILURE", "contexts": {
            "totalCount": 150, "nodes": [{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]}}}})
        self.assertEqual(mq.checks_summary(pr(commits=commits))["state"], "failure")
        commits["nodes"][0]["commit"]["statusCheckRollup"]["state"] = "PENDING"
        self.assertEqual(mq.checks_summary(pr(commits=commits))["state"], "pending")

    def test_missing_required_check_is_pending(self):
        self.assertEqual(mq.checks_summary(pr(), ["ci", "e2e"])["state"], "pending")
        r = mq.evaluate_pr(self.ok_pr(), ctx(rules={"required_approvals": 0, "required_checks": ["e2e"]}))
        self.assertEqual(r["next"], "wait_checks")
        self.assertEqual(mq.checks_summary(pr(), ["ci"])["state"], "success")

    def test_truncated_labels_or_threads_block(self):
        many = {"totalCount": 101, "nodes": [{"name": "x"}] * 100}
        self.assertEqual(mq.evaluate_pr(self.ok_pr(labels=many), ctx())["next"], "skip")
        threads = {"totalCount": 120, "nodes": []}
        self.assertEqual(mq.evaluate_pr(self.ok_pr(reviewThreads=threads), ctx())["next"], "skip")

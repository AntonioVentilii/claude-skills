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


class FieldTest(unittest.TestCase):
    """Regressions from the first live run (AntonioVentilii/neve)."""

    def run_status(self, prs, fmt="json", rules_payload=None, meta_extra=None, cfg_extra=None, pr_args=None,
                   approved_heads=None, compare=None, open_bases=None, base_commits=("b", "m652"),
                   merge_checker=None):
        import argparse
        import contextlib
        import io
        from unittest import mock
        meta = {"nameWithOwner": "o/r", "isPrivate": True, "viewerPermission": "ADMIN",
                "defaultBranchRef": {"name": "main"}, "autoMergeAllowed": True,
                "squashMergeAllowed": True, "mergeCommitAllowed": True, "rebaseMergeAllowed": True}
        meta.update(meta_extra or {})
        rules_payload = rules_payload if rules_payload is not None else [
            {"type": "pull_request", "parameters": {"required_approving_review_count": 0,
                                                    "require_code_owner_review": True,
                                                    "allowed_merge_methods": ["squash", "rebase"]}}]

        def fake_rest(path):
            if "/rules/branches/" in path:
                return True, rules_payload
            if "/compare/" in path and path.endswith("...main"):
                # base history: <since>...main lists the base's commits; <sha>...main
                # says whether sha is an ancestor of main ("ahead") or not.
                frm = path.rsplit("/compare/", 1)[1].split("...")[0]
                return True, {"status": "ahead" if frm in base_commits else "behind",
                              "commits": [{"sha": c} for c in base_commits]}
            if "/compare/" in path and compare is not None:
                return True, compare
            return False, "404"
        cfg = dict(mq.DEFAULTS)
        cfg.update(cfg_extra or {})
        a = argparse.Namespace(repo="o/r", pr=pr_args, author=None, copilot=None, update=None, method=None,
                               confirmed=None, format=fmt, approved_heads=approved_heads)
        buf = io.StringIO()
        bases = open_bases if open_bases is not None else [(p_["number"], p_.get("baseRefName")) for p_ in prs]
        with mock.patch.object(mq, "fetch_repo", return_value=(meta, prs, "antonio")), \
                mock.patch.object(mq, "open_pr_bases", return_value=bases), \
                mock.patch.object(mq, "make_merge_checker", return_value=merge_checker), \
                mock.patch.object(mq, "rest", side_effect=fake_rest), \
                mock.patch.object(mq, "repo_uses_copilot", return_value=True), \
                mock.patch.object(mq, "behind_by", return_value=0), \
                mock.patch.object(mq, "load_config", return_value=cfg), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(mq.cmd_status(a), 0)
        return buf.getvalue()

    def queue(self):
        p100 = pr(number=100, headRefName="av/base", reviews=conn(review(YELLOW)), reviewThreads=conn(thread(True)))
        p101 = pr(number=101, baseRefName="av/base", headRefName="av/stacked", reviews=conn(review(GREEN)))
        p105 = pr(number=105, headRefName="av/other", reviews=conn(review(GREEN)))
        return [p100, p101, p105]

    def test_json_output_with_allowed_merge_methods(self):
        import json
        out = json.loads(self.run_status(self.queue()))
        self.assertEqual(out["rules"]["allowed_methods"], ["rebase", "squash"])
        self.assertEqual(out["merge_method"], "squash")

    def test_direct_merge_is_default(self):
        import json
        out = json.loads(self.run_status(self.queue()))
        self.assertEqual(out["merge_mode"], "direct")
        self.assertIn("direct merge", self.run_status(self.queue(), fmt="brief"))
        out = json.loads(self.run_status(self.queue(), cfg_extra={"auto_merge": True}))
        self.assertEqual(out["merge_mode"], "auto")
        out = json.loads(self.run_status(self.queue(), cfg_extra={"auto_merge": True}, meta_extra={"autoMergeAllowed": False}))
        self.assertEqual(out["merge_mode"], "direct")

    def test_stacked_dependents_flagged(self):
        import json
        out = json.loads(self.run_status(self.queue()))
        q = {r["number"]: r for r in out["queue"]}
        self.assertEqual(q[100]["dependents"], [101])
        self.assertIn("#101", " ".join(q[100]["warnings"]))
        self.assertIn("Stacked PRs", self.run_status(self.queue(), fmt="brief"))

    def test_brief_plan_why_and_closing_line(self):
        text = self.run_status(self.queue(), fmt="brief")
        row105 = [l for l in text.splitlines() if l.startswith("| [#105]")][0]
        self.assertIn("after the PRs above land", row105)
        row100 = [l for l in text.splitlines() if l.startswith("| [#100]")][0]
        self.assertIn("🟡", row100)
        self.assertNotIn("all gates pass", row100)
        self.assertTrue(text.rstrip().endswith("Reply to go ahead."), text[-200:])
        self.assertIn("only when someone else owns the files", text)

    def test_code_owner_rule_explained_in_approvals(self):
        r = mq.eval_approvals(pr(), {"code_owner_review": True})
        self.assertTrue(r["ok"])
        self.assertIn("code-owner rule exists but GitHub doesn't apply it here: no CODEOWNERS file", r["detail"])


def carried(*merged_pr_numbers, merge_commit=False):
    """prCommits for a PR that still carries commits of other, merged PRs."""
    nodes_ = [{"commit": {"oid": f"c{n}", "parents": {"totalCount": 1},
                          "associatedPullRequests": conn({"number": n, "merged": True})}} for n in merged_pr_numbers]
    nodes_.append({"commit": {"oid": "own", "parents": {"totalCount": 2 if merge_commit else 1},
                              "associatedPullRequests": conn()}})
    return {"totalCount": len(nodes_), "nodes": nodes_}


class SecondRun(unittest.TestCase):
    """Second live run on neve: six retargeted PRs failed `update-branch --rebase`
    because they still carried #100's commits, already squash-merged into main.
    Rebase updates are opt-in now (`"update": "rebase"`); these tests cover that path."""

    REBASE = {"update": "rebase"}

    def run_status(self, prs, fmt="json", cfg_extra=None, **kw):
        return FieldTest.run_status(self, prs, fmt=fmt, cfg_extra={**self.REBASE, **(cfg_extra or {})}, **kw)

    def rctx(self, **kw):
        c = ctx(**kw)
        c["cfg"]["update"] = "rebase"
        return c

    def neve(self):
        p101 = pr(number=101, reviews=conn(review(GREEN)))
        p102 = pr(number=102, reviews=conn(review(GREEN)), prCommits=carried(100))
        p103 = pr(number=103, reviews=conn(review(GREEN)), prCommits=carried(100))
        return [p101, p102, p103]

    def test_rebase_risk_detection(self):
        self.assertIsNone(mq.rebase_risk(pr()))
        self.assertIsNone(mq.rebase_risk(pr(number=7, prCommits=carried(7))))  # its own PR doesn't count
        r = mq.rebase_risk(pr(number=102, prCommits=carried(100)))
        self.assertEqual(r["merged_prs"], [100])
        self.assertEqual(mq.rebase_risk(pr(prCommits=carried(merge_commit=True)))["merge_commits"], 1)

    def test_predicted_conflict_switches_to_merge_update(self):
        c = self.rctx(behind={102: 3}, merge_method="squash")
        r = mq.evaluate_pr(pr(number=102, reviews=conn(review(GREEN)), prCommits=carried(100)), c)
        self.assertEqual((r["next"], r["update_method"]), ("update", "merge"))
        self.assertIn("#100", r["rebase_risk"]["reason"])

    def test_no_fallback_without_squash_or_when_disabled(self):
        p = pr(number=102, reviews=conn(review(GREEN)), prCommits=carried(100))
        r = mq.evaluate_pr(p, self.rctx(behind={102: 3}, merge_method="rebase"))
        self.assertEqual(r["next"], "skip")
        self.assertIn("rebase would conflict", " ".join(r["blockers"]))
        c = self.rctx(behind={102: 3}, merge_method="squash")
        c["cfg"]["rebase_fallback"] = "skip"
        self.assertEqual(mq.evaluate_pr(p, c)["next"], "skip")

    def test_rerun_no_longer_repeats_the_failing_plan(self):
        import json
        out = json.loads(self.run_status(self.neve()))
        q = {r["number"]: r for r in out["queue"]}
        self.assertEqual(q[101]["update_method"], "rebase")
        self.assertEqual(q[102]["update_method"], "merge")
        text = self.run_status(self.neve(), fmt="brief")
        row102 = [l for l in text.splitlines() if l.startswith("| [#102]")][0]
        self.assertIn("update with main via a merge commit", row102)
        self.assertNotIn("rebase", row102.split("|")[3])

    def test_common_cause_said_once(self):
        text = self.run_status(self.neve(), fmt="brief")
        self.assertEqual(text.count("carries the original commits of #100"), 1)
        self.assertIn("#102, #103: carries the original commits of #100", text)
        self.assertIn("If a rebase can't work", text)



class UpdateBranchDefault(unittest.TestCase):
    """Updating = GitHub's "Update branch" button with its default method,
    "Update with merge commit" (gh pr update-branch N, no --rebase)."""

    run_status = FieldTest.run_status

    def test_default_is_merge_commit(self):
        self.assertEqual(mq.DEFAULTS["update"], "merge")
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN))), ctx(behind={1: 2}))
        self.assertEqual((r["next"], r["update_method"]), ("update", "merge"))

    def test_carried_commits_dont_matter_for_merge_update(self):
        # Only a rebase replays commits: the merge-commit update just merges main in.
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN)), prCommits=carried(100)), ctx(behind={1: 2}))
        self.assertNotIn("rebase_risk", r)
        self.assertEqual(r["update_method"], "merge")

    def test_brief_names_the_button(self):
        import json
        p = [pr(number=101, reviews=conn(review(GREEN))), pr(number=102, reviews=conn(review(GREEN)), prCommits=carried(100))]
        text = self.run_status(p, fmt="brief")
        self.assertIn("Update branch", text)
        self.assertIn("Update with merge commit", text)
        self.assertNotIn("Why some PRs can't be rebased", text)
        self.assertNotIn("If a rebase can't work", text)
        out = json.loads(self.run_status(p))
        self.assertEqual({r["update_method"] for r in out["queue"]}, {"merge"})



def merge_commit(base="main", sha="m1"):
    return {"sha": sha, "parents": [{"sha": "a"}, {"sha": "b"}],
            "commit": {"message": f"Merge branch '{base}' into feature\n\nbody"}}


def plain_commit(msg="fix: tweak", sha="p1"):
    return {"sha": sha, "parents": [{"sha": "a"}], "commit": {"message": msg}}


class ThirdRun(unittest.TestCase):
    """Third live run on neve: all six merged, plus four findings."""

    run_status = FieldTest.run_status

    def test_later_prs_say_after_the_ones_above_even_when_behind(self):
        r = mq.evaluate_pr(pr(number=103, reviews=conn(review(GREEN))), ctx(behind={103: 2}))
        self.assertIn("after the PRs above land", mq.plan_text(r, "main", later=True))
        self.assertNotIn("after the PRs above land", mq.plan_text(r, "main", later=False))

    def test_behind_count_is_labelled_as_a_snapshot(self):
        r = mq.evaluate_pr(pr(reviews=conn(review(GREEN))), ctx(behind={1: 1}))
        self.assertIn("behind by 1 right now", mq.why_text(r))

    def test_commits_after_copilot_review(self):
        rv = {**review(YELLOW), "commit": {"oid": "c1"}}
        commits = {"totalCount": 4, "nodes": [
            {"commit": {"oid": "c1", "parents": {"totalCount": 1}}},
            {"commit": {"oid": "c2", "parents": {"totalCount": 1}}},
            {"commit": {"oid": "c3", "parents": {"totalCount": 2}}},
            {"commit": {"oid": "c4", "parents": {"totalCount": 1}}}]}
        p = pr(reviews=conn(rv), reviewThreads=conn(thread(True)), prCommits=commits)
        cp = mq.eval_copilot(p, "auto", True, mq.DEFAULTS)
        self.assertEqual(cp["status"], "ok")
        self.assertEqual(cp["after_review"], {"commits": 3, "merges": 1})
        self.assertIn("2 new commit(s) + 1 merge(s) of the base since the Copilot review", cp["detail"])
        gone = pr(reviews=conn({**rv, "commit": {"oid": "zz"}}), reviewThreads=conn(thread(True)), prCommits=commits)
        self.assertIn("history rewritten", mq.eval_copilot(gone, "auto", True, mq.DEFAULTS)["detail"])

    def test_classify_head_change(self):
        self.assertEqual(mq.classify_head_change({"status": "ahead", "commits": [merge_commit()]}, "main"),
                         {"kind": "merges_only", "count": 1})
        self.assertEqual(mq.classify_head_change({"status": "ahead", "commits": [merge_commit("origin/main")]}, "main")["kind"],
                         "merges_only")
        ch = mq.classify_head_change({"status": "ahead", "commits": [merge_commit(), plain_commit()]}, "main")
        self.assertEqual(ch, {"kind": "new_commits", "commits": ["fix: tweak"]})
        self.assertEqual(mq.classify_head_change({"status": "diverged", "commits": []}, "main")["kind"], "rewritten")
        # a merge of some other branch is new work, not a base update
        self.assertEqual(mq.classify_head_change({"status": "ahead", "commits": [merge_commit("feat/x")]}, "main")["kind"],
                         "new_commits")

    def test_head_changed_since_briefing(self):
        import json
        p = [pr(number=108, headRefOid="9eb2543ffff", reviews=conn(review(GREEN)))]
        # only a merge of main by someone else: continue, but say so
        out = json.loads(self.run_status(p, pr_args=[108], approved_heads=["108=64ad16b"],
                                         compare={"status": "ahead", "commits": [merge_commit("origin/main")]}))
        r = out["queue"][0]
        self.assertEqual(r["head_changed"]["kind"], "merges_only")
        self.assertNotEqual(r["next"], "skip")
        self.assertIn("pushed to it during the run", " ".join(r["warnings"]))
        # new work nobody approved: skip
        out = json.loads(self.run_status(p, pr_args=[108], approved_heads=["108=64ad16b"],
                                         compare={"status": "ahead", "commits": [plain_commit("feat: more")]}))
        r = out["queue"][0]
        self.assertEqual(r["next"], "skip")
        self.assertIn("feat: more", " ".join(r["blockers"]))
        # unchanged head: nothing to say
        out = json.loads(self.run_status(p, pr_args=[108], approved_heads=["108=9eb2543"]))
        self.assertNotIn("head_changed", out["queue"][0])



class FourthRun(unittest.TestCase):
    """Fourth live run (uliveto): 2 of 4 merged, plus seven findings."""

    run_status = FieldTest.run_status

    def test_heads_split_inside_one_argument(self):
        # zsh passes an unquoted $HEADS as ONE argument
        self.assertEqual(mq.parse_heads(["651=0505fb8 655=8298B6D,658=59ee43f"]),
                         {651: "0505fb8", 655: "8298b6d", 658: "59ee43f"})
        self.assertEqual(mq.parse_heads(["651=0505fb8", "655=8298b6d"]), {651: "0505fb8", 655: "8298b6d"})

    def test_bad_heads_are_an_error_not_a_skipped_check(self):
        for bad in (["651"], ["651=xyz!"], ["abc=0505fb8"], ["651=0505fb8 655"]):
            with self.assertRaises(mq.UsageError, msg=bad):
                mq.parse_heads(bad)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(mq.main(["status", "--repo", "o/r", "--approved-heads", "651=nothex"]), 3)
        self.assertIn("bad entry", buf.getvalue())

    def test_missing_heads_are_reported(self):
        import json
        p = [pr(number=651, headRefOid="0505fb8aa", reviews=conn(review(GREEN))),
             pr(number=655, headRefOid="8298b6daa", reviews=conn(review(GREEN)))]
        out = json.loads(self.run_status(p, pr_args=[651, 655], approved_heads=["651=0505fb8"]))
        self.assertIn("#655: their head was NOT checked", " ".join(out["notes"]))

    def test_compare_failure_is_unverified_not_force_push(self):
        import json
        p = [pr(number=651, headRefOid="1111111aa", reviews=conn(review(GREEN)))]
        out = json.loads(self.run_status(p, pr_args=[651], approved_heads=["651=0505fb8"]))  # compare -> 404
        r = out["queue"][0]
        self.assertEqual(r["head_changed"]["kind"], "unverified")
        self.assertEqual(r["next"], "skip")
        self.assertIn("can't verify", " ".join(r["blockers"]))
        self.assertNotIn("force", " ".join(r["blockers"]))

    def test_stacked_warning_survives_pr_filter(self):
        import json
        p = [pr(number=651, headRefName="av/finanza", reviews=conn(review(GREEN)))]
        out = json.loads(self.run_status(p, pr_args=[651], open_bases=[(651, "main"), (652, "av/finanza"), (653, "av/finanza")]))
        self.assertEqual(out["queue"][0]["dependents"], [652, 653])
        w = " ".join(out["queue"][0]["warnings"])
        self.assertIn("can conflict", w)
        self.assertNotIn("usually", w)

    def test_other_rules_and_copilot_ruleset(self):
        import json
        payload = [
            {"type": "pull_request", "parameters": {"required_approving_review_count": 0, "require_code_owner_review": True,
                                                    "require_extra_approval_for_unattributed_changes": True,
                                                    "dismiss_stale_reviews_on_push": False}},
            {"type": "code_quality", "parameters": {}},
            {"type": "copilot_code_review", "parameters": {"review_on_push": True}},
        ]
        p = [pr(number=651, reviews=conn(review(GREEN)))]
        out = json.loads(self.run_status(p, rules_payload=payload))
        self.assertEqual(out["rules"]["other"], ["code_quality", "pull_request.require_extra_approval_for_unattributed_changes"])
        self.assertEqual(out["rules"]["copilot_review"], {"review_on_push": True, "review_drafts": False})
        text = self.run_status(p, fmt="brief", rules_payload=payload)
        self.assertIn("Other branch rules", text)
        self.assertIn("re-reviews after every push", text)


class FifthRun(unittest.TestCase):
    """Fifth live run (uliveto): 3 of 3 approved merged; five briefing findings."""

    run_status = FieldTest.run_status

    def blue_with_late_commit(self):
        rv = {**review(BLUE), "commit": {"oid": "c1"}, "url": "https://x/r"}
        commits = {"totalCount": 4, "nodes": [
            {"commit": {"oid": "c1", "parents": {"totalCount": 1}}},
            {"commit": {"oid": "m1", "parents": {"totalCount": 2}}},
            {"commit": {"oid": "m2", "parents": {"totalCount": 2}}},
            {"commit": {"oid": "fix", "parents": {"totalCount": 1}}}]}
        return pr(number=655, reviews=conn(rv), prCommits=commits,
                  comments=conn({"url": "https://x/c", "author": ME, "createdAt": "2026-11-01T11:00:00Z"}))

    def test_confirm_shows_commits_copilot_never_saw(self):
        cp = mq.eval_copilot(self.blue_with_late_commit(), "auto", True, mq.DEFAULTS)
        self.assertEqual(cp["status"], "confirm")
        self.assertIn("1 new commit(s) + 2 merge(s) of the base since the Copilot review", cp["detail"])
        text = self.run_status([self.blue_with_late_commit()], fmt="brief")
        self.assertIn("1 new commit(s) arrived after the review, and Copilot hasn't seen them", text)

    def test_skipped_row_says_it_once(self):
        r = mq.evaluate_pr(pr(number=652), ctx())  # no Copilot review, none requested
        self.assertEqual(r["next"], "skip")
        self.assertEqual(mq.why_text(r).count("none requested"), 1)

    def test_branch_only_rules_are_not_listed(self):
        import json
        payload = [{"type": t, "parameters": {}} for t in ("creation", "deletion", "non_fast_forward", "code_quality")]
        out = json.loads(self.run_status([pr(reviews=conn(review(GREEN)))], rules_payload=payload))
        self.assertEqual(out["rules"]["other"], ["code_quality"])

    def test_merge_of_base_recognised_by_parents(self):
        odd = {"sha": "6443ff7", "parents": [{"sha": "feat"}, {"sha": "mainsha"}],
               "commit": {"message": "Merge origin/main into av/family-loans"}}
        cmp_ = {"status": "ahead", "commits": [odd]}
        # message alone doesn't match the standard git wording...
        self.assertEqual(mq.classify_head_change(cmp_, "main")["kind"], "new_commits")
        # ...but its second parent is in main's history: it is a merge of the base
        self.assertEqual(mq.classify_head_change(cmp_, "main", in_base=lambda s: s == "mainsha"),
                         {"kind": "merges_only", "count": 1})
        # a merge of another branch stays new work, whatever its message says
        fake = {"sha": "x", "parents": [{"sha": "feat"}, {"sha": "other"}],
                "commit": {"message": "Merge branch 'main' into feat"}}
        self.assertEqual(mq.classify_head_change({"status": "ahead", "commits": [fake]}, "main",
                                                 in_base=lambda s: False)["kind"], "new_commits")

    def test_confirm_plan_skips_update_when_up_to_date(self):
        r = mq.evaluate_pr(self.blue_with_late_commit(), ctx(behind={655: 0}))
        self.assertEqual(r["next"], "confirm")
        self.assertEqual(mq.plan_text(r, "main", later=False), "ASK YOU first (Copilot), then merge")
        self.assertIn("update with main", mq.plan_text(r, "main", later=True))
        r = mq.evaluate_pr(self.blue_with_late_commit(), ctx(behind={655: 2}))
        self.assertIn("update with main", mq.plan_text(r, "main", later=False))


class SixthRun(unittest.TestCase):
    """Sixth live run (neve): no open PRs at all."""

    run_status = FieldTest.run_status

    def test_empty_repo_says_nothing_to_do(self):
        text = self.run_status([], fmt="brief")
        self.assertIn("0 open PR(s) seen", text)
        self.assertIn("nothing to do", text)
        self.assertNotIn("Reply to go ahead", text)
        self.assertNotIn("| PR | Title |", text)

    def test_only_skipped_or_excluded_needs_no_go(self):
        p = [pr(number=652), pr(number=653, author=BOB)]  # no Copilot review; other author
        text = self.run_status(p, fmt="brief")
        self.assertIn("2 open PR(s) seen:** 0 can go now, 1 will be skipped, 1 out of the queue", text)
        self.assertIn("No PR can go right now", text)
        self.assertNotIn("Reply to go ahead", text)

    def test_counts_and_go_line_when_something_can_go(self):
        text = self.run_status([pr(number=1, reviews=conn(review(GREEN)))], fmt="brief")
        self.assertIn("1 open PR(s) seen:** 1 can go now, 0 will be skipped, 0 out of the queue", text)
        self.assertTrue(text.rstrip().endswith("Reply to go ahead."))

    def test_strict_rule_is_named(self):
        payload = [{"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": True, "required_status_checks": [{"context": "checks-pass"}]}}]
        text = self.run_status([pr(reviews=conn(review(GREEN)))], fmt="brief", rules_payload=payload)
        self.assertIn("branch must be up to date with `main` before merging", text)


class SeventhRun(unittest.TestCase):
    """Seventh live run (uliveto): 4 of 6 merged; #657 wrongly skipped."""

    run_status = FieldTest.run_status

    def merge_with_main_commits(self):
        # What compare <approved>...<new head> really returns after someone
        # merges origin/main: the base's own commits AND the merge commit.
        main1 = {"sha": "m652", "parents": [{"sha": "m0"}], "commit": {"message": "feat(finanza): … (#652)"}}
        merge = {"sha": "5ef59a4", "parents": [{"sha": "approved"}, {"sha": "m652"}],
                 "commit": {"message": "Merge origin/main into av/sicurezza-infrastruttura-meno-rumore"}}
        return {"status": "ahead", "commits": [main1, merge]}

    def test_base_commits_brought_in_by_a_merge_are_not_new_work(self):
        in_base = lambda sha: sha in {"m652", "m0"}
        self.assertEqual(mq.classify_head_change(self.merge_with_main_commits(), "main", in_base=in_base),
                         {"kind": "merges_only", "count": 1})
        # a real new commit on top is still caught
        cmp_ = self.merge_with_main_commits()
        cmp_["commits"].append({"sha": "own", "parents": [{"sha": "5ef59a4"}], "commit": {"message": "feat: more"}})
        self.assertEqual(mq.classify_head_change(cmp_, "main", in_base=in_base),
                         {"kind": "new_commits", "commits": ["feat: more"]})

    def test_end_to_end_merge_of_main_mid_run_goes_ahead(self):
        import json
        p = [pr(number=657, headRefOid="5ef59a4", reviews=conn(review(GREEN)))]
        out = json.loads(self.run_status(p, pr_args=[657], approved_heads=["657=a0bcdef"],
                                         compare=self.merge_with_main_commits(), base_commits=("m652", "m0")))
        r = out["queue"][0]
        self.assertEqual(r["head_changed"]["kind"], "merges_only")
        self.assertNotEqual(r["next"], "skip")

    def test_base_membership_uses_one_compare(self):
        from unittest import mock
        calls = []

        def fake_rest(path):
            calls.append(path)
            if path.endswith("/compare/abc1234...main"):
                return True, {"commits": [{"sha": "m1"}, {"sha": "m2"}]}
            return True, {"status": "behind"}  # in_history: not in main
        with mock.patch.object(mq, "rest", side_effect=fake_rest):
            in_base = mq.base_membership("o/r", "main", "abc1234")
            self.assertTrue(in_base("m1") and in_base("m2"))
            self.assertFalse(in_base("own"))
            self.assertFalse(in_base("own"))  # cached
        self.assertEqual(len(calls), 2)

    def test_counts_separate_prs_waiting_for_an_answer(self):
        blue = pr(number=656, reviews=conn(review(BLUE)),
                  comments=conn({"url": "u", "author": ME, "createdAt": "2026-11-01T11:00:00Z"}))
        text = self.run_status([pr(number=652, reviews=conn(review(GREEN))), blue], fmt="brief")
        self.assertIn("1 can go now, 1 wait for your answer (Copilot), 0 will be skipped", text)

    def test_update_method_always_in_json(self):
        import json
        out = json.loads(self.run_status([pr(number=652), pr(number=653, reviews=conn(review(GREEN)))]))
        self.assertTrue(all("update_method" in r for r in out["queue"]))

    def test_required_check_named_in_why(self):
        payload = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "ci"}]}}]
        text = self.run_status([pr(reviews=conn(review(GREEN)))], fmt="brief", rules_payload=payload)
        self.assertIn("1 check(s) green (required: ci)", text)



def git_repo_with_merges():
    """A real repo: main + feature, and three merges of main into feature:
    clean, conflict resolved by hand, and clean-but-edited."""
    import subprocess, tempfile
    d = tempfile.mkdtemp()

    def g(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                               *a], cwd=d, capture_output=True, text=True, check=True).stdout.strip()

    def write(name, text):
        with open(os.path.join(d, name), "w") as f:
            f.write(text)
    g("init", "-q")
    write("a.txt", "one\n"); write("b.txt", "x\n")
    g("add", "."); g("commit", "-qm", "base")
    g("checkout", "-qb", "feature")
    write("b.txt", "feature\n"); g("commit", "-qam", "feature work")
    g("checkout", "-q", "main")
    write("a.txt", "two\n"); g("commit", "-qam", "main moves")
    g("checkout", "-q", "feature")
    g("merge", "-q", "--no-edit", "main")
    clean = g("rev-parse", "HEAD")
    g("checkout", "-q", "main")
    write("b.txt", "main\n"); g("commit", "-qam", "main touches b")
    g("checkout", "-q", "feature")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "main"], cwd=d, capture_output=True)
    write("b.txt", "resolved by hand\n"); g("add", "b.txt"); g("commit", "-qm", "Merge origin/main into feature")
    resolved = g("rev-parse", "HEAD")
    g("checkout", "-q", "main")
    write("a.txt", "three\n"); g("commit", "-qam", "main again")
    g("checkout", "-q", "feature")
    g("merge", "-q", "--no-commit", "main")
    write("c.txt", "sneaked in\n"); g("add", "c.txt"); g("commit", "-qm", "Merge branch 'main' into feature")
    edited = g("rev-parse", "HEAD")
    parents = lambda sha: g("rev-list", "--parents", "-n1", sha).split()[1:]
    return d, {"clean": (clean, parents(clean)), "resolved": (resolved, parents(resolved)),
               "edited": (edited, parents(edited))}


class EighthRun(unittest.TestCase):
    """Eighth live run (uliveto): 2 merged, 1 skipped on a real conflict."""

    run_status = FieldTest.run_status

    def test_merge_check_on_a_real_repo(self):
        d, m = git_repo_with_merges()
        for kind, (sha, parents) in m.items():
            self.assertEqual(mq.merge_check(sha, parents, cwd=d), kind, kind)
        self.assertIsNone(mq.merge_check("0" * 40, ["1" * 40, "2" * 40], cwd=d))  # unknown objects

    def test_hand_resolved_merge_mid_run_is_new_code(self):
        cmp_ = {"status": "ahead", "commits": [{"sha": "r1", "parents": [{"sha": "f"}, {"sha": "m"}],
                                                "commit": {"message": "Merge origin/main into feature"}}]}
        in_base = lambda sha: sha == "m"
        self.assertEqual(mq.classify_head_change(cmp_, "main", in_base, merge_checker=lambda s, p: "clean")["kind"],
                         "merges_only")
        ch = mq.classify_head_change(cmp_, "main", in_base, merge_checker=lambda s, p: "resolved")
        self.assertEqual(ch["kind"], "new_commits")
        self.assertIn("conflicts resolved by hand", ch["commits"][0])
        ch = mq.classify_head_change(cmp_, "main", in_base, merge_checker=lambda s, p: None)
        self.assertEqual(ch, {"kind": "merges_only", "count": 1, "unchecked_merges": 1})

    def test_hand_resolved_merge_after_copilot_review_is_flagged(self):
        commits = {"totalCount": 2, "nodes": [
            {"commit": {"oid": "c1", "parents": {"totalCount": 1, "nodes": [{"oid": "c0"}]}}},
            {"commit": {"oid": "r1", "parents": {"totalCount": 2, "nodes": [{"oid": "c1"}, {"oid": "m"}]}}}]}
        ar = mq.commits_after_review(pr(prCommits=commits), "c1", merge_checker=lambda s, p: "resolved")
        self.assertEqual(ar, {"commits": 1, "merges": 1, "hand_merges": 1})
        self.assertIn("conflicts resolved by hand", mq.after_review_text(ar))

    def test_shared_files_warned_in_briefing(self):
        f = lambda *ps: {"totalCount": len(ps), "nodes": [{"path": x} for x in ps]}
        p = [pr(number=659, reviews=conn(review(GREEN)), files=f("app/page.tsx", "docs/ai/reusability.md", "a.ts")),
             pr(number=665, reviews=conn(review(GREEN)), files=f("app/page.tsx", "docs/ai/reusability.md", "b.ts")),
             pr(number=666, reviews=conn(review(GREEN)), files=f("c.ts"))]
        import json
        out = json.loads(self.run_status(p))
        q = {r["number"]: r for r in out["queue"]}
        self.assertEqual(q[665]["overlaps"], {"659": ["app/page.tsx", "docs/ai/reusability.md"]})
        self.assertNotIn("overlaps", q[666])
        text = self.run_status(p, fmt="brief")
        self.assertIn("#665 and #659 both change `app/page.tsx`, `docs/ai/reusability.md`", text)

    def test_retargeted_pr_explains_missing_copilot(self):
        moved = conn({"createdAt": "2026-11-20T10:00:00Z", "previousRefName": "av/base", "currentRefName": "main"})
        cp = mq.eval_copilot(pr(timelineItems=moved), "auto", True, mq.DEFAULTS)
        self.assertEqual(cp["status"], "missing")
        self.assertIn("opened against `av/base` and moved to `main`", cp["detail"])

    def test_up_to_date_gate_always_in_json(self):
        import json
        out = json.loads(self.run_status([pr(number=663), pr(number=1, reviews=conn(review(GREEN)))]))
        self.assertTrue(all("up_to_date" in r["gates"] for r in out["queue"]))

    def test_note_when_not_in_a_clone(self):
        import json
        out = json.loads(self.run_status([pr(reviews=conn(review(GREEN)))]))
        self.assertIn("not run inside a clone", " ".join(out["notes"]))
        out = json.loads(self.run_status([pr(reviews=conn(review(GREEN)))], merge_checker=lambda s, p: "clean"))
        self.assertNotIn("not run inside a clone", " ".join(out["notes"]))

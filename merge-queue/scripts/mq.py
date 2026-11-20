#!/usr/bin/env python3
"""mq.py - gate evaluation and wait helpers for the merge-queue skill.

Stdlib only. Needs an authenticated `gh` CLI (gh auth status).

Subcommands
  status        Evaluate every open PR (or --pr N ...) against the queue gates
                and print the ordered queue with the next action for each PR.
  wait-checks   Block until the PR's head commit has a terminal CI result.
  wait-merged   Block until the PR is merged (after arming auto-merge).

Exit codes
  status:       0 always (unless gh/repo errors -> 3)
  wait-checks:  0 success or no CI, 1 failure, 2 still pending at timeout, 3 error
  wait-merged:  0 merged, 2 not merged at timeout, 3 error
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "config", "repos.json")

# ---------------------------------------------------------------------------
# Defaults (overridden by config/repos.json, then by CLI flags)
# ---------------------------------------------------------------------------
DEFAULTS: dict = {
    "author": "me",  # "me" | "all" | ["login", ...]
    "copilot": "auto",  # "auto" | "required" | "off"
    # How a PR behind the base is brought up to date, like GitHub's "Update
    # branch" button: "merge" = "Update with merge commit", the button's
    # default (gh pr update-branch N); "rebase" = "Update with rebase", opt-in
    # (--rebase); "none" = don't update. GitHub has no repo setting for the
    # button's method (the UI only remembers each user's last pick), so the
    # default follows GitHub's default.
    "update": "merge",
    "method": "squash",  # "squash" | "merge" | "rebase"
    "exclude_labels": [
        "do-not-merge", "do not merge", "dont-merge", "wip", "work in progress",
        "hold", "on hold", "on-hold", "blocked", "no-merge-queue",
    ],
    "exclude_title_patterns": [r"^\s*\[?\s*(wip|draft|do not merge|dnm)\s*\]?\b"],
    "release": {
        "branches": [
            "release-please--*", "changeset-release/*", "release/*", "releases/*",
            "release-*", "prepare-release*", "chore/release*", "chore-release*",
        ],
        "labels": ["autorelease: pending", "autorelease: tagged", "release", "type: release"],
        "titles": [
            r"^(chore|build|ci|release)(\([^)]*\))?!?:\s*(prepare\s+)?release\b",
            r"^\s*\[?release\]?[\s:]",
            r"^\s*(release|bump version)\s+v?\d+\.\d+",
            r"^\s*v?\d+\.\d+\.\d+(\S*)\s*$",
            r"^chore(\([^)]*\))?:\s*version packages\b",
        ],
    },
    # Bot logins (prefix match, case-insensitive) whose comments count as a
    # human-equivalent answer to a Copilot review (e.g. an agent posting for you).
    "addressing_bots": ["claude"],
    "wait_timeout_minutes": 45,
    # Merge directly once everything is green (default). true = use GitHub
    # auto-merge (`gh pr merge --auto`) where the repo allows it. Opt-in only:
    # many users forbid --auto in their own instructions.
    "auto_merge": False,
    # When a rebase can't work (the PR carries commits already squash-merged
    # into the base, e.g. a PR that was stacked on one merged before it):
    # "merge" = update by merging the base in instead (only when the final
    # merge is a squash, so no merge commit reaches the base), "skip" = skip it.
    "rebase_fallback": "merge",
}

COPILOT_RE = re.compile(r"^(copilot-pull-request-reviewer(\[bot\])?|copilot)$", re.I)
CHECK_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
CHECK_FAIL = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE", "ERROR"}

# ---------------------------------------------------------------------------
# gh plumbing
# ---------------------------------------------------------------------------


class GhError(RuntimeError):
    pass


def gh(args: list[str], check: bool = True) -> tuple[int, str, str]:
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True)
    except FileNotFoundError as e:  # pragma: no cover
        raise GhError("gh CLI not found on PATH") from e
    if check and p.returncode != 0:
        raise GhError(f"gh {' '.join(args[:3])} ... failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.returncode, p.stdout, p.stderr


def graphql(query: str, **variables) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if v is None:
            args += ["-F", f"{k}=null"]
        elif isinstance(v, bool):
            args += ["-F", f"{k}={'true' if v else 'false'}"]
        elif isinstance(v, int):
            args += ["-F", f"{k}={v}"]
        else:
            args += ["-f", f"{k}={v}"]
    _, out, _ = gh(args)
    data = json.loads(out)
    if data.get("errors"):
        raise GhError("GraphQL errors: " + "; ".join(e.get("message", "?") for e in data["errors"]))
    return data["data"]


def rest(path: str) -> tuple[bool, object]:
    code, out, err = gh(["api", "-H", "Accept: application/vnd.github+json", path], check=False)
    if code != 0:
        return False, err.strip() or out.strip()
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def current_repo() -> str:
    _, out, _ = gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    return out.strip()


PR_FIELDS = """
number title url isDraft createdAt state merged
author { login __typename }
baseRefName headRefName headRefOid
isCrossRepository maintainerCanModify
labels(first: 100) { totalCount nodes { name } }
mergeable mergeStateStatus reviewDecision
autoMergeRequest { mergeMethod enabledAt }
reviewRequests(first: 20) { nodes { requestedReviewer { __typename ... on Actor { login } ... on Team { slug } } } }
reviews(last: 100) { totalCount nodes { id url author { login __typename } state body submittedAt commit { oid } } }
comments(last: 100) { nodes { url author { login __typename } createdAt } }
reviewThreads(first: 100) { totalCount nodes { isResolved isOutdated comments(first: 30) { nodes { url author { login __typename } createdAt pullRequestReview { id } } } } }
prCommits: commits(first: 100) { totalCount nodes { commit { oid parents { totalCount }
  associatedPullRequests(first: 5) { nodes { number merged } } } } }
commits(last: 1) { nodes { commit { oid statusCheckRollup { state contexts(first: 100) { totalCount nodes {
  __typename
  ... on CheckRun { name status conclusion detailsUrl }
  ... on StatusContext { context state targetUrl }
} } } } } }
"""

REPO_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    nameWithOwner isPrivate viewerPermission
    defaultBranchRef { name }
    autoMergeAllowed squashMergeAllowed mergeCommitAllowed rebaseMergeAllowed deleteBranchOnMerge
    pullRequests(states: OPEN, first: 20, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}
""" % PR_FIELDS

ONE_PR_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    nameWithOwner isPrivate viewerPermission
    defaultBranchRef { name }
    autoMergeAllowed squashMergeAllowed mergeCommitAllowed rebaseMergeAllowed deleteBranchOnMerge
    pullRequest(number: $number) { %s }
  }
}
""" % PR_FIELDS

OPEN_BASES_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { number baseRefName }
    }
  }
}
"""


def open_pr_bases(repo: str) -> list[tuple[int, str]]:
    owner, name = repo.split("/", 1)
    out, cursor = [], None
    while True:
        d = graphql(OPEN_BASES_QUERY, owner=owner, name=name, cursor=cursor)
        conn_ = d["repository"]["pullRequests"]
        out += [(n["number"], n["baseRefName"]) for n in conn_["nodes"]]
        if not conn_["pageInfo"]["hasNextPage"]:
            return out
        cursor = conn_["pageInfo"]["endCursor"]


HISTORY_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: [MERGED, CLOSED], last: 30, orderBy: {field: UPDATED_AT, direction: ASC}) {
      nodes { reviews(first: 40) { nodes { author { login } } } }
    }
  }
}
"""


def fetch_repo(repo: str, numbers: list[int] | None) -> tuple[dict, list[dict], str]:
    owner, name = repo.split("/", 1)
    prs: list[dict] = []
    if numbers:
        meta = None
        viewer = ""
        for n in numbers:
            d = graphql(ONE_PR_QUERY, owner=owner, name=name, number=n)
            viewer = d["viewer"]["login"]
            r = d["repository"]
            meta = meta or {k: v for k, v in r.items() if k != "pullRequest"}
            if r.get("pullRequest"):
                prs.append(r["pullRequest"])
        return meta or {}, prs, viewer
    cursor = None
    meta: dict = {}
    viewer = ""
    while True:
        d = graphql(REPO_QUERY, owner=owner, name=name, cursor=cursor)
        viewer = d["viewer"]["login"]
        r = d["repository"]
        meta = {k: v for k, v in r.items() if k != "pullRequests"}
        prs += r["pullRequests"]["nodes"]
        pi = r["pullRequests"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        cursor = pi["endCursor"]
    return meta, prs, viewer


def repo_uses_copilot(repo: str, open_prs: list[dict]) -> bool:
    for pr in open_prs:
        if any(is_copilot(r.get("author")) for r in nodes(pr.get("reviews"))):
            return True
        if any(is_copilot(rr.get("requestedReviewer")) for rr in nodes(pr.get("reviewRequests"))):
            return True
    owner, name = repo.split("/", 1)
    try:
        d = graphql(HISTORY_QUERY, owner=owner, name=name)
    except GhError:
        return False
    for pr in d["repository"]["pullRequests"]["nodes"]:
        if any(is_copilot(r.get("author")) for r in nodes(pr.get("reviews"))):
            return True
    return False


# Rule types about creating, deleting or force-pushing the branch itself:
# they never affect merging a PR, so listing them is noise.
IRRELEVANT_RULES = {"creation", "deletion", "non_fast_forward"}


def fetch_rules(repo: str, base: str) -> dict:
    """Merge rulesets + classic branch protection into one summary. Best effort:
    on private repos without a paid plan neither exists, and that is fine."""
    rules = {
        "required_approvals": 0, "code_owner_review": False, "thread_resolution": False,
        "strict_up_to_date": False, "required_checks": [], "linear_history": False,
        "allowed_methods": None, "merge_queue": False, "sources": [],
        "copilot_review": None,  # ruleset that has GitHub request Copilot reviews
        "other": [],  # rules GitHub enforces that the queue doesn't model itself
    }
    known_pr_params = {"required_approving_review_count", "require_code_owner_review",
                       "required_review_thread_resolution", "allowed_merge_methods"}
    ok, data = rest(f"repos/{repo}/rules/branches/{base}?per_page=100")
    if ok and isinstance(data, list):
        if data:
            rules["sources"].append("rulesets")
        for r in data:
            t, p = r.get("type"), r.get("parameters") or {}
            if t == "pull_request":
                rules["required_approvals"] = max(rules["required_approvals"], p.get("required_approving_review_count", 0) or 0)
                rules["code_owner_review"] |= bool(p.get("require_code_owner_review"))
                rules["thread_resolution"] |= bool(p.get("required_review_thread_resolution"))
                for k, v in p.items():
                    if k not in known_pr_params and v not in (None, False, 0, [], ""):
                        rules["other"].append(f"pull_request.{k}" + ("" if v is True else f"={v}"))
                am = p.get("allowed_merge_methods")
                if am:
                    cur = set(am)
                    rules["allowed_methods"] = cur if rules["allowed_methods"] is None else rules["allowed_methods"] & cur
            elif t == "required_status_checks":
                rules["strict_up_to_date"] |= bool(p.get("strict_required_status_checks_policy"))
                rules["required_checks"] += [c.get("context") for c in p.get("required_status_checks", [])]
            elif t == "required_linear_history":
                rules["linear_history"] = True
            elif t == "merge_queue":
                rules["merge_queue"] = True
            elif t == "copilot_code_review":
                rules["copilot_review"] = {"review_on_push": bool(p.get("review_on_push")),
                                           "review_drafts": bool(p.get("review_draft_pull_requests"))}
            elif t and t not in IRRELEVANT_RULES:
                rules["other"].append(t)
    ok, prot = rest(f"repos/{repo}/branches/{base}/protection")
    if ok and isinstance(prot, dict):
        rules["sources"].append("branch-protection")
        rsc = prot.get("required_status_checks") or {}
        rules["strict_up_to_date"] |= bool(rsc.get("strict"))
        rules["required_checks"] += list(rsc.get("contexts") or [])
        rpr = prot.get("required_pull_request_reviews") or {}
        rules["required_approvals"] = max(rules["required_approvals"], rpr.get("required_approving_review_count", 0) or 0)
        rules["code_owner_review"] |= bool(rpr.get("require_code_owner_reviews"))
        rules["thread_resolution"] |= bool((prot.get("required_conversation_resolution") or {}).get("enabled"))
        rules["linear_history"] |= bool((prot.get("required_linear_history") or {}).get("enabled"))
    rules["required_checks"] = sorted({c for c in rules["required_checks"] if c})
    rules["other"] = sorted(set(rules["other"]))
    if rules["allowed_methods"] is not None:
        rules["allowed_methods"] = sorted(rules["allowed_methods"])  # JSON-safe
    return rules


def base_membership(repo: str, base: str, since: str):
    """in_base(sha) for one approved head: one compare call lists the base's
    commits since `since` (the usual case: what a merge of the base brought
    in); only commits beyond that list cost an extra lookup each."""
    ok, data = rest(f"repos/{repo}/compare/{since}...{base}")
    known: set[str] = set()
    if ok and isinstance(data, dict):
        known = {c.get("sha") for c in data.get("commits") or [] if c.get("sha")}
    cache: dict[str, bool] = {}

    def in_base(sha: str) -> bool:
        if sha in known:
            return True
        if sha not in cache:  # older base history, or beyond the listed commits
            cache[sha] = in_history(repo, base, sha)
        return cache[sha]
    return in_base


def in_history(repo: str, base: str, sha: str) -> bool:
    """True when commit `sha` is in `base`'s history (i.e. an ancestor of it)."""
    ok, data = rest(f"repos/{repo}/compare/{sha}...{base}")
    return ok and isinstance(data, dict) and data.get("status") in ("ahead", "identical")


def behind_by(repo: str, base: str, head_sha: str) -> int | None:
    ok, data = rest(f"repos/{repo}/compare/{base}...{head_sha}")
    if ok and isinstance(data, dict):
        return int(data.get("behind_by", 0))
    return None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(repo: str, path: str = CONFIG_PATH) -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            file_cfg = json.load(f)
    except FileNotFoundError:
        return cfg
    owner = repo.split("/")[0]
    for key in ("*", f"{owner}/*", repo):
        entry = (file_cfg.get("repos") or {}).get(key)
        if entry:
            cfg = deep_merge(cfg, entry)
    return cfg


# ---------------------------------------------------------------------------
# Pure evaluation (unit-tested)
# ---------------------------------------------------------------------------


def nodes(conn) -> list:
    if not conn:
        return []
    return [n for n in conn.get("nodes", []) if n]


def truncated(conn) -> bool:
    """True when a connection has more items than we fetched (fail closed)."""
    if not conn or conn.get("totalCount") is None:
        return False
    return conn["totalCount"] > len(conn.get("nodes") or [])


def ts(s: str | None) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def is_copilot(actor) -> bool:
    return bool(actor) and bool(COPILOT_RE.match(actor.get("login") or ""))


def is_addressing_author(actor, cfg: dict) -> bool:
    """Who can 'answer' a Copilot review: any human, or an allow-listed bot."""
    if not actor or is_copilot(actor):
        return False
    login = (actor.get("login") or "").lower()
    if actor.get("__typename") == "Bot" or login.endswith("[bot]"):
        return any(login.startswith(b.lower()) for b in cfg.get("addressing_bots", []))
    return True


def copilot_verdict(body: str) -> str:
    """green = Approval recommended, blue = Needs a closer look,
    yellow = Changes recommended, none = legacy/no verdict. Earliest phrase wins."""
    b = (body or "").lower()
    found = []
    for color, pat in (
        ("green", r"approval recommended"),
        ("blue", r"needs (a )?closer look"),
        ("yellow", r"(?<!no )changes recommended"),
    ):
        m = re.search(pat, b)
        if m:
            found.append((m.start(), color))
    return min(found)[1] if found else "none"


def is_release_pr(pr: dict, cfg: dict) -> str | None:
    rel = cfg.get("release", {})
    head = pr.get("headRefName") or ""
    for pat in rel.get("branches", []):
        if fnmatch.fnmatch(head, pat):
            return f"release branch `{head}`"
    labels = {l["name"].lower() for l in nodes(pr.get("labels"))}
    for lab in rel.get("labels", []):
        if lab.lower() in labels:
            return f"release label `{lab}`"
    title = pr.get("title") or ""
    for pat in rel.get("titles", []):
        if re.search(pat, title, re.I):
            return "release title"
    return None


def checks_summary(pr: dict, required: list[str] | None = None) -> dict:
    commits = nodes(pr.get("commits"))
    commit = commits[-1]["commit"] if commits else {}
    rollup = commit.get("statusCheckRollup") or {}
    failing, pending, passed = [], [], []
    # A re-run leaves the old CheckRun in the rollup; keep the latest per name
    # by giving later entries priority (GraphQL returns them in creation order).
    latest: dict[str, dict] = {}
    for c in nodes(rollup.get("contexts")):
        name = c.get("name") or c.get("context") or "?"
        latest[name] = c
    for name, c in latest.items():
        if c.get("__typename") == "CheckRun":
            if c.get("status") != "COMPLETED":
                pending.append(name)
            elif (c.get("conclusion") or "") in CHECK_OK:
                passed.append(name)
            else:
                failing.append(name)
        else:
            st = c.get("state")
            if st == "SUCCESS":
                passed.append(name)
            elif st in ("PENDING", "EXPECTED"):
                pending.append(name)
            else:
                failing.append(name)
    # GitHub's aggregate state covers every context, including any beyond the
    # page we fetched: never report better than it.
    agg = rollup.get("state")
    if agg in ("FAILURE", "ERROR") and not failing:
        failing.append(f"(aggregate state {agg}; failing check not in fetched page)")
    if agg in ("PENDING", "EXPECTED") and not pending and not failing:
        pending.append(f"(aggregate state {agg})")
    if truncated(rollup.get("contexts")) and not failing and not pending and agg != "SUCCESS":
        pending.append("(more than 100 checks; aggregate state not SUCCESS)")
    present = set(latest)
    for req in required or []:
        if req not in present:
            pending.append(f"{req} (required, not reported yet)")
    if failing:
        state = "failure"
    elif pending:
        state = "pending"
    elif passed:
        state = "success"
    else:
        state = "none"
    return {"state": state, "failing": failing, "pending": pending, "passed": len(passed), "sha": commit.get("oid"),
            "required": sorted(set(required or []))}


def commits_after_review(pr: dict, review_oid: str | None) -> dict | None:
    """How many commits the PR got after the commit Copilot reviewed:
    {"commits": n, "merges": m} (merges = merge commits, e.g. main merged in),
    {"rewritten": True} when that commit is no longer in the PR, or None."""
    if not review_oid:
        return None
    oids = [(n.get("commit") or {}) for n in nodes(pr.get("prCommits"))]
    if not oids:
        return None
    idx = next((i for i, c in enumerate(oids) if c.get("oid") == review_oid), None)
    if idx is None:
        return None if truncated(pr.get("prCommits")) else {"rewritten": True}
    after = oids[idx + 1:]
    merges = sum(1 for c in after if ((c.get("parents") or {}).get("totalCount") or 1) > 1)
    return {"commits": len(after), "merges": merges}


def after_review_text(ar: dict | None) -> str:
    if not ar:
        return ""
    if ar.get("rewritten"):
        return "; the reviewed commit is no longer in the PR (history rewritten since the review)"
    if not ar["commits"]:
        return ""
    own = ar["commits"] - ar["merges"]
    parts = []
    if own:
        parts.append(f"{own} new commit(s)")
    if ar["merges"]:
        parts.append(f"{ar['merges']} merge(s) of the base")
    return "; " + " + ".join(parts) + " since the Copilot review"


def eval_copilot(pr: dict, mode: str, repo_uses: bool, cfg: dict, confirmed: bool = False) -> dict:
    """Returns {status: ok|pending|missing|unhandled|confirm|n/a, verdict, detail, ...}.

    `confirm` means: the verdict needs an answer (blue, or yellow without inline
    threads), and there ARE comments after the review, but whether they really
    resolve it is a human judgement. The result carries the review link and the
    candidate comment links so the user can be asked. `confirmed=True` (the user
    said yes for this PR) turns it into ok."""
    if mode == "off":
        return {"status": "n/a", "verdict": None, "detail": "Copilot gate disabled"}
    expected = mode == "required" or (mode == "auto" and repo_uses)
    reviews = sorted((r for r in nodes(pr.get("reviews")) if is_copilot(r.get("author"))), key=lambda r: ts(r.get("submittedAt")))
    requested = any(is_copilot(rr.get("requestedReviewer")) for rr in nodes(pr.get("reviewRequests")))
    if not reviews:
        if requested:
            return {"status": "pending", "verdict": None, "detail": "Copilot review requested, not arrived yet"}
        if expected:
            return {"status": "missing", "verdict": None, "detail": "no Copilot review and none requested (repo normally gets one); request it yourself if you want it"}
        return {"status": "n/a", "verdict": None, "detail": "Copilot not used in this repo"}
    latest = reviews[-1]
    verdict = copilot_verdict(latest.get("body"))
    since = ts(latest.get("submittedAt"))
    if requested:
        return {"status": "pending", "verdict": verdict, "detail": "Copilot re-review requested, not arrived yet"}

    threads = []
    for t in nodes(pr.get("reviewThreads")):
        cs = nodes(t.get("comments"))
        if cs and is_copilot(cs[0].get("author")):
            threads.append((t, cs))
    unresolved = [t for t, _ in threads if not t.get("isResolved")]
    latest_has_threads = any(
        (cs[0].get("pullRequestReview") or {}).get("id") == latest.get("id") for _, cs in threads
    )

    # Comments by people (or allow-listed agent bots) posted after the review:
    # candidates for "someone answered it". Never assumed to be an answer.
    candidates = []
    for c in nodes(pr.get("comments")):
        if is_addressing_author(c.get("author"), cfg) and ts(c.get("createdAt")) > since:
            candidates.append({"url": c.get("url"), "author": (c.get("author") or {}).get("login"), "at": c.get("createdAt")})
    for r in nodes(pr.get("reviews")):
        if is_addressing_author(r.get("author"), cfg) and ts(r.get("submittedAt")) > since and (r.get("body") or "").strip():
            candidates.append({"url": r.get("url"), "author": (r.get("author") or {}).get("login"), "at": r.get("submittedAt")})
    for _, cs in threads:
        for c in cs[1:]:
            if is_addressing_author(c.get("author"), cfg) and ts(c.get("createdAt")) > since:
                candidates.append({"url": c.get("url"), "author": (c.get("author") or {}).get("login"), "at": c.get("createdAt")})
    candidates.sort(key=lambda c: ts(c.get("at")))

    label = {"green": "green", "blue": "blue", "yellow": "yellow", "none": "no verdict"}[verdict]
    ar = commits_after_review(pr, (latest.get("commit") or {}).get("oid"))
    base = {"verdict": verdict, "review_url": latest.get("url"), "after_review": ar}
    if unresolved:
        return {**base, "status": "unhandled",
                "detail": f"{label}: {len(unresolved)} unresolved Copilot thread(s)" + after_review_text(ar)}
    needs_answer = verdict == "blue" or (verdict == "yellow" and not latest_has_threads)
    if needs_answer:
        what = "blue (Needs a closer look)" if verdict == "blue" else "yellow (Changes recommended) without inline threads"
        if not candidates:
            return {**base, "status": "unhandled", "detail": f"{what}: nobody has commented since the review" + after_review_text(ar)}
        if not confirmed:
            return {**base, "status": "confirm", "candidates": candidates,
                    "detail": f"{what}: {len(candidates)} comment(s) since the review; ask the user whether it is resolved"
                              + after_review_text(ar)}
        return {**base, "status": "ok", "detail": f"{label}, confirmed resolved by the user" + after_review_text(ar)}
    return {**base, "status": "ok", "detail": f"{label}, handled" + after_review_text(ar)}


def rebase_risk(pr: dict) -> dict | None:
    """Predict a server-side rebase conflict. A PR's commit list only holds
    commits that aren't in the base yet; if some of them belong to ANOTHER,
    already merged PR, that PR was squash- or rebase-merged, so its changes
    are in the base under different commits and replaying them conflicts.
    Merge commits in the PR are another usual cause."""
    merged: set[int] = set()
    merge_commits = 0
    for n in nodes(pr.get("prCommits")):
        c = n.get("commit") or {}
        if ((c.get("parents") or {}).get("totalCount") or 1) > 1:
            merge_commits += 1
        for ap in nodes(c.get("associatedPullRequests")):
            if ap.get("merged") and ap.get("number") != pr.get("number"):
                merged.add(ap["number"])
    if not merged and not merge_commits:
        return None
    bits = []
    if merged:
        bits.append("carries the original commits of " + ", ".join(f"#{n}" for n in sorted(merged))
                    + ", already merged into the base as different commits")
    if merge_commits:
        bits.append(f"contains {merge_commits} merge commit(s)")
    return {"merged_prs": sorted(merged), "merge_commits": merge_commits, "reason": "; ".join(bits)}


def eval_approvals(pr: dict, rules: dict) -> dict:
    latest_by: dict[str, str] = {}
    for r in sorted(nodes(pr.get("reviews")), key=lambda r: ts(r.get("submittedAt"))):
        a = r.get("author") or {}
        if is_copilot(a):
            continue
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest_by[a.get("login") or "?"] = r["state"]
    approvers = sorted(k for k, v in latest_by.items() if v == "APPROVED")
    blockers = sorted(k for k, v in latest_by.items() if v == "CHANGES_REQUESTED")
    decision = pr.get("reviewDecision")
    need = rules.get("required_approvals", 0)
    if blockers:
        enforced = decision == "CHANGES_REQUESTED"
        return {"ok": False, "detail": "changes requested by " + ", ".join("@" + b for b in blockers) + ("" if enforced else " (not enforced by rules, still outstanding)")}
    if decision == "CHANGES_REQUESTED":
        return {"ok": False, "detail": "GitHub reports changes requested (reviewer not in the fetched reviews)"}
    if decision == "REVIEW_REQUIRED":
        bits = [f"requires {need} approving review(s)" if need else "requires approving review(s)", f"has {len(approvers)}"]
        if rules.get("code_owner_review"):
            bits.append("code-owner review required")
        return {"ok": False, "detail": ", ".join(bits) + " (you cannot approve your own PR)"}
    if decision == "APPROVED":
        return {"ok": True, "detail": "approved by " + ", ".join("@" + a for a in approvers) if approvers else "approved"}
    detail = "GitHub requires no approval for this PR"
    if rules.get("code_owner_review"):
        detail += " (the code-owner rule exists but GitHub doesn't apply it here: no CODEOWNERS file, or you own the files changed)"
    if approvers:
        detail += f"; {len(approvers)} approval(s) anyway"
    return {"ok": True, "detail": detail}


def evaluate_pr(pr: dict, ctx: dict) -> dict:
    """ctx: cfg, viewer, base, rules, repo_uses_copilot, explicit (bool)."""
    cfg, rules = ctx["cfg"], ctx["rules"]
    author = (pr.get("author") or {}).get("login") or "ghost"
    res = {
        "number": pr["number"], "title": pr.get("title"), "url": pr.get("url"), "author": author,
        "base": pr.get("baseRefName"), "head": pr.get("headRefName"), "head_sha": pr.get("headRefOid"),
        "excluded": None, "blockers": [], "warnings": [], "gates": {}, "next": None,
        "update_method": ctx["cfg"].get("update", "merge"),
    }

    # ---- filters (exclusion = not part of this queue at all) ----
    if pr.get("merged") or pr.get("state") not in (None, "OPEN"):
        res["excluded"] = f"not open ({pr.get('state')})"
    rel = is_release_pr(pr, cfg)
    if not res["excluded"] and rel:
        res["excluded"] = f"release PR ({rel})"
    want = cfg.get("author", "me")
    if not res["excluded"] and not ctx.get("explicit"):
        if want == "me" and author.lower() != ctx["viewer"].lower():
            res["excluded"] = f"author @{author} (filter: mine)"
        elif isinstance(want, list) and author.lower() not in {w.lower() for w in want}:
            res["excluded"] = f"author @{author} not in filter"
    if not res["excluded"] and pr.get("baseRefName") != ctx["base"]:
        res["excluded"] = f"targets `{pr.get('baseRefName')}`, not the default branch `{ctx['base']}`"
    if res["excluded"]:
        res["next"] = "excluded"
        return res

    if truncated(pr.get("labels")):
        res["blockers"].append("more than 100 labels: cannot check hold labels safely, check manually")
    if truncated(pr.get("reviewThreads")):
        res["blockers"].append("more than 100 review threads: cannot check them safely, check manually")
    if truncated(pr.get("reviews")):
        res["warnings"].append("more than 100 reviews: only the latest 100 were read (GitHub's review decision still applies)")
    labels = {l["name"].lower() for l in nodes(pr.get("labels"))}
    hold = sorted(labels & {x.lower() for x in cfg.get("exclude_labels", [])})
    if hold:
        res["blockers"].append("hold label: " + ", ".join(hold))
    for pat in cfg.get("exclude_title_patterns", []):
        if re.search(pat, pr.get("title") or "", re.I):
            res["blockers"].append("title marks it WIP / do-not-merge")
            break

    # ---- 1. ready for review ----
    res["gates"]["ready"] = {"ok": not pr.get("isDraft"), "detail": "draft" if pr.get("isDraft") else "ready for review"}
    if pr.get("isDraft"):
        res["blockers"].append("draft (not ready for review)")

    # ---- 2. Copilot review ----
    cp = eval_copilot(pr, cfg.get("copilot", "auto"), ctx["repo_uses_copilot"], cfg,
                      confirmed=pr["number"] in ctx.get("confirmed", set()))
    res["gates"]["copilot"] = cp
    if cp["status"] in ("pending", "missing", "unhandled"):
        res["blockers"].append("Copilot: " + cp["detail"])

    # ---- 3. approvals ----
    ap = eval_approvals(pr, rules)
    res["gates"]["approvals"] = ap
    if not ap["ok"]:
        res["blockers"].append("approvals: " + ap["detail"])

    # ---- conversations ----
    other_unresolved = 0
    for t in nodes(pr.get("reviewThreads")):
        cs = nodes(t.get("comments"))
        if not t.get("isResolved") and cs and not is_copilot(cs[0].get("author")):
            other_unresolved += 1
    if other_unresolved:
        msg = f"{other_unresolved} unresolved non-Copilot review thread(s)"
        if rules.get("thread_resolution"):
            res["blockers"].append(msg + " (conversation resolution required)")
        else:
            res["warnings"].append(msg)

    # ---- conflicts ----
    mergeable = pr.get("mergeable")
    res["gates"]["mergeable"] = {"ok": mergeable == "MERGEABLE", "detail": mergeable}
    if mergeable == "CONFLICTING":
        res["blockers"].append("merge conflicts with base - needs manual resolution")
    elif mergeable != "MERGEABLE":
        res["blockers"].append(f"mergeability is {mergeable or 'unknown'} (GitHub still computing it) - re-run shortly")
    if pr.get("isCrossRepository") and not pr.get("maintainerCanModify") and cfg.get("update") != "none":
        res["warnings"].append("fork PR without maintainer edits: cannot update branch")

    # ---- CI (informational at triage; re-checked after update) ----
    ck = checks_summary(pr, rules.get("required_checks"))
    res["gates"]["checks"] = ck

    if pr.get("autoMergeRequest"):
        res["warnings"].append("auto-merge already enabled (" + (pr["autoMergeRequest"].get("mergeMethod") or "?") + ")")

    if res["blockers"]:
        res["next"] = "skip"
        return res
    behind = ctx.get("behind", {}).get(pr["number"])
    res["gates"]["up_to_date"] = {"behind_by": behind}
    if cp["status"] == "confirm":
        # Everything else is fine; only the user can say whether the comments
        # after the blue/yellow review actually resolve it.
        res["update_method"] = cfg.get("update", "merge")
        res["next"] = "confirm"
        return res

    needs_update = cfg.get("update") != "none" and (behind is None or behind > 0 or pr.get("mergeStateStatus") == "BEHIND")
    upd = cfg.get("update", "merge")
    risk = rebase_risk(pr) if upd == "rebase" else None
    if risk:
        res["rebase_risk"] = risk
        can_fallback = cfg.get("rebase_fallback", "merge") == "merge" and ctx.get("merge_method", "squash") == "squash"
        if can_fallback:
            upd = "merge"
            res["warnings"].append("rebase would conflict (see below): will merge the base in instead")
        elif needs_update:
            res["blockers"].append("rebase would conflict: " + risk["reason"]
                                   + " (fix the branch, or allow `rebase_fallback: merge` with squash merges)")
            res["update_method"] = "rebase"
            res["next"] = "skip"
            return res
        else:
            res["warnings"].append("a rebase would conflict if the base moves: " + risk["reason"])
    res["update_method"] = upd
    if needs_update:
        if pr.get("isCrossRepository") and not pr.get("maintainerCanModify"):
            res["blockers"].append(f"behind `{ctx['base']}` by {behind} and branch cannot be updated (fork)")
            res["next"] = "skip"
        else:
            res["next"] = "update"
    elif ck["state"] == "failure":
        res["blockers"].append("CI failing: " + ", ".join(ck["failing"]))
        res["next"] = "skip"
    elif ck["state"] == "pending":
        res["next"] = "wait_checks"
    else:
        res["next"] = "merge"
    return res


MERGE_OF_BASE = r"^Merge (remote-tracking )?branch '(origin/)?{base}'"


def classify_head_change(compare: dict, base: str, in_base=None) -> dict:
    """compare = REST compare <approved head>...<current head>. Returns
    {"kind": "rewritten"} (force-push: the approved head isn't an ancestor),
    {"kind": "merges_only", "count": n} (only merges of the base were added,
    e.g. someone pressed Update branch), or {"kind": "new_commits", "commits":
    [headline, ...]} (new work nobody approved)."""
    if compare.get("status") not in ("ahead", "identical"):
        return {"kind": "rewritten", "status": compare.get("status")}
    pat = re.compile(MERGE_OF_BASE.format(base=re.escape(base)))
    new, merges = [], 0
    for c in compare.get("commits") or []:
        # The compare lists every commit reachable from the new head but not
        # from the approved one, so a merge of the base brings the base's own
        # commits along: those are already in the base, not new work.
        if in_base and c.get("sha") and in_base(c["sha"]):
            continue
        msg = ((c.get("commit") or {}).get("message") or "").splitlines()[0] if c.get("commit") else ""
        parents = [p.get("sha") for p in (c.get("parents") or [])]
        # A merge of the base: a merge commit one of whose other parents is in the
        # base's history. Decided from the parents (in_base), whatever the message
        # says; the standard git message is only the fallback without a lookup.
        is_base_merge = len(parents) > 1 and (
            any(in_base(p) for p in parents[1:]) if in_base else bool(pat.match(msg)))
        if is_base_merge:
            merges += 1
        else:
            new.append(msg or c.get("sha", "?")[:7])
    if new:
        return {"kind": "new_commits", "commits": new}
    return {"kind": "merges_only", "count": merges}


def apply_head_change(r: dict, approved: str, change: dict) -> None:
    """Approved-head check (only PRs the user approved in the briefing)."""
    r["head_changed"] = {"approved": approved, **change}
    if change["kind"] == "merges_only":
        r["warnings"].append(f"head changed since the briefing ({approved[:7]} → {(r['head_sha'] or '')[:7]}): "
                             f"only {change['count']} merge(s) of the base, OK")
        return
    if change["kind"] == "unverified":
        why = (f"can't verify the head against the briefing (comparing {approved[:7]}...{(r['head_sha'] or '')[:7]}"
               f" failed: {change.get('error', '?')})")
    elif change["kind"] == "rewritten":
        why = f"branch rewritten since the briefing (was {approved[:7]}, now {change.get('status') or 'diverged'})"
    else:
        why = (f"{len(change['commits'])} new commit(s) pushed since the briefing: "
               + "; ".join(change["commits"][:3]) + ("…" if len(change["commits"]) > 3 else ""))
    r["blockers"].append(why + " - not what you approved; re-run the queue to review it")
    r["next"] = "skip"


def choose_method(meta: dict, rules: dict, preferred: str) -> tuple[str | None, str]:
    allowed = []
    if meta.get("squashMergeAllowed"):
        allowed.append("squash")
    if meta.get("rebaseMergeAllowed"):
        allowed.append("rebase")
    if meta.get("mergeCommitAllowed") and not rules.get("linear_history"):
        allowed.append("merge")
    if rules.get("allowed_methods"):
        allowed = [m for m in allowed if m in rules["allowed_methods"]]
    if not allowed:
        return None, "no merge method allowed by repo settings/rules"
    if preferred in allowed:
        return preferred, f"{preferred} (preferred)"
    return allowed[0], f"{allowed[0]} (preferred `{preferred}` not allowed here; allowed: {', '.join(allowed)})"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def apply_cli_overrides(cfg: dict, a) -> dict:
    cfg = dict(cfg)
    if a.author:
        cfg["author"] = a.author if a.author in ("me", "all") else [x.strip().lstrip("@") for x in a.author.split(",")]
    for k in ("copilot", "update", "method"):
        v = getattr(a, k, None)
        if v:
            cfg[k] = v
    return cfg


class UsageError(Exception):
    pass


def parse_heads(items) -> dict[int, str]:
    """`N=SHA` pairs. Each argument may hold several pairs separated by spaces
    or commas: zsh doesn't split an unquoted $HEADS, so `--approved-heads
    $HEADS` arrives as ONE argument there. Anything malformed is an error,
    never silently ignored: a skipped check is worse than a failed command."""
    out: dict[int, str] = {}
    for it in items or []:
        for tok in re.split(r"[\s,]+", it.strip()):
            if not tok:
                continue
            n, eq, sha = tok.partition("=")
            n = n.strip().lstrip("#")
            if not eq or not n.isdigit() or not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha.strip()):
                raise UsageError(f"--approved-heads: bad entry {tok!r}, expected N=SHA (hex)")
            out[int(n)] = sha.strip().lower()
    return out


def cmd_status(a) -> int:
    approved = parse_heads(getattr(a, "approved_heads", None))  # validate before any network call
    repo = a.repo or current_repo()
    cfg = apply_cli_overrides(load_config(repo), a)
    meta, prs, viewer = fetch_repo(repo, a.pr)
    # Only PRs into the repository's default branch are ever queued (by design).
    base = (meta.get("defaultBranchRef") or {}).get("name") or "main"
    rules = fetch_rules(repo, base)
    # GitHub computes mergeability lazily: the first read is often UNKNOWN.
    for i, pr in enumerate(prs):
        for delay in (2, 4, 6):
            if pr.get("mergeable") != "UNKNOWN" or pr.get("baseRefName") != base:
                break
            time.sleep(delay)
            pr = prs[i] = fetch_one(repo, pr["number"])
    uses = cfg.get("copilot") == "auto" and (bool(rules.get("copilot_review")) or repo_uses_copilot(repo, prs))
    method, method_note = choose_method(meta, rules, cfg.get("method", "squash"))
    ctx = {"cfg": cfg, "viewer": viewer, "base": base, "rules": rules, "repo_uses_copilot": uses, "merge_method": method,
           "explicit": bool(a.pr), "behind": {}, "confirmed": set(a.confirmed or [])}

    # First pass without behind info, then compute behind only for PRs still in play.
    prelim = [evaluate_pr(pr, ctx) for pr in prs]
    for pr, r in zip(prs, prelim):
        if r["next"] in ("update", "merge", "wait_checks", "confirm"):
            ctx["behind"][pr["number"]] = behind_by(repo, base, pr["headRefOid"])
    results = [evaluate_pr(pr, ctx) for pr in prs]
    if not a.pr:
        results.sort(key=lambda r: r["number"])

    # Heads the user approved in the briefing: anything else pushed since
    # (other than merges of the base) is not what they said go to.
    unchecked = []
    for r in results:
        if r["next"] == "excluded":
            continue
        want = approved.get(r["number"])
        if not want:
            if approved:
                unchecked.append(r["number"])
            continue
        if (r["head_sha"] or "").lower().startswith(want):
            continue
        ok, cmp_ = rest(f"repos/{repo}/compare/{want}...{r['head_sha']}")
        if ok and isinstance(cmp_, dict):
            change = classify_head_change(cmp_, base, in_base=base_membership(repo, base, want))
        else:
            change = {"kind": "unverified", "error": str(cmp_).strip().splitlines()[0][:160] if cmp_ else "no response"}
        apply_head_change(r, want, change)

    # Stacked PRs: a queued PR whose head branch is the base of other open PRs.
    # Merging it makes GitHub retarget them to the default branch (when the
    # head branch is deleted on merge), carrying its original commits.
    by_base: dict[str, list[int]] = {}
    bases = [(pr["number"], pr.get("baseRefName")) for pr in prs]
    if a.pr:  # --pr fetched only some PRs: stacked ones are among the others
        try:
            bases = open_pr_bases(repo)
        except GhError:
            pass
    for n, b in bases:
        by_base.setdefault(b or "", []).append(n)
    for r in results:
        deps = sorted(n for n in by_base.get(r["head"] or "", []) if n != r["number"])
        if r["next"] != "excluded" and deps:
            r["dependents"] = deps
            r["warnings"].append(
                "base of open PR(s) " + ", ".join(f"#{n}" for n in deps) + ": merging it retargets them to "
                f"`{base}` (if its branch is deleted on merge), still carrying its original commits, which can "
                "conflict after a squash; they are NOT part of this run")

    perm = meta.get("viewerPermission")
    notes = []
    if unchecked:
        notes.append("no approved head given for " + ", ".join(f"#{n}" for n in unchecked)
                     + ": their head was NOT checked against the briefing")
    if perm not in ("WRITE", "MAINTAIN", "ADMIN"):
        notes.append(f"viewer permission is {perm}: you cannot update or merge here")
    if rules.get("merge_queue"):
        notes.append("this branch has a native GitHub merge queue: `gh pr merge --auto` will enqueue instead of merging")
    auto = bool(cfg.get("auto_merge")) and bool(meta.get("autoMergeAllowed"))
    if cfg.get("auto_merge") and not meta.get("autoMergeAllowed"):
        notes.append("auto_merge is on in the config but not available in this repo: merging directly")

    out = {
        "repo": repo, "viewer": viewer, "base": base, "private": meta.get("isPrivate"),
        "permission": perm, "auto_merge_allowed": meta.get("autoMergeAllowed"),
        "merge_mode": "auto" if auto else "direct",
        "delete_branch_on_merge": meta.get("deleteBranchOnMerge"),
        "merge_method": method, "merge_method_note": method_note,
        "copilot_mode": cfg.get("copilot"), "repo_uses_copilot": uses if cfg.get("copilot") == "auto" else None,
        "config": {k: cfg.get(k) for k in ("author", "copilot", "update", "method", "wait_timeout_minutes", "auto_merge", "rebase_fallback")},
        "rules": rules, "notes": notes,
        "queue": [r for r in results if r["next"] != "excluded"],
        "excluded": [{"number": r["number"], "title": r["title"], "author": r["author"], "reason": r["excluded"]} for r in results if r["next"] == "excluded"],
    }
    if a.format == "table":
        print_table(out)
    elif a.format == "brief":
        print_brief(out)
    else:
        print(json.dumps(out, indent=2, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o)))
    return 0


def print_table(out: dict) -> None:
    print(f"# {out['repo']} -> {out['base']}  (viewer @{out['viewer']}, perm {out['permission']}, method {out['merge_method_note']})")
    print(f"# copilot={out['copilot_mode']} uses={out['repo_uses_copilot']}  update={out['config']['update']}  author={out['config']['author']}  merge={out['merge_mode']}")
    for n in out["notes"]:
        print(f"# NOTE: {n}")
    print()
    for r in out["queue"]:
        g = r["gates"]
        print(f"#{r['number']} [{r['next']}] {r['title']} (@{r['author']})")
        if "copilot" in g:
            print(f"    copilot: {g['copilot']['status']} - {g['copilot']['detail']}")
        if "approvals" in g:
            print(f"    approvals: {g['approvals']['detail']}")
        ck = g.get("checks", {})
        print(f"    checks: {ck.get('state')} failing={ck.get('failing')} pending={ck.get('pending')}")
        if "up_to_date" in g:
            print(f"    behind_by: {g['up_to_date']['behind_by']}")
        for b in r["blockers"]:
            print(f"    BLOCKER: {b}")
        for w in r["warnings"]:
            print(f"    warn: {w}")
    if out["excluded"]:
        print("\nExcluded:")
        for e in out["excluded"]:
            print(f"  #{e['number']} {e['title']} - {e['reason']}")


COLOR = {"green": "🟢", "blue": "🔵", "yellow": "🟡", "none": "no verdict"}


def why_text(r: dict) -> str:
    """Why column: always show the Copilot verdict and CI state, then problems."""
    g = r.get("gates", {})
    bits = []
    cp = g.get("copilot")
    if cp and cp.get("status") not in ("n/a", "pending", "missing", "unhandled"):  # those are already blockers
        bits.append(f"Copilot {COLOR.get(cp.get('verdict') or '', '')} {cp['detail']}".replace("  ", " "))
    ck = g.get("checks")
    if ck:
        req = ck.get("required") or []
        green = f"{ck['passed']} check(s) green" + (f" (required: {', '.join(req)})" if req else "")
        bits.append({"success": green, "none": "no CI",
                     "pending": "CI running", "failure": "CI failing"}.get(ck["state"], ck["state"]))
    behind = (g.get("up_to_date") or {}).get("behind_by")
    if behind:
        bits.append(f"behind by {behind} right now")
    bits += r.get("blockers", []) + r.get("warnings", [])
    return "; ".join(bits) or "all gates pass"


def update_phrase(r: dict, base: str) -> str:
    return {"rebase": f"update with rebase on {base}", "merge": f"update with {base} via a merge commit",
            "none": "no update"}.get(r.get("update_method") or "merge", f"update with {base} via a merge commit")


def plan_text(r: dict, base: str, later: bool) -> str:
    """What will happen to this PR. `later`: PRs before it will have landed."""
    up = update_phrase(r, base)
    nxt = r["next"]
    if nxt == "update" or (later and r.get("update_method") != "none" and nxt in ("merge", "wait_checks")):
        when = " (after the PRs above land)" if later else ""
        return f"{up}{when}, wait for CI, merge"
    if nxt == "confirm":
        behind = (r.get("gates", {}).get("up_to_date") or {}).get("behind_by")
        needs_up = r.get("update_method") != "none" and (later or behind is None or behind > 0)
        when = " (after the PRs above land)" if later else ""
        return "ASK YOU first (Copilot), then " + (f"{up}{when}, CI, merge" if needs_up else "merge")
    return {"wait_checks": "wait for CI, merge", "merge": "merge", "skip": "skip"}.get(nxt, nxt)


def print_brief(out: dict) -> None:
    """Schematic pre-run briefing: what will happen and under which rules.
    Written in English; the agent presents it in the user's language."""
    c = out["config"]
    author = {"me": f"only PRs opened by you (@{out['viewer']})", "all": "PRs by anyone"}.get(
        c["author"] if isinstance(c["author"], str) else "", None) or "PRs by " + ", ".join("@" + x for x in c["author"])
    update = {"rebase": f"if it's behind `{out['base']}`, GitHub's **Update branch → Update with rebase** (set for this repo)",
              "merge": f"if it's behind `{out['base']}`, GitHub's **Update branch** button with its default, "
                       "**Update with merge commit**",
              "none": "do not update it"}[c["update"]]
    cp_mode = out["copilot_mode"]
    if cp_mode == "off":
        copilot = "ignored in this repo"
    else:
        used = "required" if cp_mode == "required" else ("used in this repo" if out["repo_uses_copilot"] else "not used in this repo, so not checked")
        crv = (out.get("rules") or {}).get("copilot_review")
        if crv and cp_mode != "off":
            used += (" (a branch rule has GitHub request it" + ("; it re-reviews after every push" if crv["review_on_push"]
                     else "; it doesn't re-review after a push") + ")")
        copilot = used
    rules = out["rules"]
    q, ex = out["queue"], out["excluded"]
    goers = [r for r in q if r["next"] in ("merge", "wait_checks", "update", "confirm")]
    print(f"## Merge queue: {out['repo']}\n")
    waiting = [r for r in goers if r["next"] == "confirm"]
    print(f"**{len(q) + len(ex)} open PR(s) seen:** {len(goers) - len(waiting)} can go now,"
          + (f" {len(waiting)} wait for your answer (Copilot)," if waiting else "")
          + f" {len(q) - len(goers)} will be skipped, {len(ex)} out of the queue.\n")
    print("### Settings")
    print(f"- **Which PRs:** {author}, targeting the default branch `{out['base']}` only. Release PRs are never touched.")
    print("- **Order:** oldest first, one at a time. The next PR starts only after the previous one is merged or skipped.")
    print(f"- **Copilot review:** {copilot}.")
    print(f"- **Before merging:** {update}, then wait for **all** checks to be green.")
    if c["update"] == "merge" and out.get("merge_method") == "rebase":
        print("- **Note:** the update adds a merge commit, and GitHub may refuse **Rebase and merge** on a branch"
              " with merge commits: consider `\"update\": \"rebase\"` for this repo.")
    if c["update"] == "rebase":
        if c.get("rebase_fallback", "merge") == "merge" and out.get("merge_method") == "squash":
            print(f"- **If a rebase can't work:** merge `{out['base']}` into the PR instead. Safe here because the final"
                  " merge is a squash: no merge commit reaches the base.")
        else:
            print("- **If a rebase can't work:** the PR is skipped.")
    am = "GitHub auto-merge" if out.get("merge_mode") == "auto" else "a direct merge once everything is green (no auto-merge)"
    print(f"- **Merge:** {out['merge_method_note']}, via {am}.")
    req = []
    if rules.get("required_approvals"):
        req.append(f"{rules['required_approvals']} approval(s)")
    if rules.get("code_owner_review"):
        req.append("code-owner approval (only when someone else owns the files changed)")
    if rules.get("thread_resolution"):
        req.append("all conversations resolved")
    if rules.get("required_checks"):
        req.append("required checks: " + ", ".join(rules["required_checks"]))
    if rules.get("strict_up_to_date"):
        req.append(f"branch must be up to date with `{out['base']}` before merging")
    print("- **Branch rules found:** " + ("; ".join(req) if req else "none (nothing enforced by GitHub, the queue's own gates still apply)") + ".")
    if rules.get("other"):
        print("- **Other branch rules** (GitHub enforces them; the queue doesn't check them itself, a merge they block"
              " shows up as \"not merged\"): " + ", ".join(f"`{x}`" for x in rules["other"]) + ".")
    for n in out["notes"]:
        print(f"- **Note:** {n}")
    print("\n### Gates (a PR that fails any of them is skipped, never fixed)")
    print("1. Ready for review: not a draft, no hold/WIP label or title.")
    if cp_mode != "off" and (cp_mode == "required" or out["repo_uses_copilot"]):
        print("2. Copilot review has arrived (it's never requested for you) and is handled:")
        print("   - green: every Copilot thread resolved;")
        print("   - blue: threads resolved, and **you confirm** that the comments after it resolve it (links below);")
        print("   - yellow: every Copilot thread resolved (no inline threads: same as blue).")
    else:
        print("2. Copilot: not checked.")
    print("3. Approvals the rules require are there; no outstanding \"changes requested\".")
    print("4. No merge conflicts.")
    print("5. After the update, every check is green (a failure is reported, not retried).")
    print("\n### What will happen")
    if not q and not ex:
        print(f"No open PRs in {out['repo']}: nothing to do. Nothing will be changed.")
        return
    print("| PR | Title | Plan | Why |")
    print("|---|---|---|---|")
    first_go = True
    for r in out["queue"]:
        plan = plan_text(r, out["base"], later=not first_go)
        if r["next"] in ("merge", "wait_checks", "update", "confirm"):
            first_go = False
        print(f"| [#{r['number']}]({r['url']}) | {r['title']} | {plan} | {why_text(r)} |")
    for e in out["excluded"]:
        print(f"| #{e['number']} | {e['title']} | not in queue | {e['reason']} |")
    asks = [r for r in out["queue"] if (r["gates"].get("copilot") or {}).get("status") == "confirm"]
    if asks:
        print("\n### Need your answer: are these Copilot reviews resolved?")
        for r in asks:
            g = r["gates"]["copilot"]
            print(f"- **#{r['number']}** {g['verdict']} review: {g.get('review_url')}")
            for cand in g.get("candidates", []):
                print(f"  - comment by @{cand['author']}: {cand['url']}")
            ar = g.get("after_review") or {}
            own = (ar.get("commits") or 0) - (ar.get("merges") or 0)
            if ar.get("rewritten"):
                print("  - **Note:** the reviewed commit is no longer in the PR: Copilot hasn't seen the code as it is now.")
            elif own > 0:
                print(f"  - **Note:** {own} new commit(s) arrived after the review, and Copilot hasn't seen them."
                      " Confirming the review also accepts them.")
    # Same cause, said once: PRs that can't be rebased for the same reason.
    by_cause: dict[str, list[int]] = {}
    for r in out["queue"]:
        if r.get("rebase_risk"):
            by_cause.setdefault(r["rebase_risk"]["reason"], []).append(r["number"])
    if by_cause:
        print("\n### Why some PRs can't be rebased")
        for reason, nums in by_cause.items():
            print(f"- " + ", ".join(f"#{n}" for n in nums) + f": {reason}. Replaying those commits on top of"
                  f" `{out['base']}` conflicts, so GitHub's rebase fails ({'they will be updated by merging the base in instead' if c.get('rebase_fallback', 'merge') == 'merge' and out.get('merge_method') == 'squash' else 'they are skipped'}).")
    deps = [r for r in out["queue"] if r.get("dependents")]
    if deps:
        print("\n### Stacked PRs")
        for r in deps:
            print(f"- Merging #{r['number']} moves " + ", ".join(f"#{n}" for n in r["dependents"])
                  + f" onto `{out['base']}` (if its branch is deleted on merge), still carrying #{r['number']}'s original"
                  " commits, which can conflict after a squash. They stay out of this run.")
    if not goers:
        print("\nNo PR can go right now: nothing to approve, and nothing will be changed."
              + (" Answer the Copilot questions above to unblock those PRs." if asks else ""))
    elif asks:
        print("\nReply to go ahead, and say which of the Copilot reviews above are resolved.")
    else:
        print("\nReply to go ahead.")


def fetch_one(repo: str, number: int) -> dict:
    owner, name = repo.split("/", 1)
    d = graphql(ONE_PR_QUERY, owner=owner, name=name, number=number)
    pr = d["repository"].get("pullRequest")
    if not pr:
        raise GhError(f"PR #{number} not found in {repo}")
    return pr


def cmd_wait_checks(a) -> int:
    repo = a.repo or current_repo()
    deadline = time.time() + a.timeout_sec
    first_seen_new_head = None
    last = None
    first = fetch_one(repo, a.pr[0])
    required = fetch_rules(repo, first.get("baseRefName") or "main").get("required_checks")
    while True:
        pr = fetch_one(repo, a.pr[0])
        sha = pr.get("headRefOid")
        if a.not_sha and sha and sha.startswith(a.not_sha):
            # Server-side update not visible yet.
            last = {"result": "pending", "reason": "waiting for the updated head commit", "head": sha}
        else:
            first_seen_new_head = first_seen_new_head or time.time()
            ck = checks_summary(pr, required)
            last = {"result": ck["state"], "head": sha, "failing": ck["failing"], "pending": ck["pending"], "passed": ck["passed"]}
            if ck["state"] == "failure":
                print(json.dumps(last))
                return 1
            if ck["state"] == "success" and time.time() - first_seen_new_head >= min(a.settle_sec, 30):
                # Short settle so late-registering workflows get a chance to appear.
                pr2 = fetch_one(repo, a.pr[0])
                ck2 = checks_summary(pr2, required)
                if ck2["state"] == "success" and pr2.get("headRefOid") == sha:
                    last.update(passed=ck2["passed"])
                    print(json.dumps(last))
                    return 0
            if ck["state"] == "none" and time.time() - first_seen_new_head >= a.settle_sec:
                last["reason"] = f"no checks registered after {a.settle_sec}s: treating as no CI"
                print(json.dumps(last))
                return 0
        if time.time() >= deadline:
            print(json.dumps(last))
            return 2
        time.sleep(a.interval)


def cmd_wait_merged(a) -> int:
    repo = a.repo or current_repo()
    deadline = time.time() + a.timeout_sec
    while True:
        pr = fetch_one(repo, a.pr[0])
        if pr.get("merged"):
            print(json.dumps({"result": "merged"}))
            return 0
        if pr.get("state") == "CLOSED":
            print(json.dumps({"result": "closed"}))
            return 3
        if time.time() >= deadline:
            print(json.dumps({
                "result": "not_merged", "mergeStateStatus": pr.get("mergeStateStatus"),
                "reviewDecision": pr.get("reviewDecision"), "autoMerge": pr.get("autoMergeRequest"),
                "checks": checks_summary(pr),
            }))
            return 2
        time.sleep(a.interval)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mq.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status")
    s.add_argument("--repo")
    s.add_argument("--pr", type=int, nargs="*", help="only these PRs, in this order (author filter ignored)")
    s.add_argument("--author", help="me | all | login1,login2")
    s.add_argument("--copilot", choices=["auto", "required", "off"])
    s.add_argument("--update", choices=["rebase", "merge", "none"])
    s.add_argument("--method", choices=["squash", "merge", "rebase"])
    s.add_argument("--confirmed", type=int, nargs="*", help="PRs whose blue/yellow Copilot review the user confirmed as resolved")
    s.add_argument("--approved-heads", nargs="*", metavar="N=SHA",
                   help="head SHA of each PR as shown in the approved briefing; a PR whose head got new commits since is skipped")
    s.add_argument("--format", choices=["json", "table", "brief"], default="json")
    s.set_defaults(fn=cmd_status)

    w = sub.add_parser("wait-checks")
    w.add_argument("--repo")
    w.add_argument("--pr", type=int, nargs=1, required=True)
    w.add_argument("--not-sha", help="wait until the head is no longer this sha (after an update)")
    w.add_argument("--timeout-sec", type=int, default=540)
    w.add_argument("--settle-sec", type=int, default=90)
    w.add_argument("--interval", type=int, default=20)
    w.set_defaults(fn=cmd_wait_checks)

    m = sub.add_parser("wait-merged")
    m.add_argument("--repo")
    m.add_argument("--pr", type=int, nargs=1, required=True)
    m.add_argument("--timeout-sec", type=int, default=180)
    m.add_argument("--interval", type=int, default=15)
    m.set_defaults(fn=cmd_wait_merged)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (GhError, UsageError) as e:
        print(json.dumps({"error": str(e)}))
        return 3


if __name__ == "__main__":
    sys.exit(main())

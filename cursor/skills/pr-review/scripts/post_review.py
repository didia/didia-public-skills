#!/usr/bin/env python3
"""Post a batched PR review with inline comments via the gh CLI.

Validates that every comment targets a line inside the PR diff before posting,
because one out-of-diff line rejects the entire review. If a post still fails,
falls back to posting the summary alone, then each comment individually, then
each stubborn comment as a file-level comment -- so findings are never lost
silently.

Usage:
    python3 post_review.py findings.json [--dry-run] [--repo owner/name]

findings.json:
    {
      "pr": "https://github.com/owner/repo/pull/123",   # URL, number, or branch
      "commit_id": "<sha>",                             # optional; resolved from head
      "event": "COMMENT",                               # or REQUEST_CHANGES/APPROVE; omit for pending
      "body": "Review summary...",
      "comments": [
        {"path": "src/x.ts", "line": 42, "side": "RIGHT", "body": "**High** - ..."}
      ]
    }

Requires: python3, gh (authenticated).
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict


def run(args, check=True):
    """Run a command, returning (returncode, stdout, stderr)."""
    p = subprocess.run(args, capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"Command failed: {' '.join(args)}\n{p.stderr.strip()}")
    return p.returncode, p.stdout, p.stderr


def resolve_pr(pr, repo):
    """Return (owner_repo, number, head_sha) for the PR."""
    args = ["gh", "pr", "view", str(pr), "--json", "number,headRefOid,url"]
    if repo:
        args += ["--repo", repo]
    _, out, _ = run(args)
    data = json.loads(out)
    m = re.match(r"https://[^/]+/([^/]+/[^/]+)/pull/\d+", data["url"])
    if not m:
        sys.exit(f"Could not parse owner/repo from {data['url']}")
    return m.group(1), data["number"], data["headRefOid"]


def commentable_lines(diff_text):
    """Map (path, side) -> set of line numbers that appear in the diff.

    Parses unified-diff hunk headers. RIGHT-side lines are added and context
    lines (numbered in the new file); LEFT-side lines are removed and context
    lines (numbered in the old file). Only these are valid comment anchors.
    """
    def strip_prefix(t):
        return None if t == "/dev/null" else (t[2:] if t[:2] in ("a/", "b/") else t)

    lines = defaultdict(set)
    path = None
    old_path = None
    old_no = new_no = 0
    hunk_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw in diff_text.splitlines():
        if raw.startswith("--- "):
            old_path = strip_prefix(raw[4:].strip())
            continue
        if raw.startswith("+++ "):
            # For a deleted file the new path is /dev/null, but its LEFT-side
            # lines are still valid comment anchors under the old path.
            path = strip_prefix(raw[4:].strip()) or old_path
            continue
        if raw.startswith("diff --git"):
            continue
        m = hunk_re.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(2))
            continue
        if path is None or not raw:
            continue
        tag = raw[0]
        if tag == "+":
            lines[(path, "RIGHT")].add(new_no)
            new_no += 1
        elif tag == "-":
            lines[(path, "LEFT")].add(old_no)
            old_no += 1
        elif tag == " ":
            lines[(path, "RIGHT")].add(new_no)
            lines[(path, "LEFT")].add(old_no)
            old_no += 1
            new_no += 1
        # '\' (no newline marker) and anything else: ignore

    return lines


def validate(comments, valid):
    """Return list of (index, comment, reason) for comments outside the diff."""
    problems = []
    for i, c in enumerate(comments):
        if c.get("subject_type") == "file":
            continue
        path, side = c["path"], c.get("side", "RIGHT")
        allowed = valid.get((path, side), set())
        if not allowed:
            problems.append((i, c, f"no {side}-side changes in diff for {path}"))
            continue
        for key in ("line", "start_line"):
            if key in c and c[key] not in allowed:
                nearest = min(allowed, key=lambda n: abs(n - c[key]))
                problems.append((i, c, f"{key} {c[key]} not in diff (nearest commentable: {nearest})"))
    return problems


def gh_api(method, endpoint, payload):
    """POST a JSON payload to the GitHub API. Returns (ok, parsed_or_stderr)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        tmp = f.name
    code, out, err = run(["gh", "api", "--method", method, endpoint, "--input", tmp], check=False)
    if code != 0:
        return False, err.strip()
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return True, {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings", help="path to findings JSON")
    ap.add_argument("--dry-run", action="store_true", help="validate only, post nothing")
    ap.add_argument("--repo", help="owner/name, if not inferable from cwd")
    args = ap.parse_args()

    with open(args.findings) as f:
        data = json.load(f)

    comments = data.get("comments", [])
    owner_repo, number, head_sha = resolve_pr(data["pr"], args.repo)
    commit_id = data.get("commit_id") or head_sha

    if data.get("commit_id") and data["commit_id"] != head_sha:
        print(f"WARNING: head has moved. reviewed={data['commit_id']} current={head_sha}")
        print("Re-diff before posting -- the code you reviewed may no longer exist.\n")

    diff_args = ["gh", "pr", "diff", str(number)] + (["--repo", args.repo] if args.repo else [])
    _, diff_text, _ = run(diff_args)
    valid = commentable_lines(diff_text)

    problems = validate(comments, valid)
    for i, c, reason in problems:
        print(f"INVALID [{i}] {c['path']}:{c.get('line', '?')} -- {reason}")

    print(f"\n{len(comments)} comment(s), {len(problems)} invalid, PR {owner_repo}#{number} @ {commit_id[:8]}")

    if args.dry_run:
        print("Dry run: nothing posted.")
        return 1 if problems else 0

    if problems:
        print("\nFix the invalid anchors before posting (move to a changed line, use "
              "subject_type=file, or move the finding into the review body).")
        return 1

    payload = {"commit_id": commit_id, "body": data.get("body", ""), "comments": comments}
    if data.get("event"):
        payload["event"] = data["event"]

    ok, result = gh_api("POST", f"repos/{owner_repo}/pulls/{number}/reviews", payload)
    if ok:
        print(f"\nReview posted: {result.get('html_url', '(no url returned)')}")
        return 0

    # Fallback: summary alone, then each comment individually.
    print(f"\nBatched review rejected:\n{result}\nFalling back to individual posts.\n")
    summary = {"commit_id": commit_id, "body": data.get("body", "")}
    if data.get("event"):
        summary["event"] = data["event"]
    ok, result = gh_api("POST", f"repos/{owner_repo}/pulls/{number}/reviews", summary)
    print(f"Summary: {'posted -> ' + result.get('html_url', '') if ok else 'FAILED -> ' + str(result)}")

    failed = []
    for i, c in enumerate(comments):
        body = dict(c, commit_id=commit_id)
        ok, result = gh_api("POST", f"repos/{owner_repo}/pulls/{number}/comments", body)
        if not ok:
            file_level = {"commit_id": commit_id, "path": c["path"],
                          "subject_type": "file", "body": c["body"]}
            ok, result = gh_api("POST", f"repos/{owner_repo}/pulls/{number}/comments", file_level)
        status = "posted" if ok else "FAILED"
        print(f"[{i}] {c['path']}:{c.get('line', 'file')} -- {status}")
        if not ok:
            failed.append((i, c, result))

    if failed:
        print("\nUnposted findings -- surface these to the user so they aren't lost:")
        for i, c, err in failed:
            print(f"\n--- [{i}] {c['path']}:{c.get('line', '?')} ({err})\n{c['body']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

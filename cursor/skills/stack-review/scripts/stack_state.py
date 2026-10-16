#!/usr/bin/env python3
"""Pick the next stack-develop or stack-review action from GitHub JSON.

The model fetches PR state and passes it here. This script returns one action.
It does not sleep, merge, or post.

Usage:
    python3 stack_state.py develop payload.json
    python3 stack_state.py review payload.json

payload.json:
    {
      "trunk": "main",
      "stack_id": "optional-filter",
      "slices_remaining": 1,
      "max_unreviewed_ahead": 2,
      "trusted_reviewers": ["reviewer-login"],
      "trusted_developers": ["developer-login"],
      "prs": [
        {
          "number": 1,
          "state": "OPEN",
          "baseRefName": "main",
          "headRefName": "feat-a",
          "headRefOid": "abc",
          "mergeable": "MERGEABLE",
          "labels": ["harness:awaiting-review"],
          "body": "<!-- harness-stack\\n...\\n-->",
          "reviews": [{
            "state": "COMMENTED",
            "author": {"login": "reviewer-login"},
            "body": "<!-- harness-review round: 1 verdict: approved head: abc -->"
          }],
          "comments": [{
            "author": {"login": "developer-login"},
            "body": "<!-- harness-fix round: 1 head: abc -->"
          }]
        }
      ]
    }

Include merged and closed parent PRs. A missing parent is an incomplete payload.

develop actions: retarget, sync, address, merge, promote, continue, idle, stop
review actions: review, idle, stop
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

STACK_RE = re.compile(r"<!-- harness-stack\s*(.*?)-->", re.DOTALL)
REVIEW_RE = re.compile(
    r"<!-- harness-review\s+round:\s*(\d+)\s+verdict:\s*"
    r"(approved|changes-requested)\s+head:\s*(\S+)\s*-->"
)
FIX_RE = re.compile(r"<!-- harness-fix\s+round:\s*(\d+)\s+head:\s*(\S+)\s*-->")

BLOCKING_LABELS = {"harness:syncing", "harness:addressing-review"}
SUBMITTED_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
REMOVE_ON_PROMOTE = [
    "harness:stacked",
    "harness:syncing",
    "harness:addressing-review",
]


def _marker_fields(body: str) -> dict[str, str]:
    match = STACK_RE.search(body or "")
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _login(item: dict[str, Any]) -> str:
    author = item.get("author")
    if isinstance(author, str):
        return author
    if isinstance(author, dict) and author.get("login"):
        return str(author["login"])
    user = item.get("user")
    if isinstance(user, dict) and user.get("login"):
        return str(user["login"])
    return ""


def _name_set(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _reviews(pr: dict[str, Any], trusted: set[str]) -> list[dict[str, Any]]:
    found = []
    for review in pr.get("reviews") or []:
        if _login(review) not in trusted:
            continue
        state = str(review.get("state") or "").upper()
        if state not in SUBMITTED_REVIEW_STATES:
            continue
        for match in REVIEW_RE.finditer(review.get("body") or ""):
            found.append(
                {
                    "round": int(match.group(1)),
                    "verdict": match.group(2),
                    "head": match.group(3),
                    "author": _login(review),
                }
            )
    return sorted(found, key=lambda item: item["round"])


def _fixes(pr: dict[str, Any], trusted: set[str]) -> list[dict[str, Any]]:
    found = []
    for comment in pr.get("comments") or []:
        if _login(comment) not in trusted:
            continue
        for match in FIX_RE.finditer(comment.get("body") or ""):
            found.append(
                {
                    "round": int(match.group(1)),
                    "head": match.group(2),
                    "author": _login(comment),
                }
            )
    return found


def _labels(pr: dict[str, Any]) -> set[str]:
    labels = pr.get("labels") or []
    names = set()
    for label in labels:
        if isinstance(label, str):
            names.add(label)
        elif isinstance(label, dict) and label.get("name"):
            names.add(str(label["name"]))
    return names


def _normalize(
    payload: dict[str, Any],
    reviewers: set[str],
    developers: set[str],
) -> list[dict[str, Any]]:
    stack_id = (payload.get("stack_id") or "").strip()
    rows = []
    for pr in payload.get("prs") or []:
        fields = _marker_fields(pr.get("body") or "")
        if not fields:
            continue
        if stack_id and fields.get("stack-id") != stack_id:
            continue
        parent = fields.get("stack-parent") or ""
        rows.append(
            {
                "number": int(pr["number"]),
                "state": (pr.get("state") or "").upper(),
                "base": pr.get("baseRefName") or "",
                "head_name": pr.get("headRefName") or "",
                "head": pr.get("headRefOid") or "",
                "mergeable": (pr.get("mergeable") or "") or "",
                "labels": _labels(pr),
                "index": int(fields.get("stack-index") or 0),
                "parent": int(parent) if parent else None,
                "max_rounds": int(fields.get("max-rounds") or 2),
                "reviews": _reviews(pr, reviewers),
                "fixes": _fixes(pr, developers),
            }
        )
    return sorted(rows, key=lambda row: row["index"])


def _by_number(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {row["number"]: row for row in rows}


def _open_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["state"] == "OPEN"]


def _ancestry_stop(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_num = _by_number(rows)
    for row in rows:
        parent_number = row["parent"]
        if parent_number is None:
            continue
        parent = by_num.get(parent_number)
        if parent is None:
            return {
                "action": "stop",
                "reason": (
                    f"payload is missing parent PR {parent_number} of PR {row['number']}; "
                    "refetch the stack including merged and closed PRs"
                ),
            }
        if parent["state"] not in {"OPEN", "MERGED"}:
            return {
                "action": "stop",
                "reason": (
                    f"parent PR {parent_number} is {parent['state']} and was not merged"
                ),
            }
    return None


def _expected_base(row: dict[str, Any], by_num: dict[int, dict[str, Any]], trunk: str) -> str:
    parent_number = row["parent"]
    if parent_number is None:
        return trunk
    parent = by_num[parent_number]
    if parent["state"] == "MERGED":
        return trunk
    return parent["head_name"]


def _fixes_for(row: dict[str, Any], round_n: int) -> list[dict[str, Any]]:
    return [fix for fix in row["fixes"] if fix["round"] == round_n]


def _merge_head(row: dict[str, Any]) -> str | None:
    if not row["reviews"] or not row["head"]:
        return None
    latest = row["reviews"][-1]
    if latest["verdict"] == "approved" and latest["head"] == row["head"]:
        return row["head"]
    if (
        latest["verdict"] == "changes-requested"
        and len(row["reviews"]) >= row["max_rounds"]
        and any(fix["head"] == row["head"] for fix in _fixes_for(row, latest["round"]))
    ):
        return row["head"]
    return None


def _promote(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "promote",
        "pr": row["number"],
        "add_labels": ["harness:awaiting-review"],
        "remove_labels": REMOVE_ON_PROMOTE,
        "reason": (
            "bottom PR is MERGEABLE and is not labeled harness:awaiting-review"
        ),
    }


def _prepare(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    reviewers = _name_set(payload.get("trusted_reviewers"))
    developers = _name_set(payload.get("trusted_developers"))
    if not reviewers or not developers:
        return (
            {
                "action": "stop",
                "reason": (
                    "payload needs trusted_reviewers and trusted_developers "
                    "(GitHub logins). Markers from other accounts are ignored."
                ),
            },
            [],
        )
    rows = _normalize(payload, reviewers, developers)
    return None, rows


def decide_develop(payload: dict[str, Any]) -> dict[str, Any]:
    trunk = payload.get("trunk") or "main"
    ahead_cap = int(payload.get("max_unreviewed_ahead") or 2)
    slices_remaining = int(payload.get("slices_remaining") or 0)
    problem, rows = _prepare(payload)
    if problem:
        return problem
    if not rows:
        if slices_remaining > 0:
            return {
                "action": "continue",
                "next_index": 1,
                "base_branch": trunk,
                "reason": "fresh stack; start slice 1 on trunk",
            }
        return {"action": "stop", "reason": "no stack PRs in the payload"}

    ancestry = _ancestry_stop(rows)
    if ancestry:
        return ancestry

    by_num = _by_number(rows)
    open_rows = _open_rows(rows)
    if not open_rows:
        if slices_remaining > 0:
            next_index = max(row["index"] for row in rows) + 1
            return {
                "action": "continue",
                "next_index": next_index,
                "base_branch": trunk,
                "reason": "every open PR is merged; start the next slice on trunk",
            }
        return {"action": "stop", "reason": "every stack PR is merged"}

    for row in open_rows:
        expected = _expected_base(row, by_num, trunk)
        if row["base"] != expected:
            return {
                "action": "retarget",
                "pr": row["number"],
                "base": expected,
                "reason": (
                    f"PR {row['number']} bases on {row['base']}; "
                    f"set the base to {expected} with gh pr edit. "
                    "Do not wait for GitHub to retarget after a merge."
                ),
            }

    for row in open_rows:
        if row["mergeable"] == "CONFLICTING":
            return {
                "action": "sync",
                "pr": row["number"],
                "base": row["base"],
                "reason": "mergeable is CONFLICTING; update the head onto its base",
            }

    bottom = open_rows[0]
    latest = bottom["reviews"][-1] if bottom["reviews"] else None
    if latest and latest["verdict"] == "changes-requested":
        round_fixes = _fixes_for(bottom, latest["round"])
        if not round_fixes:
            return {
                "action": "address",
                "pr": bottom["number"],
                "round": latest["round"],
                "verdict": latest["verdict"],
                "reviewed_head": latest["head"],
                "reason": (
                    "latest trusted review requested changes and that round has no "
                    "trusted harness-fix yet; the review head does not have to match "
                    "the current head"
                ),
            }
        if not any(fix["head"] == bottom["head"] for fix in round_fixes):
            return {
                "action": "idle",
                "reason": (
                    "a harness-fix exists for the latest round but its head does not "
                    "match the live head; post a harness-fix for the current head"
                ),
            }

    merge_head = _merge_head(bottom)
    if merge_head:
        return {
            "action": "merge",
            "pr": bottom["number"],
            "head": merge_head,
            "reason": (
                "approval or the capped fix matches the live head; "
                "merge with gh pr merge --match-head-commit"
            ),
        }

    if (
        latest
        and latest["verdict"] == "approved"
        and latest["head"] != bottom["head"]
        and len(bottom["reviews"]) >= bottom["max_rounds"]
    ):
        return {
            "action": "stop",
            "reason": (
                "the live head moved after the last allowed review; "
                "refusing to merge code the reviewer did not approve"
            ),
        }

    if bottom["mergeable"] != "MERGEABLE":
        return {
            "action": "idle",
            "reason": "bottom mergeability is not MERGEABLE yet; refetch before promoting",
        }

    if "harness:awaiting-review" not in bottom["labels"]:
        return _promote(bottom)

    unreviewed_above = [row for row in open_rows[1:] if not row["reviews"]]
    if slices_remaining > 0 and len(unreviewed_above) < ahead_cap:
        parent = open_rows[-1]
        return {
            "action": "continue",
            "parent_pr": parent["number"],
            "base_branch": parent["head_name"],
            "next_index": parent["index"] + 1,
            "reason": "fewer than the cap of unreviewed PRs sit above the bottom",
        }

    if slices_remaining > 0:
        return {
            "action": "idle",
            "reason": (
                f"{len(unreviewed_above)} unreviewed PR(s) already sit above the bottom; "
                f"cap is {ahead_cap}"
            ),
        }
    return {"action": "idle", "reason": "nothing to retarget, sync, address, merge, or promote"}


def decide_review(payload: dict[str, Any]) -> dict[str, Any]:
    problem, rows = _prepare(payload)
    if problem:
        return problem
    if not rows:
        return {"action": "stop", "reason": "no stack PRs in the payload"}
    ancestry = _ancestry_stop(rows)
    if ancestry:
        return ancestry
    by_num = _by_number(rows)
    trunk = payload.get("trunk") or "main"
    for row in _open_rows(rows):
        parent = by_num.get(row["parent"]) if row["parent"] else None
        if parent is not None and parent["state"] != "MERGED":
            continue
        if "harness:awaiting-review" not in row["labels"]:
            continue
        if row["labels"] & BLOCKING_LABELS:
            continue
        if row["mergeable"] != "MERGEABLE":
            continue
        if any(review["head"] == row["head"] for review in row["reviews"]):
            continue
        if len(row["reviews"]) >= row["max_rounds"]:
            continue
        if row["reviews"]:
            latest = row["reviews"][-1]
            if latest["verdict"] == "changes-requested" and not any(
                fix["head"] == row["head"] for fix in _fixes_for(row, latest["round"])
            ):
                continue
        expected = _expected_base(row, by_num, trunk)
        if row["base"] != expected:
            continue
        return {
            "action": "review",
            "pr": row["number"],
            "round": len(row["reviews"]) + 1,
            "head": row["head"],
            "max_rounds": row["max_rounds"],
            "reason": "bottom PR is awaiting review on a head that has not been reviewed",
        }
    if not _open_rows(rows):
        return {"action": "stop", "reason": "no open stack PRs"}
    return {"action": "idle", "reason": "no eligible bottom PR"}


def decide(role: str, payload: dict[str, Any]) -> dict[str, Any]:
    if role == "develop":
        return decide_develop(payload)
    if role == "review":
        return decide_review(payload)
    raise SystemExit(f"Unknown role {role!r}. Use develop or review.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["develop", "review"])
    parser.add_argument("payload", type=argparse.FileType("r"))
    args = parser.parse_args(argv)
    payload = json.load(args.payload)
    json.dump(decide(args.role, payload), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

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
          "reviews": [{"body": "... harness-review ..."}],
          "comments": [{"body": "... harness-fix ..."}]
        }
      ]
    }

develop actions: retarget, sync, address, merge, continue, idle, stop
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


def _reviews(pr: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for review in pr.get("reviews") or []:
        for match in REVIEW_RE.finditer(review.get("body") or ""):
            found.append(
                {
                    "round": int(match.group(1)),
                    "verdict": match.group(2),
                    "head": match.group(3),
                }
            )
    return sorted(found, key=lambda item: item["round"])


def _fixes(pr: dict[str, Any]) -> set[int]:
    rounds: set[int] = set()
    for comment in pr.get("comments") or []:
        for match in FIX_RE.finditer(comment.get("body") or ""):
            rounds.add(int(match.group(1)))
    return rounds


def _labels(pr: dict[str, Any]) -> set[str]:
    labels = pr.get("labels") or []
    names = set()
    for label in labels:
        if isinstance(label, str):
            names.add(label)
        elif isinstance(label, dict) and label.get("name"):
            names.add(str(label["name"]))
    return names


def _normalize(payload: dict[str, Any]) -> list[dict[str, Any]]:
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
                "reviews": _reviews(pr),
                "fix_rounds": _fixes(pr),
            }
        )
    return sorted(rows, key=lambda row: row["index"])


def _by_number(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {row["number"]: row for row in rows}


def _expected_base(row: dict[str, Any], by_num: dict[int, dict[str, Any]], trunk: str) -> str:
    parent_number = row["parent"]
    if parent_number is None:
        return trunk
    parent = by_num.get(parent_number)
    if parent is None or parent["state"] == "MERGED":
        return trunk
    return parent["head_name"]


def _open_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["state"] == "OPEN"]


def decide_develop(payload: dict[str, Any]) -> dict[str, Any]:
    trunk = payload.get("trunk") or "main"
    ahead_cap = int(payload.get("max_unreviewed_ahead") or 2)
    slices_remaining = int(payload.get("slices_remaining") or 0)
    rows = _normalize(payload)
    if not rows:
        return {"action": "stop", "reason": "no stack PRs in the payload"}

    by_num = _by_number(rows)
    open_rows = _open_rows(rows)
    if not open_rows:
        if slices_remaining > 0:
            return {
                "action": "continue",
                "next_index": 1,
                "base_branch": trunk,
                "reason": "stack has no open PR; start slice 1",
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
    if (
        latest
        and latest["verdict"] == "changes-requested"
        and latest["round"] not in bottom["fix_rounds"]
    ):
        return {
            "action": "address",
            "pr": bottom["number"],
            "round": latest["round"],
            "verdict": latest["verdict"],
            "reviewed_head": latest["head"],
            "reason": (
                "latest external review requested changes and that round has no "
                "harness-fix yet; the review head does not have to match the current head"
            ),
        }

    if latest and (
        latest["verdict"] == "approved"
        or (
            len(bottom["reviews"]) >= bottom["max_rounds"]
            and latest["round"] in bottom["fix_rounds"]
        )
    ):
        return {
            "action": "merge",
            "pr": bottom["number"],
            "reason": "bottom PR is approved, or the round cap is used and the fix is pushed",
        }

    unreviewed_above = [
        row
        for row in open_rows[1:]
        if not row["reviews"]
    ]
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
    return {"action": "idle", "reason": "nothing to retarget, sync, address, or merge"}


def decide_review(payload: dict[str, Any]) -> dict[str, Any]:
    rows = _normalize(payload)
    if not rows:
        return {"action": "stop", "reason": "no stack PRs in the payload"}
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

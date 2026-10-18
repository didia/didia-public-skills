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
      "land": "progressive",
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

develop actions: rebase, address, merge, label, continue, idle, stop
review actions: review, idle, stop

land is progressive (default) or atomic. progressive merges the longest ready
prefix with `gh stack merge <through>`. atomic merges the top only when every
open PR is ready and slices_remaining is 0. A harness-rebase comment carries a
review or fix onto a new head when the layer diff did not change.
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
REBASE_RE = re.compile(r"<!-- harness-rebase\s+from:\s*(\S+)\s+head:\s*(\S+)\s*-->")
RANGE_DIFF_SUMMARY = re.compile(
    r"^\s*(?:\d+|-):\s+\S+\s+(?P<op>[=!<>])\s+(?:\d+|-):"
)

BLOCKING_LABELS = {"harness:syncing", "harness:addressing-review"}
SUBMITTED_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
LAND_MODES = {"progressive", "atomic"}
REMOVE_ON_LABEL = [
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


def _rebases(pr: dict[str, Any], trusted: set[str]) -> list[dict[str, str]]:
    found = []
    for comment in pr.get("comments") or []:
        if _login(comment) not in trusted:
            continue
        for match in REBASE_RE.finditer(comment.get("body") or ""):
            found.append({"from": match.group(1), "head": match.group(2)})
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
                "land": fields.get("land") or "progressive",
                "reviews": _reviews(pr, reviewers),
                "fixes": _fixes(pr, developers),
                "rebases": _rebases(pr, developers),
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


def _covers_live_head(row: dict[str, Any], sha: str) -> bool:
    live = row["head"]
    if not sha or not live:
        return False
    seen: set[str] = set()
    frontier = [sha]
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        if current == live:
            return True
        for edge in row["rebases"]:
            if edge["from"] == current:
                frontier.append(edge["head"])
    return False


def _verdict_covers(row: dict[str, Any]) -> bool:
    if not row["reviews"] or not row["head"]:
        return False
    latest = row["reviews"][-1]
    if latest["verdict"] == "approved" and _covers_live_head(row, latest["head"]):
        return True
    return (
        latest["verdict"] == "changes-requested"
        and len(row["reviews"]) >= row["max_rounds"]
        and any(
            _covers_live_head(row, fix["head"]) for fix in _fixes_for(row, latest["round"])
        )
    )


def _ready(row: dict[str, Any], by_num: dict[int, dict[str, Any]], trunk: str) -> bool:
    if row["labels"] & BLOCKING_LABELS:
        return False
    if row["mergeable"] != "MERGEABLE":
        return False
    if row["base"] != _expected_base(row, by_num, trunk):
        return False
    return _verdict_covers(row)


def _needs_address(row: dict[str, Any]) -> bool:
    if not row["reviews"]:
        return False
    latest = row["reviews"][-1]
    return latest["verdict"] == "changes-requested" and not _fixes_for(row, latest["round"])


def _fix_mismatch(row: dict[str, Any]) -> bool:
    if not row["reviews"]:
        return False
    latest = row["reviews"][-1]
    if latest["verdict"] != "changes-requested":
        return False
    fixes = _fixes_for(row, latest["round"])
    if not fixes:
        return False
    return not any(_covers_live_head(row, fix["head"]) for fix in fixes)


def _stale_exhausted(row: dict[str, Any]) -> bool:
    if not row["reviews"] or not row["head"]:
        return False
    if len(row["reviews"]) < row["max_rounds"]:
        return False
    return not _verdict_covers(row)


def _needs_review(row: dict[str, Any]) -> bool:
    if row["labels"] & BLOCKING_LABELS or _needs_address(row) or _fix_mismatch(row):
        return False
    if _verdict_covers(row) or _stale_exhausted(row):
        return False
    if any(_covers_live_head(row, review["head"]) for review in row["reviews"]):
        return False
    return len(row["reviews"]) < row["max_rounds"]


def _broken(row: dict[str, Any], by_num: dict[int, dict[str, Any]], trunk: str) -> bool:
    return (
        row["base"] != _expected_base(row, by_num, trunk)
        or row["mergeable"] == "CONFLICTING"
    )


def _land_mode(open_rows: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None]:
    modes = {row["land"] for row in open_rows}
    if len(modes) != 1:
        return None, {
            "action": "stop",
            "reason": (
                "open PRs disagree on land ("
                + ", ".join(sorted(modes))
                + "). Stamp the same land value on every open PR."
            ),
        }
    mode = modes.pop()
    if mode not in LAND_MODES:
        return None, {
            "action": "stop",
            "reason": f"land must be progressive or atomic, got {mode!r}",
        }
    return mode, None


def range_diff_unchanged(text: str) -> bool:
    """True when git range-diff shows no added, removed, or changed patches.

    An unchanged rebase prints one `old = new` summary row per commit. Empty
    output is unchanged too. A `!`, `<`, or `>` summary, or a diff hunk under
    a summary, is a changed layer.
    """
    for line in text.splitlines():
        if not line.strip():
            continue
        match = RANGE_DIFF_SUMMARY.match(line)
        if match is None or match.group("op") != "=":
            return False
    return True


def _merge_via(rows: list[dict[str, Any]]) -> str:
    return "stack" if len(rows) >= 2 else "pr"


def _merge_action(mode: str, group: list[dict[str, Any]], via: str) -> dict[str, Any]:
    through = group[-1]["number"]
    head = group[-1]["head"]
    numbers = ", ".join(str(row["number"]) for row in group)
    if via == "pr":
        reason = (
            f"PR {through} is ready and is the only pull request in the payload, "
            "so GitHub will not form a stack. "
            f"gh pr merge {through} --merge --match-head-commit {head}. "
            "Do not gh stack merge."
        )
    elif mode == "atomic":
        reason = (
            f"every open PR is ready and no slices remain; "
            f"gh stack merge {through} --yes --merge lands PRs {numbers} or nothing. "
            "Refetch and confirm each headRefOid still matches heads. Do not gh pr merge."
        )
    else:
        reason = (
            f"PRs {numbers} are a ready deployable prefix; "
            f"gh stack merge {through} --yes --merge lands that prefix and leaves the rest open. "
            "Refetch and confirm each headRefOid still matches heads. Do not gh pr merge."
        )
    return {
        "action": "merge",
        "land": mode,
        "via": via,
        "through": through,
        "prs": [row["number"] for row in group],
        "heads": {str(row["number"]): row["head"] for row in group},
        "reason": reason,
    }


def _label(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "label",
        "pr": row["number"],
        "add_labels": ["harness:awaiting-review"],
        "remove_labels": REMOVE_ON_LABEL,
        "reason": "open layer is MERGEABLE and its live head has not been reviewed",
    }


def _rebase(
    row: dict[str, Any],
    expected: str,
    open_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "action": "rebase",
        "pr": row["number"],
        "base": expected,
        "sync_prs": [item["number"] for item in open_rows],
        "reason": (
            f"PR {row['number']} is {row['mergeable'] or 'mis-based'} on {row['base']}; "
            f"expected base {expected}. "
            "Set harness:syncing on every PR in sync_prs before rewriting. "
            "Check out the stack, then gh stack rebase and gh stack push. "
            "Do not gh pr edit --base and do not merge the base into the head. "
            "Post a harness-rebase marker only when "
            "stack_state.py range-diff reports unchanged."
        ),
    }


def _ancestor_blocking(row: dict[str, Any], by_num: dict[int, dict[str, Any]]) -> bool:
    seen: set[int] = set()
    parent_number = row["parent"]
    while parent_number and parent_number not in seen:
        seen.add(parent_number)
        parent = by_num.get(parent_number)
        if parent is None:
            return False
        if parent["labels"] & BLOCKING_LABELS:
            return True
        parent_number = parent["parent"]
    return False


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

    mode, land_stop = _land_mode(open_rows)
    if land_stop:
        return land_stop

    if any(row["labels"] & BLOCKING_LABELS for row in open_rows):
        return {
            "action": "idle",
            "reason": (
                "a PR is harness:syncing or harness:addressing-review; "
                "finish that action and clear the label"
            ),
        }

    prefix = []
    for row in open_rows:
        if not _ready(row, by_num, trunk):
            break
        prefix.append(row)
    broken = next((row for row in open_rows if _broken(row, by_num, trunk)), None)
    prefix_end = prefix[-1]["index"] if prefix else None

    if (
        mode == "progressive"
        and prefix
        and len(rows) < 2
        and slices_remaining > 0
        and (broken is None or broken["index"] > prefix_end)
    ):
        parent = open_rows[-1]
        return {
            "action": "continue",
            "parent_pr": parent["number"],
            "base_branch": parent["head_name"],
            "next_index": parent["index"] + 1,
            "land": mode,
            "reason": (
                "the only pull request is ready, but GitHub needs two pull "
                "requests before gh stack merge; open the next slice first"
            ),
        }
    if mode == "progressive" and prefix and (broken is None or broken["index"] > prefix_end):
        return _merge_action("progressive", prefix, _merge_via(rows))
    if (
        mode == "atomic"
        and slices_remaining == 0
        and broken is None
        and len(prefix) == len(open_rows)
    ):
        return _merge_action("atomic", open_rows, _merge_via(rows))
    if broken is not None:
        return _rebase(broken, _expected_base(broken, by_num, trunk), open_rows)

    for row in open_rows:
        if _ready(row, by_num, trunk):
            continue
        if _needs_address(row):
            latest = row["reviews"][-1]
            return {
                "action": "address",
                "pr": row["number"],
                "round": latest["round"],
                "verdict": latest["verdict"],
                "reviewed_head": latest["head"],
                "sync_prs": [
                    item["number"] for item in open_rows if item["index"] > row["index"]
                ],
                "reason": (
                    "latest trusted review requested changes and that round has no "
                    "trusted harness-fix yet; the review head does not have to match "
                    "the current head"
                ),
            }
        if _fix_mismatch(row):
            return {
                "action": "idle",
                "reason": (
                    "a harness-fix exists for the latest round but its head does not "
                    "match the live head; post a harness-fix for the current head "
                    "or a harness-rebase marker when the diff is unchanged"
                ),
            }
        if _stale_exhausted(row):
            return {
                "action": "stop",
                "reason": (
                    f"PR {row['number']} used its review cap and the live head is not "
                    "covered by that review; refusing to merge code the reviewer did not approve"
                ),
            }
        if row["mergeable"] != "MERGEABLE":
            return {
                "action": "idle",
                "reason": f"PR {row['number']} mergeability is not MERGEABLE yet; refetch",
            }
        if _needs_review(row) and "harness:awaiting-review" not in row["labels"]:
            return _label(row)

    unreviewed_above = [row for row in open_rows[1:] if not row["reviews"]]
    if slices_remaining > 0 and len(unreviewed_above) < ahead_cap:
        parent = open_rows[-1]
        return {
            "action": "continue",
            "parent_pr": parent["number"],
            "base_branch": parent["head_name"],
            "next_index": parent["index"] + 1,
            "land": mode,
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
    return {"action": "idle", "reason": "nothing to rebase, address, merge, or label"}


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
        if "harness:awaiting-review" not in row["labels"]:
            continue
        if row["labels"] & BLOCKING_LABELS or _ancestor_blocking(row, by_num):
            continue
        if row["mergeable"] != "MERGEABLE":
            continue
        if row["base"] != _expected_base(row, by_num, trunk):
            continue
        if any(_covers_live_head(row, review["head"]) for review in row["reviews"]):
            continue
        if len(row["reviews"]) >= row["max_rounds"]:
            continue
        if row["reviews"]:
            latest = row["reviews"][-1]
            if latest["verdict"] == "changes-requested" and not any(
                _covers_live_head(row, fix["head"]) for fix in _fixes_for(row, latest["round"])
            ):
                continue
        return {
            "action": "review",
            "pr": row["number"],
            "round": len(row["reviews"]) + 1,
            "head": row["head"],
            "max_rounds": row["max_rounds"],
            "reason": "layer is awaiting review on a head that has not been reviewed",
        }
    if not _open_rows(rows):
        return {"action": "stop", "reason": "no open stack PRs"}
    return {"action": "idle", "reason": "no eligible layer"}


def decide(role: str, payload: Any) -> dict[str, Any]:
    if role == "develop":
        return decide_develop(payload)
    if role == "review":
        return decide_review(payload)
    if role == "range-diff":
        text = payload if isinstance(payload, str) else ""
        return {"unchanged": range_diff_unchanged(text)}
    raise SystemExit(f"Unknown role {role!r}. Use develop, review, or range-diff.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["develop", "review", "range-diff"])
    parser.add_argument("payload", type=argparse.FileType("r"))
    args = parser.parse_args(argv)
    if args.role == "range-diff":
        payload: dict[str, Any] | str = args.payload.read()
    else:
        payload = json.load(args.payload)
    json.dump(decide(args.role, payload), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

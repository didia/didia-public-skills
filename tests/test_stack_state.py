import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "templates" / "shared"))

import stack_state  # noqa: E402


def marker(index, parent="", max_rounds=2):
    return (
        "<!-- harness-stack\n"
        "version: 1\n"
        "stack-id: demo\n"
        f"stack-index: {index}\n"
        f"stack-parent: {parent}\n"
        f"max-rounds: {max_rounds}\n"
        "-->"
    )


def review(round_n, verdict, head):
    return {
        "body": (
            f"<!-- harness-review round: {round_n} verdict: {verdict} head: {head} -->"
        )
    }


def pr(
    number,
    index,
    *,
    parent="",
    base="main",
    head_name="feat",
    head="abc",
    state="OPEN",
    mergeable="MERGEABLE",
    labels=None,
    reviews=None,
    comments=None,
    max_rounds=2,
):
    return {
        "number": number,
        "state": state,
        "baseRefName": base,
        "headRefName": head_name,
        "headRefOid": head,
        "mergeable": mergeable,
        "labels": labels or [],
        "body": marker(index, parent, max_rounds),
        "reviews": reviews or [],
        "comments": comments or [],
    }


class DevelopTests(unittest.TestCase):
    def test_retarget_when_parent_merged(self):
        payload = {
            "trunk": "main",
            "prs": [
                pr(1, 1, state="MERGED", head_name="feat-1"),
                pr(2, 2, parent="1", base="feat-1", head_name="feat-2"),
            ],
        }
        action = stack_state.decide("develop", payload)
        self.assertEqual(action["action"], "retarget")
        self.assertEqual(action["pr"], 2)
        self.assertEqual(action["base"], "main")

    def test_sync_only_when_conflicting(self):
        payload = {
            "trunk": "main",
            "prs": [pr(1, 1, base="main", mergeable="MERGEABLE")],
        }
        self.assertNotEqual(stack_state.decide("develop", payload)["action"], "sync")
        payload["prs"][0]["mergeable"] = "CONFLICTING"
        self.assertEqual(stack_state.decide("develop", payload)["action"], "sync")

    def test_address_ignores_head_mismatch(self):
        payload = {
            "trunk": "main",
            "prs": [
                pr(
                    1,
                    1,
                    head="new",
                    reviews=[review(1, "changes-requested", "old")],
                )
            ],
        }
        action = stack_state.decide("develop", payload)
        self.assertEqual(action["action"], "address")
        self.assertEqual(action["round"], 1)

    def test_approved_merges_instead_of_address(self):
        payload = {
            "trunk": "main",
            "prs": [pr(1, 1, reviews=[review(1, "approved", "old")])],
        }
        self.assertEqual(stack_state.decide("develop", payload)["action"], "merge")

    def test_cap_unreviewed_ahead(self):
        payload = {
            "trunk": "main",
            "slices_remaining": 1,
            "prs": [
                pr(1, 1, head_name="a"),
                pr(2, 2, parent="1", base="a", head_name="b"),
                pr(3, 3, parent="2", base="b", head_name="c"),
            ],
        }
        action = stack_state.decide("develop", payload)
        self.assertEqual(action["action"], "idle")
        payload["prs"].pop()
        action = stack_state.decide("develop", payload)
        self.assertEqual(action["action"], "continue")


class ReviewTests(unittest.TestCase):
    def test_reviews_bottom_awaiting_current_head(self):
        payload = {
            "trunk": "main",
            "prs": [
                pr(
                    1,
                    1,
                    labels=["harness:awaiting-review"],
                    reviews=[review(1, "changes-requested", "old")],
                    head="new",
                )
            ],
        }
        action = stack_state.decide("review", payload)
        self.assertEqual(action["action"], "review")
        self.assertEqual(action["round"], 2)

    def test_skips_already_reviewed_head(self):
        payload = {
            "trunk": "main",
            "prs": [
                pr(
                    1,
                    1,
                    labels=["harness:awaiting-review"],
                    reviews=[review(1, "changes-requested", "abc")],
                )
            ],
        }
        self.assertEqual(stack_state.decide("review", payload)["action"], "idle")


if __name__ == "__main__":
    unittest.main()

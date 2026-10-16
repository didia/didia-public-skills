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


def review(round_n, verdict, head, author="reviewer", state="COMMENTED"):
    return {
        "state": state,
        "author": {"login": author},
        "body": (
            f"<!-- harness-review round: {round_n} verdict: {verdict} head: {head} -->"
        ),
    }


def fix(round_n, head, author="developer"):
    return {
        "author": {"login": author},
        "body": f"<!-- harness-fix round: {round_n} head: {head} -->",
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


def payload(prs, **extra):
    body = {
        "trunk": "main",
        "trusted_reviewers": ["reviewer"],
        "trusted_developers": ["developer"],
        "prs": prs,
    }
    body.update(extra)
    return body


class DevelopTests(unittest.TestCase):
    def test_retarget_when_parent_merged(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, state="MERGED", head_name="feat-1"),
                    pr(2, 2, parent="1", base="feat-1", head_name="feat-2"),
                ]
            ),
        )
        self.assertEqual(action["action"], "retarget")
        self.assertEqual(action["pr"], 2)
        self.assertEqual(action["base"], "main")

    def test_sync_only_when_conflicting(self):
        body = payload([pr(1, 1, base="main", mergeable="MERGEABLE")])
        self.assertEqual(stack_state.decide("develop", body)["action"], "promote")
        body["prs"][0]["mergeable"] = "CONFLICTING"
        self.assertEqual(stack_state.decide("develop", body)["action"], "sync")

    def test_address_ignores_head_mismatch(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="new",
                        reviews=[review(1, "changes-requested", "old")],
                    )
                ]
            ),
        )
        self.assertEqual(action["action"], "address")
        self.assertEqual(action["round"], 1)

    def test_approved_merges_only_when_head_matches(self):
        action = stack_state.decide(
            "develop",
            payload([pr(1, 1, head="abc", reviews=[review(1, "approved", "abc")])]),
        )
        self.assertEqual(action["action"], "merge")
        self.assertEqual(action["head"], "abc")
        stale = stack_state.decide(
            "develop",
            payload([pr(1, 1, head="new", reviews=[review(1, "approved", "old")])]),
        )
        self.assertNotEqual(stale["action"], "merge")

    def test_untrusted_or_unpublished_review_cannot_merge(self):
        for item in (
            review(1, "approved", "abc", author="stranger"),
            review(1, "approved", "abc", state="PENDING"),
            review(1, "approved", "abc", state="DISMISSED"),
        ):
            action = stack_state.decide(
                "develop",
                payload([pr(1, 1, reviews=[item])]),
            )
            self.assertNotEqual(action["action"], "merge")

    def test_cap_merge_requires_fix_on_live_head(self):
        approved = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="abc",
                        max_rounds=1,
                        reviews=[review(1, "changes-requested", "old")],
                        comments=[fix(1, "abc")],
                    )
                ]
            ),
        )
        self.assertEqual(approved["action"], "merge")
        self.assertEqual(approved["head"], "abc")
        forged = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="abc",
                        max_rounds=1,
                        reviews=[review(1, "changes-requested", "old")],
                        comments=[fix(1, "nonexistent")],
                    )
                ]
            ),
        )
        self.assertNotEqual(forged["action"], "merge")

    def test_cap_unreviewed_ahead(self):
        body = payload(
            [
                pr(1, 1, head_name="a", labels=["harness:awaiting-review"]),
                pr(2, 2, parent="1", base="a", head_name="b"),
                pr(3, 3, parent="2", base="b", head_name="c"),
            ],
            slices_remaining=1,
        )
        self.assertEqual(stack_state.decide("develop", body)["action"], "idle")
        body["prs"].pop()
        action = stack_state.decide("develop", body)
        self.assertEqual(action["action"], "continue")

    def test_fresh_stack_starts_slice_one(self):
        action = stack_state.decide("develop", payload([], slices_remaining=3))
        self.assertEqual(action["action"], "continue")
        self.assertEqual(action["next_index"], 1)
        self.assertEqual(action["base_branch"], "main")

    def test_next_slice_keeps_index_after_merge(self):
        action = stack_state.decide(
            "develop",
            payload([pr(1, 1, state="MERGED")], slices_remaining=1),
        )
        self.assertEqual(action["action"], "continue")
        self.assertEqual(action["next_index"], 2)
        self.assertEqual(action["base_branch"], "main")

    def test_promote_after_parent_merge(self):
        retargeted = payload(
            [
                pr(1, 1, state="MERGED", head_name="feat-1"),
                pr(
                    2,
                    2,
                    parent="1",
                    base="main",
                    head_name="feat-2",
                    labels=["harness:stacked"],
                ),
            ],
            slices_remaining=0,
        )
        action = stack_state.decide("develop", retargeted)
        self.assertEqual(action["action"], "promote")
        self.assertEqual(action["pr"], 2)
        retargeted["prs"][1]["labels"] = ["harness:awaiting-review"]
        self.assertEqual(stack_state.decide("review", retargeted)["action"], "review")

    def test_missing_or_closed_parent_stops(self):
        missing = stack_state.decide(
            "develop",
            payload([pr(2, 2, parent="1", base="feat-1")]),
        )
        self.assertEqual(missing["action"], "stop")
        closed = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, state="CLOSED", head_name="feat-1"),
                    pr(2, 2, parent="1", base="feat-1"),
                ]
            ),
        )
        self.assertEqual(closed["action"], "stop")

    def test_identities_required(self):
        action = stack_state.decide("develop", {"trunk": "main", "prs": [], "slices_remaining": 1})
        self.assertEqual(action["action"], "stop")


class ReviewTests(unittest.TestCase):
    def test_second_round_requires_a_fix_on_the_live_head(self):
        waiting = payload(
            [
                pr(
                    1,
                    1,
                    labels=["harness:awaiting-review"],
                    reviews=[review(1, "changes-requested", "old")],
                    head="new",
                )
            ]
        )
        self.assertEqual(stack_state.decide("review", waiting)["action"], "idle")
        waiting["prs"][0]["comments"] = [fix(1, "new")]
        action = stack_state.decide("review", waiting)
        self.assertEqual(action["action"], "review")
        self.assertEqual(action["round"], 2)

    def test_skips_already_reviewed_head(self):
        action = stack_state.decide(
            "review",
            payload(
                [
                    pr(
                        1,
                        1,
                        labels=["harness:awaiting-review"],
                        reviews=[review(1, "changes-requested", "abc")],
                    )
                ]
            ),
        )
        self.assertEqual(action["action"], "idle")


if __name__ == "__main__":
    unittest.main()

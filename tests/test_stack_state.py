import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "templates" / "shared"))

import stack_state  # noqa: E402


def marker(index, parent="", max_rounds=2, land=""):
    land_line = f"land: {land}\n" if land else ""
    return (
        "<!-- harness-stack\n"
        "version: 1\n"
        "stack-id: demo\n"
        f"stack-index: {index}\n"
        f"stack-parent: {parent}\n"
        f"max-rounds: {max_rounds}\n"
        f"{land_line}"
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


def rebase(old, new, author="developer"):
    return {
        "author": {"login": author},
        "body": f"<!-- harness-rebase from: {old} head: {new} -->",
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
    land="",
):
    return {
        "number": number,
        "state": state,
        "baseRefName": base,
        "headRefName": head_name,
        "headRefOid": head,
        "mergeable": mergeable,
        "labels": labels or [],
        "body": marker(index, parent, max_rounds, land),
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
    def test_rebase_when_parent_merged_and_base_is_stale(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, state="MERGED", head_name="feat-1"),
                    pr(2, 2, parent="1", base="feat-1", head_name="feat-2"),
                ]
            ),
        )
        self.assertEqual(action["action"], "rebase")
        self.assertEqual(action["pr"], 2)
        self.assertEqual(action["base"], "main")

    def test_label_when_mergeable_and_rebase_when_conflicting(self):
        body = payload([pr(1, 1, base="main", mergeable="MERGEABLE")])
        labeled = stack_state.decide("develop", body)
        self.assertEqual(labeled["action"], "label")
        self.assertEqual(labeled["add_labels"], ["harness:awaiting-review"])
        body["prs"][0]["mergeable"] = "CONFLICTING"
        self.assertEqual(stack_state.decide("develop", body)["action"], "rebase")

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
        self.assertEqual(action["land"], "progressive")
        self.assertEqual(action["via"], "pr")
        self.assertEqual(action["through"], 1)
        self.assertEqual(action["prs"], [1])
        self.assertEqual(action["heads"], {"1": "abc"})
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
        self.assertEqual(approved["through"], 1)
        self.assertEqual(approved["heads"], {"1": "abc"})
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
        waiting = ["harness:awaiting-review"]
        body = payload(
            [
                pr(1, 1, head_name="a", labels=waiting),
                pr(2, 2, parent="1", base="a", head_name="b", labels=waiting),
                pr(3, 3, parent="2", base="b", head_name="c", labels=waiting),
            ],
            slices_remaining=1,
        )
        self.assertEqual(stack_state.decide("develop", body)["action"], "idle")
        body["prs"].pop()
        action = stack_state.decide("develop", body)
        self.assertEqual(action["action"], "continue")

    def test_unlabeled_upper_is_labeled_before_continue(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, head_name="a", labels=["harness:awaiting-review"]),
                    pr(2, 2, parent="1", base="a", head_name="b"),
                ],
                slices_remaining=1,
            ),
        )
        self.assertEqual(action["action"], "label")
        self.assertEqual(action["pr"], 2)

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

    def test_label_after_parent_merge_when_github_already_retargeted(self):
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
        self.assertEqual(action["action"], "label")
        self.assertEqual(action["pr"], 2)
        self.assertIn("harness:stacked", action["remove_labels"])
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

    def test_progressive_merges_ready_prefix_only(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, head_name="a", head="aaa", reviews=[review(1, "approved", "aaa")]),
                    pr(
                        2,
                        2,
                        parent="1",
                        base="a",
                        head_name="b",
                        head="bbb",
                        reviews=[review(1, "approved", "bbb")],
                    ),
                    pr(3, 3, parent="2", base="b", head_name="c", head="ccc"),
                ],
                slices_remaining=1,
            ),
        )
        self.assertEqual(action["action"], "merge")
        self.assertEqual(action["land"], "progressive")
        self.assertEqual(action["via"], "stack")
        self.assertEqual(action["through"], 2)
        self.assertEqual(action["prs"], [1, 2])
        self.assertEqual(action["heads"], {"1": "aaa", "2": "bbb"})

    def test_progressive_stops_prefix_at_first_unready(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, head_name="a", head="aaa", reviews=[review(1, "approved", "aaa")]),
                    pr(2, 2, parent="1", base="a", head_name="b", head="bbb"),
                    pr(
                        3,
                        3,
                        parent="2",
                        base="b",
                        head_name="c",
                        head="ccc",
                        reviews=[review(1, "approved", "ccc")],
                    ),
                ]
            ),
        )
        self.assertEqual(action["through"], 1)
        self.assertEqual(action["prs"], [1])

    def test_atomic_waits_until_every_open_pr_is_ready(self):
        open_stack = [
            pr(
                1,
                1,
                head_name="a",
                head="aaa",
                land="atomic",
                reviews=[review(1, "approved", "aaa")],
            ),
            pr(
                2,
                2,
                parent="1",
                base="a",
                head_name="b",
                head="bbb",
                land="atomic",
                reviews=[review(1, "approved", "bbb")],
            ),
            pr(3, 3, parent="2", base="b", head_name="c", head="ccc", land="atomic"),
        ]
        waiting = stack_state.decide("develop", payload(open_stack, slices_remaining=0))
        self.assertNotEqual(waiting["action"], "merge")
        open_stack[2]["reviews"] = [review(1, "approved", "ccc")]
        landed = stack_state.decide("develop", payload(open_stack, slices_remaining=0))
        self.assertEqual(landed["action"], "merge")
        self.assertEqual(landed["land"], "atomic")
        self.assertEqual(landed["through"], 3)
        self.assertEqual(landed["prs"], [1, 2, 3])

    def test_atomic_does_not_merge_while_slices_remain(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="aaa",
                        land="atomic",
                        reviews=[review(1, "approved", "aaa")],
                    )
                ],
                slices_remaining=1,
            ),
        )
        self.assertEqual(action["action"], "continue")

    def test_rebase_marker_carries_approval_to_new_head(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="new",
                        reviews=[review(1, "approved", "old")],
                        comments=[rebase("old", "mid"), rebase("mid", "new")],
                    )
                ]
            ),
        )
        self.assertEqual(action["action"], "merge")
        self.assertEqual(action["heads"], {"1": "new"})
        stranger = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="new",
                        reviews=[review(1, "approved", "old")],
                        comments=[rebase("old", "new", author="stranger")],
                    )
                ]
            ),
        )
        self.assertNotEqual(stranger["action"], "merge")

    def test_exhausted_stale_head_stops(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="new",
                        max_rounds=1,
                        reviews=[review(1, "approved", "old")],
                    )
                ]
            ),
        )
        self.assertEqual(action["action"], "stop")

    def test_disagreeing_land_modes_stop(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, head_name="a", land="progressive"),
                    pr(2, 2, parent="1", base="a", head_name="b", land="atomic"),
                ]
            ),
        )
        self.assertEqual(action["action"], "stop")

    def test_address_upper_while_bottom_waits_for_review(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, head_name="a", labels=["harness:awaiting-review"]),
                    pr(
                        2,
                        2,
                        parent="1",
                        base="a",
                        head_name="b",
                        head="bbb",
                        labels=["harness:awaiting-review"],
                        reviews=[review(1, "changes-requested", "bbb")],
                    ),
                ]
            ),
        )
        self.assertEqual(action["action"], "address")
        self.assertEqual(action["pr"], 2)
        self.assertEqual(action["sync_prs"], [])

    def test_ready_lone_pr_opens_next_slice_before_stack_merge(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(
                        1,
                        1,
                        head_name="a",
                        head="aaa",
                        reviews=[review(1, "approved", "aaa")],
                    )
                ],
                slices_remaining=1,
            ),
        )
        self.assertEqual(action["action"], "continue")
        self.assertEqual(action["next_index"], 2)
        self.assertEqual(action["base_branch"], "a")

    def test_last_pr_of_an_existing_stack_uses_stack_merge(self):
        action = stack_state.decide(
            "develop",
            payload(
                [
                    pr(1, 1, state="MERGED", head_name="a"),
                    pr(
                        2,
                        2,
                        parent="1",
                        base="main",
                        head_name="b",
                        head="bbb",
                        reviews=[review(1, "approved", "bbb")],
                    ),
                ]
            ),
        )
        self.assertEqual(action["action"], "merge")
        self.assertEqual(action["via"], "stack")
        self.assertEqual(action["through"], 2)


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

    def test_reviews_upper_pr_while_parent_is_open(self):
        waiting = ["harness:awaiting-review"]
        both = stack_state.decide(
            "review",
            payload(
                [
                    pr(1, 1, head_name="a", head="aaa", labels=waiting),
                    pr(
                        2,
                        2,
                        parent="1",
                        base="a",
                        head_name="b",
                        head="bbb",
                        labels=waiting,
                    ),
                ]
            ),
        )
        self.assertEqual(both["action"], "review")
        self.assertEqual(both["pr"], 1)
        upper = stack_state.decide(
            "review",
            payload(
                [
                    pr(
                        1,
                        1,
                        head_name="a",
                        head="aaa",
                        labels=waiting,
                        reviews=[review(1, "approved", "aaa")],
                    ),
                    pr(
                        2,
                        2,
                        parent="1",
                        base="a",
                        head_name="b",
                        head="bbb",
                        labels=waiting,
                    ),
                ]
            ),
        )
        self.assertEqual(upper["action"], "review")
        self.assertEqual(upper["pr"], 2)

    def test_rebase_marker_satisfies_reviewed_head(self):
        action = stack_state.decide(
            "review",
            payload(
                [
                    pr(
                        1,
                        1,
                        head="new",
                        labels=["harness:awaiting-review"],
                        reviews=[review(1, "approved", "old")],
                        comments=[rebase("old", "new")],
                    )
                ]
            ),
        )
        self.assertEqual(action["action"], "idle")

    def test_skips_layer_while_an_ancestor_is_being_rewritten(self):
        for label in ("harness:syncing", "harness:addressing-review"):
            action = stack_state.decide(
                "review",
                payload(
                    [
                        pr(1, 1, head_name="a", labels=[label]),
                        pr(
                            2,
                            2,
                            parent="1",
                            base="a",
                            head_name="b",
                            labels=["harness:awaiting-review"],
                        ),
                    ]
                ),
            )
            self.assertEqual(action["action"], "idle", label)


class RangeDiffTests(unittest.TestCase):
    def test_unchanged_summary_rows_count_as_unchanged(self):
        text = (
            "1:  9d19f1b = 1:  abcdef0 Land stack prefixes\n"
            "2:  1111111 = 2:  2222222 Second commit\n"
        )
        self.assertTrue(stack_state.range_diff_unchanged(text))
        self.assertEqual(
            stack_state.decide("range-diff", text),
            {"unchanged": True},
        )

    def test_empty_output_is_unchanged(self):
        self.assertTrue(stack_state.range_diff_unchanged(""))

    def test_changed_added_or_removed_patches_are_not_unchanged(self):
        changed = "1:  aaaaaaa ! 1:  bbbbbbb Reword\n    @@ -1 +1 @@\n"
        added = "-:  ------- > 1:  ccccccc New commit\n"
        removed = "1:  ddddddd < -:  ------- Dropped\n"
        self.assertFalse(stack_state.range_diff_unchanged(changed))
        self.assertFalse(stack_state.range_diff_unchanged(added))
        self.assertFalse(stack_state.range_diff_unchanged(removed))


if __name__ == "__main__":
    unittest.main()

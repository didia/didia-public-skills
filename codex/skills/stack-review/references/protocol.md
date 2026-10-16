# Harness stack protocol

Shared contract for `stack-develop` and `stack-review`. GitHub is the only shared
state. Either harness can resume after a restart by reading labels, PR bodies, and
markers below.

## Labels

Create with `gh label create` if missing (any color; descriptions optional):

| Label | Meaning |
|---|---|
| `harness:awaiting-review` | Current stack bottom, ready for the external reviewer |
| `harness:addressing-review` | Developer is applying external review feedback |
| `harness:syncing` | Developer is updating a branch after the parent merged |
| `harness:stacked` | Open PR that is not the stack bottom; reviewer ignores it |

Only one open PR in a stack should carry `harness:awaiting-review` at a time.
Never put that label on a PR while `mergeable` is `CONFLICTING` or while
`harness:syncing` / `harness:addressing-review` is set.

## PR body marker

Every PR in the stack carries this HTML comment (exact keys). Keep it at the
end of the body so humans still read the summary first.

```html
<!-- harness-stack
version: 1
stack-id: <slug>
stack-index: 2
stack-parent: 123
max-rounds: 2
-->
```

- `stack-id` — short slug shared by every PR in the stack (and the stack issue).
- `stack-index` — 1-based position; 1 is the bottom.
- `stack-parent` — parent PR number, or empty on the bottom.
- `max-rounds` — max `pr-review` passes by the external harness for this PR.
  Default **2** when omitted from the user invocation, so the reviewer sees the
  fix. Copied onto every PR; the reviewer never raises it.

## Review and fix markers

Each external review is **one** GitHub pull-request review. End its body with:

```html
<!-- harness-review round: N verdict: approved|changes-requested head: <sha> -->
```

- `round` — 1-based index among `harness-review` markers on that PR.
- `verdict` — `approved` when no Critical or High findings remain; otherwise
  `changes-requested`. Medium and Low do not block.
- `head` — `headRefOid` that was reviewed.

Each developer response to an external review is a top-level PR comment:

```html
<!-- harness-fix round: N head: <sha> -->
```

- `round` — the `harness-review` round this push answers.
- `head` — new `headRefOid` after the fix push.

Round count is the number of `harness-review` markers on the PR. Do not keep a
separate counter that both sides edit.

## Blocking findings

Same severity rubric as `pr-review`: Critical and High block merge and further
external rounds until fixed. Medium and Low do not block.

## Stack issue (from-scratch stacks)

When the developer slices a new task, it opens a GitHub issue titled
`stack: <slug>` with the ordered slice list and `max-rounds`. That issue is
documentation and recovery; labels and PR markers remain authoritative for the
runtime loop.

## Merge and base rules

- Stack order: PR *n* bases on the head branch of PR *n−1* (PR 1 bases on the
  repo trunk, e.g. `main` or `dev`).
- Prefer `gh pr merge --merge` so child history stays intact. If the repo
  forbids merge commits, use squash/rebase as required.
- After a parent merges, retarget the child yourself:
  `gh pr edit <child> --base <trunk-or-new-parent-head>`. GitHub does not
  reliably retarget children when the parent branch is kept. Do not depend on
  "Automatically delete head branches" or on `--delete-branch`.
- Then sync the child if `mergeable` is `CONFLICTING`, before labeling it
  `harness:awaiting-review`.
- At most two open PRs above the bottom may have zero `harness-review` markers.
  That is `max_unreviewed_ahead: 2`.

## Next action

`scripts/stack_state.py` is the state machine. Fetch PR JSON, write the payload
described in that script, and run `develop` or `review`. Do the one action it
returns. Do not re-derive retarget, sync, address, or merge from this prose.

Schedule the next poll with `/loop` or a scheduled wakeup. A foreground
`sleep 60` does not work: Claude Code blocks long sleeps, and the context
grows on every poll.

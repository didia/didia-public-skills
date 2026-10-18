# Harness stack protocol

Shared contract for `stack-develop` and `stack-review`. GitHub is the only shared
state. Either harness can resume after a restart by reading labels, PR bodies, and
markers below.

## Labels

Create with `gh label create` if missing (any color; descriptions optional):

| Label | Meaning |
|---|---|
| `harness:awaiting-review` | This layer is ready for an external review pass. Any open layer may carry it |
| `harness:addressing-review` | Developer is applying external review feedback on this layer |
| `harness:syncing` | Developer is rebasing the stack |
| `harness:stacked` | Legacy. Do not treat it as a reason to skip review. Remove it when labeling `harness:awaiting-review` |

Several open PRs may carry `harness:awaiting-review` at once. Never put that
label on a PR while `mergeable` is `CONFLICTING` or while
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
land: progressive
-->
```

- `stack-id` — short slug shared by every PR in the stack (and the stack issue).
- `stack-index` — 1-based position; 1 is the bottom.
- `stack-parent` — parent PR number, or empty on the bottom.
- `max-rounds` — max `pr-review` passes by the external harness for this PR.
  Default **2** when omitted from the user invocation, so the reviewer sees the
  fix. Copied onto every PR; the reviewer never raises it.
- `land` — `progressive` (default) or `atomic`. Every open PR must agree.
  Omitted means `progressive`.

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

A trusted developer comment carries an earlier review or fix onto a new SHA
when a rebase did not change that layer's diff:

```html
<!-- harness-rebase from: <old-sha> head: <new-sha> -->
```

Chain them (`old` → `mid` → `new`). Post one only when
`git range-diff <old-base>..<old-head> <new-base>..<new-head>` is empty.
A non-empty range-diff means the approval does not cover the new head.

Round count is the number of `harness-review` markers on the PR. Do not keep a
separate counter that both sides edit.

## Blocking findings

Same severity rubric as `pr-review`: Critical and High block merge and further
external rounds until fixed. Medium and Low do not block.

## Stack issue (from-scratch stacks)

When the developer slices a new task, or follows an approved plan's stack, it
opens a GitHub issue titled `stack: <slug>` with the ordered slice list,
`land`, and `max-rounds`. That issue is
documentation and recovery; labels and PR markers remain authoritative for the
runtime loop.

## Land modes

The chain must be a GitHub stack (`gh stack submit` or `gh stack link`), in one
repository. `gh pr merge` cannot merge a stack.

| `land` | What merges |
|---|---|
| `progressive` (default) | The longest ready prefix from the bottom, in one `gh stack merge <through>`. PRs above it stay open. Each slice has to be independently testable and deployable. |
| `atomic` | The top PR, only when every open PR is ready and `slices_remaining` is 0. All-or-nothing: GitHub merges the whole group or nothing. |

A layer is ready when it is `MERGEABLE`, its base is the parent head (or trunk
if the parent is merged), it is not `harness:syncing` or
`harness:addressing-review`, and a trusted approval covers the live head — or
the round cap is used and a trusted fix covers the live head. A SHA covers the
live head when it is that head, or a chain of `harness-rebase` markers connects
them.

`progressive` may land that prefix while upper PRs are still in review and
while planned slices are still unopened. `atomic` waits. Do not switch mode
because the top is unfinished. If one slice cannot ship without a later slice,
the stack is `atomic`.

## Merge and base rules

- Stack order: PR *n* bases on the head branch of PR *n−1* (PR 1 bases on the
  repo trunk, e.g. `main` or `dev`).
- Merge with `gh stack merge <through> --yes --merge`, where `through` is the
  field the state script returned. Refetch first and stop if any PR in `heads`
  has a different `headRefOid`. If the repo rejects merge commits, rerun the
  same command with `--squash` or `--rebase`. Do not use `gh pr merge`.
- An approval or fix counts only when its SHA covers the live head, its author
  is a trusted login, and the review is submitted (not pending or dismissed).
- After a prefix merges, GitHub rebases the PRs above it onto trunk. Do not
  `gh pr edit --base`. If a child still bases on a merged parent, or any PR is
  `CONFLICTING`, the script returns `rebase`: `gh stack rebase`, then
  `gh stack push`. A merge commit in the stack breaks it; do not merge the base
  into the head.
- A payload that omits a `stack-parent`, or whose parent is closed and
  unmerged, is a stop. Do not point that child at trunk yourself.
- At most two open PRs above the bottom may have zero `harness-review` markers.
  That is `max_unreviewed_ahead: 2`. Those PRs are still eligible for review.
- Pass `slices_remaining` as the number of planned slices that have no PR yet.
  An adopted stack with nothing left to open passes 0.

## Next action

`scripts/stack_state.py` is the state machine. Fetch PR JSON, write the payload
described in that script, and run `develop` or `review`. Do the one action it
returns. Do not re-derive rebase, address, merge, or label from this prose.

Schedule the next poll with `/loop` or a scheduled wakeup. A foreground
`sleep 60` does not work: Claude Code blocks long sleeps, and the context
grows on every poll.

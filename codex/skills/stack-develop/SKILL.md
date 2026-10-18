---
name: stack-develop
description: Use when the user says you are the developer in a cross-harness review, asks to drive a stack of PRs while another harness reviews, mentions "stack-develop", stacked PRs with an external reviewer, or wants to keep opening child PRs while waiting for review comments on earlier ones. Also use when they hand an ordered list of existing PRs to adopt as a stack, a larger task to slice into stacked PRs, or they want the stack to land progressively or all at once (`land: atomic`). Requires develop-review installed on this harness, git, the gh CLI, and the gh-stack extension.
compatibility: Codex (needs subagent support to run separate generative/adversarial context windows), develop-review installed alongside this skill, a git repository, and the gh CLI authenticated for opening and merging pull requests.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# Stack-Develop

Orchestrates a stack of pull requests on **this** harness while another harness
runs `stack-review`. You do not invent an implementation loop: every code change
goes through `develop-review`. You own stack order, labels, merge, and sync.

Read `references/protocol.md` before the first GitHub write. That file is the
contract both harnesses share.

## Prerequisites

Check up front and say what is missing:

- **`develop-review`** at `~/.codex/skills/develop-review/SKILL.md` (or the
  project install path). This skill does nothing useful without it.
- **git** and an authenticated **`gh`** (`gh auth status`).
- The **gh-stack** extension (`gh extension install github/gh-stack`, then
  `gh stack --help`). Stacks stay in one repository; forks cannot join one.
- Subagents as required by `develop-review`.

## Configuration

- **`max-rounds`** — from the user (`review rounds: 5`). Default **2**, so the
  external reviewer sees the fix. Written on the stack issue and every PR
  marker. Counts external `pr-review` passes only; `develop-review` keeps its
  own internal cap of 5.
- **Trunk** — base of stack index 1 (`main`, `dev`, or whatever the user
  confirms). Default for a from-scratch stack in this repo's generator is
  `dev` when the user does not name one.
- **`trusted_reviewers` / `trusted_developers`** — GitHub logins. Ask once if
  the user did not name them. The state script ignores review and fix markers
  from any other account, and it ignores pending or dismissed reviews.
- **`land`** — `progressive` (default) or `atomic`. Write it on the stack issue
  and every PR marker. `progressive` lands a ready prefix while later PRs stay
  open; each slice must be independently testable and deployable. `atomic`
  lands the whole open stack in one merge once every layer is ready and no
  planned slice is left. Use `atomic` when the user asks for all-or-nothing,
  or when a slice cannot ship without a later slice. Do not flip the mode
  because the top PR is still open.

## Step 0: Establish the stack

### Existing PRs

When the user passes an ordered list of PR URLs/numbers:

1. Verify each PR's `baseRefName` is the previous PR's `headRefName` (first base
   is trunk). Stop and say so if the chain is wrong.
2. Link them into a GitHub stack, bottom to top: `gh stack link <pr> <pr> ...`.
3. Ensure the four `harness:*` labels exist.
4. Stamp or update the `harness-stack` marker on each body (`stack-index`,
   `stack-parent`, shared `stack-id`, `max-rounds`, `land`).
5. Label every open `MERGEABLE` PR `harness:awaiting-review`. Do not leave
   upper PRs labeled only `harness:stacked`.
6. Do **not** reimplement those PRs. Enter the main loop. `slices_remaining`
   is 0 unless the user still has unopened slices.

### From scratch

1. Take the ordered slices and `land` from the task.
   - Approved plan with `Delivery: stack`: use its slices and its
     `Land: progressive` or `Land: atomic` line. Do not re-slice or change land.
   - No such plan: slice the task into PR-sized slices. Under `progressive`,
     each slice must be independently testable and deployable. If one cannot
     ship alone, set `land: atomic` and say why.
2. Open a GitHub issue titled `stack: <slug>` with that list, `max-rounds`,
   and `land`.
3. Ensure the four `harness:*` labels exist.
4. Enter the main loop and implement slice 1 first (Continue priority).

## Main loop

Fetch every stack PR, including merged and closed parents (`gh pr view` with
`reviews` and `comments`, which include `author.login` and review `state`).
Write the JSON payload documented in `scripts/stack_state.py`, including
`trusted_reviewers`, `trusted_developers`, and `slices_remaining` (planned
slices that have no PR yet). Run:

```bash
python3 scripts/stack_state.py develop payload.json
```

Do the one action it prints. Then fetch again and ask the script again. Do not
re-derive the priority yourself. Schedule the next poll with `/loop` or a
scheduled wakeup. Do not foreground-sleep.

Exit when the script returns `stop`, or a blocking finding cannot be fixed —
then tell the user.

### rebase

1. Set `harness:syncing` on every PR in `sync_prs` and clear
   `harness:awaiting-review` on those PRs. The rebase rewrites the whole stack.
2. `gh stack checkout <pr>` when the stack is not checked out locally.
3. Record each open layer's base and head SHA.
4. `gh stack rebase`, then `gh stack push`. On a conflict, resolve it and
   `gh stack rebase --continue`. When the resolution changes behavior beyond
   taking one side, follow `develop-review` in **fix mode** on that layer
   before continuing. Never force-push trunk. Do not `gh pr edit --base`. Do
   not merge the base into the head.
5. For each layer, run
   `git -c color.ui=never range-diff <old-base>..<old-head> <new-base>..<new-head>`
   and pass that output to `python3 scripts/stack_state.py range-diff`. Post
   `<!-- harness-rebase from: <old-head> head: <new-head> -->` only when it
   prints `"unchanged": true`. That is every summary row using `=`, including
   output that is only those rows. Do not post the marker when a row uses
   `!`, `<`, or `>`, or when a diff hunk is present.
6. Clear `harness:syncing` only after the push. Leave `harness:awaiting-review`
   off until the script returns `label`.

### address

Only when the script says `address`. An `approved` verdict is not this action.

1. Finish an in-progress `develop-review` first if one is mid-flight.
2. Set `harness:addressing-review` on that PR (remove `harness:awaiting-review`).
   Set `harness:syncing` on every PR in `sync_prs` and clear
   `harness:awaiting-review` there too. Those layers will be rewritten.
3. Read and follow `develop-review` in **fix mode** with the external comments.
4. Commit any uncommitted changes on the layer you fixed. Skip
   `develop-review`'s push and `gh pr create`, then push that layer's branch.
5. `gh stack rebase --upstack`, then `gh stack push`, so layers above pick up
   the fix. Post `harness-rebase` on each upper layer only when
   `stack_state.py range-diff` reports `"unchanged": true`.
6. Post a top-level comment with the `harness-fix` marker for that `round` and
   the new head SHA of the layer you fixed.
7. Clear `harness:addressing-review` and `harness:syncing`. If rounds remain
   and the verdict was `changes-requested`, set `harness:awaiting-review` on
   the layer you fixed again.

### merge

Refetch every PR in `prs`. If any `headRefOid` differs from `heads`, do not
merge; ask the script again.

When `via` is `stack`:

```bash
gh stack merge <through> --yes --merge
```

`through` is the script field. That command lands `through` and every unmerged
PR below it, and leaves PRs above it open. GitHub then rebases the remainder
onto trunk. `land: progressive` does this for the ready prefix even when upper
PRs are still in review. `land: atomic` does this for the top PR only when the
script says the whole open stack is ready. If any PR in the group cannot merge,
none do. If the repo rejects merge commits, rerun with `--squash` or
`--rebase`. Do not `gh pr merge`.

When `via` is `pr`, the payload has a single pull request, so GitHub will not
form a stack. Merge that pull request with
`gh pr merge <through> --merge --match-head-commit <head>` using the SHA in
`heads`. Do not `gh stack merge` it. If `slices_remaining` is still positive,
the script returns `continue` instead, so the next slice exists before the
first stack merge.

### label

Remove `remove_labels` and add `add_labels` on that PR. This marks any open
layer, not only the bottom, as `harness:awaiting-review`. Do it again when
GitHub's mergeability was `UNKNOWN` and a later fetch says `MERGEABLE`.

### continue

1. Create the next branch at `next_index`. When the stack has no branches yet,
   `gh stack init --base <base_branch> <branch>`. Otherwise check out
   `base_branch` and `gh stack add <branch>`.
2. Read and follow `develop-review` for that slice through approval. The branch
   already exists. Skip its branch question.
3. Commit any uncommitted changes with a message describing the slice. That is
   the commit step of `develop-review`'s "open a pull request" section. Skip
   that section's push and `gh pr create`.
4. `gh stack submit --auto --open`.
5. Stamp the `harness-stack` marker (`max-rounds` default 2, and `land`).
6. Label that PR `harness:awaiting-review` when it is `MERGEABLE`.

The script refuses `continue` when two unreviewed PRs already sit above the
bottom. Adopted PRs are not reimplemented.

## Honesty

- Do not write feature code outside `develop-review`.
- Do not raise `max-rounds` or invent a second review procedure.
- Do not spawn `stack-review`; the other harness runs that skill.
- Do not merge past unfixed Critical/High findings.
- Do not `gh pr merge` unless the script sets `via` to `pr`. Do not
  `gh pr edit --base`.
- Do not `gh stack merge` the first slice while it is the only pull request
  and another slice is still planned.
- Do not hold a `progressive` prefix because a PR above it is still open.
- Do not merge an `atomic` stack until the script returns `merge`.
- Do not post `harness-rebase` unless `stack_state.py range-diff` reports
  `"unchanged": true`.

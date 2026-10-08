---
name: stack-develop
description: Use when the user says you are the developer in a cross-harness review, asks to drive a stack of PRs while another harness reviews, mentions "stack-develop", stacked PRs with an external reviewer, or wants to keep opening child PRs while waiting for review comments on earlier ones. Also use when they hand an ordered list of existing PRs to adopt as a stack, or a larger task to slice into stacked PRs. Requires develop-review installed on this harness, git, and the gh CLI.
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
- Subagents as required by `develop-review`.

## Configuration

- **`max-rounds`** — from the user (`review rounds: 5`). Default **1**. Written
  on the stack issue and every PR marker. Counts external `pr-review` passes
  only; `develop-review` keeps its own internal cap of 5.
- **Trunk** — base of stack index 1 (`main`, `dev`, or whatever the user
  confirms).

## Step 0: Establish the stack

### Existing PRs

When the user passes an ordered list of PR URLs/numbers:

1. Verify each PR's `baseRefName` is the previous PR's `headRefName` (first base
   is trunk). Stop and say so if the chain is wrong.
2. Ensure the four `harness:*` labels exist.
3. Stamp or update the `harness-stack` marker on each body (`stack-index`,
   `stack-parent`, shared `stack-id`, `max-rounds`).
4. Label the bottom `harness:awaiting-review` only if `mergeable` is
   `MERGEABLE`; label every open PR above it `harness:stacked`.
5. Do **not** reimplement those PRs. Enter the main loop.

### From scratch

When the user passes a task (and optional round cap):

1. Slice the task into an ordered list of PR-sized slices.
2. Open a GitHub issue titled `stack: <slug>` with that list and `max-rounds`.
3. Ensure the four `harness:*` labels exist.
4. Enter the main loop and implement slice 1 first (Continue priority).

## Main loop

Each pass, run these checks **in order**. Re-check before starting another
slice. When idle, sleep about 60 seconds and poll again. Exit when every PR in
the stack is merged, or a blocking finding cannot be fixed — then tell the user.

### 1. Sync

If a parent is merged, or a child reports `mergeable: CONFLICTING`:

1. Set `harness:syncing` on the child (remove `harness:awaiting-review` /
   `harness:stacked` while syncing).
2. Fetch. Let GitHub retarget the base when the parent branch is gone.
3. Update the head: merge the new base into the head and push. Use
   `git push --force-with-lease` on that head branch only when a rebase is
   required to drop commits already on trunk (typical after squash merge).
   Never force-push trunk.
4. If the resolution changes behavior beyond taking one side of a conflict,
   follow `develop-review` in **fix mode** on that diff and let its internal
   reviewer sign off before clearing the label.
5. Clear `harness:syncing` only after a successful push.
6. Walk the stack from lowest `stack-index` upward.
7. Do not set `harness:awaiting-review` until `mergeable` is `MERGEABLE`
   (re-query when GitHub returns null).

### 2. Address external review

If the bottom open PR has a `harness-review` for the current head with no
matching `harness-fix` for that round:

1. Prefer this over starting new slice work. Finish an in-progress
   `develop-review` (including its PR open) first if one is mid-flight.
2. Set `harness:addressing-review` (remove `harness:awaiting-review`).
3. Read and follow `develop-review` in **fix mode**: pass the external
   comments verbatim; its developer applies targeted fixes; its internal
   reviewer signs off on the new diff.
4. The PR already exists — **skip** `develop-review`'s "open a pull request"
   step; push to the existing head instead.
5. Post a top-level comment with the `harness-fix` marker for that round and
   the new head SHA.
6. Clear `harness:addressing-review`. If more external rounds remain
   (`reviews posted < max-rounds`) and the last verdict was
   `changes-requested`, set `harness:awaiting-review` again. If the verdict was
   `approved`, or the cap is already used and fixes are pushed with internal
   sign-off, go to Merge.

### 3. Merge

On the bottom open PR, merge when:

- the latest external verdict is `approved`, **or**
- external `max-rounds` is already used, fixes for that last review are
  pushed, and `develop-review`'s internal reviewer signed off.

Do **not** merge while any Critical or High from the latest external review is
still unfixed — stop and tell the user.

Prefer `gh pr merge --merge`. If the repo forbids merge commits, use
squash/rebase as required, then Sync the child. After merge, Sync the next PR
so it becomes the new bottom.

### 4. Continue

If nothing above is pending:

1. Create the next branch off the current top head (or trunk for index 1).
2. Read and follow `develop-review` for that slice. Tell it the branch and base
   already exist: base is the parent head (trunk for the first PR). It must
   skip its own branch question and open the PR against that base.
3. After it returns, stamp the `harness-stack` marker onto the PR body.
4. Label: bottom open PR → `harness:awaiting-review` (only if `MERGEABLE`);
   every open PR above it → `harness:stacked`.

New slice work does not start while an external review or a sync is waiting.
Adopted PRs are not reimplemented; `develop-review` runs for them only on
review fixes or non-trivial conflict resolution.

## Honesty

- Do not write feature code outside `develop-review`.
- Do not raise `max-rounds` or invent a second review procedure.
- Do not spawn `stack-review`; the other harness runs that skill.
- Do not merge past unfixed Critical/High findings.

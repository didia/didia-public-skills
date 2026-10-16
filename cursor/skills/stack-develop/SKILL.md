---
name: stack-develop
description: Use when the user says you are the developer in a cross-harness review, asks to drive a stack of PRs while another harness reviews, mentions "stack-develop", stacked PRs with an external reviewer, or wants to keep opening child PRs while waiting for review comments on earlier ones. Also use when they hand an ordered list of existing PRs to adopt as a stack, or a larger task to slice into stacked PRs. Requires develop-review installed on this harness, git, and the gh CLI.
compatibility: Cursor (needs Task-tool subagents to run separate generative/adversarial context windows), develop-review installed alongside this skill, a git repository, and the gh CLI authenticated for opening and merging pull requests.
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

- **`develop-review`** at `~/.cursor/skills/develop-review/SKILL.md` (or the
  project install path). This skill does nothing useful without it.
- **git** and an authenticated **`gh`** (`gh auth status`).
- Subagents as required by `develop-review`.

## Configuration

- **`max-rounds`** — from the user (`review rounds: 5`). Default **2**, so the
  external reviewer sees the fix. Written on the stack issue and every PR
  marker. Counts external `pr-review` passes only; `develop-review` keeps its
  own internal cap of 5.
- **Trunk** — base of stack index 1 (`main`, `dev`, or whatever the user
  confirms). Default for a from-scratch stack in this repo's generator is
  `dev` when the user does not name one.

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

Fetch the stack PRs (`gh pr view` / `gh pr list` plus reviews and comments),
write the JSON payload documented in `scripts/stack_state.py`, and run:

```bash
python3 scripts/stack_state.py develop payload.json
```

Do the one action it prints. Then fetch again and ask the script again. Do not
re-derive the priority yourself. Schedule the next poll with `/loop` or a
scheduled wakeup. Do not foreground-sleep.

Exit when the script returns `stop`, or a blocking finding cannot be fixed —
then tell the user.

### retarget

`gh pr edit <pr> --base <base>` using the `base` field. Then fetch again. Do
not wait for GitHub to retarget children after a merge.

### sync

1. Set `harness:syncing` (remove `harness:awaiting-review` / `harness:stacked`).
2. Merge the current base into the head and push. Use
   `git push --force-with-lease` on that head branch only when a rebase is
   required to drop commits already on trunk. Never force-push trunk.
3. If the resolution changes behavior beyond taking one side of a conflict,
   follow `develop-review` in **fix mode** and let its internal reviewer sign
   off before clearing the label.
4. Clear `harness:syncing` only after a successful push. Do not set
   `harness:awaiting-review` until `mergeable` is `MERGEABLE`.

### address

Only when the script says `address`. An `approved` verdict is not this action.

1. Finish an in-progress `develop-review` first if one is mid-flight.
2. Set `harness:addressing-review` (remove `harness:awaiting-review`).
3. Read and follow `develop-review` in **fix mode** with the external comments.
4. Skip `develop-review`'s "open a pull request" step; push to the existing head.
5. Post a top-level comment with the `harness-fix` marker for that `round` and
   the new head SHA.
6. Clear `harness:addressing-review`. If rounds remain and the verdict was
   `changes-requested`, set `harness:awaiting-review` again.

### merge

Prefer `gh pr merge --merge`. If the repo forbids merge commits, use
squash/rebase as required. After the merge, ask the script again — the child
usually needs `retarget`, then maybe `sync`. Do not merge while a Critical or
High from the latest external review is still unfixed.

### continue

1. Create the next branch off `base_branch` from the script (trunk for index 1).
2. Read and follow `develop-review` for that slice. The branch and base already
   exist. Skip its branch question and open the PR against that base.
3. Stamp the `harness-stack` marker (`max-rounds` default 2).
4. Label the bottom `harness:awaiting-review` only if `MERGEABLE`; label open
   PRs above it `harness:stacked`.

The script refuses `continue` when two unreviewed PRs already sit above the
bottom. Adopted PRs are not reimplemented.

## Honesty

- Do not write feature code outside `develop-review`.
- Do not raise `max-rounds` or invent a second review procedure.
- Do not spawn `stack-review`; the other harness runs that skill.
- Do not merge past unfixed Critical/High findings.

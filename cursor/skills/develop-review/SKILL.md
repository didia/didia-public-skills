---
name: develop-review
description: Implements a coding task and loops a Composer developer against a Grok reviewer — reviewing the real diff, not the developer's summary — applying targeted fixes until the reviewer signs off, then opens a pull request. Use this whenever the user wants something built, implemented, or fixed with real cross-model code review before it's considered done, wants a second model to review a diff or catch what the first one missed, mentions "develop-review", or hands over an already-approved plan to be built. Also use it as the implementation half of the plan-develop pipeline. Requires an environment with subagents (Cursor), a git repo, and the gh CLI.
compatibility: Cursor (needs Task-tool subagents to run separate generative/adversarial context windows), a git repository so the reviewer can read the real diff, and the gh CLI authenticated for opening pull requests.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# Develop-Review

A bounded two-model loop that turns an approved plan (or a well-scoped task) into reviewed
code: **develop → review → fix → …** until the reviewer approves or the
cap is hit. The model for each spawn follows the plan's **Complexity** rating
(`low` / `medium` / `high`). See `references/complexity-rubric.md`.

## Why this shape

A model reviewing its own diff is grading its own homework with the answer key it wrote.
It will re-derive the same assumptions and call them correct. So the review goes to a
different model, on fresh context, reading the actual `git diff` rather than the
developer's account of what it changed — because "I implemented it and the tests pass" is
precisely the claim under review, not evidence for it.

The loop is capped so a real disagreement surfaces to you as a decision rather than a
grinding fix-review cycle.

**This skill ends with an opened pull request, not a merged change.** It pushes the branch
and opens the PR automatically once the reviewer approves — merging stays a human decision
made on the PR, not something this skill does.

## Prerequisites

Check before starting, and say plainly if something is missing rather than half-running it:

- A git repository, checked out locally, so the reviewer can read a real diff. Working on
  a dedicated branch rather than directly on `main`/`dev` is strongly preferable — if the
  repo is sitting on a shared branch, create one first.
- The `gh` CLI, installed and authenticated (`gh auth status`). If it's missing, still run
  the full develop/review loop — just hand back a pushed branch at the end instead of
  opening a PR, and say so up front rather than at the end.
- An environment with subagents. **In a plain chat interface with no subagent
  capability you cannot get a genuinely independent Grok review** — say so, and offer to
  run the two stages sequentially yourself, switching hats explicitly, as a weaker
  substitute.

## Setup: install the two subagents (once)

This skill bundles two subagent definitions in `agents/`. Each pins a default model in
frontmatter (`model: composer-2.5-fast` or `model: grok-4.7-high`). The model for each spawn is the matching row below. Do not add an effort argument.

Check whether `develop-review-developer` and `develop-review-reviewer` are already
available. If not, copy both from this skill's `agents/` directory into either:

- `~/.cursor/agents/` — available in every project on this machine (default choice), or
- `<repo>/.cursor/agents/` — committed and shared with the team, if this workflow belongs
  to one specific project.

The two agents:

- `develop-review-developer.md` — writes the code and applies fixes.
- `develop-review-reviewer.md` — reviews the diff.

## Model routing by Complexity

Read the approved plan's **Complexity** line (`low` / `medium` / `high`). Spawn every
developer and reviewer call in this run from the matching row. Keep that row for the whole
fix loop — do not re-rate mid-run. Pass only the arguments written in that row.

| Complexity | Developer spawn | Reviewer spawn |
|---|---|---|
| low | Invoke the Task tool with `subagent_type: develop-review-developer` and `model: composer-2.5-fast` | Invoke the Task tool with `subagent_type: develop-review-reviewer` and `model: composer-2.5-fast` |
| medium | Invoke the Task tool with `subagent_type: develop-review-developer` and `model: composer-2.5-fast` | Invoke the Task tool with `subagent_type: develop-review-reviewer` and `model: grok-4.7-high` |
| high | Invoke the Task tool with `subagent_type: develop-review-developer` and `model: composer-2.5-fast` | Invoke the Task tool with `subagent_type: develop-review-reviewer` and `model: grok-4.7-high` |

Resolved defaults for this provider (config may override any cell):


| Complexity | Developer model | Reviewer model |
|---|---|---|
| low | Composer (`composer-2.5-fast`) | Composer (`composer-2.5-fast`) |
| medium | Composer (`composer-2.5-fast`) | Grok (`grok-4.7-high`) |
| high | Composer (`composer-2.5-fast`) | Grok (`grok-4.7-high`) |


## Step 0: Establish what's being built

You need something concrete enough to implement against. That's either:

- **An approved plan** — from `plan-review`, or written by the user. Use it as given.
  Extract its **Complexity** rating. If the plan has no Complexity line, classify once
  using `references/complexity-rubric.md`, record the rating, and proceed.
- **A direct task** — if the user hands you a task with no plan, that's fine for small,
  well-understood changes. Classify Complexity once with the rubric before the first
  spawn and record it. If the task is large or the right approach is genuinely
  unclear, say so and suggest running `plan-review` first: an unreviewed approach tends to
  turn the fix loop into a redesign loop, which is the expensive way to discover it.

Confirm which branch the work belongs on before any code is written.

## Step 1: Develop

Using the Complexity row from Step 0, spawn the developer in **build mode**.
Give it the plan or task, plus any constraints the user stated. It writes the code,
follows existing conventions in the repo, runs whatever tests and linters already exist,
and reports what it changed file by file and what it ran.

## Step 2: Review

Using the same Complexity row, spawn the reviewer with:

- the plan or task it's supposed to satisfy,
- the actual diff (`git diff`) — the reviewer also runs `git diff` itself, so it isn't
  limited to what you chose to show it,
- the test/lint output.

Do **not** pass the developer's summary in place of the diff. The reviewer ends with
exactly one line: `IMPLEMENTATION_APPROVED` or `NEEDS_FIXES: <numbered, specific list>`.

## Step 3: Fix loop

- **Approved** → go to Step 4.
- **Needs fixes** → spawn the developer again (same Complexity row) in **fix mode** with the
  numbered feedback verbatim, asking for targeted fixes rather than a rewrite → back to
  Step 2. **Cap: 5 fix/review cycles.**

If five rounds pass without approval, stop. Show the user the current diff and the
reviewer's remaining objections, and let them decide whether to override the reviewer,
take it from here manually, or scope the task down. Five failed rounds is rarely a fixable
detail — it usually means the approach is wrong, and continuing to patch it is the wrong
move.

Watch for the reviewer moving the goalposts between rounds — new objections about code
that never changed suggest it's reviewing to a shifting standard. If round three is
flagging things round one didn't, mention it to the user rather than looping on it.

## Step 4: Open the pull request

Once Step 3 ends in `IMPLEMENTATION_APPROVED`, open the PR automatically — don't pause to
show the branch or diff first. The user reviews at the PR level, not before it exists.

1. Commit any uncommitted changes with a message describing the change.
2. Push the branch.
3. `gh pr create --base <target-branch> --head <branch> --title "<title>" --body "<body>"`.
   Use whatever base branch this work was actually branched from (`dev`, if this was
   invoked from `plan-develop`; otherwise whatever the user confirmed in Step 0). In the
   body, briefly note it went through the develop-review loop, how many fix cycles it
   took, and the **Complexity** rating used for the spawn — a first-pass approval and a
   fifth-round approval mean different things to a human reviewer, and that's useful
   signal for whoever picks up the review.

Share the PR link and stop. Don't merge it yourself — that decision stays with the human
review on the PR.

If `gh` isn't available, skip the PR step and instead tell the user the branch name and
that it's pushed (or ready to push) and reviewed, so they can open the PR themselves.

## Keeping the loop honest

- The reviewer reads the diff, never the developer's narration of the diff. Self-reported
  "this works" is the thing being checked, not an input to the check.
- Don't quietly raise the cap when a loop stalls — the cap exists to surface disagreement.
- If the developer's fixes keep breaking something the previous round fixed, stop looping
  and surface it. Oscillation means the two models disagree about the design, not the
  details, and no number of fix rounds resolves that.

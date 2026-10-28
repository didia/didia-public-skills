---
name: develop-review
description: Implements a coding task and loops a GPT 6.1 Sol developer against a GPT 6 Astra reviewer — reviewing the real diff, not the developer's summary — applying targeted fixes until the reviewer signs off, then opens a pull request. Use this whenever the user wants something built, implemented, or fixed with real cross-model code review before it's considered done, wants a second model to review a diff or catch what the first one missed, mentions "develop-review", or hands over an already-approved plan to be built. Also use it as the implementation half of the plan-develop pipeline. Requires an environment with subagents (Codex), a git repo, and the gh CLI.
compatibility: Codex (needs subagent support to run separate generative/adversarial context windows), a git repository so the reviewer can read the real diff, and the gh CLI authenticated for opening pull requests.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# Develop-Review

A bounded two-model loop that turns an approved plan (or a well-scoped task) into reviewed
code: **develop → review → fix → …** until the reviewer approves or the
cap is hit. Model and effort for each spawn follow the plan's **Complexity** rating
(`low` / `medium` / `high`). See `references/complexity-rubric.md`.

How many times the reviewer is spawned depends on the **review budget** the caller
names. The default, **full**, is the loop above. A caller that already has an external
reviewer names a tighter budget so this skill does not spend a reviewer spawn on every
fix. The model row does not change with the budget.

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
  capability you cannot get a genuinely independent GPT 6 Astra review** — say so, and offer to
  run the two stages sequentially yourself, switching hats explicitly, as a weaker
  substitute.

## Setup: install the two subagents (once)

This skill bundles two subagent definitions in `agents/`. Each pins a default model in
frontmatter (`model: gpt-6.1-sol` or `model: gpt-6-astra`). Effort (and
any per-complexity model override) is passed on each spawn so it can follow the plan's
Complexity rating.

Check whether `develop-review-developer` and `develop-review-reviewer` are already
available. If not, copy both from this skill's `agents/` directory into either:

- `~/.codex/agents/` — available in every project on this machine (default choice), or
- `<repo>/.codex/agents/` — committed and shared with the team, if this workflow belongs
  to one specific project.

The two agents:

- `develop-review-developer.toml` — writes the code and applies fixes.
- `develop-review-reviewer.toml` — reviews the diff. A different model from the developer.

## Effort routing by Complexity

Read the approved plan's **Complexity** line (`low` / `medium` / `high`). Spawn the
developer and reviewer from that row. Pass only the arguments written in that row.

You may **raise** the rating during the run when the work turns out heavier than the plan
said (auth, money, migrations, concurrency, a public API). Use the new row for every
spawn after that. Never lower the rating. The reviewer's effort is already floored, so a
`low` row does not put the critic on low effort when this provider has an effort dial.

| Complexity | Developer spawn | Reviewer spawn |
|---|---|---|
| low | Spawn a subagent named `develop-review-developer` in a fresh context with `model: gpt-6.1-sol` and `model_reasoning_effort: low` | Spawn a subagent named `develop-review-reviewer` in a fresh context with `model: gpt-6-astra` and `model_reasoning_effort: medium` |
| medium | Spawn a subagent named `develop-review-developer` in a fresh context with `model: gpt-6.1-sol` and `model_reasoning_effort: medium` | Spawn a subagent named `develop-review-reviewer` in a fresh context with `model: gpt-6-astra` and `model_reasoning_effort: medium` |
| high | Spawn a subagent named `develop-review-developer` in a fresh context with `model: gpt-6.1-sol` and `model_reasoning_effort: high` | Spawn a subagent named `develop-review-reviewer` in a fresh context with `model: gpt-6-astra` and `model_reasoning_effort: high` |

Resolved defaults for this provider (config may override any cell):


| Complexity | Developer model | Developer effort | Reviewer model | Reviewer effort |
|---|---|---|---|---|
| low | GPT 6.1 Sol (`gpt-6.1-sol`) | low | GPT 6 Astra (`gpt-6-astra`) | medium |
| medium | GPT 6.1 Sol (`gpt-6.1-sol`) | medium | GPT 6 Astra (`gpt-6-astra`) | medium |
| high | GPT 6.1 Sol (`gpt-6.1-sol`) | high | GPT 6 Astra (`gpt-6-astra`) | high |


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

## Review budget

Use **full** when nobody names a budget. That is the direct-task case and `plan-develop`
with `Delivery: single`: this skill is the only code review before the PR opens.

`stack-develop` names one of the other three. An external `pr-review` is the quality
gate there, so this skill must not repeat that gate. Spawn the reviewer from the same
Complexity row in every budget. Do not switch to a cheaper model, and do not lower the
rating, to save tokens.

| Budget | Reviewer spawns | After `NEEDS_FIXES` |
|---|---|---|
| **full** | Once, then again after each fix. Cap: 5 fix/review cycles | Back to Step 2, until approval or the cap |
| **preflight** | Once, before the PR exists | One developer fix. Do not spawn the reviewer again |
| **apply** | None | The caller already has the feedback. One developer fix |
| **verify** | Once, after the developer applies the feedback | Stop. Do not spawn the reviewer again, and do not treat the diff as approved |

Tell the reviewer which budget this spawn is, in one line:

- **full** — this pass can be followed by another internal pass, up to the cap.
- **preflight** — an external review will read this diff next. Block on defects. Approve nits.
- **verify** — this is the last read before the change can merge.

## Step 1: Develop

Skip this step on budget **apply** or **verify**. The caller already has a diff.

Using the Complexity row from Step 0, spawn the developer in **build mode**.
Give it the plan or task, plus any constraints the user stated. It writes the code,
follows existing conventions in the repo, runs whatever tests and linters already exist,
and reports what it changed file by file and what it ran.

## Step 2: Review

Skip this step on budget **apply**. **verify** runs it once, after the fix in Step 3, not before.

Using the same Complexity row, spawn the reviewer with:

- the plan or task it's supposed to satisfy,
- the actual diff (`git diff`) — the reviewer also runs `git diff` itself, so it isn't
  limited to what you chose to show it,
- the test/lint output.

Do **not** pass the developer's summary in place of the diff. The reviewer ends with
exactly one line: `IMPLEMENTATION_APPROVED` or `NEEDS_FIXES: <numbered, specific list>`.

## Step 3: Fix loop

Follow the budget from the caller.

### full

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

### preflight

Step 2 already ran once.

- **Approved** → hand the diff back to the caller. Do not open a pull request.
- **Needs fixes** → one developer spawn in **fix mode** with the numbered feedback
  verbatim. Then hand the diff back, including any item the fix did not claim to clear.
  Do not return to Step 2. This is a normal end. The external reviewer reads the result.

### apply

Skip Steps 1 and 2. Spawn the developer once in **fix mode** with the feedback the
caller passed. Hand the diff back. Do not spawn the reviewer.

### verify

Skip Step 1.

1. Spawn the developer once in **fix mode** with the caller's feedback.
2. Run Step 2 once on the diff that fix produced.
3. **Approved** → hand back `IMPLEMENTATION_APPROVED`. Do not open a pull request.
4. **Needs fixes** → stop. Show the caller the diff and the objections. Do not spawn
   the reviewer again, and do not hand back an approval.

## Step 4: Open the pull request

Step 4 runs only for budget **full**, and only once Step 3 ends in
`IMPLEMENTATION_APPROVED`. **preflight**, **apply**, and **verify** hand the diff back
to the caller; they do not push and they do not open a pull request.

Open the PR automatically — don't pause to show the branch or diff first. The user
reviews at the PR level, not before it exists.

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
- Don't spawn the reviewer a second time on **preflight** or **verify**, and don't spawn
  it at all on **apply**. Don't change models to buy another pass.
- If the developer's fixes keep breaking something the previous round fixed, stop looping
  and surface it. Oscillation means the two models disagree about the design, not the
  details, and no number of fix rounds resolves that.

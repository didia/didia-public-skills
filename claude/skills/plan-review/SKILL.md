---
name: plan-review
description: Produces a battle-tested implementation plan for a coding task by looping a Opus planner against a Opus validator until the validator signs off — no code is written. Use this whenever the user wants a plan, design, or approach worked out before implementation, wants a second model to poke holes in a plan, mentions "plan-review", "validate this plan", "review my approach", "stress-test this design", or asks to think something through properly before building it. Also use it as the planning half of the plan-develop pipeline. Requires an environment with subagents (Claude Code or Cowork).
compatibility: Claude Code or Cowork (needs Task-tool subagents to run separate generative/adversarial context windows). Read-only on the repo — this skill never writes code.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# Plan-Review

A bounded two-model loop that turns a coding task into an approved implementation plan:
**plan (Opus) → validate (Opus) → revise → …** until the validator approves or the
cap is hit.

Every approved plan carries a **Complexity** rating (`low` / `medium` / `high`). Downstream
skills (`develop-review`, `pr-review`) use that rating to choose the model and effort. The
planner and validator always run at **high** effort so classification is
not cheapened by the rating itself. See `references/complexity-rubric.md`.

## Why this shape

A model that drafts a plan is a poor judge of that plan. It has already committed to an
approach, and the reasoning that produced the blind spot is the same reasoning that would
have to catch it. So the critique goes to a different model, on fresh context, seeing the
plan itself rather than the planner's narration of why the plan is good.

The loop is capped so a real disagreement between the two models surfaces to you as a
decision, instead of burning calls on a stalemate.

**Nothing in this skill writes code.** It ends with an approved plan. Implementation is a
separate concern — see `develop-review`, or `plan-develop` for both halves end to end.

## Prerequisites

Check before starting, and say plainly if something is missing rather than half-running it:

- An environment with subagents. **In a plain chat interface with no subagent
  capability you cannot get a genuinely independent Opus pass** — say so, and offer to run
  the two stages sequentially yourself, switching hats explicitly, as a weaker substitute.
- A repository to ground the plan in. A plan written without reading the actual codebase
  is a guess; both subagents have read-only tools specifically so they can check.

## Setup: install the two subagents (once)

This skill bundles two subagent definitions in `agents/`. Each pins its model in
frontmatter (`model: opus` / `model: opus`)
and planning effort (`effort: high`) so planning stays at
high effort regardless of what the main session is using.

Check whether `plan-review-planner` and `plan-review-validator` are already available. If
not, copy both from this skill's `agents/` directory into either:

- `~/.claude/agents/` — available in every project on this machine (default choice), or
- `<repo>/.claude/agents/` — committed and shared with the team, if this workflow belongs
  to one specific project.

The two agents:

- `plan-review-planner.md` — Opus at high effort, drafts and revises the plan.
- `plan-review-validator.md` — Opus at high effort, critiques and tightens it.

## Step 0: Pin down the task

Make sure you understand what's being asked before spending model calls on it. If the
request is vague on scope — "add pagination" without saying which endpoint, "make it
faster" without saying what's slow — ask one clarifying question rather than letting the
planner guess and the validator catch the guess three minutes later.

Note any constraints the user gave (framework, deadline, "don't touch the auth layer") —
these travel with the task into every subagent call, or they get silently dropped.

## Step 1: Plan (Opus)

Invoke the Task tool with `subagent_type: plan-review-planner`, `model: opus`, and `effort: high`. Give it:

- the task description and any constraints from Step 0,
- enough repo context to be useful: relevant directories, existing patterns worth
  following, where the related code lives,
- on later iterations, the validator's feedback verbatim.

Ask for a plan, not code. The planner returns Approach / Files to touch / Edge cases &
risks / Test plan / **Complexity** (`low` | `medium` | `high` plus a short reason).

## Step 2: Validate (Opus)

Invoke the Task tool with `subagent_type: plan-review-validator`, `model: opus`, and `effort: high` with the task and **the plan text itself** —
not the planner's reasoning transcript, not your summary of it. The whole point is a
critique that isn't anchored by the planner's own justification.

The validator ends with exactly one line: `PLAN_APPROVED` or
`PLAN_NEEDS_REVISION: <specific feedback>`. It must reject a plan that lacks a valid
Complexity rating or whose rating contradicts the described scope.

- **Approved** → done. Go to Step 3.
- **Needs revision** → back to Step 1 with the feedback, asking the planner to revise the
  existing plan rather than start over. **Cap: 3 plan iterations.**

If three rounds pass without approval, stop. Show the user the latest plan and the
validator's outstanding objection side by side, and let them call it — the two models
disagreeing on the third pass usually means the task itself is underspecified or genuinely
contested, and picking a side for the user hides that.

## Step 3: Hand back the approved plan

Return the plan as the validator left it — the validator is allowed to rewrite parts, so
its version is the one to carry forward, not the planner's last draft. Confirm the
**Complexity** line is still present and accurate; that rating is what `develop-review`
and `pr-review` will use for effort.

Report alongside it:

- how many iterations it took (one-pass approval and third-round approval mean different
  things about how settled the plan is),
- the Complexity rating,
- anything the validator flagged as a risk but approved anyway — that's the list worth
  watching during implementation.

If this was invoked as the first half of `plan-develop`, pass the approved plan straight
into `develop-review`. If it was invoked on its own, ask whether the user wants to proceed
to implementation via `develop-review`.

## Keeping the loop honest

- Pass the validator the *artifact*, never the other model's account of it. "The planner
  says it considered edge cases" is exactly what the validator is there to check.
- Don't quietly raise the cap when a loop stalls — the cap exists to surface disagreement,
  and raising it converts a signal into more of the same noise.
- If the planner keeps expanding scope or the validator keeps finding whole missing
  pieces, that's usually a sign the task should be split into several smaller plans.
  Pause and check with the user rather than planning one enormous change.

---
name: plan-develop
description: End-to-end coding pipeline that chains plan-review (Sonnet plans, Opus validates) into develop-review for one pull request, or into stack-develop when the approved plan is a stack. Use this whenever the user asks to implement, build, ship, or fix something and wants it turned into a PR with real cross-model review at both the plan and the code stage, or explicitly mentions "plan-develop", a plan-then-build pipeline, or wanting a second model to catch what the first missed before it becomes a PR. For just the planning half use plan-review; for just the implementation half (including the PR) use develop-review. Requires Claude Code or Cowork or another environment with subagents, plus git and the gh CLI.
compatibility: Claude Code or Cowork (needs Task-tool subagents to run separate generative/adversarial context windows), a git repo with a dev branch, the gh CLI authenticated for opening pull requests, and the plan-review and develop-review skills installed alongside this one.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# Plan-Develop

The full pipeline for one coding task, from a sentence of intent to an open pull request.
It is deliberately thin: the two review loops, and the PR they end in, live in their own
skills — this one just sequences them.

```
Step 0  capture the task; confirm dev
Step 1  plan-review      → approved plan   (Sonnet plans, Opus validates, both at high effort, cap 3)
Step 2  Delivery: single → develop-review opens one PR
        Delivery: stack  → stack-develop opens the stack using the plan's Land line
```

The approved plan's **Complexity** rating (`low` / `medium` / `high`) selects development
and review effort in Step 2. Its **Delivery** line chooses one PR or a stack, and a stack's **Land** line (`progressive` or `atomic`) is the landing rule `stack-develop` follows. Planning itself always runs at high effort.
See `references/complexity-rubric.md`.

## Why this shape

A single model planning, writing, and reviewing its own code approves its own blind spots
— it's hard to spot a flaw in an approach you just committed to. Both halves of this
pipeline therefore split generative work (Sonnet / Sonnet) from adversarial work (Opus), with
the critic getting fresh context and the real artifact rather than the author's account
of it.

Catching a bad approach at the plan stage is worth far more than catching it in review, so
the pipeline spends a full loop on the plan before a line of code exists. Each loop is
bounded, so genuine model disagreement surfaces to you as a decision instead of spinning.

`develop-review` owns a single PR: it opens one itself the moment its reviewer approves.
`stack-develop` owns a stack: it opens each slice from the approved plan and lands them
with that plan's Land line. This skill doesn't duplicate either step — it makes sure a
validated plan exists, then follows the Delivery line.

## Prerequisites

Check these up front and tell the user plainly if one is missing, rather than half-running
the pipeline:

- **The `plan-review`, `develop-review`, and `stack-develop` skills**, installed
  alongside this one — this skill is an orchestrator and does nothing useful without
  them. They're normally in `~/.claude/skills/`. `stack-develop` is required when the
  approved plan says `Delivery: stack`.
- **A git repository** with a `dev` branch to branch from and target.
- **The `gh` CLI**, installed and authenticated (`gh auth status`). `develop-review` is
  the skill that actually calls it; if it's missing, still run both loops — `develop-review`
  will hand back a reviewed, pushed branch instead of opening a PR — and say so up front
  rather than at the end.
- **Subagents** (Claude Code or Cowork). Without them there's no independent Opus
  pass at all; say so and offer the sequential hat-switching substitute described in the
  two sub-skills.

The subagents themselves are installed by the sub-skills — `plan-review` brings its
planner and validator, `develop-review` brings its developer and reviewer. This skill
bundles none of its own.

## Step 0: Capture the task

Make sure you actually understand what's being asked before spending model calls on it. If
the request is vague on scope (e.g. "add pagination" without which endpoint), ask one
clarifying question rather than guessing — a misunderstood task costs both loops.

Confirm the repo can branch from `dev`. Do not create the implementation branch
yet. A single-PR plan gets a branch in Step 2. A stack gets one branch per slice from
`stack-develop`.

## Step 1: Plan (delegate to plan-review)

Read and follow the `plan-review` skill — normally at `~/.claude/skills/plan-review/SKILL.md`
— with the task and constraints from Step 0. Run its full loop: planner drafts, validator
critiques, revise until `PLAN_APPROVED`, capped at 3 iterations. Both planning agents run
at high effort.

Carry forward the plan **as the validator left it**, not the planner's last draft —
including its **Complexity** line and its **Delivery** line (`single`, or `stack` with
`Land: progressive` or `Land: atomic`). Complexity is what Step 2 uses for effort.
Delivery chooses which skill builds it. Do not change Land after approval.

If `plan-review` hits its cap without approval, the pipeline stops here. Show the user the
latest plan and the outstanding objection and let them decide — don't start writing code
against a plan that failed validation, and don't pick a side on their behalf.

## Step 2: Build what the plan's Delivery line says

### Delivery: single

Create `plan-develop/<short-slug>` off the latest `dev`. Read and follow the
`develop-review` skill — normally at `~/.claude/skills/develop-review/SKILL.md` — passing
it the approved plan (Complexity included) and that branch. Run its full sequence end to
end: developer builds, reviewer reads the real diff, targeted fixes until
`IMPLEMENTATION_APPROVED` (capped at 5 cycles), then it pushes the branch and opens the
PR itself (base `dev`, head `plan-develop/<slug>`). Developer and reviewer spawn
at the effort and model for the plan's Complexity rating.

Skip that skill's own Step 0 branch question — the branch already exists. Otherwise let it
run its own Step 4 (the PR) rather than intercepting before that point; this skill has
nothing to add there.

Ask it to mention in the PR body that the change also went through `plan-review` first,
how many plan iterations that took, and the **Complexity** rating — that's context
`develop-review` doesn't have on its own for the plan-loop history, since it only sees the
approved plan, not the loop that produced it.

### Delivery: stack

Do not open one PR and do not create the `plan-develop/<slug>` branch. Read and follow
`stack-develop` — normally at `~/.claude/skills/stack-develop/SKILL.md` — with the
approved slice list and the plan's Land value. Those slices and that Land line are the
stack. Do not re-slice the plan and do not change `progressive` to `atomic`, or the
reverse, because a later slice is still open. `stack-develop` runs `develop-review`
in budget **preflight** once per slice: one reviewer spawn, one fix if needed, no
internal re-review. External `pr-review` is the quality gate for those slices. The
5-cycle **full** budget applies only to `Delivery: single`.

On a single PR, if `develop-review` hits its fix/review cap without approval, it stops
on its own and shows the user the diff and the reviewer's remaining objections. The
pipeline ends there. Don't override that and open a PR for an implementation the
reviewer didn't approve. On a stack, a preflight that still has findings after its one
fix is not that stop — `stack-develop` opens the PR anyway. A **verify** budget that
fails on the last external round does stop; don't post a fix the reviewer rejected.

## Keeping the pipeline honest

- Don't collapse the two loops into one pass because the task looks small. If it's small
  enough that the plan loop feels like overhead, `develop-review` on its own is the right
  tool — reach for that instead of running a degraded version of this one.
- Don't silently raise either sub-skill's iteration cap. The caps exist to surface
  disagreement, and raising them converts a signal into more noise.
- If the task turns out to be much bigger than scoped — the planner keeps expanding it, or
  the validator keeps finding missing pieces — the plan's Delivery line should be a stack
  with an explicit Land value, or the work should be separate plan-develop runs when the
  pieces are unrelated. Do not push one enormous PR.

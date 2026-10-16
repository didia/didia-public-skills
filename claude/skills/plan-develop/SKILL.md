---
name: plan-develop
description: End-to-end coding pipeline that chains plan-review (Opus plans, Opus validates) into develop-review (Sonnet builds, Opus reviews the real diff and opens the pull request). Use this whenever the user asks to implement, build, ship, or fix something and wants it turned into a PR with real cross-model review at both the plan and the code stage, or explicitly mentions "plan-develop", a plan-then-build pipeline, or wanting a second model to catch what the first missed before it becomes a PR. For just the planning half use plan-review; for just the implementation half (including the PR) use develop-review. Requires Claude Code or Cowork or another environment with subagents, plus git and the gh CLI.
compatibility: Claude Code or Cowork (needs Task-tool subagents to run separate generative/adversarial context windows), a git repo with a dev branch, the gh CLI authenticated for opening pull requests, and the plan-review and develop-review skills installed alongside this one.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# Plan-Develop

The full pipeline for one coding task, from a sentence of intent to an open pull request.
It is deliberately thin: the two review loops, and the PR they end in, live in their own
skills — this one just sequences them.

```
Step 0  branch off dev
Step 1  plan-review      → approved plan   (Opus plans, Opus validates, both at high effort, cap 3)
Step 2  develop-review   → open PR         (developer + reviewer at the plan's Complexity effort, cap 5, opens PR)
```

The approved plan's **Complexity** rating (`low` / `medium` / `high`) selects development
and review effort in Step 2. Planning itself always runs at high effort.
See `references/complexity-rubric.md`.

## Why this shape

A single model planning, writing, and reviewing its own code approves its own blind spots
— it's hard to spot a flaw in an approach you just committed to. Both halves of this
pipeline therefore split generative work (Opus / Sonnet) from adversarial work (Opus), with
the critic getting fresh context and the real artifact rather than the author's account
of it.

Catching a bad approach at the plan stage is worth far more than catching it in review, so
the pipeline spends a full loop on the plan before a line of code exists. Each loop is
bounded, so genuine model disagreement surfaces to you as a decision instead of spinning.

`develop-review` owns the PR: it opens one itself the moment its reviewer approves. This
skill doesn't duplicate that step — it just makes sure a validated plan exists before
`develop-review` starts building against it.

## Prerequisites

Check these up front and tell the user plainly if one is missing, rather than half-running
the pipeline:

- **The `plan-review` and `develop-review` skills**, installed alongside this one — this
  skill is an orchestrator and does nothing useful without them. They're normally in
  `~/.claude/skills/`.
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

## Step 0: Capture the task and branch

Make sure you actually understand what's being asked before spending model calls on it. If
the request is vague on scope (e.g. "add pagination" without which endpoint), ask one
clarifying question rather than guessing — a misunderstood task costs both loops.

Confirm the repo is on, or can cleanly branch from, `dev`. Create a working branch named
`plan-develop/<short-slug>` off the latest `dev`, and do all the work there.

## Step 1: Plan (delegate to plan-review)

Read and follow the `plan-review` skill — normally at `~/.claude/skills/plan-review/SKILL.md`
— with the task and constraints from Step 0. Run its full loop: planner drafts, validator
critiques, revise until `PLAN_APPROVED`, capped at 3 iterations. Both planning agents run
at high effort.

Carry forward the plan **as the validator left it**, not the planner's last draft —
including its **Complexity** line. That rating is what Step 2 uses for effort.

If `plan-review` hits its cap without approval, the pipeline stops here. Show the user the
latest plan and the outstanding objection and let them decide — don't start writing code
against a plan that failed validation, and don't pick a side on their behalf.

## Step 2: Develop, review, and open the PR (delegate to develop-review)

Read and follow the `develop-review` skill — normally at
`~/.claude/skills/develop-review/SKILL.md` — passing it the approved plan (Complexity
included) and the branch from Step 0. Run its full sequence end to end: developer builds,
reviewer reads the real diff, targeted fixes until `IMPLEMENTATION_APPROVED` (capped at 5
cycles), then it pushes the branch and opens the PR itself (base `dev`, head
`plan-develop/<slug>`). Developer and reviewer spawn at the effort and model for the
plan's Complexity rating.

Skip that skill's own Step 0 branch question — the branch already exists from Step 0 here.
Otherwise let it run its own Step 4 (the PR) rather than intercepting before that point;
this skill has nothing to add there.

Ask it to mention in the PR body that the change also went through `plan-review` first,
how many plan iterations that took, and the **Complexity** rating — that's context
`develop-review` doesn't have on its own for the plan-loop history, since it only sees the
approved plan, not the loop that produced it.

If `develop-review` hits its fix/review cap without approval, it stops on its own and
shows the user the diff and the reviewer's remaining objections — the pipeline ends there
too. Don't override that and open a PR for an implementation the reviewer didn't approve.

## Keeping the pipeline honest

- Don't collapse the two loops into one pass because the task looks small. If it's small
  enough that the plan loop feels like overhead, `develop-review` on its own is the right
  tool — reach for that instead of running a degraded version of this one.
- Don't silently raise either sub-skill's iteration cap. The caps exist to surface
  disagreement, and raising them converts a signal into more noise.
- If the task turns out to be much bigger than scoped — the planner keeps expanding it, or
  the validator keeps finding missing pieces — pause and check whether to split it into
  several plan-develop runs rather than pushing one enormous PR.

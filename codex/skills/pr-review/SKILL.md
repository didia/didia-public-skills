---
name: pr-review
description: Run a deep, systematic pull request review and post findings as inline GitHub comments via the gh CLI. Use this whenever the user asks to review a PR, pass a PR or merge request URL, say things like "review PR #123", "look over this pull request", "leave comments on my PR", "do a thorough/exhaustive code review", "what did I miss in this branch", or ask for a second opinion on someone else's PR before merging — even if they don't use the word "skill" or "review checklist". Also use it when a review needs coverage guarantees (every changed file, migration, state transition, failure path) rather than a quick skim.
compatibility: Codex (needs subagent support to run separate generative/adversarial context windows), a git repository, and the gh CLI authenticated for posting reviews.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# PR Review

A review is only worth the author's attention if it finds things they would not have found themselves. That means reading the code around the diff, not just the diff; reasoning about paths no test exercises; and reporting each finding precisely enough that the author can act without a follow-up conversation.

This skill runs a full review of the **current PR head** — not an incremental pass over the latest commits, and not a re-tread of whatever was discussed in earlier threads.

Effort and scope follow a **Complexity** rating (`low` / `medium` / `high`). See
`references/complexity-rubric.md`.

## Effort routing by Complexity

After Phase 1, determine Complexity from the diff, not from the author's word:

1. Classify with the rubric from the diff and PR description.
2. A **Complexity** line in the body is a floor. If your reading is higher, use yours.
   Never lower the rating because the body says `low`.
3. **Focused** mode only when *your* rating is `low` and the diff does not touch auth,
   money, migrations, concurrency, or a public API. Otherwise run the full review.

Then pick scope and spawn effort from that rating.
Use the same model and effort as the **develop-review** reviewer row for that Complexity (table below). Review effort is floored at `low` unless the complexity row sets it higher.


| Complexity | Review mode | Review spawn (model + effort) |
|---|---|---|
| low | **Focused** — phases 1, 3, 6, 7; skip the coverage matrix | GPT 6.1 Sol (`gpt-6.1-sol`) at `medium` |
| medium | **Full** — every phase below | GPT 6 Astra (`gpt-6-astra`) at `low` |
| high | **Full** — every phase below | GPT 6 Astra (`gpt-6-astra`) at `medium` |


Say which Complexity and mode you are using before Phase 2.

If the user asked for an exhaustive review, deliver a full review (treat as at least
`medium`) or explicitly report what you did not cover. Never describe a review as
exhaustive when a changed file or checklist category was skipped — an overstated coverage
claim is worse than an honest gap, because it stops the author from looking there
themselves.

## Phase 1 — Ground yourself in current state

Refresh everything before reading a line of code. Stale context produces confident wrong comments.

```bash
gh pr view <pr> --json number,title,body,url,state,isDraft,mergeable,baseRefName,headRefName,headRefOid,files,commits
gh pr diff <pr> > /tmp/pr.diff          # full patch, the object of review
gh pr checks <pr>                        # CI status
gh pr view <pr> --json comments,reviews  # existing discussion
```

Record `headRefOid` — that SHA is what you are reviewing and what you will report. Re-check it before posting; if it moved, re-diff rather than commenting on code that no longer exists.

Then read the project's own rules, because a "defect" that contradicts a documented convention is noise: `CLAUDE.md`, `CONTRIBUTING.md`, `AGENTS.md`, `.cursorrules`, ADRs, and the architecture, schema, feature, and API docs relevant to what changed. Load `references/audit-checklist.md` now — it drives the rest of the review.

After grounding, set Complexity as described under Effort routing, then continue in the
matching mode.

## Phase 2 — Build a private coverage matrix

Skip this phase on a **focused** (`low`) review.

Not for the user; for you. It's the mechanism that stops the review from drifting into whatever caught your eye first. In a scratch file, map each item below to *where it's implemented* and *what test exercises it*, leaving the test cell blank when nothing does — blank cells are candidate findings:

- every changed field, column, and type
- every migration, constraint, index, policy, grant, trigger, view, and database function
- every UI state and user-initiated action
- every status/lifecycle transition
- every async path and every failure path
- every stored-object lifecycle (upload, replace, delete, orphan)
- every notification, email, webhook, and deep link
- every requirement stated in the PR description, linked issue, or docs

## Phase 3 — Trace workflows end to end

For each user-visible workflow the PR touches, follow one request the whole way: UI event → client state → API/data access → database → storage → async jobs/notifications → admin or owner views. Open the callers and callees, not just the diff hunks. Most real defects live at a seam between two files that each look correct alone.

## Phase 4 — Run the targeted audits

Skip this phase on a **focused** (`low`) review.

Work through `references/audit-checklist.md`. It's organized by area (data layer, authorization, concurrency, lifecycle, input boundaries, frontend state, accessibility, async/notifications, storage, compatibility, tests, docs) with a relevance trigger on each — skip a section only when nothing in the diff touches it, and note the skip.

## Phase 5 — Verify rather than assume

Skip this phase on a **focused** (`low`) review (still glance at CI from Phase 1).

Green CI means the tests that exist passed. It says nothing about the paths nobody wrote a test for, which is where you're looking.

- Run the relevant test suite, type checker, and linter yourself; report the exact commands and results.
- Read the tests that claim to cover new behavior and check they assert on **behavior**, not that they merely mirror the implementation's shape or re-assert mocks.
- When a finding is non-obvious, build the reproduction — a failing test, a SQL query, a curl sequence — before writing the comment. A verified finding with repro steps gets fixed; a speculative one gets argued about.

## Phase 6 — Second pass and deduplication

Re-read the whole diff with a different question in mind: *what does this change assume, and does anything elsewhere in the PR invalidate that assumption?* Cross-file contradictions rarely surface on the first read, when you're still building a model of each file.

Then compare against existing review threads. Don't repost what someone already raised — but do verify claimed fixes independently. "Fixed in a1b2c3d" is a hypothesis until you read a1b2c3d.

## Phase 7 — Post the findings

Full mechanics (payload shape, line/side semantics, 422 recovery, the `scripts/post_review.py` helper) are in `references/github-review-mechanics.md`. Read it before posting.

If you are not the PR author, omit `event` in the `post_review.py` payload so the review
stays a pending draft the user submits. Posting `COMMENT` or `REQUEST_CHANGES` is
outward-facing; do that only when the user asked you to publish, or when you opened the PR.

Post everything as **one batched review** so the author gets one notification, anchored to the narrowest relevant line. Each comment carries five things, because each answers a question the author would otherwise have to ask:

1. **Severity** — Critical / High / Medium / Low (rubric in the checklist reference)
2. **The exact failing scenario** — concrete inputs, ordering, or state, not "could fail under load"
3. **The impact** — what breaks, for whom, and whether it's recoverable
4. **Why current safeguards don't catch it** — the constraint that doesn't apply, the test that mocks past it
5. **A concrete direction for the fix** — enough to act on; you don't have to write the patch

Two disciplines that determine whether the review is trusted:

- **Don't manufacture findings to pad the count.** Ten real issues beat ten real issues plus fifteen nitpicks, because the padding is what makes authors stop reading. If something is uncertain, investigate it; if it's still uncertain, report it as a residual risk in the summary instead of as a defect comment.
- **Don't stop at the first few issues.** Finding a serious bug in file 3 of 20 is a reason to keep going, not to wrap up.

## Final report

End your turn with:

```
## Review summary
- Reviewed commit: <sha>
- Review link: <url>
- Complexity: <low|medium|high> (<focused|full> mode)

### Findings by severity
Critical / High / Medium / Low — each with file:line and one-line description

### Coverage
- Changed files: N/N inspected (list any skipped and why)
- Checklist categories: which ran, which were not applicable

### Verification performed
- Commands run and their results

### Residual risk
- What could not be fully verified, and exactly why (no access, needs prod data, timing-dependent)
```

The residual-risk section is not a formality. It is how the author learns where *not* to trust the review.

## Parallelism

If subagents are available, split the work three ways after Phase 1 (and after Complexity
is set), giving each the same PR context. Spawn each pass with the review model and effort
for that Complexity (not the develop-review reviewer agent — any capable read-only
subagent is fine):


| Complexity | Model | Effort |
|---|---|---|
| low | `gpt-6.1-sol` | `medium` |
| medium | `gpt-6-astra` | `low` |
| high | `gpt-6-astra` | `medium` |


When spawning, pass that row's `model` and `model_reasoning_effort`. On a focused (`low`) review, keep the work in the parent unless a single pass clearly benefits from isolation.

Pass assignments (full mode):

1. data layer, authorization, and concurrency
2. frontend, client state, and accessibility
3. end-to-end workflows, storage, async paths, and test quality

Reconcile their findings against the code yourself before posting anything. Subagents miss
cross-cutting interactions and occasionally report plausible-sounding issues that the code
already handles — you own the accuracy of what gets posted.

Without subagents, state the Complexity rating and run the matching mode in the current
session. A mid-turn effort change is not reliable, so do not promise a
different effort than the session already has.

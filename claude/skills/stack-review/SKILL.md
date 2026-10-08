---
name: stack-review
description: Use when the user says you are the reviewer in a cross-harness review, asks to watch a stack of PRs for harness:awaiting-review, mentions "stack-review", or wants another harness to review stacked PRs while a developer keeps opening child PRs. Also use when they point at a repo and ask you to review the bottom of a labeled stack until the round cap is hit. Requires pr-review installed on this harness and the gh CLI.
compatibility: Claude Code or Cowork (needs Task-tool subagents to run separate generative/adversarial context windows), pr-review installed alongside this skill, and the gh CLI authenticated for reading PRs and posting reviews.
---
<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->
# Stack-Review

Orchestrates external review of a PR stack on **this** harness while another
harness runs `stack-develop`. You do not invent a review procedure: every
review follows `pr-review`. You own eligibility, the round cap, and the
`harness-review` marker.

Read `references/protocol.md` before the first review. That file is the
contract both harnesses share.

## Prerequisites

Check up front and say what is missing:

- **`pr-review`** at `~/.claude/skills/pr-review/SKILL.md` (or the project
  install path). This skill does nothing useful without it.
- Authenticated **`gh`** (`gh auth status`).

You do not need a local clone of the feature branch beyond what `pr-review`
asks for. You do **not** edit code or merge.

## Configuration

- **`max-rounds`** — read from the PR's `harness-stack` marker. Default **1**
  if missing. Counts your `pr-review` passes only. Never raise the cap.
- Blocking findings: Critical and High (same rubric as `pr-review`). Medium
  and Low do not set `changes-requested`.

## Main loop

Poll with something like:

```bash
gh pr list --label harness:awaiting-review --state open --json number,title,body,labels,url
```

Among candidates, pick the eligible PR with the lowest `stack-index` from the
marker. When idle, sleep about 60 seconds and poll again. Exit when the user
stops you, or when no open stack PRs remain and nothing is labeled
`harness:awaiting-review` for a long idle stretch — say so and stop.

### Eligibility

Skip a PR unless **all** of these hold:

1. It carries `harness:awaiting-review` (not only `harness:stacked`).
2. It does **not** carry `harness:syncing` or `harness:addressing-review`.
3. It is the stack bottom: `stack-parent` is empty, or that parent PR is
   merged.
4. `mergeable` is `MERGEABLE` (re-query when GitHub returns null). Do not
   review while conflicts exist — the developer must sync first.
5. This `headRefOid` has no `harness-review` marker yet.
6. Count of existing `harness-review` markers on the PR is less than
   `max-rounds`.

Do not post a "waiting" or "still polling" comment on every idle poll.

### Review

When a PR is eligible:

1. Record `headRefOid` and the next `round` number (existing markers + 1).
2. Read and follow `pr-review` **end to end** for that PR. Do not summarize,
   shorten, or replace it with a custom pass.
3. Ask it to include this HTML comment at the end of the single review body
   it posts:

   ```html
   <!-- harness-review round: N verdict: approved|changes-requested head: <sha> -->
   ```

4. Set `verdict` from its findings: any remaining Critical or High →
   `changes-requested`; otherwise `approved`.
5. After that one review is posted, remove `harness:awaiting-review` from the
   PR (leave other labels alone; the developer will re-label as needed).
6. Stop for that PR until a new head appears with a matching `harness-fix`
   and the developer sets `harness:awaiting-review` again — and only if
   rounds remain.

With `max-rounds: 1`, you review once. The developer may still apply blocking
fixes and merge without a second pass. With a higher cap, `approved` stops
early; `changes-requested` allows another review after the fix push, up to
the cap.

## Honesty

- Do not edit code, push branches, or merge.
- Do not review stacked (non-bottom) PRs, conflicting PRs, or PRs still
  labeled `harness:syncing` / `harness:addressing-review`.
- Do not raise `max-rounds` or invent a second review procedure.
- Do not spawn `stack-develop`; the other harness runs that skill.

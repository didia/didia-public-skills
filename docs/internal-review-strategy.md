# Internal review strategy

Models do not change between these two strategies. The critic stays a different model from the author (`config.yaml`). What changes is how often that reviewer is spawned.

The active strategy is **preflight orchestration**. The previous strategy is **full loop on every code change**. Restore the previous one if the preflight budgets do not reduce token use.

## Active: preflight orchestration

`develop-review` takes a budget. Default is **full**.

| Budget | Who uses it | Reviewer spawns |
|---|---|---|
| **full** | Direct `develop-review`, and `plan-develop` when `Delivery: single` | Once, then again after each fix. Cap: 5 fix/review cycles. The PR opens only after `IMPLEMENTATION_APPROVED`. |
| **preflight** | `stack-develop` when opening a slice | Once. On `NEEDS_FIXES`, one developer fix, then the PR opens. No second review. |
| **apply** | `stack-develop` answering an external round below `max-rounds`, and a rebase that changes behavior | None. One developer fix. The next external pass, or the state script's refusal to merge an uncovered head, is the check. |
| **verify** | `stack-develop` answering the last external round (`round` >= `max-rounds`) | Once, after the developer applies the comments. `harness-fix` is posted only on `IMPLEMENTATION_APPROVED`. Otherwise stop. No second review. |

External `max-rounds` (default 2) is unchanged. `pr-review` depth is unchanged.

## Previous: full loop on every code change

Before the preflight budgets, every code path used the 5-cycle loop, including stacks. To restore that behavior, put the text below back into the templates, delete the budget sections added for the active strategy, and run `python scripts/generate.py`.

### `templates/skills/develop-review/SKILL.md.tmpl`

Remove the review-budget section, the budget branches in Step 3, and the Step 4 restriction. Step 3 is only:

```markdown
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
```

Step 4 opens the pull request once that loop ends in `IMPLEMENTATION_APPROVED`. There is no preflight, apply, or verify budget.

In `templates/agents/develop-review-reviewer.md.tmpl`, remove the paragraph that tells the reviewer about preflight and verify budgets.

### `templates/skills/stack-develop/SKILL.md.tmpl`

`max-rounds` counts external `pr-review` passes only. `develop-review` keeps its own internal cap of 5.

Rebase, when the resolution changes behavior beyond taking one side:

```markdown
follow `develop-review` in **fix mode** on that layer before continuing.
```

Address:

```markdown
3. Read and follow `develop-review` in **fix mode** with the external comments.
```

That fix mode is the full skill loop, including reviewer spawns, up to the internal cap. Then commit, push the layer, rebase upstack, and post `harness-fix`.

Continue:

```markdown
2. Read and follow `develop-review` for that slice through approval. The branch
   already exists. Skip its branch question.
```

Do not open the slice's pull request until the internal reviewer returns `IMPLEMENTATION_APPROVED`.

### `templates/skills/plan-develop/SKILL.md.tmpl`

`stack-develop` runs `develop-review` once per slice through the 5-cycle loop. On a single PR or any stack slice, if `develop-review` hits its cap without approval, the pipeline stops. Do not open a pull request for an implementation the reviewer did not approve.

### `templates/skills/stack-review/SKILL.md.tmpl` and `templates/shared/harness-stack-protocol.md`

Remove the notes that the developer harness preflights once and verifies only the last external fix. External review behavior (`pr-review`, `max-rounds`, verdicts) was the same under both strategies and does not need a restore.

### README

Remove the paragraph that describes preflight, apply, and verify. Point readers at this file only while the active strategy is the preflight one.

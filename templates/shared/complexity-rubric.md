# Complexity rubric

Every approved plan must include a **Complexity** section with exactly one of
`low`, `medium`, or `high`, plus a short reason. Downstream skills use that rating
to pick the development and review spawn: model always, and effort when the provider
supports a separate effort dial (Claude / Codex). On Cursor, Complexity selects the
model (and PR-review scope); there is no effort argument.

| Rating | Use when |
|---|---|
| **low** | One area, existing patterns, no new data model, auth, money, or concurrency |
| **medium** | A feature or fix across a few modules, with real edge cases, still inside one system |
| **high** | Auth, money, migrations, concurrency, public API, or a wrong approach that is expensive to undo |

When classifying without a plan (direct develop-review task, or a PR with no plan in the
body), apply the same table once, record the rating, and keep that rating for every spawn
in the run.

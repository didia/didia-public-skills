# didia-public-skills

Provider-specific agent skills generated from shared templates.

Workflows:

| Skill | Role |
|---|---|
| `plan-review` | Bounded plan → validate loop (no code) |
| `develop-review` | Bounded develop → review loop, then open a PR |
| `plan-develop` | Orchestrator: plan-review, then one PR or a stack (`Land: progressive` or `atomic`) |
| `pr-review` | Deep GitHub PR review with inline comments |
| `stack-develop` | Cross-harness developer: stack PRs via develop-review, merge, sync |
| `stack-review` | Cross-harness reviewer: every eligible stack layer via pr-review |

Templates live under `templates/`. Generated trees are committed at `claude/`, `codex/`, and `cursor/`. **Edit templates and `config.yaml`, not the generated files.**

## Generate

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# defaults from config.yaml
python scripts/generate.py

# one provider
python scripts/generate.py --provider claude
python scripts/generate.py --provider cursor

# override models for this run
python scripts/generate.py \
  --planning-model claude-sonnet-5 \
  --development-model claude-sonnet-5 \
  --review-model claude-opus-5
```

**Precedence:** CLI flags replace the role model, including every per-complexity `model` cell. Provider block overrides `defaults`. Effort cells in a complexity map stay unless you change them in config. A CLI review model that matches the developer model is rejected.

## Config

[`config.yaml`](config.yaml) sets default models and per-provider paths / compatibility / subagent invoke wording. Claude defaults are family aliases (`sonnet`, `opus`), which resolve to the latest model in that family. Codex has no equivalent alias, so its provider block names a current slug (`gpt-6.1-sol`, `gpt-5.6-terra`, `gpt-6-astra`). Plan on Sol, validate plans on Astra, build with Terra on low complexity else Sol. **develop-review** and **pr-review** spawn **gpt-6.1-sol** at low, medium, or high `model_reasoning_effort` from Complexity. Cursor slots take `inherit` (Auto), `grok-4.7-high` (Grok), or `composer-2.5-fast` (Composer). Claude and Cursor still pair a different critic model from the author; Codex allows the same Sol slug for implement and code-review when effort differs.

Planning always runs at `planning_effort` (default `high`) on providers that support a separate effort dial (Claude / Codex). The plan's **Complexity** rating (`low` / `medium` / `high`) selects development and review spawn settings. During implementation the rating may be raised, never lowered. Review effort is floored at `review_effort_floor` (default `medium`). Cursor has no `effort_key` — Complexity selects PR-review scope (focused vs full), and the review model stays Grok. Optional maps `development_by_complexity` and `review_by_complexity` can override `model` and/or `effort` per level; unspecified cells inherit the role model and use the complexity word as the effort when effort applies. A malformed map (unknown level, non-mapping cell, unknown key) stops generation.

`trunk` (default `dev`) is the branch `plan-develop` uses. Codex agents are generated as `.toml` (`name`, `description`, `model`, optional `model_reasoning_effort`, `developer_instructions`). Cursor `readonly_subagents` is false so planner, validator, and reviewer can still run git and tests; their tool lists omit Write and Edit.

`stack-develop` and `stack-review` call `scripts/stack_state.py` for the next action (rebase, address, merge, label, continue, review). Default `land: progressive` merges a ready prefix with `gh stack merge` while upper layers stay open. `land: atomic` merges the whole open stack once every layer is ready. The script caps unreviewed PRs above the stack bottom at two, and those PRs are still reviewable. Poll with `/loop` or a scheduled wakeup.

On a stack, `develop-review` does not run its 5-cycle loop. A new slice gets one reviewer spawn and at most one fix (`preflight`). A fix for an external round that will be reviewed again is developer-only (`apply`). The fix for the last external round gets one reviewer spawn (`verify`) and is posted only if that spawn approves. A single PR with no external reviewer still uses the 5-cycle loop. Models are unchanged. The previous always-on 5-cycle behavior, and how to restore it, is in [docs/internal-review-strategy.md](docs/internal-review-strategy.md).

Optional label overrides per provider: `planning_model_label`, `development_model_label`, `review_model_label`.

## Install

```bash
# every provider, all skills (paths from config.yaml)
python scripts/install.py

# one provider / specific skill(s)
python scripts/install.py --provider claude
python scripts/install.py --provider cursor
python scripts/install.py --provider codex --skill plan-review
python scripts/install.py --provider claude plan-review develop-review
```

See [INSTALL.md](INSTALL.md) for `--project`, `--dry-run`, and generate steps.

## Layout

```
templates/          # source of truth (.tmpl + static assets)
scripts/generate.py
config.yaml
claude/             # GENERATED
codex/              # GENERATED
cursor/             # GENERATED
```

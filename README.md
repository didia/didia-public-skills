# didia-public-skills

Provider-specific agent skills generated from shared templates.

Workflows:

| Skill | Role |
|---|---|
| `plan-review` | Bounded plan → validate loop (no code) |
| `develop-review` | Bounded develop → review loop, then open a PR |
| `plan-develop` | Orchestrator: branch → plan-review → develop-review → PR |
| `pr-review` | Deep GitHub PR review with inline comments |
| `stack-develop` | Cross-harness developer: stack PRs via develop-review, merge, sync |
| `stack-review` | Cross-harness reviewer: eligible stack bottom via pr-review |

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

**Precedence:** CLI flags → provider block in `config.yaml` → `defaults`.

## Config

[`config.yaml`](config.yaml) sets default models and per-provider paths / compatibility / subagent invoke wording. Claude defaults are family aliases (`sonnet`, `opus`), which resolve to the latest model in that family. Codex has no equivalent alias, so its provider block names the current newest model in each family. Cursor slots take `inherit` (Auto), `grok-4.7-high` (Grok), or `composer-2.5-fast` (Composer). The default split is Composer for planning and development, Grok for review.

Planning always runs at `planning_effort` (default `high`) on providers that support a separate effort dial (Claude / Codex). The plan's **Complexity** rating (`low` / `medium` / `high`) selects development and review spawn settings: effort where supported, otherwise model. Cursor has no `effort_key` — Complexity selects model and PR-review scope (focused vs full). Optional maps `development_by_complexity` and `review_by_complexity` can override `model` and/or `effort` per level; unspecified cells inherit the role model and use the complexity word as the effort when effort applies.

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

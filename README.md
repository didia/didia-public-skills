# didia-public-skills

Provider-specific agent skills generated from shared templates.

Workflows:

| Skill | Role |
|---|---|
| `plan-review` | Bounded plan → validate loop (no code) |
| `develop-review` | Bounded develop → review loop, then open a PR |
| `plan-develop` | Orchestrator: branch → plan-review → develop-review → PR |
| `pr-review` | Deep GitHub PR review with inline comments |

Templates live under `templates/`. Generated trees are committed at `claude/` and `codex/`. **Edit templates and `config.yaml`, not the generated files.**

## Generate

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# defaults from config.yaml
python scripts/generate.py

# one provider
python scripts/generate.py --provider claude

# override models for this run
python scripts/generate.py \
  --planning-model claude-sonnet-5 \
  --development-model claude-sonnet-5 \
  --review-model claude-opus-5
```

**Precedence:** CLI flags → provider block in `config.yaml` → `defaults`.

## Config

[`config.yaml`](config.yaml) sets default models and per-provider paths / compatibility / subagent invoke wording. Codex defaults use different model IDs than Claude.

Optional label overrides per provider: `planning_model_label`, `development_model_label`, `review_model_label`.

## Install

See [INSTALL.md](INSTALL.md).

## Layout

```
templates/          # source of truth (.tmpl + static assets)
scripts/generate.py
config.yaml
claude/             # GENERATED
codex/              # GENERATED
```

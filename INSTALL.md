# Install

## Generate (if you changed templates or config)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate.py
```

## Install skills

Paths come from `config.yaml` (`skills_dir`, `agents_dir` per provider).

```bash
# both providers, all skills
python scripts/install.py

# one provider
python scripts/install.py --provider claude
python scripts/install.py --provider codex

# one or more specific skills
python scripts/install.py --provider claude --skill plan-review
python scripts/install.py --provider codex plan-review develop-review

# preview without copying
python scripts/install.py --provider all --skill pr-review --dry-run

# install agents into the current project's agents dir (from config project_agents_dir)
python scripts/install.py --provider claude --project
```

The script copies each skill directory and any agents that skill owns, and removes
obsolete `plan-develop-{planner,validator,developer,reviewer}.md` agents if present.

Also check any repo that still has those obsolete agents under
`<repo>/.claude/agents/` or `<repo>/.codex/agents/`.

## Layout

```
claude/skills/plan-review/      planning loop
claude/skills/develop-review/   implementation loop → PR
claude/skills/plan-develop/     orchestrator
claude/skills/pr-review/        deep GitHub PR review
claude/agents/                  four subagents (user-wide install)

codex/…                         same skills/agents, Codex models + paths
```

Each loop skill also keeps a copy of its agents under its `agents/` directory so the
skill stays self-contained in a project install.

Default models come from `config.yaml`. Change them there or pass
`--planning-model` / `--development-model` / `--review-model` when generating.

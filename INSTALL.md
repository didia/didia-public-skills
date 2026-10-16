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
# every provider, all skills
python scripts/install.py

# one provider
python scripts/install.py --provider claude
python scripts/install.py --provider codex
python scripts/install.py --provider cursor

# one or more specific skills
python scripts/install.py --provider claude --skill plan-review
python scripts/install.py --provider codex plan-review develop-review

# preview without copying
python scripts/install.py --provider all --skill pr-review --dry-run

# install agents into the current project's agents dir (from config project_agents_dir)
python scripts/install.py --provider claude --project
```

The script copies each skill directory and any agents that skill owns.

## Layout

```
claude/skills/plan-review/      planning loop
claude/skills/develop-review/   implementation loop → PR
claude/skills/plan-develop/     orchestrator
claude/skills/pr-review/        deep GitHub PR review
claude/skills/stack-develop/    cross-harness stack developer (needs develop-review)
claude/skills/stack-review/     cross-harness stack reviewer (needs pr-review)
claude/agents/                  four subagents (user-wide install)

codex/…                         same skills/agents, Codex models + paths
cursor/…                        same skills/agents, Cursor models + paths
```

Cursor installs skills to `~/.cursor/skills` and subagents to `~/.cursor/agents`
(or `<repo>/.cursor/agents` with `--project`). Model slots are `inherit` (Auto),
`grok-4.7-high` (Grok), or `composer-2.5-fast` (Composer).

Each loop skill also keeps a copy of its agents under its `agents/` directory so the
skill stays self-contained in a project install.

`stack-develop` and `stack-review` coordinate only through GitHub labels and PR
markers. Install `stack-develop` with `develop-review` on the developer harness,
and `stack-review` with `pr-review` on the reviewer harness (they may be
different providers).

Default models come from `config.yaml`. Change them there or pass
`--planning-model` / `--development-model` / `--review-model` when generating.

# Install

## Generate (if you changed templates or config)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate.py
```

## Claude

```bash
cp -r claude/skills/* ~/.claude/skills/
cp    claude/agents/*  ~/.claude/agents/
```

Remove obsolete agents from the old single-skill layout, if present:

```bash
rm -f ~/.claude/agents/plan-develop-{planner,validator,developer,reviewer}.md
```

Also check any repo that has them under `<repo>/.claude/agents/`.

## Codex

```bash
cp -r codex/skills/* ~/.codex/skills/
cp    codex/agents/*  ~/.codex/agents/
```

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

Default models come from `config.yaml` (Claude: Sonnet/Opus; Codex: GPT-5/o3). Change
them there or pass `--planning-model` / `--development-model` / `--review-model` when
generating.

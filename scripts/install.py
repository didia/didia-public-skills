#!/usr/bin/env python3
"""Install generated skills (and their agents) for Claude and/or Codex.

Reads install paths from config.yaml. Installs all skills by default, or only
those named via --skill / positional arguments.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"

# Agents owned by each skill (also present under {provider}/agents/)
SKILL_AGENTS: dict[str, list[str]] = {
    "plan-review": [
        "plan-review-planner.md",
        "plan-review-validator.md",
    ],
    "develop-review": [
        "develop-review-developer.md",
        "develop-review-reviewer.md",
    ],
    "plan-develop": [],
    "pr-review": [],
    "stack-develop": [],
    "stack-review": [],
}

# Skills that need sibling skills installed on the same harness
SKILL_DEPS: dict[str, list[str]] = {
    "plan-develop": ["plan-review", "develop-review"],
    "stack-develop": ["develop-review"],
    "stack-review": ["pr-review"],
}


def load_config(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def expand(path: str) -> Path:
    return Path(path).expanduser().resolve()


def available_skills(provider: str) -> list[str]:
    skills_root = ROOT / provider / "skills"
    if not skills_root.is_dir():
        raise SystemExit(
            f"Generated tree missing: {skills_root}\n"
            "Run: python scripts/generate.py"
        )
    return sorted(p.name for p in skills_root.iterdir() if p.is_dir())


def resolve_skills(provider: str, requested: list[str]) -> list[str]:
    available = available_skills(provider)
    if not requested:
        return available
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise SystemExit(
            f"Unknown skill(s) for {provider}: {', '.join(unknown)}\n"
            f"Available: {', '.join(available)}"
        )
    # Preserve request order, unique
    seen: set[str] = set()
    out: list[str] = []
    for name in requested:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def copy_skill(provider: str, skill: str, dest_skills: Path, dry_run: bool) -> None:
    src = ROOT / provider / "skills" / skill
    dest = dest_skills / skill
    print(f"  skill  {src.relative_to(ROOT)} → {dest}")
    if dry_run:
        return
    dest_skills.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def copy_agents(
    provider: str,
    agent_names: list[str],
    dest_agents: Path,
    dry_run: bool,
) -> None:
    if not agent_names:
        return
    src_agents = ROOT / provider / "agents"
    for name in agent_names:
        src = src_agents / name
        if not src.is_file():
            raise SystemExit(f"Missing agent file: {src}")
        dest = dest_agents / name
        print(f"  agent  {src.relative_to(ROOT)} → {dest}")
        if dry_run:
            continue
        dest_agents.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def install_provider(
    provider: str,
    config: dict,
    skills: list[str],
    *,
    project: bool,
    dry_run: bool,
) -> None:
    providers = config.get("providers") or {}
    if provider not in providers:
        raise SystemExit(f"Unknown provider {provider!r}. Known: {sorted(providers)}")

    cfg = providers[provider] or {}
    skills_dir = expand(cfg["skills_dir"])
    if project:
        agents_dir = Path.cwd() / cfg["project_agents_dir"]
        agents_dir = agents_dir.resolve()
    else:
        agents_dir = expand(cfg["agents_dir"])

    print(f"[{provider}] skills → {skills_dir}")
    print(f"[{provider}] agents → {agents_dir}")

    agent_names: list[str] = []
    for skill in skills:
        copy_skill(provider, skill, skills_dir, dry_run)
        agent_names.extend(SKILL_AGENTS.get(skill, []))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_agents = []
    for name in agent_names:
        if name not in seen:
            seen.add(name)
            unique_agents.append(name)

    copy_agents(provider, unique_agents, agents_dir, dry_run)

    all_available = set(available_skills(provider))
    # Warn on partial installs that omit sibling deps
    if set(skills) != all_available:
        for skill in skills:
            deps = SKILL_DEPS.get(skill, [])
            missing = [d for d in deps if d not in skills]
            if missing:
                print(
                    f"  note: {skill} needs {', '.join(missing)} installed as well"
                )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/install.py
  python scripts/install.py --provider claude
  python scripts/install.py --provider codex --skill plan-review
  python scripts/install.py --provider claude plan-review develop-review
  python scripts/install.py --provider all --skill pr-review --dry-run
  python scripts/install.py --provider claude --project
""".strip(),
    )
    p.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to config.yaml (default: repo root config.yaml)",
    )
    p.add_argument(
        "--provider",
        choices=["claude", "codex", "all"],
        default="all",
        help="Which provider tree(s) to install (default: all)",
    )
    p.add_argument(
        "--skill",
        action="append",
        default=[],
        metavar="NAME",
        help="Install only this skill (repeatable). Same as positional args.",
    )
    p.add_argument(
        "skills",
        nargs="*",
        metavar="SKILL",
        help="Skill name(s) to install (default: all skills for the provider)",
    )
    p.add_argument(
        "--project",
        action="store_true",
        help="Install agents into <cwd>/<project_agents_dir> from config "
        "instead of the user-wide agents_dir",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be installed without copying",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.config.is_file():
        raise SystemExit(f"Config not found: {args.config}")

    config = load_config(args.config)
    providers = list((config.get("providers") or {}).keys())
    if args.provider != "all":
        providers = [args.provider]

    requested = list(args.skill) + list(args.skills)

    for provider in providers:
        skills = resolve_skills(provider, requested)
        install_provider(
            provider,
            config,
            skills,
            project=args.project,
            dry_run=args.dry_run,
        )

    if args.dry_run:
        print("Dry run complete — nothing written.")
    else:
        print("Install complete.")


if __name__ == "__main__":
    main()
    sys.exit(0)

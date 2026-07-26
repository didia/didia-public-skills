#!/usr/bin/env python3
"""Generate provider-specific skill trees from templates.

Reads config.yaml for defaults; CLI flags override when passed.
Emits committed trees under claude/ and codex/.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
DEFAULT_CONFIG = ROOT / "config.yaml"

GENERATED_HEADER = (
    "<!-- AUTO-GENERATED — do not edit. Regenerate: python scripts/generate.py -->\n"
)

# Agent template basename → skill that also bundles a copy under agents/
AGENT_SKILL_MAP = {
    "plan-review-planner.md": "plan-review",
    "plan-review-validator.md": "plan-review",
    "develop-review-developer.md": "develop-review",
    "develop-review-reviewer.md": "develop-review",
}

KNOWN_LABELS = {
    "claude-sonnet-5": "Sonnet 5",
    "claude-opus-5": "Opus 5",
    "gpt-5": "GPT-5",
    "gpt-5.1": "GPT-5.1",
    "o3": "o3",
    "o4-mini": "o4-mini",
}


def humanize_model(model_id: str) -> str:
    if model_id in KNOWN_LABELS:
        return KNOWN_LABELS[model_id]
    s = model_id
    if s.startswith("claude-"):
        s = s[len("claude-") :]
    parts = s.replace("_", "-").split("-")
    out = []
    for part in parts:
        if part.lower() == "gpt":
            out.append("GPT")
        elif part.isdigit() or (part and part[0].isdigit()):
            out.append(part)
        else:
            out.append(part.capitalize())
    return " ".join(out)


def load_config(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def merge_provider_context(
    config: dict,
    provider: str,
    cli_overrides: dict[str, str | None],
) -> dict:
    defaults = dict(config.get("defaults") or {})
    providers = config.get("providers") or {}
    if provider not in providers:
        raise SystemExit(f"Unknown provider {provider!r}. Known: {sorted(providers)}")

    merged = {**defaults, **(providers[provider] or {})}
    for key, value in cli_overrides.items():
        if value is not None:
            merged[key] = value

    required = (
        "planning_model",
        "development_model",
        "review_model",
        "skills_dir",
        "agents_dir",
        "project_agents_dir",
        "compatibility",
        "subagent_invoke",
        "environment_name",
    )
    missing = [k for k in required if not merged.get(k)]
    if missing:
        raise SystemExit(f"Provider {provider!r} missing config keys: {missing}")

    planning_label = merged.get("planning_model_label") or humanize_model(
        merged["planning_model"]
    )
    development_label = merged.get("development_model_label") or humanize_model(
        merged["development_model"]
    )
    review_label = merged.get("review_model_label") or humanize_model(
        merged["review_model"]
    )

    def invoke(name: str) -> str:
        return str(merged["subagent_invoke"]).format(name=name)

    return {
        "provider": provider,
        "planning_model": merged["planning_model"],
        "development_model": merged["development_model"],
        "review_model": merged["review_model"],
        "planning_model_label": planning_label,
        "development_model_label": development_label,
        "review_model_label": review_label,
        "skills_dir": merged["skills_dir"],
        "agents_dir": merged["agents_dir"],
        "project_agents_dir": merged["project_agents_dir"],
        "compatibility": merged["compatibility"],
        "environment_name": merged["environment_name"],
        "subagent_invoke": merged["subagent_invoke"],
        "invoke": invoke,
        "invoke_planner": invoke("plan-review-planner"),
        "invoke_validator": invoke("plan-review-validator"),
        "invoke_developer": invoke("develop-review-developer"),
        "invoke_reviewer": invoke("develop-review-reviewer"),
    }


def write_text(path: Path, content: str, stamp: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if stamp and path.suffix == ".md" and "AUTO-GENERATED" not in content[:200]:
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                end += len("\n---")
                rest = content[end:].lstrip("\n")
                content = content[:end] + "\n" + GENERATED_HEADER + rest
            else:
                content = GENERATED_HEADER + content
        else:
            content = GENERATED_HEADER + content
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content)


def render_tree(provider: str, ctx: dict, env: Environment) -> None:
    out_root = ROOT / provider
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    skills_src = TEMPLATES / "skills"
    agents_src = TEMPLATES / "agents"

    # Skills: render .tmpl, copy everything else
    for src in skills_src.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(skills_src)
        if src.suffix == ".tmpl":
            dest_rel = Path(str(rel)[: -len(".tmpl")])
            template_name = str(Path("skills") / rel).replace("\\", "/")
            rendered = env.get_template(template_name).render(**ctx)
            dest = out_root / "skills" / dest_rel
            write_text(dest, rendered, stamp=True)
        else:
            dest = out_root / "skills" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # Agents: render once to provider/agents/, copy into owning skill agents/
    for src in sorted(agents_src.glob("*.tmpl")):
        basename = src.name[: -len(".tmpl")]  # e.g. plan-review-planner.md
        template_name = f"agents/{src.name}"
        rendered = env.get_template(template_name).render(**ctx)

        top = out_root / "agents" / basename
        write_text(top, rendered, stamp=True)

        skill = AGENT_SKILL_MAP.get(basename)
        if skill:
            bundled = out_root / "skills" / skill / "agents" / basename
            write_text(bundled, rendered, stamp=True)

    print(f"Generated {provider}/")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
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
        help="Which provider tree(s) to generate (default: all)",
    )
    p.add_argument("--planning-model", default=None)
    p.add_argument("--development-model", default=None)
    p.add_argument("--review-model", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.config.is_file():
        raise SystemExit(f"Config not found: {args.config}")
    if not TEMPLATES.is_dir():
        raise SystemExit(f"Templates dir not found: {TEMPLATES}")

    config = load_config(args.config)
    providers = list((config.get("providers") or {}).keys())
    if args.provider != "all":
        providers = [args.provider]

    cli_overrides = {
        "planning_model": args.planning_model,
        "development_model": args.development_model,
        "review_model": args.review_model,
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )

    for provider in providers:
        ctx = merge_provider_context(config, provider, cli_overrides)
        render_tree(provider, ctx, env)


if __name__ == "__main__":
    main()
    sys.exit(0)

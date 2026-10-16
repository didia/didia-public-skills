#!/usr/bin/env python3
"""Generate provider-specific skill trees from templates.

Reads config.yaml for defaults; CLI flags override when passed.
Emits committed trees under claude/, codex/, and cursor/.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

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

# Shared reference files copied into skill references/ directories
SHARED_REFERENCES = {
    "harness-stack-protocol.md": (
        "stack-develop",
        "stack-review",
    ),
    "complexity-rubric.md": (
        "plan-review",
        "develop-review",
        "pr-review",
        "plan-develop",
    ),
}

COMPLEXITY_LEVELS = ("low", "medium", "high")

KNOWN_LABELS = {
    "claude-sonnet-5": "Sonnet 5",
    "claude-opus-5": "Opus 5",
    "gpt-5": "GPT-5",
    "gpt-5.1": "GPT-5.1",
    "gpt-5.6-sol": "GPT 5.6 Sol",
    "gpt-5.6-terra": "GPT 5.6 Terra",
    "gpt-6.1-sol": "GPT 6.1 Sol",
    "o3": "o3",
    "o4-mini": "o4-mini",
    "sonnet": "Sonnet",
    "opus": "Opus",
    "inherit": "Auto",
    "grok-4.7-high": "Grok",
    "composer-2.5-fast": "Composer",
}


def readonly_line(merged: dict, readonly: bool) -> str:
    """Cursor pins read-only subagents with `readonly: true`. Other providers omit it."""
    if readonly and merged.get("readonly_subagents"):
        return "readonly: true\n"
    return ""


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


def deep_merge_complexity_maps(
    base: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Merge per-complexity maps cell-by-cell. Provider cells override default cells."""
    result: dict[str, dict[str, Any]] = {}
    for level, cell in (base or {}).items():
        if isinstance(cell, dict):
            result[str(level)] = dict(cell)
    for level, cell in (override or {}).items():
        key = str(level)
        if isinstance(cell, dict):
            result[key] = {**(result.get(key) or {}), **cell}
    return result


def resolve_complexity_matrix(
    default_model: str,
    overrides: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, str]]:
    """Fill every complexity level with model + effort (defaults to the level name)."""
    overrides = overrides or {}
    matrix: dict[str, dict[str, str]] = {}
    for level in COMPLEXITY_LEVELS:
        cell = overrides.get(level) or {}
        model = str(cell.get("model") or default_model)
        effort = str(cell.get("effort") or level)
        matrix[level] = {
            "model": model,
            "effort": effort,
            "model_label": humanize_model(model),
        }
    return matrix


def merge_provider_context(
    config: dict,
    provider: str,
    cli_overrides: dict[str, str | None],
) -> dict:
    defaults = dict(config.get("defaults") or {})
    providers = config.get("providers") or {}
    if provider not in providers:
        raise SystemExit(f"Unknown provider {provider!r}. Known: {sorted(providers)}")

    provider_cfg = dict(providers[provider] or {})

    development_by_complexity = deep_merge_complexity_maps(
        defaults.pop("development_by_complexity", None),
        provider_cfg.pop("development_by_complexity", None),
    )
    review_by_complexity = deep_merge_complexity_maps(
        defaults.pop("review_by_complexity", None),
        provider_cfg.pop("review_by_complexity", None),
    )

    merged = {**defaults, **provider_cfg}
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

    planning_effort = str(merged.get("planning_effort") or "high")
    # Providers without a separate effort dial (e.g. Cursor) leave effort_key unset.
    effort_key = merged.get("effort_key")
    if effort_key is not None:
        effort_key = str(effort_key)

    planning_label = merged.get("planning_model_label") or humanize_model(
        merged["planning_model"]
    )
    development_label = merged.get("development_model_label") or humanize_model(
        merged["development_model"]
    )
    review_label = merged.get("review_model_label") or humanize_model(
        merged["review_model"]
    )

    development_matrix = resolve_complexity_matrix(
        str(merged["development_model"]),
        development_by_complexity,
    )
    review_matrix = resolve_complexity_matrix(
        str(merged["review_model"]),
        review_by_complexity,
    )

    invoke_template = str(merged["subagent_invoke"])

    def invoke(
        name: str,
        model: str | None = None,
        effort: str | None = None,
    ) -> str:
        kwargs: dict[str, str] = {"name": name}
        if "{model}" in invoke_template:
            kwargs["model"] = model if model is not None else ""
        if "{effort}" in invoke_template:
            kwargs["effort"] = effort if effort is not None else ""
        return invoke_template.format(**kwargs)

    planning_model = str(merged["planning_model"])
    review_model = str(merged["review_model"])

    invoke_developer_by_complexity = {
        level: invoke(
            "develop-review-developer",
            row["model"],
            row["effort"],
        )
        for level, row in development_matrix.items()
    }
    invoke_reviewer_by_complexity = {
        level: invoke(
            "develop-review-reviewer",
            row["model"],
            row["effort"],
        )
        for level, row in review_matrix.items()
    }

    return {
        "provider": provider,
        "planning_model": planning_model,
        "development_model": merged["development_model"],
        "review_model": review_model,
        "planning_effort": planning_effort,
        "effort_key": effort_key,
        "planning_model_label": planning_label,
        "development_model_label": development_label,
        "review_model_label": review_label,
        "development_matrix": development_matrix,
        "review_matrix": review_matrix,
        "skills_dir": merged["skills_dir"],
        "agents_dir": merged["agents_dir"],
        "project_agents_dir": merged["project_agents_dir"],
        "compatibility": merged["compatibility"],
        "environment_name": merged["environment_name"],
        "subagent_invoke": merged["subagent_invoke"],
        "invoke": invoke,
        "invoke_planner": invoke(
            "plan-review-planner",
            planning_model,
            planning_effort,
        ),
        "invoke_validator": invoke(
            "plan-review-validator",
            review_model,
            planning_effort,
        ),
        "invoke_developer": invoke(
            "develop-review-developer",
            str(merged["development_model"]),
            "medium",
        ),
        "invoke_reviewer": invoke(
            "develop-review-reviewer",
            review_model,
            "medium",
        ),
        "invoke_developer_by_complexity": invoke_developer_by_complexity,
        "invoke_reviewer_by_complexity": invoke_reviewer_by_complexity,
        "planner_readonly": readonly_line(merged, True),
        "validator_readonly": readonly_line(merged, True),
        "developer_readonly": readonly_line(merged, False),
        "reviewer_readonly": readonly_line(merged, True),
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

    # Shared references: same file into each owning skill
    shared_src = TEMPLATES / "shared"
    for filename, skills in SHARED_REFERENCES.items():
        src = shared_src / filename
        if not src.is_file():
            raise SystemExit(f"Missing shared reference: {src}")
        dest_name = "protocol.md" if filename == "harness-stack-protocol.md" else filename
        for skill in skills:
            dest = out_root / "skills" / skill / "references" / dest_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

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
        choices=["claude", "codex", "cursor", "all"],
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

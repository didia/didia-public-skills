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
COMPLEXITY_CELL_KEYS = {"model", "effort"}
EFFORT_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
    "max": 5,
    "ultra": 6,
}

KNOWN_LABELS = {
    "claude-sonnet-5": "Sonnet 5",
    "claude-opus-5": "Opus 5",
    "gpt-5": "GPT-5",
    "gpt-5.1": "GPT-5.1",
    "gpt-5.6-sol": "GPT 5.6 Sol",
    "gpt-5.6-terra": "GPT 5.6 Terra",
    "gpt-6.1-sol": "GPT 6.1 Sol",
    "gpt-6-astra": "GPT 6 Astra",
    "o3": "o3",
    "o4-mini": "o4-mini",
    "haiku": "Haiku",
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


def validate_complexity_map(name: str, raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise SystemExit(f"{name} must be a mapping of low/medium/high")
    for level, cell in raw.items():
        if str(level) not in COMPLEXITY_LEVELS:
            raise SystemExit(
                f"{name}: unknown level {level!r}. Use {', '.join(COMPLEXITY_LEVELS)}"
            )
        if not isinstance(cell, dict):
            raise SystemExit(f"{name}.{level} must be a mapping with model and/or effort")
        extra = set(cell) - COMPLEXITY_CELL_KEYS
        if extra:
            raise SystemExit(
                f"{name}.{level} has unknown keys {sorted(extra)}. Use model and/or effort"
            )
        effort = cell.get("effort")
        if effort is not None and str(effort) not in EFFORT_RANK:
            raise SystemExit(f"{name}.{level}.effort unknown value {effort!r}")


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


def _apply_model(matrix: dict[str, dict[str, str]], model: str) -> None:
    label = humanize_model(model)
    for row in matrix.values():
        row["model"] = model
        row["model_label"] = label


def _apply_effort_floor(matrix: dict[str, dict[str, str]], floor: str) -> None:
    floor_rank = EFFORT_RANK.get(floor)
    if floor_rank is None:
        raise SystemExit(f"Unknown review_effort_floor {floor!r}")
    for level, row in matrix.items():
        rank = EFFORT_RANK.get(row["effort"])
        if rank is None:
            raise SystemExit(f"Unknown review effort {row['effort']!r} at {level}")
        if rank < floor_rank:
            row["effort"] = floor


def _require_distinct_critics(
    provider: str,
    planning_model: str,
    validator_model: str,
    development_matrix: dict[str, dict[str, str]],
    review_matrix: dict[str, dict[str, str]],
    *,
    allow_same_develop_review_model: bool = False,
) -> None:
    # Plan validation uses the base review model, not the per-complexity matrix.
    if planning_model == validator_model:
        raise SystemExit(
            f"Provider {provider!r}: planning_model {planning_model!r} matches the plan "
            "validator model. The plan critic has to be a different model; use effort to "
            "control cost."
        )
    if allow_same_develop_review_model:
        return
    for level in COMPLEXITY_LEVELS:
        author = development_matrix[level]["model"]
        critic = review_matrix[level]["model"]
        if author == critic:
            raise SystemExit(
                f"Provider {provider!r}: development and review both use {author!r} at "
                f"{level}. The reviewer has to be a different model."
            )


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

    default_dev_map = defaults.pop("development_by_complexity", None)
    provider_dev_map = provider_cfg.pop("development_by_complexity", None)
    default_review_map = defaults.pop("review_by_complexity", None)
    provider_review_map = provider_cfg.pop("review_by_complexity", None)
    validate_complexity_map("development_by_complexity", default_dev_map)
    validate_complexity_map("development_by_complexity", provider_dev_map)
    validate_complexity_map("review_by_complexity", default_review_map)
    validate_complexity_map("review_by_complexity", provider_review_map)
    development_by_complexity = deep_merge_complexity_maps(
        default_dev_map,
        provider_dev_map,
    )
    review_by_complexity = deep_merge_complexity_maps(
        default_review_map,
        provider_review_map,
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

    development_matrix = resolve_complexity_matrix(
        str(merged["development_model"]),
        development_by_complexity,
    )
    review_matrix = resolve_complexity_matrix(
        str(merged["review_model"]),
        review_by_complexity,
    )
    # CLI model flags replace every cell's model. Effort overrides in the map stay.
    if cli_overrides.get("development_model"):
        _apply_model(development_matrix, str(cli_overrides["development_model"]))
    if cli_overrides.get("review_model"):
        _apply_model(review_matrix, str(cli_overrides["review_model"]))
    if effort_key:
        floor = str(merged.get("review_effort_floor") or "medium")
        _apply_effort_floor(review_matrix, floor)

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
    if cli_overrides.get("planning_model"):
        planning_model = str(cli_overrides["planning_model"])
    if cli_overrides.get("review_model"):
        review_model = str(cli_overrides["review_model"])
    allow_same_develop_review = bool(
        merged.pop("allow_same_develop_review_model", False)
    )
    _require_distinct_critics(
        provider,
        planning_model,
        review_model,
        development_matrix,
        review_matrix,
        allow_same_develop_review_model=allow_same_develop_review,
    )
    development_model = str(
        cli_overrides.get("development_model") or merged["development_model"]
    )
    planning_label = (
        humanize_model(planning_model)
        if cli_overrides.get("planning_model")
        else merged.get("planning_model_label") or humanize_model(planning_model)
    )
    development_label = (
        humanize_model(development_model)
        if cli_overrides.get("development_model")
        else merged.get("development_model_label") or humanize_model(development_model)
    )
    review_label = (
        humanize_model(review_model)
        if cli_overrides.get("review_model")
        else merged.get("review_model_label") or humanize_model(review_model)
    )

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
        "development_model": development_model,
        "review_model": review_model,
        "planning_effort": planning_effort,
        "effort_key": effort_key,
        "trunk": str(merged.get("trunk") or "dev"),
        "agent_suffix": ".toml" if provider == "codex" else ".md",
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
        "invoke_developer_by_complexity": invoke_developer_by_complexity,
        "invoke_reviewer_by_complexity": invoke_reviewer_by_complexity,
        "planner_readonly": readonly_line(merged, True),
        "validator_readonly": readonly_line(merged, True),
        "developer_readonly": readonly_line(merged, False),
        "reviewer_readonly": readonly_line(merged, True),
    }


def markdown_agent_to_toml(markdown: str, *, include_model: bool = True) -> str:
    """Codex custom agents are TOML. Markdown frontmatter is not what Codex loads."""
    if not markdown.startswith("---"):
        raise SystemExit("Agent is missing frontmatter")
    end = markdown.find("\n---", 3)
    if end == -1:
        raise SystemExit("Agent frontmatter is not closed")
    frontmatter = markdown[4:end]
    body = markdown[end + 4 :].lstrip("\n")
    if body.startswith(GENERATED_HEADER):
        body = body[len(GENERATED_HEADER) :]
    fields: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    lines = [
        f"name = {_toml_string(fields.get('name', ''))}",
        f"description = {_toml_string(fields.get('description', ''))}",
    ]
    # Codex applies an agent file's model after the spawn arguments, so a pin
    # here would hide per-complexity routing. Planning agents keep the pin.
    if include_model and fields.get("model"):
        lines.append(f"model = {_toml_string(fields['model'])}")
    effort = fields.get("model_reasoning_effort") or fields.get("effort")
    if include_model and effort:
        lines.append(f"model_reasoning_effort = {_toml_string(effort)}")
    lines.append('developer_instructions = """')
    lines.append(body.rstrip("\n"))
    lines.append('"""')
    lines.append("")
    return "\n".join(lines)


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


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

        skill = AGENT_SKILL_MAP.get(basename)
        if provider == "codex":
            toml_name = Path(basename).with_suffix(".toml").name
            # Developer and reviewer models come from the complexity row at spawn.
            dynamic = basename in {
                "develop-review-developer.md",
                "develop-review-reviewer.md",
            }
            toml = markdown_agent_to_toml(rendered, include_model=not dynamic)
            top = out_root / "agents" / toml_name
            write_text(top, toml, stamp=False)
            if skill:
                bundled = out_root / "skills" / skill / "agents" / toml_name
                write_text(bundled, toml, stamp=False)
        else:
            top = out_root / "agents" / basename
            write_text(top, rendered, stamp=True)
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

    stack_script = shared_src / "stack_state.py"
    if stack_script.is_file():
        for skill in ("stack-develop", "stack-review"):
            dest = out_root / "skills" / skill / "scripts" / "stack_state.py"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stack_script, dest)

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

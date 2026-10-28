import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate  # noqa: E402


class GenerateTests(unittest.TestCase):
    def test_defaults_keep_critics_distinct_and_floor_review(self):
        config = generate.load_config(ROOT / "config.yaml")
        for provider in ("claude", "codex", "cursor"):
            ctx = generate.merge_provider_context(config, provider, {})
            self.assertNotEqual(ctx["planning_model"], ctx["review_model"])
            for level in generate.COMPLEXITY_LEVELS:
                self.assertNotEqual(
                    ctx["development_matrix"][level]["model"],
                    ctx["review_matrix"][level]["model"],
                )
            if ctx["effort_key"]:
                floor = "low" if provider == "codex" else "medium"
                for row in ctx["review_matrix"].values():
                    self.assertGreaterEqual(
                        generate.EFFORT_RANK[row["effort"]],
                        generate.EFFORT_RANK[floor],
                    )

    def test_cli_replaces_complexity_model_cells(self):
        config = generate.load_config(ROOT / "config.yaml")
        ctx = generate.merge_provider_context(
            config,
            "codex",
            {"development_model": "gpt-6.1-sol"},
        )
        self.assertEqual(
            ctx["development_matrix"]["low"]["model"],
            "gpt-6.1-sol",
        )

    def test_malformed_complexity_map_exits(self):
        config = {
            "defaults": {
                "planning_model": "sonnet",
                "development_model": "sonnet",
                "review_model": "opus",
            },
            "providers": {
                "claude": {
                    "skills_dir": "~/.claude/skills",
                    "agents_dir": "~/.claude/agents",
                    "project_agents_dir": ".claude/agents",
                    "compatibility": "x",
                    "subagent_invoke": "model: {model}",
                    "environment_name": "Claude",
                    "development_by_complexity": {"Low": {"model": "opus"}},
                }
            },
        }
        with self.assertRaises(SystemExit):
            generate.merge_provider_context(config, "claude", {})

    def test_same_model_critic_exits(self):
        config = generate.load_config(ROOT / "config.yaml")
        with self.assertRaises(SystemExit):
            generate.merge_provider_context(
                config,
                "claude",
                {"review_model": "sonnet", "planning_model": "opus"},
            )

    def test_validator_model_checked_apart_from_matrix(self):
        config = generate.load_config(ROOT / "config.yaml")
        claude = config["providers"]["claude"]
        claude["review_model"] = "sonnet"
        claude["review_by_complexity"] = {
            level: {"model": "opus"} for level in generate.COMPLEXITY_LEVELS
        }
        with self.assertRaises(SystemExit):
            generate.merge_provider_context(config, "claude", {})

    def test_codex_agent_toml(self):
        md = (
            "---\n"
            "name: plan-review-planner\n"
            "description: drafts\n"
            "model: gpt-6.1-sol\n"
            "model_reasoning_effort: high\n"
            "---\n"
            "Do the work.\n"
        )
        toml = generate.markdown_agent_to_toml(md)
        self.assertIn('model = "gpt-6.1-sol"', toml)
        self.assertIn('model_reasoning_effort = "high"', toml)
        self.assertIn("developer_instructions", toml)
        self.assertIn("Do the work.", toml)
        dynamic = generate.markdown_agent_to_toml(md, include_model=False)
        self.assertNotIn("model =", dynamic)
        self.assertNotIn("model_reasoning_effort", dynamic)


if __name__ == "__main__":
    unittest.main()

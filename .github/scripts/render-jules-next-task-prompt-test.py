#!/usr/bin/env python3
"""Tests for the deterministic Jules next-task prompt renderer."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("render-jules-next-task-prompt.py")
TEMPLATE = Path(__file__).parents[1] / "prompts" / "jules_next_task_prompt.txt"
SPEC = importlib.util.spec_from_file_location("render_jules_prompt", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RenderJulesPromptTest(unittest.TestCase):
    def test_renders_all_dynamic_fields_and_preserves_literal_shell_examples(self) -> None:
        values = {
            "REPOSITORY": "owner/repo",
            "FOCUS": "proxy",
            "TASK_ID": "runtime-task",
            "SELECTED_TASK_TITLE": "Runtime title",
            "SELECTED_TASK_SCORE": "290",
            "SELECTED_TASK_REASON": "runtime-first",
            "RECOVERY_SESSION_ID": "",
            "RECOVERY_REASON": "",
            "RISK_CEILING": "medium",
        }
        rendered = MODULE.render(TEMPLATE.read_text(encoding="utf-8"), values)
        self.assertIn("Repository: owner/repo", rendered)
        self.assertIn("Selected task id: runtime-task", rendered)
        self.assertIn("Selected task score: 290", rendered)
        self.assertNotIn("{{", rendered)
        self.assertIn("$files", rendered)

    def test_rejects_unresolved_placeholder(self) -> None:
        with self.assertRaisesRegex(ValueError, "MISSING"):
            MODULE.render("value={{MISSING}}", {})


if __name__ == "__main__":
    unittest.main()

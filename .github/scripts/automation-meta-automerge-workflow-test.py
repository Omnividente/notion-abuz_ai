#!/usr/bin/env python3
"""Regression tests for automation_meta_automerge.yml control-plane PR allowlist."""

from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / "workflows" / "automation_meta_automerge.yml"


class AutomationMetaAutomergeWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_circuit_breaker_followup_pr_is_allowed(self) -> None:
        self.assertIn("automation-circuit-breaker-followup-", self.text)
        self.assertIn("AUTONOMOUS_CIRCUIT_BREAKER_FOLLOWUP_TASK", self.text)

    def test_manifest_only_guard_remains(self) -> None:
        self.assertIn("Automation meta PRs may only change agent_tasks.json", self.text)
        self.assertIn("python3 scripts/validate_agent_tasks.py agent_tasks.json", self.text)


if __name__ == "__main__":
    unittest.main()

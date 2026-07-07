#!/usr/bin/env python3
"""Regression tests for jules_next_task.yml control-plane merge triggers."""

from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / "workflows" / "jules_next_task.yml"


class JulesNextTaskWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_circuit_breaker_followup_merge_triggers_next_task(self) -> None:
        self.assertIn("automation-circuit-breaker-followup-", self.text)
        self.assertIn("AUTONOMOUS_CIRCUIT_BREAKER_FOLLOWUP_TASK", self.text)

    def test_stopped_prs_still_do_not_trigger_next_task(self) -> None:
        self.assertIn("!contains(github.event.pull_request.labels.*.name, 'stop-loop')", self.text)

    def test_next_task_filters_inactive_jules_sessions_before_duplicate_guard(self) -> None:
        self.assertIn("filter-active-jules-sessions.py", self.text)
        self.assertIn("JULES_RECENT_SESSION_TASKS", self.text)
        self.assertIn("--stopped-task-ids", self.text)
        self.assertIn("Ignored ${ignored} inactive Jules session", self.text)
        self.assertIn("blocking active Jules session", self.text)


if __name__ == "__main__":
    unittest.main()

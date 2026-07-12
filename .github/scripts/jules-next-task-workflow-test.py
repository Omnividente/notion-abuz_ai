#!/usr/bin/env python3
"""Regression tests for jules_next_task.yml control-plane merge triggers."""

from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / "workflows" / "jules_next_task.yml"
AUTOMERGE_WORKFLOW = Path(__file__).parents[1] / "workflows" / "jules_automerge.yml"
META_AUTOMERGE_WORKFLOW = (
    Path(__file__).parents[1] / "workflows" / "automation_meta_automerge.yml"
)


class JulesNextTaskWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.prompt_text = (
            Path(__file__).parents[1] / "prompts" / "jules_next_task_prompt.txt"
        ).read_text(encoding="utf-8")

    def test_automerge_explicitly_wakes_next_cycle(self) -> None:
        text = AUTOMERGE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Wake next Jules cycle after token-authenticated merge", text)
        self.assertIn("actions/workflows/jules_next_task.yml/dispatches", text)
        self.assertIn('allow_parallel: "false"', text)

    def test_meta_automerge_explicitly_wakes_next_cycle(self) -> None:
        text = META_AUTOMERGE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Wake next Jules cycle after automation meta merge", text)
        self.assertIn("actions/workflows/jules_next_task.yml/dispatches", text)
        self.assertIn('allow_parallel: "false"', text)

    def test_large_prompt_is_external_to_workflow_expression(self) -> None:
        self.assertIn(".github/prompts/jules_next_task_prompt.txt", self.text)
        self.assertIn("render-jules-next-task-prompt.py", self.text)
        self.assertNotIn("PROMPT=$(cat <<EOF", self.text)

    def test_rerun_checks_out_current_master_state(self) -> None:
        self.assertIn("# Workflow reruns preserve the original event SHA.", self.text)
        self.assertIn("      - uses: actions/checkout@v5\n        with:\n          ref: master", self.text)

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

    def test_active_session_runs_recovery_observation_before_duplicate_skip(self) -> None:
        self.assertIn("running one recovery observation", self.text)
        self.assertIn("bash .github/scripts/jules-unattended-monitor.sh", self.text)
        self.assertIn('MAX_STALE_IN_PROGRESS_ESCALATIONS="1"', self.text)
        self.assertIn("Skipping new dispatch to avoid duplicate sessions.", self.text)

    def test_thin_queue_dispatches_automation_health_even_when_task_selected(self) -> None:
        self.assertIn('write_output("minimum_todo_tasks", minimum_todo_tasks)', self.text)
        self.assertIn('write_output("below_minimum", str(below_minimum).lower())', self.text)
        self.assertIn("steps.select-task.outputs.below_minimum == 'true'", self.text)
        self.assertIn("Minimum todo tasks: ${{ steps.select-task.outputs.minimum_todo_tasks }}", self.text)

    def test_risk_ceiling_supports_guarded_high_risk_opt_in(self) -> None:
        self.assertIn("          - high", self.text)
        self.assertIn("unguarded high-risk", self.prompt_text)
        self.assertIn("CI/smoke/artifact/self-hosted evidence", self.prompt_text)
        self.assertIn("rollback notes", self.prompt_text)


if __name__ == "__main__":
    unittest.main()

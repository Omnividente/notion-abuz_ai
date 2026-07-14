#!/usr/bin/env python3
"""Regression tests for the leased Jules executor and authoritative wake path."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / "workflows" / "jules_next_task.yml"
RECONCILER_WORKFLOW = ROOT / "workflows" / "jules_unattended_monitor.yml"
OBSERVER_WORKFLOW = ROOT / "workflows" / "jules_session_observer.yml"
AUTOMERGE_WORKFLOW = ROOT / "workflows" / "jules_automerge.yml"
META_AUTOMERGE_WORKFLOW = ROOT / "workflows" / "automation_meta_automerge.yml"
BURST_WORKFLOW = ROOT / "workflows" / "jules_burst_monitor.yml"
ROUTER_WORKFLOW = ROOT / "workflows" / "jules_recovery_router.yml"
EXECUTOR = ROOT / "scripts" / "jules_task_executor.py"
PROMPT = ROOT / "prompts" / "jules_next_task_prompt.txt"


class JulesNextTaskWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.executor = EXECUTOR.read_text(encoding="utf-8")
        cls.prompt = PROMPT.read_text(encoding="utf-8")
        cls.observer = OBSERVER_WORKFLOW.read_text(encoding="utf-8")

    def test_executor_has_no_scheduler_or_recovery_wakeup(self) -> None:
        self.assertIn("workflow_dispatch:", self.text)
        self.assertNotIn("schedule:", self.text)
        self.assertNotIn("workflow_run:", self.text)
        self.assertNotIn("pull_request:", self.text)
        self.assertNotIn("select_agent_task.py", self.text)
        self.assertNotIn("automation_health.yml", self.text)

    def test_executor_requires_exact_task_and_durable_lease(self) -> None:
        self.assertIn("task_id:", self.text)
        self.assertIn("lease_key:", self.text)
        self.assertIn("--task-id", self.text)
        self.assertIn("--lease-key", self.text)
        self.assertIn("--state-branch automation-state-v2", self.text)
        self.assertIn("--ledger-path autonomy/ledger.json", self.text)

    def test_executor_is_trusted_master_only(self) -> None:
        self.assertIn("github.ref == 'refs/heads/master'", self.text)
        self.assertIn("      - uses: actions/checkout@v5\n        with:\n          ref: master", self.text)
        self.assertIn("contents: write", self.text)

    def test_executor_shares_the_single_mutation_domain(self) -> None:
        self.assertIn("group: notion-abuz-autonomy-mutation", self.text)
        self.assertIn("cancel-in-progress: false", self.text)
        reconciler = RECONCILER_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("group: notion-abuz-autonomy-mutation", reconciler)

    def test_executor_starts_one_bounded_observer_for_exact_session(self) -> None:
        self.assertIn("steps.execute.outputs.session_id", self.text)
        self.assertIn("gh workflow run jules_session_observer.yml", self.text)
        self.assertIn('-f session_id="${SESSION_ID}"', self.text)
        self.assertIn("actions: write", self.text)

    def test_observer_is_read_only_bounded_and_wakes_only_reconciler(self) -> None:
        self.assertIn("workflow_dispatch:", self.observer)
        self.assertNotIn("schedule:", self.observer)
        self.assertNotIn("workflow_run:", self.observer)
        self.assertIn("contents: read", self.observer)
        self.assertNotIn("contents: write", self.observer)
        self.assertIn("group: notion-abuz-jules-observer-${{ inputs.session_id }}", self.observer)
        self.assertIn("--max-watch-minutes 50", self.observer)
        self.assertIn("steps.observe.outputs.reason == 'watch_deadline'", self.observer)
        self.assertIn("gh workflow run jules_unattended_monitor.yml", self.observer)
        self.assertNotIn("gh workflow run jules_next_task.yml", self.observer)

    def test_executor_precommits_before_create_and_rejects_duplicates(self) -> None:
        precommit = self.executor.index('"state": "session_create_requested"')
        create = self.executor.index('api.jules(key, "sessions", method="POST"')
        self.assertLess(precommit, create)
        self.assertIn("refusing duplicate dispatch; active Jules sessions exist", self.executor)
        self.assertIn('"duplicate_dispatch_suppressed": True', self.executor)
        self.assertIn("existing_active_session_for_task", self.executor)
        self.assertIn("validate_lease", self.executor)

    def test_executor_recovers_failed_open_pr_in_place(self) -> None:
        self.assertIn("recovery_pr_number:", self.text)
        self.assertIn("recovery_pr_head:", self.text)
        self.assertIn("--recovery-pr-number", self.text)
        self.assertIn("head changed from", self.executor)
        self.assertIn("Do not create a new PR", self.executor)

    def test_prompt_is_repository_owned_and_forbids_manifest_recovery_followup(self) -> None:
        self.assertIn(".github/prompts/jules_next_task_prompt.txt", self.executor)
        self.assertIn("AUTONOMY_SCOPE_REQUEST", self.prompt)
        self.assertIn("AUTONOMY_DEFER_REQUEST", self.prompt)
        self.assertIn("verified_no_change", self.prompt)

    def test_project_automerge_wakes_reconciler_not_executor(self) -> None:
        text = AUTOMERGE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Wake authoritative reconciler after token-authenticated merge", text)
        self.assertIn("actions/workflows/jules_unattended_monitor.yml/dispatches", text)
        self.assertNotIn("actions/workflows/jules_next_task.yml/dispatches", text)
        self.assertNotIn("actions/workflows/jules_recovery_router.yml/dispatches", text)

    def test_meta_automerge_wakes_reconciler_not_executor(self) -> None:
        text = META_AUTOMERGE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Wake and verify authoritative reconciler after queue mutation", text)
        self.assertIn('workflow_path="jules_unattended_monitor.yml"', text)
        self.assertNotIn('workflow_path="jules_next_task.yml"', text)
        self.assertIn("No started workflow_dispatch run appeared", text)

    def test_retired_event_amplifiers_are_manual_and_read_only(self) -> None:
        for path in (BURST_WORKFLOW, ROUTER_WORKFLOW):
            text = path.read_text(encoding="utf-8")
            self.assertIn("workflow_dispatch:", text)
            self.assertNotIn("workflow_run:", text)
            self.assertNotIn("schedule:", text)
            self.assertNotIn("contents: write", text)
            self.assertNotIn("JULES_API_KEY", text)

    def test_risk_ceiling_supports_guarded_high_risk_opt_in(self) -> None:
        self.assertIn("          - high", self.text)
        self.assertIn("unguarded high-risk", self.prompt)
        self.assertIn("CI/smoke/artifact/self-hosted evidence", self.prompt)
        self.assertIn("rollback notes", self.prompt)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit tests for automation-health-report.py fixture mode."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("automation-health-report.py")
FIXTURE_ROOT = SCRIPT_PATH.parents[1] / "fixtures" / "automation-health"
SPEC = importlib.util.spec_from_file_location("automation_health_report", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
health = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = health
SPEC.loader.exec_module(health)


def run_fixture(name: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        output_json = Path(tmpdir) / "automation-health.json"
        output_md = Path(tmpdir) / "automation-health.md"
        github_output = Path(tmpdir) / "github-output.txt"
        with redirect_stdout(StringIO()):
            exit_code = health.main(
                [
                    "--fixture-dir",
                    str(FIXTURE_ROOT / name),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                    "--github-output",
                    str(github_output),
                ]
            )
        assert exit_code == 0
        report = json.loads(output_json.read_text(encoding="utf-8"))
        report["_markdown"] = output_md.read_text(encoding="utf-8")
        report["_github_output"] = github_output.read_text(encoding="utf-8")
        return report


def finding_codes(report: dict) -> set[str]:
    return {finding["code"] for finding in report.get("findings", [])}


class AutomationHealthReportTest(unittest.TestCase):
    def assert_has_finding(self, report: dict, code: str) -> None:
        self.assertIn(code, finding_codes(report))

    def test_healthy_report(self) -> None:
        report = run_fixture("healthy")

        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["findings"], [])
        self.assertFalse(report["pause_loop"])
        self.assertFalse(report["create_meta_task"])
        self.assertTrue(report["recovery_needed"])
        self.assertTrue(report["read_only"])
        self.assertIn("status=healthy", report["_github_output"])
        self.assertIn("recovery_needed=true", report["_github_output"])

    def test_degraded_quality_failure(self) -> None:
        report = run_fixture("degraded-quality-failure")

        self.assertEqual(report["status"], "degraded")
        self.assertTrue(report["create_meta_task"])
        self.assert_has_finding(report, "quality_failure")

    def test_merged_quality_fix_label_is_historical_not_current_failure(self) -> None:
        report = run_fixture("merged-quality-fix-label-ignored")

        self.assertEqual(report["status"], "healthy")
        self.assertFalse(report["create_meta_task"])
        self.assertEqual(report["metrics"]["autonomous_prs"]["labels"]["needs-quality-fix"], 1)
        self.assertEqual(report["metrics"]["autonomous_prs"]["unresolved_labels"]["needs-quality-fix"], 0)
        self.assertNotIn("quality_failure", finding_codes(report))

    def test_closed_unmerged_quality_labels_are_historical(self) -> None:
        data = health.read_fixture(FIXTURE_ROOT / "merged-quality-fix-label-ignored")
        pull = data["pulls"][0]
        pull["merged"] = False
        pull["merged_at"] = None
        pull["closed_at"] = "2026-06-28T10:30:00Z"

        report = health.analyze(data)

        self.assertEqual(
            report["metrics"]["autonomous_prs"]["unresolved_labels"]["needs-quality-fix"],
            0,
        )
        self.assertNotIn("quality_failure", finding_codes(report))

    def test_critical_duplicate_active_sessions(self) -> None:
        report = run_fixture("critical-duplicate-active-sessions")

        self.assertEqual(report["status"], "critical")
        self.assertFalse(report["pause_loop"])
        self.assert_has_finding(report, "duplicate_active_product_sessions")

    def test_active_product_session_does_not_request_idle_recovery(self) -> None:
        data = health.read_fixture(FIXTURE_ROOT / "healthy")
        data["jules_sessions"] = [
            {"id": "active-runtime", "state": "IN_PROGRESS", "task_id": "runtime-task"}
        ]

        report = health.analyze(data)

        self.assertEqual(report["metrics"]["jules_sessions"]["active_product_count"], 1)
        self.assertFalse(report["recovery_needed"])

    def test_recent_executor_run_owns_session_visibility_grace(self) -> None:
        data = health.read_fixture(FIXTURE_ROOT / "healthy")
        data["workflow_runs"].append(
            {
                "id": 1002,
                "name": "2. Execute Leased Jules Task",
                "status": "completed",
                "conclusion": "success",
                "updated_at": "2026-06-28T11:58:00Z",
            }
        )

        report = health.analyze(data)

        self.assertFalse(report["recovery_needed"])
        self.assertEqual(
            report["metrics"]["loop_ownership"]["recent_executor_run_ids"], [1002]
        )

    def test_stopped_control_plane_sessions_are_not_active_product(self) -> None:
        report = run_fixture("stopped-control-plane-sessions")

        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["metrics"]["jules_sessions"]["active_product_count"], 0)
        self.assertEqual(report["metrics"]["autonomous_prs"]["unresolved_labels"]["needs-quality-fix"], 1)
        self.assertNotIn("duplicate_active_product_sessions", finding_codes(report))
        self.assertNotIn("quality_failure", finding_codes(report))
        self.assertNotIn("repeated_followup_generation", finding_codes(report))

    def test_inactive_manifest_task_sessions_are_not_active_product(self) -> None:
        report = run_fixture("inactive-task-sessions")

        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["metrics"]["jules_sessions"]["active_product_count"], 0)
        self.assertNotIn("duplicate_active_product_sessions", finding_codes(report))

    def test_blocked_task_without_reason(self) -> None:
        report = run_fixture("blocked-without-reason")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "blocked_task_without_reason")

    def test_todo_below_minimum(self) -> None:
        report = run_fixture("todo-below-minimum")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "todo_below_minimum")

    def test_no_eligible_autonomous_task(self) -> None:
        report = run_fixture("no-eligible-autonomous-task")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "no_eligible_autonomous_task")
        self.assertEqual(report["metrics"]["tasks"]["todo_count"], 2)
        self.assertEqual(report["metrics"]["tasks"]["eligible_count"], 0)
        self.assertEqual(report["metrics"]["tasks"]["rejected_count"], 2)
        self.assertEqual(report["metrics"]["tasks"]["selector_reason_code"], "no_eligible_autonomous_task")
        self.assertIn("placeholder", report["findings"][0]["message"])
        self.assertIn("Eligible autonomous tasks", report["_markdown"])

    def test_high_risk_only_queue_reports_legacy_starvation(self) -> None:
        report = run_fixture("legacy-queue-starvation")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "legacy_queue_starvation")
        self.assertNotIn("no_eligible_autonomous_task", finding_codes(report))
        finding = report["findings"][0]
        self.assertIn("Only high-risk tasks remain", finding["message"])
        self.assertEqual(finding["evidence"]["risk_ceiling"], "medium")
        self.assertEqual(report["metrics"]["tasks"]["todo_count"], 2)
        self.assertEqual(report["metrics"]["tasks"]["eligible_count"], 0)
        self.assertEqual(report["metrics"]["tasks"]["selector_reason_code"], "no_eligible_autonomous_task")

    def test_missing_jules_api_key_is_not_a_failure(self) -> None:
        report = run_fixture("missing-jules-api-key")

        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["findings"], [])
        self.assertIn("jules_api", report["missing_sources"])

    def test_jules_api_unavailable_is_degraded(self) -> None:
        report = run_fixture("jules-api-unavailable")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "jules_api_unavailable")

    def test_suspicious_micro_test_pr(self) -> None:
        report = run_fixture("suspicious-micro-test-pr")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "suspicious_micro_test_pr")

    def test_multiple_open_autonomous_prs(self) -> None:
        report = run_fixture("multiple-open-autonomous-prs")

        self.assertEqual(report["status"], "critical")
        self.assert_has_finding(report, "duplicate_open_autonomous_prs")

    def test_tolerated_duplicate_open_autonomous_prs(self) -> None:
        report = run_fixture("tolerated-duplicate-open-autonomous-prs")

        self.assertEqual(report["status"], "healthy")

    def test_failed_sessions_for_same_task(self) -> None:
        report = run_fixture("failed-sessions-same-task")

        self.assertEqual(report["status"], "critical")
        self.assert_has_finding(report, "repeated_failed_sessions_same_task")

    def test_failed_session_history_for_done_task_is_not_actionable(self) -> None:
        data = health.read_fixture(FIXTURE_ROOT / "failed-sessions-same-task")
        data["manifest"]["tasks"][0]["status"] = "done"

        report = health.analyze(data)

        self.assertNotIn("repeated_failed_sessions_same_task", finding_codes(report))
        self.assertNotIn("failed_session", finding_codes(report))

    def test_stale_awaiting_user_feedback_after_continue(self) -> None:
        report = run_fixture("stale-awaiting-user-feedback")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "stale_awaiting_user_feedback_after_continue")
        self.assertEqual(report["metrics"]["jules_sessions"]["stale_waiting_after_continue_count"], 1)

    def test_master_ci_failed_is_critical(self) -> None:
        report = run_fixture("master-ci-failed")

        self.assertEqual(report["status"], "critical")
        self.assert_has_finding(report, "master_ci_failed")

    def test_github_api_partial_failure_is_degraded(self) -> None:
        report = run_fixture("github-api-partial-failure")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "github_api_partial_failure")

    def test_repeated_followup_generation_finding(self) -> None:
        report = run_fixture("repeated-followup-generation")

        self.assertEqual(report["status"], "degraded")
        self.assert_has_finding(report, "repeated_followup_generation")

    def test_repeated_followup_generation_fix_is_ignored(self) -> None:
        report = run_fixture("repeated-followup-generation-fix")

        self.assertEqual(report["status"], "healthy")
        self.assertNotIn("repeated_followup_generation", finding_codes(report))

    def test_malformed_pr_metadata(self) -> None:
        report = run_fixture("malformed-pr-metadata")

        self.assertEqual(report["status"], "healthy")

    def test_health_workflow_has_deduplicated_idle_recovery(self) -> None:
        workflow = (SCRIPT_PATH.parents[1] / "workflows" / "automation_health.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('recovery_needed: ${{ steps.health.outputs.recovery_needed }}', workflow)
        self.assertIn("recover-idle-loop:", workflow)
        self.assertIn("jules_unattended_monitor.yml/runs?per_page=20", workflow)
        self.assertIn("jules_next_task.yml/runs?per_page=20", workflow)
        self.assertIn("reconciler or task executor run already owns recovery", workflow)
        self.assertIn("jules_unattended_monitor.yml/dispatches", workflow)


if __name__ == "__main__":
    unittest.main()

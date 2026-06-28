"""Unit tests for validate_agent_tasks.py."""

from __future__ import annotations

import unittest

import validate_agent_tasks


def base_manifest(task: dict) -> dict:
    return {
        "schema_version": 1,
        "project": "notion-abuz_ai",
        "task_source_priority": ["agent_tasks.json"],
        "risk_levels": ["low", "medium", "high", "critical"],
        "merge_policy": {
            "low": "auto_merge_after_ci",
            "medium": "auto_merge_after_ci",
            "high": "human_review_required",
            "critical": "manual_only",
        },
        "replenishment_policy": {
            "minimum_todo_tasks": 1,
            "batch_size": 1,
            "max_todo_tasks": 10,
            "allowed_risks_for_generated_tasks": ["low", "medium"],
            "instruction": "Keep useful tasks queued.",
        },
        "autonomous_loop_policy": {
            "operating_model": "docs/jules_autonomous_loop.md",
            "selection_rule": "Select useful work.",
            "anti_stall_rule": "Do not stall.",
            "max_pr_scope": "one task id per PR",
            "failure_rule": "Fix own failures.",
        },
        "tasks": [task],
    }


def task(*, status: str, blocked_reason: str | None = None) -> dict:
    result = {
        "id": "example-task",
        "status": status,
        "area": "proxy",
        "risk": "low",
        "title": "Example task",
        "description": "Example task description.",
        "allowed_paths": ["agent_tasks.json"],
        "acceptance": ["Acceptance criterion."],
    }
    if blocked_reason is not None:
        result["blocked_reason"] = blocked_reason
    return result


class ValidateAgentTasksTest(unittest.TestCase):
    def test_blocked_task_without_reason_warns(self) -> None:
        warnings = validate_agent_tasks.validate_manifest(base_manifest(task(status="blocked")))

        self.assertIn("blocked task example-task is missing blocked_reason", warnings)

    def test_blocked_task_with_reason_does_not_warn(self) -> None:
        warnings = validate_agent_tasks.validate_manifest(
            base_manifest(task(status="blocked", blocked_reason="Waiting for concrete evidence."))
        )

        self.assertNotIn("blocked task example-task is missing blocked_reason", warnings)


if __name__ == "__main__":
    unittest.main()

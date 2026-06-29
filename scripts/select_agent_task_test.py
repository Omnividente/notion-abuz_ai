"""Unit tests for scripts/select_agent_task.py."""

from __future__ import annotations

import unittest

import select_agent_task


def task(task_id: str, *, title: str, description: str, risk: str, allowed_paths: list[str]) -> dict:
    return {
        "id": task_id,
        "status": "todo",
        "area": "proxy",
        "risk": risk,
        "title": title,
        "description": description,
        "allowed_paths": allowed_paths,
        "acceptance": ["acceptance"],
    }


class SelectAgentTaskTest(unittest.TestCase):
    def test_exact_task_id_overrides_micro_filter(self) -> None:
        data = {
            "tasks": [
                task(
                    "micro",
                    title="Add tests for HandleFrame missing metadata",
                    description="One parser edge case.",
                    risk="low",
                    allowed_paths=["internal/proxy/anthropic_test.go", "agent_tasks.json"],
                )
            ]
        }

        selected = select_agent_task.select_task(
            data,
            risk_ceiling="medium",
            focus="proxy",
            task_id="micro",
        )

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "micro")
        self.assertEqual(selected.reason, "exact task id requested")

    def test_runtime_task_beats_evidence_backed_test_only_task(self) -> None:
        data = {
            "tasks": [
                task(
                    "test-only",
                    title="Add test coverage for CI failure",
                    description="CI failure reproduced in PR #123.",
                    risk="low",
                    allowed_paths=["internal/proxy/anthropic_test.go", "agent_tasks.json"],
                ),
                task(
                    "runtime",
                    title="Implement runtime fix from live smoke failure",
                    description="Use local live smoke artifact to fix reproduced runtime failure.",
                    risk="medium",
                    allowed_paths=[
                        "internal/proxy/anthropic.go",
                        "internal/proxy/anthropic_test.go",
                        "docs/claude-code-integration.md",
                        "agent_tasks.json",
                    ],
                ),
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "runtime")
        self.assertEqual(selected.reason_code, "selected")
        self.assertEqual(selected.todo_count, 2)
        self.assertEqual(selected.eligible_count, 2)
        self.assertEqual(selected.rejected_count, 0)

    def test_test_only_without_evidence_is_rejected(self) -> None:
        data = {
            "tasks": [
                task(
                    "micro",
                    title="Add tests for Anthropic HandleFrame missing metadata",
                    description="Ensure parser handles missing metadata.",
                    risk="low",
                    allowed_paths=["internal/proxy/anthropic_test.go", "agent_tasks.json"],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertFalse(selected.selected)
        self.assertEqual(selected.rejected[0]["task_id"], "micro")
        self.assertEqual(selected.reason_code, "no_eligible_autonomous_task")
        self.assertEqual(selected.todo_count, 1)
        self.assertEqual(selected.eligible_count, 0)
        self.assertEqual(selected.rejected_count, 1)

    def test_test_only_with_evidence_is_allowed(self) -> None:
        data = {
            "tasks": [
                task(
                    "evidence-test",
                    title="Add test coverage for CI failure",
                    description="Reproduced CI failure in PR #456.",
                    risk="low",
                    allowed_paths=["internal/proxy/anthropic_test.go", "agent_tasks.json"],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "evidence-test")

    def test_no_eligible_task_returns_empty_selection(self) -> None:
        data = {
            "tasks": [
                task(
                    "high-risk",
                    title="Runtime task",
                    description="Runtime failure.",
                    risk="high",
                    allowed_paths=["internal/proxy/anthropic.go", "agent_tasks.json"],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertFalse(selected.selected)
        self.assertEqual(selected.reason, "no eligible todo task matched the risk ceiling and micro-task policy")
        self.assertEqual(selected.reason_code, "no_eligible_autonomous_task")
        self.assertEqual(selected.todo_count, 1)
        self.assertEqual(selected.eligible_count, 0)
        self.assertEqual(selected.rejected_count, 0)

    def test_no_todo_tasks_has_distinct_reason_code(self) -> None:
        data = {
            "tasks": [
                {
                    **task(
                        "done-task",
                        title="Runtime task",
                        description="Runtime failure.",
                        risk="medium",
                        allowed_paths=["internal/proxy/anthropic.go", "agent_tasks.json"],
                    ),
                    "status": "done",
                }
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertFalse(selected.selected)
        self.assertEqual(selected.reason_code, "no_todo_tasks")
        self.assertEqual(selected.todo_count, 0)
        self.assertEqual(selected.eligible_count, 0)
        self.assertEqual(selected.rejected_count, 0)


if __name__ == "__main__":
    unittest.main()

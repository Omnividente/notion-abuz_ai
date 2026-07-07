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

    def test_focus_area_can_beat_generic_runtime_task(self) -> None:
        automation_task = task(
            "failed-check-context",
            title="Include failed check job log context in recovery router",
            description="Use failed check artifacts and job log details URL to recover a stuck Jules session.",
            risk="low",
            allowed_paths=[
                ".github/scripts/jules-recovery-router.py",
                ".github/scripts/jules-recovery-router-test.py",
                "agent_tasks.json",
            ],
        )
        automation_task["area"] = "automation"
        data = {
            "tasks": [
                task(
                    "runtime",
                    title="Implement runtime fix from reproduced failure",
                    description="Use offline reproduction to fix a runtime bridge failure.",
                    risk="medium",
                    allowed_paths=[
                        "internal/proxy/anthropic.go",
                        "internal/proxy/anthropic_test.go",
                        "agent_tasks.json",
                    ],
                ),
                automation_task,
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="automation")

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "failed-check-context")
        self.assertIn("focus area match", selected.reason)

    def test_excluded_task_id_selects_next_candidate(self) -> None:
        data = {
            "tasks": [
                task(
                    "runtime",
                    title="Implement runtime fix from live smoke failure",
                    description="Use local live smoke artifact to fix reproduced runtime failure.",
                    risk="medium",
                    allowed_paths=[
                        "internal/proxy/anthropic.go",
                        "internal/proxy/anthropic_test.go",
                        "agent_tasks.json",
                    ],
                ),
                task(
                    "fallback",
                    title="Implement fallback fix from CI failure",
                    description="CI failure reproduced in PR #789.",
                    risk="medium",
                    allowed_paths=["internal/proxy/openai.go", "agent_tasks.json"],
                ),
            ]
        }

        selected = select_agent_task.select_task(
            data,
            risk_ceiling="medium",
            focus="proxy",
            exclude_task_ids={"runtime"},
        )

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "fallback")
        self.assertEqual(selected.rejected[0]["task_id"], "runtime")
        self.assertIn("stopped autonomous PR", selected.rejected[0]["reason"])

    def test_exact_task_id_respects_exclusion(self) -> None:
        data = {
            "tasks": [
                task(
                    "runtime",
                    title="Implement runtime fix from live smoke failure",
                    description="Use local live smoke artifact to fix reproduced runtime failure.",
                    risk="medium",
                    allowed_paths=["internal/proxy/anthropic.go", "agent_tasks.json"],
                )
            ]
        }

        with self.assertRaisesRegex(ValueError, "is excluded"):
            select_agent_task.select_task(
                data,
                risk_ceiling="medium",
                focus="proxy",
                task_id="runtime",
                exclude_task_ids={"runtime"},
            )

    def test_exact_task_id_rejects_placeholder_replenishment_task(self) -> None:
        data = {
            "tasks": [
                task(
                    "test-dummy-task-replenishment",
                    title="Dummy replenishment task",
                    description="Ensure the required minimum tasks are available.",
                    risk="low",
                    allowed_paths=["agent_tasks.json"],
                )
            ]
        }

        with self.assertRaisesRegex(ValueError, "placeholder replenishment task"):
            select_agent_task.select_task(
                data,
                risk_ceiling="medium",
                focus="proxy",
                task_id="test-dummy-task-replenishment",
            )

    def test_placeholder_replenishment_task_is_rejected_and_next_task_selected(self) -> None:
        data = {
            "tasks": [
                task(
                    "test-dummy-task-replenishment",
                    title="Dummy replenishment task",
                    description="Ensure the required minimum tasks are available.",
                    risk="low",
                    allowed_paths=["agent_tasks.json"],
                ),
                task(
                    "runtime",
                    title="Implement runtime fix from live smoke failure",
                    description="Use local live smoke artifact to fix reproduced runtime failure.",
                    risk="medium",
                    allowed_paths=[
                        "internal/proxy/anthropic.go",
                        "internal/proxy/anthropic_test.go",
                        "agent_tasks.json",
                    ],
                ),
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "runtime")
        self.assertEqual(selected.rejected[0]["task_id"], "test-dummy-task-replenishment")
        self.assertIn("placeholder", selected.rejected[0]["reason"])

    def test_runtime_quota_task_is_not_treated_as_placeholder(self) -> None:
        data = {
            "tasks": [
                task(
                    "runtime-quota",
                    title="Fix quota retry runtime failure",
                    description="Reproduced runtime failure in PR #456 when quota retry loses tool-call mode.",
                    risk="medium",
                    allowed_paths=["internal/proxy/session.go", "agent_tasks.json"],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "runtime-quota")

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

    def test_narrow_runtime_metric_boundary_without_evidence_is_rejected(self) -> None:
        data = {
            "tasks": [
                task(
                    "runtime-boundary",
                    title="Validate system prompt truncation metrics for Unicode",
                    description=(
                        "Add boundary tests for exactly 1200 runes and verify the metric is emitted."
                    ),
                    risk="medium",
                    allowed_paths=[
                        "internal/proxy/session.go",
                        "internal/proxy/session_test.go",
                        "agent_tasks.json",
                    ],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertFalse(selected.selected)
        self.assertEqual(selected.rejected[0]["task_id"], "runtime-boundary")
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

    def test_narrow_runtime_metric_boundary_with_evidence_is_allowed(self) -> None:
        data = {
            "tasks": [
                task(
                    "runtime-boundary",
                    title="Fix truncation metric boundary from CI failure",
                    description="Reproduced CI failure in PR #456 for Unicode truncation metrics.",
                    risk="medium",
                    allowed_paths=[
                        "internal/proxy/session.go",
                        "internal/proxy/session_test.go",
                        "agent_tasks.json",
                    ],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="medium", focus="proxy")

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "runtime-boundary")

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
        self.assertEqual(
            selected.reason,
            "no eligible todo task matched the risk ceiling, high-risk evidence guard, placeholder, and micro-task policy",
        )
        self.assertEqual(selected.reason_code, "no_eligible_autonomous_task")
        self.assertEqual(selected.todo_count, 1)
        self.assertEqual(selected.eligible_count, 0)
        self.assertEqual(selected.rejected_count, 0)

    def test_high_ceiling_selects_guarded_legacy_smoke_task(self) -> None:
        data = {
            "tasks": [
                task(
                    "guarded-high",
                    title="Enable legacy compatibility smoke for offline lab runners",
                    description=(
                        "High-risk workflow change is bounded by legacy compatibility smoke, "
                        "self-hosted CentOS runner labels, artifacts, and rollback notes."
                    ),
                    risk="high",
                    allowed_paths=[
                        ".github/workflows/legacy_compat_smoke.yml",
                        ".github/scripts/legacy-smoke-auto-dispatch.py",
                        "agent_tasks.json",
                    ],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="high", focus="automation")

        self.assertTrue(selected.selected)
        self.assertEqual(selected.task_id, "guarded-high")
        self.assertIn("guarded high-risk", selected.reason)
        self.assertEqual(selected.rejected_count, 0)

    def test_high_ceiling_rejects_unguarded_high_task(self) -> None:
        data = {
            "tasks": [
                task(
                    "unguarded-high",
                    title="Rewrite proxy routing",
                    description="Large high-risk network rewrite.",
                    risk="high",
                    allowed_paths=["internal/proxy/reverseproxy.go", "agent_tasks.json"],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="high", focus="proxy")

        self.assertFalse(selected.selected)
        self.assertEqual(selected.reason_code, "no_eligible_autonomous_task")
        self.assertEqual(selected.rejected_count, 1)
        self.assertIn("high-risk task", selected.rejected[0]["reason"])

    def test_high_ceiling_rejects_high_task_with_forbidden_path(self) -> None:
        data = {
            "tasks": [
                task(
                    "forbidden-high",
                    title="Enable legacy compatibility smoke",
                    description="High-risk task with legacy compatibility smoke and rollback evidence.",
                    risk="high",
                    allowed_paths=["production/accounts.json", "agent_tasks.json"],
                )
            ]
        }

        selected = select_agent_task.select_task(data, risk_ceiling="high", focus="proxy")

        self.assertFalse(selected.selected)
        self.assertEqual(selected.rejected_count, 1)
        self.assertIn("high-risk task", selected.rejected[0]["reason"])

    def test_exact_high_task_id_requires_guard(self) -> None:
        data = {
            "tasks": [
                task(
                    "unguarded-high",
                    title="Rewrite proxy routing",
                    description="Large high-risk network rewrite.",
                    risk="high",
                    allowed_paths=["internal/proxy/reverseproxy.go", "agent_tasks.json"],
                )
            ]
        }

        with self.assertRaisesRegex(ValueError, "high risk without required legacy/lab evidence guard"):
            select_agent_task.select_task(
                data,
                risk_ceiling="high",
                focus="proxy",
                task_id="unguarded-high",
            )

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

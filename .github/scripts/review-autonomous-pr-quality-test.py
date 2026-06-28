#!/usr/bin/env python3
"""Unit tests for review-autonomous-pr-quality.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("review-autonomous-pr-quality.py")
SPEC = importlib.util.spec_from_file_location("review_autonomous_pr_quality", SCRIPT_PATH)
assert SPEC is not None
quality = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = quality
SPEC.loader.exec_module(quality)


def task(
    task_id: str,
    *,
    status: str,
    title: str = "Ensure workspace reframing events are logged as bridge decisions",
    description: str = "Verify and test that workspace reframing is explicitly emitted as a bridge decision log.",
    allowed_paths: list[str] | None = None,
    acceptance: list[str] | None = None,
    blocked_reason: str | None = None,
) -> dict:
    result = {
        "id": task_id,
        "status": status,
        "area": "proxy",
        "risk": "low",
        "title": title,
        "description": description,
        "allowed_paths": allowed_paths
        or ["internal/proxy/anthropic_bridge_test.go", "internal/proxy/anthropic.go", "agent_tasks.json"],
        "acceptance": acceptance
        or [
            "Bridge decision logging includes workspace reframing explicitly.",
            "Tests cover the new or existing observability path for this signal.",
        ],
    }
    if blocked_reason is not None:
        result["blocked_reason"] = blocked_reason
    return result


def manifest(tasks: list[dict]) -> dict:
    return {"tasks": tasks}


class ReviewAutonomousPRQualityTest(unittest.TestCase):
    def evaluate(
        self,
        before: dict,
        after: dict,
        *,
        changed_files: list[str],
        diff_text: str = "",
        pr_title: str = "",
        pr_body: str = "",
        numstat: dict[str, tuple[int, int]] | None = None,
    ):
        return quality.evaluate_quality(
            before_manifest=before,
            after_manifest=after,
            changed_files=changed_files,
            diff_text=diff_text,
            numstat=numstat or {path: (10, 0) for path in changed_files},
            pr_title=pr_title,
            pr_body=pr_body,
        )

    def test_blocks_116_style_test_only_observability_completion(self) -> None:
        before = manifest([task("proxy-observability-workspace-reframing-4964e353", status="todo")])
        after = manifest(
            [
                task("proxy-observability-workspace-reframing-4964e353", status="done"),
                task(
                    "proxy-observability-notion-persona-leakage-4964e354",
                    status="todo",
                    title="Ensure Notion persona leakage events are logged as bridge decisions",
                ),
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/anthropic_bridge_test.go", "agent_tasks.json"],
            diff_text="+ {name: \"JSON block\", output: \"```json ... workspace ...```\"}",
            pr_body="Тесты добавлены. Runtime logging требует сложного мокинга, вместо этого добавлен follow-up.",
        )

        self.assertFalse(decision.passed)
        self.assertIn("proxy-observability-workspace-reframing-4964e353", decision.task_ids)
        self.assertTrue(any("changed only tests" in reason for reason in decision.reasons))
        self.assertTrue(any("follow-up" in reason.lower() for reason in decision.reasons))

    def test_runtime_change_for_operational_task_passes(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/anthropic.go", "internal/proxy/anthropic_bridge_test.go", "agent_tasks.json"],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body="Acceptance: runtime bridge decision logging and regression test were updated.",
        )

        self.assertTrue(decision.passed)
        self.assertEqual(decision.recommendation, "Autonomous PR quality gate passed.")

    def test_test_only_task_without_operational_claim_passes(self) -> None:
        before = manifest(
            [
                task(
                    "parser-test",
                    status="todo",
                    title="Add parser edge-case tests",
                    description="Add focused offline tests for parser behavior.",
                    allowed_paths=["internal/proxy/tools_test.go", "agent_tasks.json"],
                    acceptance=["Tests cover the parser edge case."],
                )
            ]
        )
        after = manifest(
            [
                task(
                    "parser-test",
                    status="done",
                    title="Add parser edge-case tests",
                    description="Add focused offline tests for parser behavior.",
                    allowed_paths=["internal/proxy/tools_test.go", "agent_tasks.json"],
                    acceptance=["Tests cover the parser edge case."],
                )
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/tools_test.go", "agent_tasks.json"],
            diff_text="+ t.Run(\"parser edge case\", func(t *testing.T) {})",
        )

        self.assertTrue(decision.passed)

    def test_manifest_only_block_with_reason_passes(self) -> None:
        before = manifest([task("blocked-task", status="todo")])
        after = manifest(
            [
                task(
                    "blocked-task",
                    status="blocked",
                    blocked_reason="Paused after repeated Jules FAILED sessions.",
                )
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=["agent_tasks.json"],
            diff_text='+ "status": "blocked"',
        )

        self.assertTrue(decision.passed)
        self.assertEqual(decision.blocked_task_ids, ["blocked-task"])

    def test_manifest_only_block_without_reason_fails(self) -> None:
        before = manifest([task("blocked-task", status="todo")])
        after = manifest([task("blocked-task", status="blocked")])

        decision = self.evaluate(
            before,
            after,
            changed_files=["agent_tasks.json"],
            diff_text='+ "status": "blocked"',
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("without blocked_reason" in reason for reason in decision.reasons))

    def test_no_task_state_update_fails(self) -> None:
        before = manifest([task("unchanged-task", status="todo")])
        after = manifest([task("unchanged-task", status="todo")])

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/anthropic.go"],
            diff_text="+ runtime change",
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("no durable task state update" in reason.lower() for reason in decision.reasons))


if __name__ == "__main__":
    unittest.main()

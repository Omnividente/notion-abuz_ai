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
    risk: str = "low",
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
        "risk": risk,
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


def evidence_body(
    task_id: str,
    *,
    status: str = "done",
    acceptance: list[str] | None = None,
    evidence_files: list[str] | None = None,
    checks: list[str] | None = None,
    blocked_reason: str = "",
    micro_pr_justification: str = "Runtime and test changes are grouped under the same task.",
) -> str:
    acceptance = acceptance or [
        "Bridge decision logging includes workspace reframing explicitly -> internal/proxy/anthropic.go",
        "Tests cover the observability path -> internal/proxy/anthropic_bridge_test.go",
    ]
    evidence_files = evidence_files or [
        "internal/proxy/anthropic.go",
        "internal/proxy/anthropic_bridge_test.go",
        "agent_tasks.json",
    ]
    checks = checks or [
        "python3 scripts/validate_agent_tasks.py agent_tasks.json",
        "go test ./...",
    ]
    lines = [
        "<!-- AUTONOMOUS_TASK_EVIDENCE",
        f"task_id: {task_id}",
        f"status: {status}",
    ]
    if blocked_reason:
        lines.append(f"blocked_reason: {blocked_reason}")
    lines.append("acceptance:")
    lines.extend(f"- {item}" for item in acceptance)
    lines.append("evidence_files:")
    lines.extend(f"- {item}" for item in evidence_files)
    lines.append("checks:")
    lines.extend(f"- {item}" for item in checks)
    if micro_pr_justification:
        lines.append(f"micro_pr_justification: {micro_pr_justification}")
    lines.append("-->")
    return "\n".join(lines)


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
        allow_evidence_autofill: bool = False,
        scope_ledger: dict | None = None,
    ):
        return quality.evaluate_quality(
            before_manifest=before,
            after_manifest=after,
            changed_files=changed_files,
            diff_text=diff_text,
            numstat=numstat or {path: (10, 0) for path in changed_files},
            pr_title=pr_title,
            pr_body=pr_body,
            allow_evidence_autofill=allow_evidence_autofill,
            scope_ledger=scope_ledger,
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
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body("runtime-fix"),
        )

        self.assertTrue(decision.passed)
        self.assertEqual(decision.recommendation, "Autonomous PR quality gate passed.")
        self.assertTrue(decision.evidence["present"])

    def test_glob_allowed_paths_cover_runtime_and_tests(self) -> None:
        before_task = task(
            "runtime-fix",
            status="todo",
            allowed_paths=["internal/proxy/*.go", "agent_tasks.json"],
        )
        after_task = task(
            "runtime-fix",
            status="done",
            allowed_paths=["internal/proxy/*.go", "agent_tasks.json"],
        )

        decision = self.evaluate(
            manifest([before_task]),
            manifest([after_task]),
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body("runtime-fix"),
        )

        self.assertTrue(decision.passed)

    def test_file_outside_task_allowed_paths_fails(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])
        changed_files = [
            "internal/proxy/anthropic.go",
            ".github/scripts/jules_recovery_prompt.py",
            "agent_tasks.json",
        ]

        decision = self.evaluate(
            before,
            after,
            changed_files=changed_files,
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body(
                "runtime-fix",
                evidence_files=changed_files,
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(
            any(
                "outside task runtime-fix allowed_paths" in reason
                and ".github/scripts/jules_recovery_prompt.py" in reason
                for reason in decision.reasons
            )
        )

    def test_pr_cannot_self_expand_allowed_paths(self) -> None:
        before_task = task(
            "runtime-fix",
            status="todo",
            allowed_paths=["internal/proxy/*.go", "agent_tasks.json"],
        )
        after_task = task(
            "runtime-fix",
            status="done",
            allowed_paths=[
                "internal/proxy/*.go",
                ".github/scripts/*.py",
                "agent_tasks.json",
            ],
        )
        changed_files = [
            "internal/proxy/anthropic.go",
            ".github/scripts/jules_recovery_prompt.py",
            "agent_tasks.json",
        ]

        decision = self.evaluate(
            manifest([before_task]),
            manifest([after_task]),
            changed_files=changed_files,
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body(
                "runtime-fix",
                evidence_files=changed_files,
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("outside task runtime-fix allowed_paths" in reason for reason in decision.reasons))

    def test_reconciler_approved_scope_expansion_passes_read_only_gate(self) -> None:
        before_task = task(
            "runtime-fix",
            status="todo",
            allowed_paths=["internal/proxy/anthropic.go", "agent_tasks.json"],
        )
        expanded = [
            "internal/proxy/anthropic.go",
            "internal/proxy/anthropic_bridge_test.go",
            "agent_tasks.json",
        ]
        after_task = task("runtime-fix", status="done", allowed_paths=expanded)
        ledger = {
            "tasks": {
                "runtime-fix": {
                    "scope_decision": "approved_same_task",
                    "scope_override": expanded,
                    "scope_risk": "medium",
                    "scope_evidence": "reproduced failure requires a regression fixture",
                    "scope_approved_at": "2026-07-13T18:30:00Z",
                    "scope_task_fingerprint": quality.scope_task_fingerprint(before_task),
                }
            }
        }
        decision = self.evaluate(
            manifest([before_task]),
            manifest([after_task]),
            changed_files=expanded,
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body("runtime-fix", evidence_files=expanded),
            scope_ledger=ledger,
        )

        self.assertTrue(decision.passed)
        self.assertTrue(any("Applied durable scope approval" in warning for warning in decision.warnings))

    def test_stale_scope_approval_cannot_authorize_expansion(self) -> None:
        before_task = task(
            "runtime-fix",
            status="todo",
            allowed_paths=["internal/proxy/anthropic.go", "agent_tasks.json"],
        )
        expanded = [
            "internal/proxy/anthropic.go",
            "internal/proxy/anthropic_bridge_test.go",
            "agent_tasks.json",
        ]
        ledger = {
            "tasks": {
                "runtime-fix": {
                    "scope_decision": "approved_same_task",
                    "scope_override": expanded,
                    "scope_risk": "medium",
                    "scope_evidence": "old evidence",
                    "scope_approved_at": "2026-07-13T18:30:00Z",
                    "scope_task_fingerprint": "stale-fingerprint",
                }
            }
        }
        decision = self.evaluate(
            manifest([before_task]),
            manifest([task("runtime-fix", status="done", allowed_paths=expanded)]),
            changed_files=expanded,
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body("runtime-fix", evidence_files=expanded),
            scope_ledger=ledger,
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("outside task runtime-fix allowed_paths" in reason for reason in decision.reasons))
        self.assertTrue(any("Ignored durable scope approval" in warning for warning in decision.warnings))

    def test_followup_code_identifiers_do_not_trigger_repeated_followup_failure(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        body = "\n".join(
            [
                "Implemented context preservation in `buildSessionChainFollowUp`.",
                "Added `TestBuildSessionChainFollowUp_DiffContextPreservation`.",
                evidence_body("runtime-fix"),
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=body,
        )

        self.assertTrue(decision.passed)
        self.assertFalse(any("follow-up tasks" in reason for reason in decision.reasons))

    def test_followup_task_ids_do_not_trigger_repeated_followup_failure(self) -> None:
        task_id = "proxy-observability-json-tool-call-mode-loss-diagnostics-followup"
        before = manifest([task(task_id, status="todo")])
        after = manifest([task(task_id, status="done")])

        body = "\n".join(
            [
                evidence_body(task_id),
                f"### Task {task_id}",
                "Completed the requested runtime diagnostic logging and tests.",
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=body,
        )

        self.assertTrue(decision.passed)
        self.assertFalse(any("follow-up tasks" in reason for reason in decision.reasons))

    def test_followup_terms_inside_evidence_acceptance_do_not_trigger_repeated_followup_failure(self) -> None:
        task_id = "automation-replenishment-after-recovery-block"
        acceptance = [
            "Blocking a failed Jules task cannot leave todo_count below the manifest replenishment minimum without a concrete follow-up path.",
            "A focused offline test covers a block operation when todo_count would fall below minimum.",
            "Generated follow-up tasks must be evidence-backed and must not be placeholder tasks.",
        ]
        before = manifest(
            [
                task(
                    task_id,
                    status="todo",
                    title="Replenish safe work after recovery block PRs",
                    description="Keep the autonomous task queue replenished after failed session block PRs.",
                    allowed_paths=[
                        ".github/scripts/block-failed-agent-task.py",
                        ".github/scripts/block-failed-agent-task-test.py",
                        "agent_tasks.json",
                    ],
                    acceptance=acceptance,
                )
            ]
        )
        after = manifest(
            [
                task(
                    task_id,
                    status="done",
                    title="Replenish safe work after recovery block PRs",
                    description="Keep the autonomous task queue replenished after failed session block PRs.",
                    allowed_paths=[
                        ".github/scripts/block-failed-agent-task.py",
                        ".github/scripts/block-failed-agent-task-test.py",
                        "agent_tasks.json",
                    ],
                    acceptance=acceptance,
                )
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                ".github/scripts/block-failed-agent-task.py",
                ".github/scripts/block-failed-agent-task-test.py",
                "agent_tasks.json",
            ],
            pr_body=evidence_body(
                task_id,
                acceptance=[
                    f"{item} -> .github/scripts/block-failed-agent-task.py"
                    for item in acceptance
                ],
                evidence_files=[
                    ".github/scripts/block-failed-agent-task.py",
                    ".github/scripts/block-failed-agent-task-test.py",
                    "agent_tasks.json",
                ],
                checks=[
                    "pytest .github/scripts/block-failed-agent-task-test.py",
                    "python3 scripts/validate_agent_tasks.py agent_tasks.json",
                ],
                micro_pr_justification=(
                    "The PR provides a complete functional solution solving the "
                    "blocked PR missing task generation issue."
                ),
            ),
        )

        self.assertTrue(decision.passed)
        self.assertFalse(any("follow-up tasks" in reason for reason in decision.reasons))

    def test_repeated_followup_prose_still_fails(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        body = "\n".join(
            [
                "The runtime change is included, but one follow-up remains for logs.",
                "A second followup will handle remaining diagnostics.",
                evidence_body("runtime-fix"),
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=body,
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("follow-up tasks" in reason for reason in decision.reasons))

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
            pr_body=evidence_body(
                "parser-test",
                acceptance=["Tests cover the parser edge case -> internal/proxy/tools_test.go"],
                evidence_files=["internal/proxy/tools_test.go", "agent_tasks.json"],
                micro_pr_justification="This task is explicitly scoped to focused offline parser tests.",
            ),
        )

        self.assertTrue(decision.passed)

    def test_explicit_logging_test_task_passes_test_only_diff(self) -> None:
        test_task = task(
            "proxy-tools-add-unit-tests-for-debug-logging-toggle",
            status="todo",
            title="Add unit tests to verify tools.go debug logging obeys DebugLoggingEnabled",
            description=(
                "Add targeted tests asserting that the proxy mutes these logs "
                "when DebugLoggingEnabled returns false."
            ),
            allowed_paths=["internal/proxy/tools_test.go", "agent_tasks.json"],
            acceptance=[
                "A unit test verifies tool schema simplification logs are muted.",
                "A unit test verifies JSON tool-call fallback logs are muted.",
            ],
        )
        done_task = {**test_task, "status": "done"}
        decision = self.evaluate(
            manifest([test_task]),
            manifest([done_task]),
            changed_files=["internal/proxy/tools_test.go", "agent_tasks.json"],
            diff_text=(
                "+ var buf bytes.Buffer\n"
                "+ log.SetOutput(globalLogWriter)\n"
                "+ if strings.Contains(buf.String(), expectedLog) { t.Fatal() }"
            ),
            pr_body=evidence_body(
                test_task["id"],
                acceptance=[
                    "Muted schema logs -> internal/proxy/tools_test.go",
                    "Muted fallback logs -> internal/proxy/tools_test.go",
                ],
                evidence_files=["internal/proxy/tools_test.go", "agent_tasks.json"],
                micro_pr_justification="The manifest contract is explicitly test-only.",
            ),
        )

        self.assertTrue(quality.is_operational_task(done_task))
        self.assertTrue(quality.is_explicit_test_only_task(done_task))
        self.assertTrue(decision.passed, decision.reasons)

    def test_test_only_scope_does_not_excuse_runtime_acceptance(self) -> None:
        runtime_task = task(
            "logging-runtime-fix",
            status="todo",
            title="Fix runtime logging and add tests",
            description="Change runtime logging behavior and cover it with tests.",
            allowed_paths=["internal/proxy/tools_test.go", "agent_tasks.json"],
            acceptance=[
                "Runtime logging is muted when debug mode is disabled.",
                "A unit test covers the logging behavior.",
            ],
        )
        decision = self.evaluate(
            manifest([runtime_task]),
            manifest([{**runtime_task, "status": "done"}]),
            changed_files=["internal/proxy/tools_test.go", "agent_tasks.json"],
            diff_text="+ func TestMutedLogging(t *testing.T) {}",
            pr_body=evidence_body(
                runtime_task["id"],
                acceptance=[
                    "Runtime logging -> internal/proxy/tools_test.go",
                    "Test coverage -> internal/proxy/tools_test.go",
                ],
                evidence_files=["internal/proxy/tools_test.go", "agent_tasks.json"],
            ),
        )

        self.assertFalse(quality.is_explicit_test_only_task(runtime_task))
        self.assertFalse(decision.passed)
        self.assertTrue(any("changed only tests" in reason for reason in decision.reasons))

    def test_temporary_scratch_markdown_file_fails(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
                "plan.md",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body(
                "runtime-fix",
                evidence_files=[
                    "internal/proxy/anthropic.go",
                    "internal/proxy/anthropic_bridge_test.go",
                    "agent_tasks.json",
                    "plan.md",
                ],
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("scratch/planning files" in reason for reason in decision.reasons))

    def test_generated_python_bytecode_file_fails(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
                ".github/scripts/__pycache__/filter-active-jules-sessions.cpython-312.pyc",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body(
                "runtime-fix",
                evidence_files=[
                    "internal/proxy/anthropic.go",
                    "internal/proxy/anthropic_bridge_test.go",
                    "agent_tasks.json",
                    ".github/scripts/__pycache__/filter-active-jules-sessions.cpython-312.pyc",
                ],
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("generated cache/bytecode" in reason for reason in decision.reasons))

    def test_pr_body_scratch_artifact_fails(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
                "pr_body.txt",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body(
                "runtime-fix",
                evidence_files=[
                    "internal/proxy/anthropic.go",
                    "internal/proxy/anthropic_bridge_test.go",
                    "agent_tasks.json",
                    "pr_body.txt",
                ],
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("pr_body.txt" in reason for reason in decision.reasons))

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
            pr_body=evidence_body(
                "blocked-task",
                status="blocked",
                acceptance=[],
                evidence_files=["agent_tasks.json"],
                checks=["python3 scripts/validate_agent_tasks.py agent_tasks.json"],
                blocked_reason="Paused after repeated Jules FAILED sessions.",
                micro_pr_justification="Manifest-only blocked update documents missing evidence.",
            ),
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

    def test_missing_evidence_block_fails_done_task(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/anthropic.go", "agent_tasks.json"],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body="Runtime bridge decision logging was updated.",
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("AUTONOMOUS_TASK_EVIDENCE" in reason for reason in decision.reasons))

    def test_trusted_autofill_missing_evidence_block_for_done_task(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/anthropic.go", "agent_tasks.json"],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body="Runtime bridge decision logging was updated. Checks: go test ./...",
            allow_evidence_autofill=True,
        )

        self.assertTrue(decision.passed)
        self.assertEqual(decision.evidence["source"], "autofill")
        self.assertTrue(decision.evidence["autofilled"])
        self.assertIn("runtime-fix", decision.autofill_evidence_block)
        self.assertIn("internal/proxy/anthropic.go", decision.autofill_evidence_block)
        self.assertIn("go test ./...", decision.autofill_evidence_block)

    def test_trusted_autofill_requires_single_changed_task(self) -> None:
        before = manifest(
            [
                task("runtime-fix-one", status="todo"),
                task("runtime-fix-two", status="todo"),
            ]
        )
        after = manifest(
            [
                task("runtime-fix-one", status="done"),
                task("runtime-fix-two", status="done"),
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/anthropic.go", "agent_tasks.json"],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            allow_evidence_autofill=True,
        )

        self.assertFalse(decision.passed)
        self.assertEqual(decision.evidence["source"], "missing")
        self.assertFalse(decision.autofill_evidence_block)

    def test_mismatched_evidence_task_id_fails(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body("other-task"),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("does not match changed task" in reason for reason in decision.reasons))

    def test_evidence_file_must_be_changed_by_pr(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=["internal/proxy/anthropic.go", "agent_tasks.json"],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body(
                "runtime-fix",
                evidence_files=["internal/proxy/anthropic.go", "docs/missing.md", "agent_tasks.json"],
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("files not changed" in reason for reason in decision.reasons))

    def test_done_evidence_must_cover_acceptance_count(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body(
                "runtime-fix",
                acceptance=["Only one criterion -> internal/proxy/anthropic.go"],
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("acceptance criteria" in reason for reason in decision.reasons))

    def test_evidence_requires_micro_pr_justification(self) -> None:
        before = manifest([task("runtime-fix", status="todo")])
        after = manifest([task("runtime-fix", status="done")])

        decision = self.evaluate(
            before,
            after,
            changed_files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            diff_text='+ logger.Printf("[bridge] decision: workspace reframing")',
            pr_body=evidence_body("runtime-fix", micro_pr_justification=""),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("micro_pr_justification" in reason for reason in decision.reasons))

    def test_high_risk_done_requires_legacy_lab_evidence(self) -> None:
        before = manifest(
            [
                task(
                    "legacy-high",
                    status="todo",
                    risk="high",
                    title="Enable scheduled legacy/offline compatibility smoke after lab runners are ready",
                    description="Enable low-frequency Legacy Compatibility Smoke after lab runners are ready.",
                    allowed_paths=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
                    acceptance=["Scheduled smoke is enabled after required runner labels are available."],
                )
            ]
        )
        after = manifest(
            [
                task(
                    "legacy-high",
                    status="done",
                    risk="high",
                    title="Enable scheduled legacy/offline compatibility smoke after lab runners are ready",
                    description="Enable low-frequency Legacy Compatibility Smoke after lab runners are ready.",
                    allowed_paths=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
                    acceptance=["Scheduled smoke is enabled after required runner labels are available."],
                )
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
            diff_text="+ schedule:\n+   - cron: '17 3 * * 0'",
            pr_body=evidence_body(
                "legacy-high",
                acceptance=[
                    "Scheduled smoke is enabled after required runner labels are available -> .github/workflows/legacy_compat_smoke.yml"
                ],
                evidence_files=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
                checks=["python3 scripts/validate_agent_tasks.py agent_tasks.json"],
            ),
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("high risk" in reason for reason in decision.reasons))

    def test_high_risk_done_passes_with_legacy_smoke_evidence(self) -> None:
        before = manifest(
            [
                task(
                    "legacy-high",
                    status="todo",
                    risk="high",
                    title="Enable scheduled legacy/offline compatibility smoke after lab runners are ready",
                    description="Enable low-frequency Legacy Compatibility Smoke after lab runners are ready.",
                    allowed_paths=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
                    acceptance=["Scheduled smoke is enabled after required runner labels are available."],
                )
            ]
        )
        after = manifest(
            [
                task(
                    "legacy-high",
                    status="done",
                    risk="high",
                    title="Enable scheduled legacy/offline compatibility smoke after lab runners are ready",
                    description="Enable low-frequency Legacy Compatibility Smoke after lab runners are ready.",
                    allowed_paths=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
                    acceptance=["Scheduled smoke is enabled after required runner labels are available."],
                )
            ]
        )

        decision = self.evaluate(
            before,
            after,
            changed_files=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
            diff_text="+ schedule:\n+   - cron: '17 3 * * 0'",
            pr_body=evidence_body(
                "legacy-high",
                acceptance=[
                    "Scheduled smoke is enabled after required runner labels are available -> .github/workflows/legacy_compat_smoke.yml"
                ],
                evidence_files=[".github/workflows/legacy_compat_smoke.yml", "agent_tasks.json"],
                checks=[
                    "python3 scripts/validate_agent_tasks.py agent_tasks.json",
                    "workflow_dispatch Legacy Compatibility Smoke run checked CentOS self-hosted runner labels",
                ],
                micro_pr_justification="High-risk scheduling is bounded by Legacy Compatibility Smoke runner evidence and rollback.",
            ),
        )

        self.assertTrue(decision.passed)


if __name__ == "__main__":
    unittest.main()

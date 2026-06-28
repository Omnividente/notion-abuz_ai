#!/usr/bin/env python3
"""Unit tests for advisory-critic-review.py."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).with_name("advisory-critic-review.py")
SPEC = importlib.util.spec_from_file_location("advisory_critic_review", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
critic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = critic
SPEC.loader.exec_module(critic)


def evidence_body(
    *,
    task_id: str = "runtime-fix",
    status: str = "done",
    evidence_files: list[str] | None = None,
) -> str:
    evidence_files = evidence_files or [
        "internal/proxy/anthropic.go",
        "internal/proxy/anthropic_bridge_test.go",
        "agent_tasks.json",
    ]
    return "\n".join(
        [
            "<!-- AUTONOMOUS_TASK_EVIDENCE",
            f"task_id: {task_id}",
            f"status: {status}",
            "acceptance:",
            "- Runtime behavior is fixed -> internal/proxy/anthropic.go",
            "- Regression coverage exists -> internal/proxy/anthropic_bridge_test.go",
            "evidence_files:",
            *[f"- {path}" for path in evidence_files],
            "checks:",
            "- go test ./...",
            "micro_pr_justification: Runtime fix and regression coverage are one task theme.",
            "-->",
        ]
    )


class Args:
    repo = "Omnividente/notion-abuz_ai"
    starting_branch = "jules/task"
    gemini_api_base = "https://generativelanguage.googleapis.com"
    jules_api_base = "https://jules.googleapis.com/v1alpha"
    api_timeout = 1

    def __init__(self, llm_provider: str = "auto") -> None:
        self.llm_provider = llm_provider


class AdvisoryCriticReviewTest(unittest.TestCase):
    def evaluate(self, *, body: str, files: list[str], quality: dict | None = None):
        return critic.evaluate(
            pr_number="123",
            pr_title="Исправить runtime bridge",
            pr_body=body,
            changed_files=files,
            diff_text='+ logger.Printf("[bridge] decision: fixed")',
            quality_report=quality or {"passed": True, "reasons": []},
        )

    def test_runtime_pr_with_evidence_is_useful(self) -> None:
        report = self.evaluate(
            body=evidence_body(),
            files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
        )

        self.assertEqual(report["verdict"], "useful")
        self.assertFalse(report["should_block_merge"])
        self.assertFalse(report["should_pause_loop"])
        self.assertEqual(report["findings"], [])

    def test_quality_failure_is_needs_attention_but_non_blocking(self) -> None:
        report = self.evaluate(
            body=evidence_body(),
            files=[
                "internal/proxy/anthropic.go",
                "internal/proxy/anthropic_bridge_test.go",
                "agent_tasks.json",
            ],
            quality={"passed": False, "reasons": ["missing proof"]},
        )

        self.assertEqual(report["verdict"], "needs_attention")
        self.assertFalse(report["should_block_merge"])
        self.assertTrue(any(finding["code"] == "deterministic_quality_gate_failed" for finding in report["findings"]))

    def test_test_only_done_pr_is_flagged_as_attention(self) -> None:
        report = self.evaluate(
            body=evidence_body(evidence_files=["internal/proxy/anthropic_bridge_test.go", "agent_tasks.json"]),
            files=["internal/proxy/anthropic_bridge_test.go", "agent_tasks.json"],
        )

        self.assertEqual(report["verdict"], "needs_attention")
        self.assertTrue(any(finding["code"] == "test_doc_manifest_only_done_pr" for finding in report["findings"]))

    def test_auto_provider_without_keys_skips_llm(self) -> None:
        report = self.evaluate(body=evidence_body(), files=["internal/proxy/anthropic.go", "agent_tasks.json"])
        prompt = critic.build_critic_prompt(report, pr_body=evidence_body(), diff_text="")

        with mock.patch.dict(os.environ, {}, clear=True):
            critic.attach_llm_review(report, prompt, Args("auto"))

        self.assertEqual(report["llm"]["provider"], "none")
        self.assertEqual(report["llm"]["status"], "skipped")

    def test_auto_provider_does_not_create_jules_session(self) -> None:
        report = self.evaluate(body=evidence_body(), files=["internal/proxy/anthropic.go", "agent_tasks.json"])
        prompt = critic.build_critic_prompt(report, pr_body=evidence_body(), diff_text="")

        with mock.patch.dict(os.environ, {"JULES_API_KEY": "key"}, clear=True):
            critic.attach_llm_review(report, prompt, Args("auto"))

        self.assertEqual(report["llm"]["provider"], "none")
        self.assertEqual(report["llm"]["status"], "skipped")

    def test_gemini_response_is_parsed(self) -> None:
        report = self.evaluate(body=evidence_body(), files=["internal/proxy/anthropic.go", "agent_tasks.json"])
        prompt = critic.build_critic_prompt(report, pr_body=evidence_body(), diff_text="")

        def fake_request_json(*_args, **_kwargs):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"verdict":"useful","summary":"real value","findings":["ok"],"recommendations":[],"confidence":0.8}'
                                }
                            ]
                        }
                    }
                ]
            }

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "key", "GEMINI_CRITIC_MODEL": "gemini-test"}, clear=True):
            with mock.patch.object(critic, "request_json", side_effect=fake_request_json):
                critic.attach_llm_review(report, prompt, Args("auto"))

        self.assertEqual(report["llm"]["provider"], "gemini")
        self.assertEqual(report["llm"]["status"], "completed")
        self.assertEqual(report["llm"]["verdict"], "useful")

    def test_jules_api_failure_is_warning_only(self) -> None:
        report = self.evaluate(body=evidence_body(), files=["internal/proxy/anthropic.go", "agent_tasks.json"])
        prompt = critic.build_critic_prompt(report, pr_body=evidence_body(), diff_text="")

        with mock.patch.dict(os.environ, {"JULES_API_KEY": "key"}, clear=True):
            with mock.patch.object(critic, "request_json", side_effect=urllib.error.URLError("down")):
                critic.attach_llm_review(report, prompt, Args("jules"))

        self.assertEqual(report["llm"]["provider"], "jules")
        self.assertEqual(report["llm"]["status"], "unavailable")
        self.assertFalse(report["should_block_merge"])
        self.assertTrue(any("Jules critic unavailable" in warning for warning in report["warnings"]))

    def test_main_writes_report_and_outputs_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            body = root / "body.md"
            files = root / "files.txt"
            quality = root / "quality.json"
            output_json = root / "review.json"
            output_md = root / "review.md"
            github_output = root / "github-output.txt"
            body.write_text(evidence_body(), encoding="utf-8")
            files.write_text("internal/proxy/anthropic.go\nagent_tasks.json\n", encoding="utf-8")
            quality.write_text('{"passed": true, "reasons": []}', encoding="utf-8")

            with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(StringIO()):
                exit_code = critic.main(
                    [
                        "--pr-number",
                        "123",
                        "--pr-title",
                        "Runtime fix",
                        "--pr-body-file",
                        str(body),
                        "--changed-files-file",
                        str(files),
                        "--quality-report-json",
                        str(quality),
                        "--llm-provider",
                        "none",
                        "--output-json",
                        str(output_json),
                        "--output-md",
                        str(output_md),
                        "--github-output",
                        str(github_output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("AUTONOMOUS_CRITIC_REVIEW", output_md.read_text(encoding="utf-8"))
            self.assertIn("should_block_merge=false", github_output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

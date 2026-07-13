#!/usr/bin/env python3
"""Unit tests for block-failed-agent-task.py constants."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("block-failed-agent-task.py")
SPEC = importlib.util.spec_from_file_location("block_failed_agent_task", SCRIPT_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class BlockFailedAgentTaskTest(unittest.TestCase):
    def test_recovery_pr_does_not_use_jules_product_path(self) -> None:
        self.assertEqual(
            module.RECOVERY_BRANCH_PREFIX,
            "automation-recovery-failed-session-block",
        )
        self.assertFalse(module.RECOVERY_BRANCH_PREFIX.startswith(("jules-", "jules/")))
        self.assertNotIn("jules", module.RECOVERY_LABELS)
        self.assertIn("automation-recovery", module.RECOVERY_LABELS)
        self.assertIn("self-improvement", module.RECOVERY_LABELS)
        self.assertEqual(module.RECOVERY_MARKER, "AUTOMATION_RECOVERY_FAILED_SESSION_BLOCK")


    def test_replenishment_when_blocking_drops_below_minimum(self) -> None:
        import tempfile
        import json
        import shutil

        # Create a temporary manifest
        manifest_data = {
            "replenishment_policy": {"minimum_todo_tasks": 2},
            "tasks": [
                {
                    "id": "failing-task-1",
                    "status": "todo",
                    "area": "proxy",
                    "risk": "low",
                    "title": "Failing",
                    "description": "Fails.",
                    "allowed_paths": [],
                    "acceptance": []
                },
                {
                    "id": "other-task-2",
                    "status": "todo",
                    "area": "proxy",
                    "risk": "low",
                    "title": "Other",
                    "description": "Other.",
                    "allowed_paths": [],
                    "acceptance": []
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tmp:
            json.dump(manifest_data, tmp)
            tmp_path = tmp.name

        original_run = module.run
        original_request = module.request

        def mock_run(cmd, **kwargs):
            import subprocess
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        def mock_request(method, path, **kwargs):
            if method == "GET" and "pulls" in path:
                return []
            if method == "POST" and "pulls" in path:
                return {"number": 123}
            return None

        module.run = mock_run
        module.request = mock_request

        try:
            result = module.open_block_pr(
                manifest_path=Path(tmp_path),
                task_id="failing-task-1",
                failed_sessions=["session-abc"],
                token="dummy",
                repo="org/repo",
                api_url="http://dummy"
            )
            self.assertEqual(result, 0)

            with open(tmp_path, "r") as f:
                updated_manifest = json.load(f)

            tasks = updated_manifest.get("tasks", [])

            # The failing task should be blocked
            blocked_task = next(t for t in tasks if t["id"] == "failing-task-1")
            self.assertEqual(blocked_task["status"], "blocked")

            # The other task should still be todo
            other_task = next(t for t in tasks if t["id"] == "other-task-2")
            self.assertEqual(other_task["status"], "todo")

            # Since minimum is 2 and we blocked one, leaving 1 todo, it should have generated 1 new task
            todo_tasks = [t for t in tasks if t["status"] == "todo"]
            self.assertEqual(len(todo_tasks), 2)

            # Assert the generated task contains evidence-backed keywords
            generated_task = next(t for t in tasks if t["id"].startswith("automation-recovery-followup-"))
            self.assertIn("offline reproduction", generated_task["description"])
            self.assertIn("artifacts", generated_task["description"])

            # ensure all acceptances mentions evidence words
            self.assertTrue(any("offline reproduction" in acc for acc in generated_task["acceptance"]))
            self.assertTrue(any("artifacts" in acc or "logs" in acc or "transcripts" in acc for acc in generated_task["acceptance"]))

        finally:
            module.run = original_run
            module.request = original_request
            Path(tmp_path).unlink()

    def test_existing_source_reference_is_not_duplicated(self) -> None:
        import json
        import subprocess
        import tempfile

        manifest_data = {
            "replenishment_policy": {"minimum_todo_tasks": 3},
            "tasks": [
                {"id": "failing-task", "status": "todo"},
                {
                    "id": "automation-recovery-followup-existing",
                    "status": "done",
                    "source_reference": "Blocked task failing-task",
                },
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tmp:
            json.dump(manifest_data, tmp)
            tmp_path = tmp.name

        original_run, original_request = module.run, module.request
        module.run = lambda cmd, **kwargs: subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr=""
        )
        module.request = lambda method, path, **kwargs: (
            [] if method == "GET" else {"number": 123} if "pulls" in path else None
        )
        try:
            self.assertEqual(
                module.open_block_pr(
                    manifest_path=Path(tmp_path),
                    task_id="failing-task",
                    failed_sessions=["session-stale"],
                    token="dummy",
                    repo="org/repo",
                    api_url="http://dummy",
                ),
                0,
            )
            tasks = json.loads(Path(tmp_path).read_text())["tasks"]
            followups = [
                task
                for task in tasks
                if task.get("source_reference") == "Blocked task failing-task"
            ]
            self.assertEqual(len(followups), 1)
        finally:
            module.run, module.request = original_run, original_request
            Path(tmp_path).unlink()


if __name__ == "__main__":
    unittest.main()

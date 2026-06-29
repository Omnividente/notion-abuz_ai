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


if __name__ == "__main__":
    unittest.main()

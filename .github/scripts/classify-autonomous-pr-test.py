#!/usr/bin/env python3
"""Unit tests for classify-autonomous-pr.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("classify-autonomous-pr.py")
REPO_ROOT = Path(__file__).resolve().parents[2]
REPO = "Omnividente/notion-abuz_ai"


class ClassifyAutonomousPRTest(unittest.TestCase):
    def classify(self, **env_overrides: str) -> bool:
        env = os.environ.copy()
        env.update(
            {
                "GITHUB_REPOSITORY": REPO,
                "PR_HEAD_REF": "feature/control-plane",
                "PR_HEAD_REPO": REPO,
                "PR_USER": "Omnividente",
                "PR_TITLE": "Control-plane automation fix",
                "PR_BODY": "",
                "PR_LABELS_JSON": "[]",
            }
        )
        env.update(env_overrides)
        output = subprocess.check_output(
            [sys.executable, str(SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            encoding="utf-8",
        ).strip()
        return output == "true"

    def test_jules_signals_are_autonomous(self) -> None:
        self.assertTrue(self.classify(PR_USER="google-jules[bot]"))
        self.assertTrue(self.classify(PR_LABELS_JSON=json.dumps(["jules"])))
        self.assertTrue(self.classify(PR_BODY="PR created automatically by Jules"))
        self.assertTrue(self.classify(PR_BODY="https://jules.google.com/task/123"))
        self.assertTrue(self.classify(PR_HEAD_REF="jules/proxy-fix"))

    def test_task_id_in_body_does_not_classify_control_plane_pr(self) -> None:
        self.assertFalse(
            self.classify(
                PR_BODY=(
                    "Reproduced PR #295 locally for "
                    "proxy-observability-track-large-tool-result-fallbacks."
                )
            )
        )

    def test_task_id_branch_is_autonomous(self) -> None:
        self.assertTrue(
            self.classify(
                PR_HEAD_REF="proxy-observability-track-large-tool-result-fallbacks-fix",
                PR_BODY="ordinary body",
            )
        )


if __name__ == "__main__":
    unittest.main()

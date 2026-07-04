#!/usr/bin/env python3
"""Unit tests for count-autonomous-prs.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("count-autonomous-prs.py")
REPO_ROOT = Path(__file__).resolve().parents[2]
REPO = "Omnividente/notion-abuz_ai"


def pr(
    *,
    labels: list[str] | None = None,
    head_ref: str = "feature",
    body: str = "",
    repo: str = REPO,
    user: str = "Omnividente",
) -> dict:
    return {
        "labels": [{"name": label} for label in labels or []],
        "head": {"ref": head_ref, "repo": {"full_name": repo}},
        "user": {"login": user},
        "body": body,
    }


class CountAutonomousPRsTest(unittest.TestCase):
    def count(self, pulls: list[dict]) -> int:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(pulls, handle)
            path = Path(handle.name)

        env = os.environ.copy()
        env["GITHUB_REPOSITORY"] = REPO
        try:
            output = subprocess.check_output(
                [sys.executable, str(SCRIPT), str(path)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                encoding="utf-8",
            ).strip()
        finally:
            path.unlink(missing_ok=True)

        return int(output)

    def test_counts_all_autonomous_signals(self) -> None:
        self.assertEqual(
            self.count(
                [
                    pr(user="google-jules[bot]"),
                    pr(user="jules-agent[bot]"),
                    pr(head_ref="jules-runtime-fix"),
                    pr(body="PR created automatically by Jules"),
                    pr(body="https://jules.google.com/task/123"),
                    pr(head_ref="proxy-observability-workspace-reframing-quality-followup-fix"),
                ]
            ),
            6,
        )

    def test_ignores_unrelated_prs(self) -> None:
        self.assertEqual(
            self.count(
                [
                    pr(labels=["jules"]),
                    pr(head_ref="feature/runtime", body="human PR"),
                    pr(head_ref="jules-runtime-fix", repo="someone/fork"),
                ]
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()

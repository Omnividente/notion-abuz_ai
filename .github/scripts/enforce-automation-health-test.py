#!/usr/bin/env python3
"""Unit tests for enforce-automation-health.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("enforce-automation-health.py")
SPEC = importlib.util.spec_from_file_location("enforce_automation_health", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
enforce = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = enforce
SPEC.loader.exec_module(enforce)


def report(status: str, *, pause_loop: bool, findings: list[dict] | None = None) -> dict:
    return {
        "status": status,
        "pause_loop": pause_loop,
        "create_meta_task": status in {"degraded", "critical"},
        "findings": findings or [],
    }


def critical_finding(code: str = "duplicate_active_product_sessions") -> dict:
    return {
        "code": code,
        "severity": "critical",
        "message": "More than one active product Jules session exists.",
        "evidence": {"session_ids": ["s1", "s2"]},
    }


class EnforcementDecisionTest(unittest.TestCase):
    def test_shadow_never_pauses(self) -> None:
        decision = enforce.decide_enforcement(
            report("critical", pause_loop=True, findings=[critical_finding()]),
            mode="shadow",
        )

        self.assertEqual(decision.action, "none")
        self.assertFalse(decision.should_pause)

    def test_healthy_enforce_does_not_pause(self) -> None:
        decision = enforce.decide_enforcement(report("healthy", pause_loop=False), mode="enforce")

        self.assertEqual(decision.action, "none")
        self.assertFalse(decision.should_pause)

    def test_degraded_enforce_does_not_pause(self) -> None:
        decision = enforce.decide_enforcement(
            report(
                "degraded",
                pause_loop=False,
                findings=[
                    {
                        "code": "jules_api_unavailable",
                        "severity": "degraded",
                    }
                ],
            ),
            mode="enforce",
        )

        self.assertEqual(decision.action, "none")
        self.assertFalse(decision.should_pause)

    def test_critical_enforce_pauses(self) -> None:
        decision = enforce.decide_enforcement(
            report("critical", pause_loop=True, findings=[critical_finding()]),
            mode="enforce",
        )

        self.assertEqual(decision.action, "pause_loop")
        self.assertTrue(decision.should_pause)
        self.assertIn("duplicate_active_product_sessions", decision.reason)

    def test_critical_without_pause_loop_does_not_pause(self) -> None:
        decision = enforce.decide_enforcement(
            report("critical", pause_loop=False, findings=[critical_finding()]),
            mode="enforce",
        )

        self.assertEqual(decision.action, "none")
        self.assertFalse(decision.should_pause)

    def test_critical_without_critical_finding_does_not_pause(self) -> None:
        decision = enforce.decide_enforcement(
            report(
                "critical",
                pause_loop=True,
                findings=[
                    {
                        "code": "jules_api_unavailable",
                        "severity": "degraded",
                    }
                ],
            ),
            mode="enforce",
        )

        self.assertEqual(decision.action, "none")
        self.assertFalse(decision.should_pause)


if __name__ == "__main__":
    unittest.main()

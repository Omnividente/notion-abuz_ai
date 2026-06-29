#!/usr/bin/env python3
"""Unit tests for jules-recovery-router.py planning logic."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("jules-recovery-router.py")
SPEC = importlib.util.spec_from_file_location("jules_recovery_router", SCRIPT_PATH)
router = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = router
SPEC.loader.exec_module(router)


NOW = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)
REPO = "Omnividente/notion-abuz_ai"
TASK_IDS = ["automation-health-failed-session-86122315", "proxy-runtime-fix"]


def pr(
    *,
    number: int = 10,
    labels: list[str] | None = None,
    head_ref: str = "jules/proxy-runtime-fix-1234567890123456789",
    sha: str = "abc123",
    user: str = "google-jules[bot]",
    body: str = "",
    comments: list[str] | None = None,
    check_runs: list[dict] | None = None,
) -> dict:
    return {
        "number": number,
        "title": "Autonomous PR",
        "body": body,
        "labels": [{"name": label} for label in labels or []],
        "user": {"login": user},
        "head": {
            "ref": head_ref,
            "sha": sha,
            "repo": {"full_name": REPO},
        },
        "comments": [{"body": comment} for comment in comments or []],
        "check_runs": check_runs or [],
    }


def state(
    *,
    open_pulls: list[dict] | None = None,
    selector: dict | None = None,
    recent_unattended: bool = True,
    recent_next: bool = False,
    burst_in_progress: bool = False,
    recent_health: bool = False,
) -> dict:
    workflow_runs: dict[str, list[dict]] = {
        "jules_next_task.yml": [],
        "jules_unattended_monitor.yml": [],
        "jules_burst_monitor.yml": [],
        "automation_health.yml": [],
        "jules_automerge.yml": [],
    }
    if recent_unattended:
        workflow_runs["jules_unattended_monitor.yml"].append(
            {"created_at": (NOW - timedelta(minutes=1)).isoformat(), "status": "completed"}
        )
    if recent_next:
        workflow_runs["jules_next_task.yml"].append(
            {"created_at": (NOW - timedelta(minutes=1)).isoformat(), "status": "completed"}
        )
    if burst_in_progress:
        workflow_runs["jules_burst_monitor.yml"].append(
            {"created_at": (NOW - timedelta(minutes=1)).isoformat(), "status": "in_progress"}
        )
    if recent_health:
        workflow_runs["automation_health.yml"].append(
            {"created_at": (NOW - timedelta(minutes=1)).isoformat(), "status": "completed"}
        )
    return {
        "open_pulls": open_pulls or [],
        "workflow_runs": workflow_runs,
        "selector": selector if selector is not None else {"selected": False, "reason": "none"},
    }


def plan(input_state: dict, ledger: dict | None = None) -> list:
    return router.plan_recovery_actions(
        input_state,
        ledger or {"version": 1, "actions": {}},
        repo=REPO,
        task_ids=TASK_IDS,
        now=NOW,
    )


class RecoveryRouterTest(unittest.TestCase):
    def test_quality_fix_posts_comment_and_sends_session_message(self) -> None:
        actions = plan(state(open_pulls=[pr(labels=["jules", "needs-quality-fix"])]))

        self.assertEqual([action.type for action in actions], ["comment_pr", "dispatch_workflow"])
        self.assertEqual(actions[0].payload["pr_number"], 10)
        self.assertIn("исправь этот же PR #10", actions[0].payload["body"])
        self.assertEqual(actions[1].payload["workflow"], "jules_send_message.yml")
        self.assertEqual(actions[1].payload["inputs"]["session_id"], "1234567890123456789")

    def test_quality_fix_comment_marker_prevents_duplicate(self) -> None:
        marker = "<!-- AUTONOMOUS_RECOVERY_ROUTER action=quality-fix sha=abc123 -->"
        actions = plan(state(open_pulls=[pr(labels=["jules", "needs-quality-fix"], comments=[marker])]))

        self.assertEqual(actions, [])

    def test_quality_fix_waits_for_pending_checks_on_new_head(self) -> None:
        actions = plan(
            state(
                open_pulls=[
                    pr(
                        labels=["jules", "needs-quality-fix"],
                        check_runs=[{"name": "validate", "status": "in_progress"}],
                    )
                ]
            )
        )

        self.assertEqual(actions, [])

    def test_missing_jules_label_is_repaired(self) -> None:
        actions = plan(
            state(
                open_pulls=[
                    pr(
                        labels=[],
                        user="someone",
                        head_ref="proxy-runtime-fix-branch",
                        body="task proxy-runtime-fix",
                    )
                ]
            )
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "add_label")
        self.assertEqual(actions[0].payload["labels"], ["jules"])

    def test_failed_automerge_is_rerun_once(self) -> None:
        actions = plan(
            state(
                open_pulls=[
                    pr(
                        labels=["jules"],
                        check_runs=[
                            {
                                "name": "test-and-merge",
                                "conclusion": "failure",
                                "details_url": "https://github.com/o/r/actions/runs/12345/job/9",
                            }
                        ],
                    )
                ]
            )
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "rerun_workflow")
        self.assertEqual(actions[0].payload["run_id"], "12345")

    def test_stale_unattended_monitor_is_dispatched_before_new_task(self) -> None:
        actions = plan(
            state(
                recent_unattended=False,
                selector={"selected": True, "task_id": "automation-health-failed-session-86122315"},
            )
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "dispatch_workflow")
        self.assertEqual(actions[0].payload["workflow"], "jules_unattended_monitor.yml")

    def test_idle_selected_task_dispatches_next_task_when_monitor_recent(self) -> None:
        actions = plan(
            state(
                selector={"selected": True, "task_id": "automation-health-failed-session-86122315"}
            )
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "dispatch_workflow")
        self.assertEqual(actions[0].payload["workflow"], "jules_next_task.yml")

    def test_recent_next_task_dispatch_prevents_duplicate(self) -> None:
        actions = plan(
            state(
                recent_next=True,
                selector={"selected": True, "task_id": "automation-health-failed-session-86122315"},
            )
        )

        self.assertEqual(actions, [])

    def test_in_progress_burst_monitor_prevents_next_task_noise(self) -> None:
        actions = plan(
            state(
                burst_in_progress=True,
                selector={"selected": True, "task_id": "automation-health-failed-session-86122315"},
            )
        )

        self.assertEqual(actions, [])

    def test_no_eligible_task_dispatches_health_enforce(self) -> None:
        actions = plan(
            state(
                selector={
                    "selected": False,
                    "reason": "no eligible todo task matched the risk ceiling",
                }
            )
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].payload["workflow"], "automation_health.yml")
        self.assertEqual(actions[0].payload["inputs"]["mode"], "enforce")

    def test_recent_health_dispatch_prevents_duplicate(self) -> None:
        actions = plan(
            state(
                recent_health=True,
                selector={"selected": False, "reason": "no eligible task"},
            )
        )

        self.assertEqual(actions, [])

    def test_ledger_prevents_duplicate_action_within_ttl(self) -> None:
        dedupe = "automation-health-enforce:no-eligible-task"
        ledger = {
            "version": 1,
            "actions": {
                dedupe: {
                    "time": (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                    "type": "dispatch_workflow",
                }
            },
        }
        actions = plan(
            state(selector={"selected": False, "reason": "no eligible task"}),
            ledger=ledger,
        )

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()

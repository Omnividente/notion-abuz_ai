#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("jules_session_observer.py")
    spec = importlib.util.spec_from_file_location("jules_session_observer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


M = load_module()
NOW = datetime(2026, 7, 14, 4, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, value: datetime = NOW):
        self.value = value

    def now(self) -> datetime:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class ObserverTests(unittest.TestCase):
    def snapshot(self, state: str = "IN_PROGRESS", latest: str = "2026-07-14T03:59:00Z"):
        return {
            "session_id": "12345",
            "state": state,
            "session_update_at": latest,
            "latest_agent_at": latest,
            "activity_count": 2,
            "activity_fingerprint": "safe-fingerprint",
        }

    def test_session_name_rejects_path_injection(self):
        self.assertEqual(M.session_name("sessions/12345"), "sessions/12345")
        with self.assertRaises(ValueError):
            M.session_name("../../activities")

    def test_terminal_and_feedback_states_wake_immediately(self):
        self.assertEqual(
            M.actionable_reason(self.snapshot("COMPLETED"), current=NOW, stale_minutes=20),
            "terminal_completed",
        )
        self.assertEqual(
            M.actionable_reason(
                self.snapshot("AWAITING_USER_FEEDBACK"), current=NOW, stale_minutes=20
            ),
            "awaiting_user_feedback",
        )
        self.assertEqual(
            M.actionable_reason(
                self.snapshot("AWAITING_PLAN_APPROVAL"), current=NOW, stale_minutes=20
            ),
            "awaiting_plan_approval",
        )

    def test_only_real_agent_staleness_wakes_active_session(self):
        fresh = self.snapshot(latest="2026-07-14T03:59:00Z")
        stale = self.snapshot(latest="2026-07-14T03:39:00Z")
        self.assertEqual(M.actionable_reason(fresh, current=NOW, stale_minutes=20), "")
        self.assertEqual(
            M.actionable_reason(stale, current=NOW, stale_minutes=20),
            "stale_without_agent_progress",
        )

    def test_initial_unspecified_state_remains_observed(self):
        fresh = self.snapshot("STATE_UNSPECIFIED", latest="2026-07-14T03:59:00Z")
        self.assertEqual(M.actionable_reason(fresh, current=NOW, stale_minutes=20), "")

    def test_observer_waits_for_terminal_delta(self):
        snapshots = iter([self.snapshot(), self.snapshot("COMPLETED")])
        clock = FakeClock()
        result = M.observe(
            lambda: next(snapshots),
            stale_minutes=20,
            poll_seconds=30,
            max_watch_minutes=5,
            clock=clock.now,
            sleep=clock.sleep,
        )
        self.assertEqual(result["reason"], "terminal_completed")
        self.assertEqual(result["observations"], 2)

    def test_succeeded_alias_is_terminal(self):
        self.assertEqual(
            M.actionable_reason(self.snapshot("SUCCEEDED"), current=NOW, stale_minutes=20),
            "terminal_completed",
        )

    def test_observer_retries_bounded_transient_read(self):
        calls = 0
        clock = FakeClock()

        def fetch():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise M.TransientAPIError("reset")
            return self.snapshot("FAILED")

        result = M.observe(
            fetch,
            stale_minutes=20,
            poll_seconds=15,
            max_watch_minutes=5,
            clock=clock.now,
            sleep=clock.sleep,
        )
        self.assertEqual(result["reason"], "terminal_failed")
        self.assertEqual(calls, 2)

    def test_watch_deadline_is_bounded_and_requests_successor(self):
        clock = FakeClock()
        result = M.observe(
            lambda: self.snapshot(latest=clock.now().isoformat()),
            stale_minutes=20,
            poll_seconds=60,
            max_watch_minutes=5,
            clock=clock.now,
            sleep=clock.sleep,
        )
        self.assertEqual(result["reason"], "watch_deadline")
        self.assertEqual(result["observations"], 5)

    def test_snapshot_contains_no_raw_activity_text(self):
        class FakeAPI:
            def jules(self, key, path, allow=()):
                if path.endswith("activities?pageSize=100"):
                    return 200, {
                        "activities": [
                            {
                                "originator": "agent",
                                "createTime": "2026-07-14T03:59:00Z",
                                "message": "Authorization: Bearer secret-value-123456",
                            }
                        ]
                    }
                return 200, {"state": "IN_PROGRESS", "updateTime": "2026-07-14T03:59:00Z"}

        snapshot = M.fetch_snapshot(FakeAPI(), ["key"], "sessions/12345")
        serialized = str(snapshot)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("message", serialized)
        self.assertEqual(snapshot["activity_count"], 1)

    def test_all_keys_not_found_is_terminal_deleted(self):
        class MissingAPI:
            def jules(self, key, path, allow=()):
                return 404, {"message": "not found"}

        snapshot = M.fetch_snapshot(MissingAPI(), ["one", "two"], "sessions/12345")
        self.assertEqual(snapshot["state"], "DELETED")

    def test_initial_not_found_is_given_eventual_consistency_grace(self):
        snapshots = iter(
            [
                self.snapshot("DELETED", latest=""),
                self.snapshot("IN_PROGRESS"),
                self.snapshot("COMPLETED"),
            ]
        )
        clock = FakeClock()
        result = M.observe(
            lambda: next(snapshots),
            stale_minutes=20,
            poll_seconds=15,
            max_watch_minutes=5,
            clock=clock.now,
            sleep=clock.sleep,
        )
        self.assertEqual(result["reason"], "terminal_completed")
        self.assertEqual(result["observations"], 3)


if __name__ == "__main__":
    unittest.main()

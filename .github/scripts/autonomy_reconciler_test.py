import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


M = load_module("reconciler", "autonomy_reconciler.py")
E = load_module("executor", "jules_task_executor.py")


class ReconcilerTests(unittest.TestCase):
    def test_activity_summary_extracts_task_and_token(self):
        rows = [
            {"originator": "agent", "createTime": "2026-07-13T10:00:00Z", "message": "task_id: runtime-fix. Waiting."},
            {"originator": "user", "createTime": "2026-07-13T10:01:00Z", "message": f"{M.TOKEN} key={'a' * 24}"},
        ]
        summary = M.activity_summary(rows)
        self.assertEqual(summary["task_id"], "runtime-fix")
        self.assertIn("a" * 24, summary["token_keys"])

    def test_message_key_changes_with_state(self):
        self.assertNotEqual(M.message_key("s", 1, "a"), M.message_key("s", 2, "a"))
        self.assertNotEqual(M.message_key("s", 1, "a"), M.message_key("s", 1, "b"))

    def test_state_version_only_changes_on_observation(self):
        previous = {"state_version": 4, "session_state": "IN_PROGRESS", "activity_fingerprint": "a", "pr_fingerprint": "p"}
        self.assertEqual(M.state_version(previous, "IN_PROGRESS", "a", "p"), 4)
        self.assertEqual(M.state_version(previous, "IN_PROGRESS", "b", "p"), 5)

    def test_active_is_not_progress(self):
        self.assertTrue(M.no_op_violation(work=True, actions=0, progress=0, fresh=False))
        self.assertFalse(M.no_op_violation(work=True, actions=0, progress=1, fresh=False))

    def test_packet_is_sanitized_and_complete(self):
        task = {"id": "t", "risk": "medium", "acceptance": ["works"], "allowed_paths": ["internal/proxy/x.go"]}
        packet = M.build_packet(task, {"last_jules_message": "Authorization: Bearer abcdefghijklmnop", "task_id": "t"}, 1, False, "waiting", None, {"failed": [], "pending": [], "passed": []})
        self.assertEqual(set(packet), {"task_id", "acceptance", "allowed_scope", "risk", "wait_reason", "last_jules_message", "recent_activity", "attempt_count", "progress_delta", "scope_analysis", "pr_context"})
        self.assertNotIn("abcdefghijklmnop", packet["last_jules_message"])

    def test_recovery_user_activity_is_delivery_not_agent_progress(self):
        base = [{"originator": "agent", "createTime": "2026-07-13T10:00:00Z", "message": "working"}]
        before = M.activity_summary(base)
        after = M.activity_summary(base + [{"originator": "user", "createTime": "2026-07-13T10:01:00Z", "message": f"{M.TOKEN} key={'a' * 24}"}])
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        self.assertEqual(before["agent_fingerprint"], after["agent_fingerprint"])

    def test_runtime_task_beats_control_plane(self):
        runtime = {"id": "r", "status": "todo", "risk": "low", "allowed_paths": ["internal/proxy/runtime.go"], "description": "runtime failure"}
        control = {"id": "c", "status": "todo", "risk": "low", "allowed_paths": [".github/workflows/x.yml"], "description": "automation audit"}
        manifest = {"tasks": [control, runtime]}
        chosen = M.choose_task(manifest, {"tasks": {}}, datetime(2026, 7, 13, tzinfo=timezone.utc))
        self.assertEqual(chosen["id"], "r")

    def test_deferred_task_waits_for_retry(self):
        task = {"id": "r", "status": "todo", "risk": "low", "allowed_paths": ["internal/proxy/runtime.go"]}
        ledger = {"tasks": {"r": {"retry_at": "2026-07-13T11:00:00Z"}}}
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        self.assertIsNone(M.choose_task({"tasks": [task]}, ledger, current))

    def test_deferred_task_requires_new_evidence_after_review_date(self):
        task = {"id": "r", "status": "todo", "risk": "low", "allowed_paths": ["internal/proxy/runtime.go"], "description": "same evidence"}
        ledger = {"tasks": {"r": {"state": "deferred", "retry_at": "2026-07-13T09:00:00Z", "deferred_task_fingerprint": M.task_fingerprint(task), "deferred_evidence_fingerprint": "e", "current_evidence_fingerprint": "e"}}}
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        self.assertIsNone(M.choose_task({"tasks": [task]}, ledger, current))
        changed = {**task, "description": "new reproduced evidence"}
        self.assertEqual(M.choose_task({"tasks": [changed]}, ledger, current)["id"], "r")

    def test_control_task_needs_concrete_blocker_evidence(self):
        control = {"id": "c", "status": "todo", "risk": "low", "area": "automation", "allowed_paths": [".github/workflows/x.yml"]}
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        self.assertIsNone(M.choose_task({"tasks": [control]}, {"tasks": {}}, current))
        control["source_run_id"] = 123
        self.assertEqual(M.choose_task({"tasks": [control]}, {"tasks": {}}, current)["id"], "c")

    def test_two_control_tasks_cannot_be_dispatched_consecutively(self):
        first = {"id": "c1", "status": "todo", "risk": "low", "area": "automation", "allowed_paths": [".github/workflows/a.yml"], "source_run_id": 1}
        second = {"id": "c2", "status": "todo", "risk": "low", "area": "automation", "allowed_paths": [".github/workflows/b.yml"], "source_run_id": 2}
        ledger = {"tasks": {"__scheduler__": {"last_dispatched_kind": "control", "last_dispatched_task_id": "c1"}}}
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(M.choose_task({"tasks": [first, second]}, ledger, current)["id"], "c1")
        first["status"] = "done"
        self.assertIsNone(M.choose_task({"tasks": [first, second]}, ledger, current))

    def test_scope_expansion_requires_exact_safe_paths_and_evidence(self):
        task = {"id": "runtime", "area": "proxy", "risk": "medium", "allowed_paths": ["internal/proxy/a.go"]}
        approved, reason = M.assess_scope_request(task, {"paths": ["internal/proxy/a_test.go"], "risk": "medium", "evidence": "reproduced timeout"})
        self.assertTrue(approved, reason)
        self.assertFalse(M.assess_scope_request(task, {"paths": [".github/workflows/x.yml"], "risk": "low", "evidence": "test"})[0])
        self.assertFalse(M.assess_scope_request(task, {"paths": ["internal/proxy/a_test.go"], "risk": "high", "evidence": "test"})[0])

    def test_runtime_file_beats_flaky_test_directory_task(self):
        test_task = {"id": "tests", "status": "todo", "risk": "low", "allowed_paths": ["internal/proxy"], "title": "Fix flaky test"}
        runtime = {"id": "runtime", "status": "todo", "risk": "low", "allowed_paths": ["internal/proxy/reverseproxy.go"], "title": "Improve timeout logging"}
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(M.choose_task({"tasks": [test_task, runtime]}, {"tasks": {}}, current)["id"], "runtime")

    def test_ledger_pruning_is_bounded_and_keeps_active_rows(self):
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        messages = {f"m-{i}": {"sent_at": M.iso(current - timedelta(minutes=i)), "kind": "test"} for i in range(M.LEDGER_MAX_MESSAGES + 50)}
        sessions = {f"s-{i}": {"last_observed_at": M.iso(current - timedelta(minutes=i)), "session_state": "COMPLETED"} for i in range(M.LEDGER_MAX_SESSIONS + 20)}
        sessions["active-old"] = {"last_observed_at": "2020-01-01T00:00:00Z", "session_state": "IN_PROGRESS"}
        pruned = M.prune_ledger({"sessions": sessions, "tasks": {}, "messages": messages, "cycles": [{}] * 80}, current=current)
        self.assertLessEqual(len(pruned["messages"]), M.LEDGER_MAX_MESSAGES)
        self.assertLessEqual(len(pruned["sessions"]), M.LEDGER_MAX_SESSIONS)
        self.assertIn("active-old", pruned["sessions"])
        self.assertEqual(len(pruned["cycles"]), M.LEDGER_MAX_CYCLES)

    def test_legacy_ledger_migration_is_bounded_and_read_only(self):
        class FakeAPI:
            def __init__(self):
                self.calls = []

            def gh(self, path, **kwargs):
                self.calls.append((path, kwargs))
                value = {"actions": {"old": {"time": "2020-01-01T00:00:00Z"}, "new": {"time": "2026-07-13T09:59:00Z", "type": "send", "reason": "retry"}}, "sessions": {"1": {"task_id": "runtime", "state": "FAILED"}}}
                return 200, {"value": M.json.dumps(value)}

        api = FakeAPI()
        migrated = M.migrate_legacy_ledger(api, "o/r", current=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(migrated["migration"]["status"], "migrated")
        self.assertEqual(migrated["migration"]["imported_action_count"], 1)
        self.assertTrue(all(call[1].get("method", "GET") == "GET" for call in api.calls))

    def test_pr_detection(self):
        self.assertTrue(M.is_autonomous_pr({"body": "AUTONOMOUS_TASK_EVIDENCE", "head": {"ref": "x"}, "user": {"login": "u"}}))

    def test_executor_accepts_exact_valid_task(self):
        task = {"id": "runtime-fix", "status": "todo", "risk": "medium", "title": "Fix runtime"}
        selected = E.select_exact_task({"tasks": [task]}, "runtime-fix", "medium")
        self.assertEqual(selected["id"], "runtime-fix")

    def test_executor_allows_blocked_task_only_for_in_place_pr_recovery(self):
        task = {"id": "runtime-fix", "status": "blocked", "risk": "low", "title": "Fix runtime"}
        with self.assertRaises(RuntimeError):
            E.select_exact_task({"tasks": [task]}, "runtime-fix", "medium")
        selected = E.select_exact_task(
            {"tasks": [task]},
            "runtime-fix",
            "medium",
            allow_terminal_pr_recovery=True,
        )
        self.assertEqual(selected["id"], "runtime-fix")

    def test_executor_rejects_unleased_or_expired_dispatch(self):
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        valid = {"tasks": {"runtime-fix": {"state": "dispatch_requested", "dispatch_key": "lease", "lease_expires_at": "2026-07-13T10:30:00Z"}}}
        self.assertEqual(E.validate_lease(valid, "runtime-fix", "lease", current)["dispatch_key"], "lease")
        with self.assertRaises(RuntimeError):
            E.validate_lease(valid, "runtime-fix", "wrong", current)
        expired = {"tasks": {"runtime-fix": {"state": "dispatch_requested", "dispatch_key": "lease", "lease_expires_at": "2026-07-13T09:59:00Z"}}}
        with self.assertRaises(RuntimeError):
            E.validate_lease(expired, "runtime-fix", "lease", current)
        recovery = {"tasks": {"runtime-fix": {"state": "pr_recovery_dispatch_requested", "dispatch_key": "recovery", "lease_expires_at": "2026-07-13T10:30:00Z"}}}
        self.assertEqual(E.validate_lease(recovery, "runtime-fix", "recovery", current)["dispatch_key"], "recovery")


if __name__ == "__main__":
    unittest.main()

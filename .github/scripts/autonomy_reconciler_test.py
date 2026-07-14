import importlib.util
import io
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

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
    def test_api_retries_safe_get_after_connection_reset(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read():
                return b'{"ok": true}'

        delays = []
        api = M.API(
            "token",
            ["key"],
            request_attempts=3,
            retry_base_seconds=0.5,
            sleep_fn=delays.append,
        )
        with mock.patch.object(
            M.urllib.request,
            "urlopen",
            side_effect=[
                urllib.error.URLError(ConnectionResetError(104, "reset")),
                urllib.error.URLError(ConnectionResetError(104, "reset")),
                Response(),
            ],
        ) as urlopen:
            status, payload = api.request("https://example.invalid/state")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(delays, [0.5, 1.0])

    def test_api_does_not_retry_mutating_request_in_place(self):
        api = M.API(
            "token",
            ["key"],
            request_attempts=3,
            retry_base_seconds=0,
            sleep_fn=lambda _: None,
        )
        with mock.patch.object(
            M.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError(ConnectionResetError(104, "reset")),
        ) as urlopen:
            with self.assertRaises(M.TransientAPIError):
                api.request("https://example.invalid/dispatch", method="POST", body={})

        self.assertEqual(urlopen.call_count, 1)

    def test_api_retries_transient_http_status_and_honors_retry_after(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read():
                return b'{"ok": true}'

        transient = urllib.error.HTTPError(
            "https://example.invalid/state",
            503,
            "unavailable",
            {"Retry-After": "2"},
            io.BytesIO(b'{"message":"retry later"}'),
        )
        delays = []
        api = M.API("token", ["key"], sleep_fn=delays.append)
        with mock.patch.object(
            M.urllib.request,
            "urlopen",
            side_effect=[transient, Response()],
        ):
            status, payload = api.request("https://example.invalid/state")

        self.assertEqual((status, payload), (200, {"ok": True}))
        self.assertEqual(delays, [2.0])

    def test_transient_boundary_uses_ex_tempfail_exit_code(self):
        with mock.patch.object(
            M,
            "reconcile",
            side_effect=M.TransientAPIError("connection reset by peer"),
        ):
            self.assertEqual(M.main([]), 75)

    def test_reconciler_workflow_retries_only_transient_exit(self):
        workflow = (
            Path(__file__).parents[1] / "workflows" / "jules_unattended_monitor.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("for attempt in 1 2 3", workflow)
        self.assertIn('if [ "$status" -ne 75 ]', workflow)
        self.assertIn("Transient API failure; retrying the durable reconcile", workflow)

    def test_executor_completion_hands_control_back_to_reconciler(self):
        workflow = (
            Path(__file__).parents[1] / "workflows" / "jules_unattended_monitor.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('workflows: ["2. Execute Leased Jules Task"]', workflow)
        self.assertIn("types: [completed]", workflow)
        self.assertIn("github.event_name == 'workflow_run'", workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'master'", workflow)
        self.assertIn("github.event_name != 'pull_request'", workflow)

    def test_activity_summary_extracts_task_and_token(self):
        rows = [
            {"originator": "agent", "createTime": "2026-07-13T10:00:00Z", "message": "task_id: runtime-fix. Waiting."},
            {"originator": "user", "createTime": "2026-07-13T10:01:00Z", "message": f"{M.TOKEN} key={'a' * 24}"},
        ]
        summary = M.activity_summary(rows)
        self.assertEqual(summary["task_id"], "runtime-fix")
        self.assertIn("a" * 24, summary["token_keys"])

    def test_activity_summary_extracts_structured_verified_no_change(self):
        rows = [
            {
                "originator": "agent",
                "createTime": "2026-07-13T10:00:00Z",
                "message": (
                    'task_id: runtime-fix AUTONOMY_VERIFIED_NO_CHANGE '
                    '{"reason":"already correct","paths":["internal/proxy/x.go:10-20"],'
                    '"evidence":"go test ./internal/proxy passed"}'
                ),
            }
        ]
        request = M.activity_summary(rows)["verified_no_change"]
        self.assertEqual(request["reason"], "already correct")
        self.assertEqual(request["paths"], ["internal/proxy/x.go:10-20"])
        self.assertIn("go test", request["evidence"])

    def test_session_inspection_keeps_all_active_and_bounds_terminal_history(self):
        rows = [("k", {"name": f"sessions/{i}", "state": "COMPLETED", "updateTime": f"2026-07-13T09:{i:02d}:00Z"}) for i in range(20)]
        rows.append(("k", {"name": "sessions/active", "state": "IN_PROGRESS", "updateTime": "2020-01-01T00:00:00Z"}))
        selected = M.sessions_for_reconcile(rows, {"sessions": {}}, current=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc), limit=5)
        self.assertEqual(len(selected), 5)
        self.assertIn("sessions/active", [row[1]["name"] for row in selected])

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
        self.assertFalse(M.no_op_violation(work=True, actions=0, progress=0, fresh=False, blocked=1))

    def test_terminal_no_change_session_advances_bounded_pr_recovery_once(self):
        task = {
            "id": "proxy-improve-rproxy-timeout-handling",
            "status": "deferred",
            "risk": "low",
            "allowed_paths": ["internal/proxy/reverseproxy.go", "agent_tasks.json"],
        }
        pr = {"number": 596, "head": {"sha": "1144d"}}
        checks = {"fingerprint": "same-red-checks"}
        evidence_before, recovery_before = M.pr_recovery_fingerprints(
            {"sessions": {}}, task["id"], task, pr, checks
        )
        live_terminal = {
            "sessions": {
                "13525775686702804526": {
                    "task_id": task["id"],
                    "recovery_pr_number": 596,
                    "session_state": "COMPLETED",
                    "state_version": 4,
                    "progress_fingerprint": "terminal-without-pr-change",
                    "session_update_at": "2026-07-13T20:52:56Z",
                }
            }
        }
        evidence_after, recovery_after = M.pr_recovery_fingerprints(
            live_terminal, task["id"], task, pr, checks
        )
        self.assertEqual(evidence_before, evidence_after)
        self.assertNotEqual(recovery_before, recovery_after)
        self.assertEqual(
            (evidence_after, recovery_after),
            M.pr_recovery_fingerprints(live_terminal, task["id"], task, pr, checks),
        )

        changed_pr = {"number": 596, "head": {"sha": "new-head"}}
        changed_evidence, _ = M.pr_recovery_fingerprints(
            live_terminal, task["id"], task, changed_pr, checks
        )
        self.assertNotEqual(evidence_after, changed_evidence)

    def test_failed_and_stopped_sessions_become_actionable_deferred_tasks(self):
        task = {
            "id": "runtime-fix",
            "status": "todo",
            "risk": "low",
            "allowed_paths": ["internal/proxy/runtime.go", "agent_tasks.json"],
        }
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        for terminal_state in ("FAILED", "STOPPED"):
            with self.subTest(terminal_state=terminal_state):
                deferred, outcome, created = M.terminal_task_outcome(
                    {"state": "active", "session_id": "s"},
                    task=task,
                    session_id="s",
                    session_state=terminal_state,
                    progress_fingerprint="terminal-evidence",
                    verified_no_change=None,
                    current=current,
                    defer_minutes=60,
                )
                self.assertEqual(outcome, "deferred")
                self.assertTrue(created)
                self.assertEqual(deferred["state"], "deferred")
                self.assertIsNone(deferred["session_id"])
                self.assertIn(terminal_state, deferred["reason"])
                self.assertTrue(deferred["retry_condition"])
                self.assertTrue(deferred["evidence_requirement"])
                self.assertEqual(deferred["next_review_at"], "2026-07-13T11:00:00Z")
                repeated, repeated_outcome, repeated_created = M.terminal_task_outcome(
                    deferred,
                    task=task,
                    session_id="s",
                    session_state=terminal_state,
                    progress_fingerprint="terminal-evidence",
                    verified_no_change=None,
                    current=current,
                    defer_minutes=60,
                )
                self.assertEqual(repeated_outcome, "deferred")
                self.assertFalse(repeated_created)
                self.assertEqual(repeated["next_review_at"], deferred["next_review_at"])

    def test_structured_no_change_is_terminal_until_task_evidence_changes(self):
        task = {
            "id": "runtime-fix",
            "status": "todo",
            "risk": "low",
            "allowed_paths": ["internal/proxy/runtime.go", "agent_tasks.json"],
            "description": "original acceptance",
        }
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        completed, outcome, created = M.terminal_task_outcome(
            {"state": "active", "session_id": "s"},
            task=task,
            session_id="s",
            session_state="COMPLETED",
            progress_fingerprint="verified-evidence",
            verified_no_change={
                "reason": "runtime already satisfies acceptance",
                "paths": ["internal/proxy/runtime.go:10-20"],
                "evidence": "go test ./internal/proxy passed",
            },
            current=current,
            defer_minutes=60,
        )
        self.assertEqual(outcome, "verified_no_change")
        self.assertTrue(created)
        self.assertEqual(completed["completion_mode"], "verified_no_change")
        self.assertIsNone(M.choose_task({"tasks": [task]}, {"tasks": {"runtime-fix": completed}}, current))
        changed = {**task, "description": "new reproduced evidence"}
        self.assertEqual(
            M.choose_task({"tasks": [changed]}, {"tasks": {"runtime-fix": completed}}, current)["id"],
            "runtime-fix",
        )

    def test_historical_terminal_session_cannot_replace_active_task_owner(self):
        task_state = {
            "state": "active",
            "session_id": "5079834960180138219",
            "session_name": "sessions/5079834960180138219",
        }
        self.assertTrue(
            M.terminal_session_is_superseded(
                task_state,
                task_id="proxy-improve-rproxy-timeout-handling",
                session_id="13525775686702804526",
                session_state="COMPLETED",
                active_task_ids={"proxy-improve-rproxy-timeout-handling"},
            )
        )
        self.assertFalse(
            M.terminal_session_is_superseded(
                task_state,
                task_id="proxy-improve-rproxy-timeout-handling",
                session_id="5079834960180138219",
                session_state="IN_PROGRESS",
                active_task_ids={"proxy-improve-rproxy-timeout-handling"},
            )
        )

    def test_unchanged_failed_checks_do_not_repeat_recovery_message(self):
        self.assertEqual(
            M.should_recover_session(
                failed_checks=True,
                previous_pr_fingerprint="same",
                current_pr_fingerprint="same",
                stale=False,
            ),
            (False, "unchanged"),
        )
        self.assertEqual(
            M.should_recover_session(
                failed_checks=True,
                previous_pr_fingerprint="old",
                current_pr_fingerprint="new",
                stale=False,
            )[1],
            "new_failed_check_evidence",
        )
        self.assertTrue(
            M.should_recover_session(
                failed_checks=True,
                previous_pr_fingerprint="same",
                current_pr_fingerprint="same",
                stale=True,
            )[0]
        )

    def test_dirty_pr_is_immediate_recovery_evidence_without_checks(self):
        dirty = {"number": 607, "head": {"sha": "head"}, "mergeable_state": "dirty"}
        clean = {**dirty, "mergeable_state": "clean"}
        conflict_without_state = {"number": 607, "mergeable": False}
        checks = {"failed": [], "fingerprint": "no-checks"}
        self.assertTrue(M.pr_requires_recovery(dirty, checks))
        self.assertTrue(M.pr_requires_recovery(conflict_without_state, checks))
        self.assertFalse(M.pr_requires_recovery(clean, checks))
        self.assertEqual(
            M.should_recover_session(
                failed_checks=False,
                blocked_pr=True,
                previous_pr_fingerprint="old",
                current_pr_fingerprint="dirty",
                stale=False,
            ),
            (True, "new_pr_blocker_evidence"),
        )
        self.assertEqual(
            M.should_recover_session(
                failed_checks=False,
                blocked_pr=True,
                previous_pr_fingerprint="dirty",
                current_pr_fingerprint="dirty",
                stale=False,
            ),
            (False, "unchanged"),
        )

    def test_listed_autonomous_pr_is_hydrated_before_mergeability_decision(self):
        class FakeAPI:
            def __init__(self):
                self.calls = []

            def gh(self, path, **kwargs):
                self.calls.append(path)
                self.assert_no_list_endpoint(path)
                return 200, {
                    "number": 607,
                    "head": {"sha": "head", "ref": "jules-docs"},
                    "mergeable": False,
                    "mergeable_state": "dirty",
                }

            @staticmethod
            def assert_no_list_endpoint(path):
                if "?state=open" in path:
                    raise AssertionError("hydrate must call the pull detail endpoint")

        api = FakeAPI()
        listed = [{"number": 607, "head": {"sha": "head", "ref": "jules-docs"}}]
        hydrated, failures = M.hydrate_pull_details(api, "o/r", listed)
        self.assertEqual(failures, [])
        self.assertEqual(api.calls, ["/repos/o/r/pulls/607"])
        self.assertEqual(M.pr_mergeability(hydrated[0]), "dirty")
        self.assertTrue(M.pr_requires_recovery(hydrated[0], {"failed": []}))

    def test_unknown_mergeability_is_retried_in_the_same_cycle(self):
        class FakeAPI:
            def __init__(self):
                self.calls = 0

            def gh(self, path, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return 200, {
                        "number": 607,
                        "mergeable": None,
                        "mergeable_state": "unknown",
                    }
                return 200, {
                    "number": 607,
                    "mergeable": False,
                    "mergeable_state": "dirty",
                }

        api = FakeAPI()
        hydrated, failures = M.hydrate_pull_details(
            api,
            "o/r",
            [{"number": 607}],
            retry_delay_seconds=0,
        )
        self.assertEqual(failures, [])
        self.assertEqual(api.calls, 2)
        self.assertEqual(M.pr_mergeability(hydrated[0]), "dirty")

    def test_unresolved_mergeability_is_an_explicit_error(self):
        class FakeAPI:
            def __init__(self):
                self.calls = 0

            def gh(self, path, **kwargs):
                self.calls += 1
                return 200, {
                    "number": 607,
                    "mergeable": None,
                    "mergeable_state": "unknown",
                }

        api = FakeAPI()
        _, failures = M.hydrate_pull_details(
            api,
            "o/r",
            [{"number": 607}],
            mergeability_attempts=3,
            retry_delay_seconds=0,
        )
        self.assertEqual(api.calls, 3)
        self.assertEqual(len(failures), 1)
        self.assertIn("mergeability unresolved", failures[0])

    def test_terminal_manifest_task_retires_stale_dispatch_lease(self):
        stale = {
            "state": "session_created",
            "dispatch_key": "old-lease",
            "dispatch_requested_at": "2026-07-13T23:00:18Z",
            "lease_expires_at": "2026-07-13T23:45:46Z",
            "session_id": "10084739906341150041",
            "session_name": "sessions/10084739906341150041",
        }
        settled, changed = M.settle_terminal_manifest_task(stale, "done")
        self.assertTrue(changed)
        self.assertEqual(settled["state"], "manifest_done")
        self.assertEqual(settled["manifest_status"], "done")
        self.assertNotIn("dispatch_key", settled)
        self.assertNotIn("lease_expires_at", settled)
        self.assertNotIn("session_id", settled)
        repeated, changed_again = M.settle_terminal_manifest_task(settled, "done")
        self.assertFalse(changed_again)
        self.assertEqual(repeated, settled)

    def test_open_pr_supersedes_terminal_no_pr_defer(self):
        stale = {
            "state": "deferred",
            "retry_at": "2026-07-14T00:14:10Z",
            "next_review_at": "2026-07-14T00:14:10Z",
            "reason": "session completed without PR",
            "terminal_session_id": "18011490522809812243",
            "terminal_session_state": "COMPLETED",
        }
        recovered = M.open_pr_task_state(stale, 607)
        self.assertEqual(recovered["pr_number"], 607)
        self.assertNotIn("retry_at", recovered)
        self.assertNotIn("terminal_session_id", recovered)
        task = {"id": "docs", "status": "todo"}
        self.assertFalse(
            M.terminal_task_needs_outcome(
                "COMPLETED", task, {"number": 607}, False
            )
        )
        self.assertTrue(
            M.terminal_task_needs_outcome("COMPLETED", task, None, False)
        )

    def test_pr_recovery_fingerprint_includes_dirty_state(self):
        task = {"id": "docs", "status": "todo", "allowed_paths": ["docs/api.md"]}
        checks = {"fingerprint": "none"}
        dirty = {"number": 607, "head": {"sha": "same"}, "mergeable_state": "dirty"}
        clean = {**dirty, "mergeable_state": "clean"}
        self.assertNotEqual(
            M.pr_recovery_fingerprints({"sessions": {}}, "docs", task, dirty, checks),
            M.pr_recovery_fingerprints({"sessions": {}}, "docs", task, clean, checks),
        )

    def test_each_user_feedback_question_is_resolved_once(self):
        self.assertTrue(
            M.user_feedback_needs_resolution(
                {}, "AWAITING_USER_FEEDBACK", "question-one"
            )
        )
        resolved = {"resolved_feedback_agent_fingerprint": "question-one"}
        self.assertFalse(
            M.user_feedback_needs_resolution(
                resolved, "AWAITING_USER_FEEDBACK", "question-one"
            )
        )
        self.assertTrue(
            M.user_feedback_needs_resolution(
                resolved, "AWAITING_USER_FEEDBACK", "question-two"
            )
        )
        self.assertEqual(
            M.should_recover_session(
                failed_checks=False,
                previous_pr_fingerprint="same",
                current_pr_fingerprint="same",
                stale=False,
                awaiting_user_feedback=True,
            ),
            (True, "awaiting_user_feedback"),
        )

    def test_packet_is_sanitized_and_complete(self):
        task = {"id": "t", "risk": "medium", "acceptance": ["works"], "allowed_paths": ["internal/proxy/x.go"]}
        packet = M.build_packet(task, {"last_jules_message": "Authorization: Bearer abcdefghijklmnop", "task_id": "t"}, 1, False, "waiting", None, {"failed": [], "pending": [], "passed": []})
        self.assertEqual(set(packet), {"task_id", "acceptance", "allowed_scope", "risk", "wait_reason", "last_jules_message", "recent_activity", "attempt_count", "progress_delta", "scope_analysis", "pr_context"})
        self.assertNotIn("abcdefghijklmnop", packet["last_jules_message"])

    def test_check_context_uses_latest_workflow_run_and_failed_step(self):
        class FakeAPI:
            def gh(self, path, **kwargs):
                if "/commits/head/check-runs" in path:
                    return 200, {"check_runs": [
                        {"id": 1, "name": "validate", "status": "completed", "conclusion": "failure", "details_url": "https://github.com/o/r/actions/runs/10/job/100", "check_suite": {"id": 1}},
                        {"id": 2, "name": "validate", "status": "completed", "conclusion": "success", "details_url": "https://github.com/o/r/actions/runs/11/job/101", "check_suite": {"id": 2}},
                        {"id": 3, "name": "validate", "status": "completed", "conclusion": "failure", "details_url": "https://github.com/o/r/actions/runs/12/job/102", "check_suite": {"id": 3}},
                    ]}
                if "/pulls/1/files" in path:
                    return 200, [{"filename": "internal/proxy/reverseproxy.go"}]
                if path.endswith("/actions/runs/10"):
                    return 200, {"workflow_id": 7, "name": "CI", "created_at": "2026-07-13T09:00:00Z", "run_attempt": 1}
                if path.endswith("/actions/runs/11"):
                    return 200, {"workflow_id": 7, "name": "CI", "created_at": "2026-07-13T09:05:00Z", "run_attempt": 1}
                if path.endswith("/actions/runs/12"):
                    return 200, {"workflow_id": 8, "name": "Automerge", "created_at": "2026-07-13T09:06:00Z", "run_attempt": 1}
                if "/actions/runs/12/jobs" in path:
                    return 200, {"jobs": [{"id": 102, "name": "validate", "steps": [{"name": "Check Go formatting", "conclusion": "failure"}]}]}
                if "/check-runs/3/annotations" in path:
                    return 200, []
                raise AssertionError(path)

        context = M.check_context(FakeAPI(), "o/r", {"number": 1, "head": {"sha": "head"}})
        self.assertEqual(len(context["failed"]), 1)
        self.assertEqual(context["failed"][0]["workflow"], "Automerge")
        self.assertIn("Check Go formatting", context["failed"][0]["log_excerpt"])
        self.assertIn("CI / validate", context["passed"])

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

    def test_pr_recovery_lease_and_scheduler_survive_task_pruning(self):
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        tasks = {f"old-{i}": {"updated_at": "2020-01-01T00:00:00Z"} for i in range(M.LEDGER_MAX_TASKS + 20)}
        tasks["runtime"] = {"state": "pr_recovery_dispatch_requested", "dispatch_requested_at": M.iso(current)}
        tasks["verified"] = {"state": "verified_no_change", "verified_at": "2020-01-01T00:00:00Z"}
        tasks["__scheduler__"] = {"last_dispatched_kind": "runtime", "last_dispatched_at": M.iso(current)}
        pruned = M.prune_ledger({"sessions": {}, "tasks": tasks, "messages": {}, "cycles": []}, current=current)
        self.assertIn("runtime", pruned["tasks"])
        self.assertIn("verified", pruned["tasks"])
        self.assertIn("__scheduler__", pruned["tasks"])

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

    def test_executor_adopts_same_task_active_session_without_second_dispatch(self):
        current = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
        task_state = {
            "state": "pr_recovery_dispatch_requested",
            "dispatch_key": "recovery",
            "terminal_session_id": "session-1",
            "retry_at": "2026-07-13T11:00:00Z",
            "reason": "terminal session",
        }
        ledger = {
            "tasks": {"runtime-fix": task_state},
            "sessions": {
                "session-1": {
                    "task_id": "runtime-fix",
                    "session_state": "FAILED",
                    "state_version": 4,
                }
            },
        }
        active = [{"name": "sessions/session-1", "state": "IN_PROGRESS"}]
        existing = E.existing_active_session_for_task(active, ledger, "runtime-fix", task_state)
        self.assertEqual(E.session_id(existing), "session-1")
        self.assertEqual(E.session_id({"id": "sessions/session-1"}), "session-1")

        result = E.adopt_existing_active_session(
            ledger,
            "runtime-fix",
            task_state,
            existing,
            lease_key="recovery",
            recovery_pr_number=604,
            recovery_pr_head="head",
            current=current,
            session_lease_minutes=45,
        )
        self.assertTrue(result["duplicate_dispatch_suppressed"])
        self.assertEqual(ledger["tasks"]["runtime-fix"]["state"], "active")
        self.assertEqual(ledger["tasks"]["runtime-fix"]["session_id"], "session-1")
        self.assertEqual(ledger["tasks"]["runtime-fix"]["recovery_pr_number"], 604)
        self.assertEqual(ledger["tasks"]["runtime-fix"]["lease_expires_at"], "2026-07-13T10:45:00Z")
        self.assertNotIn("retry_at", ledger["tasks"]["runtime-fix"])
        self.assertNotIn("terminal_session_id", ledger["tasks"]["runtime-fix"])
        self.assertEqual(ledger["sessions"]["session-1"]["state_version"], 5)

    def test_executor_still_rejects_foreign_or_ambiguous_active_sessions(self):
        task_state = {"terminal_session_id": "session-1"}
        foreign = [{"name": "sessions/other", "state": "IN_PROGRESS"}]
        with self.assertRaisesRegex(RuntimeError, "refusing duplicate dispatch"):
            E.existing_active_session_for_task(foreign, {"sessions": {}}, "runtime-fix", task_state)

        duplicate = [
            {"name": "sessions/session-1", "state": "IN_PROGRESS"},
            {"name": "sessions/session-2", "state": "PLANNING"},
        ]
        ledger = {
            "sessions": {
                "session-1": {"task_id": "runtime-fix"},
                "session-2": {"task_id": "runtime-fix"},
            }
        }
        with self.assertRaisesRegex(RuntimeError, "multiple active Jules sessions"):
            E.existing_active_session_for_task(duplicate, ledger, "runtime-fix", task_state)


if __name__ == "__main__":
    unittest.main()

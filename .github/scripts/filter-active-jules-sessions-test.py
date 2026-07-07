#!/usr/bin/env python3
"""Unit tests for filter-active-jules-sessions.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("filter-active-jules-sessions.py")
SPEC = importlib.util.spec_from_file_location("filter_active_jules_sessions", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


SOURCE = "sources/github/Omnividente/notion-abuz_ai"
NOW = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)


def recent_task(task_id: str, *, minutes_ago: int = 5) -> dict:
    return {
        "task_id": task_id,
        "updateTime": (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z"),
    }


def session(session_id: str, *, state: str = "IN_PROGRESS", source: str = SOURCE) -> dict:
    return {
        "name": f"sessions/{session_id}",
        "state": state,
        "sourceContext": {"source": source},
    }


class FilterActiveJulesSessionsTest(unittest.TestCase):
    def filter(self, sessions: list[dict], *, recent_map: dict | None = None, stopped: set[str] | None = None) -> dict:
        return module.filter_sessions(
            {"sessions": sessions},
            source=SOURCE,
            active_states=module.DEFAULT_ACTIVE_STATES,
            task_statuses={
                "todo-task": "todo",
                "done-task": "done",
                "blocked-task": "blocked",
                "stopped-task": "todo",
            },
            recent_map=recent_map or {},
            stopped_tasks=stopped or set(),
            now=NOW,
        )

    def test_unknown_in_progress_session_does_not_block_dispatch(self) -> None:
        result = self.filter([session("111")])

        self.assertEqual(result["active_total"], 1)
        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["ignored_count"], 1)
        self.assertEqual(result["ignored_sessions"][0]["reason"], "unknown_in_progress_task_id")

    def test_unknown_awaiting_feedback_session_still_blocks_for_recovery(self) -> None:
        result = self.filter([session("111", state="AWAITING_USER_FEEDBACK")])

        self.assertEqual(result["blocking_count"], 1)
        self.assertEqual(result["ignored_count"], 0)
        self.assertEqual(result["blocking_sessions"][0]["reason"], "unknown_task_id")

    def test_todo_task_session_blocks_dispatch(self) -> None:
        result = self.filter([session("111")], recent_map={"111": recent_task("todo-task")})

        self.assertEqual(result["blocking_count"], 1)
        self.assertEqual(result["blocking_sessions"][0]["reason"], "active_task")

    def test_stale_recent_task_mapping_does_not_block_in_progress_dispatch(self) -> None:
        result = self.filter([session("111")], recent_map={"111": recent_task("todo-task", minutes_ago=61)})

        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["ignored_count"], 1)
        self.assertEqual(result["ignored_sessions"][0]["reason"], "stale_recent_task_mapping")
        self.assertEqual(result["ignored_sessions"][0]["recent_map_stale"], "true")

    def test_stale_recent_task_mapping_still_blocks_awaiting_feedback_for_recovery(self) -> None:
        result = self.filter(
            [session("111", state="AWAITING_USER_FEEDBACK")],
            recent_map={"111": recent_task("todo-task", minutes_ago=61)},
        )

        self.assertEqual(result["blocking_count"], 1)
        self.assertEqual(result["ignored_count"], 0)
        self.assertEqual(result["blocking_sessions"][0]["reason"], "stale_recent_task_mapping")
        self.assertEqual(result["blocking_sessions"][0]["recent_map_stale"], "true")

    def test_done_or_blocked_task_sessions_do_not_block_dispatch(self) -> None:
        result = self.filter(
            [session("111"), session("222")],
            recent_map={
                "111": recent_task("done-task"),
                "222": recent_task("blocked-task"),
            },
        )

        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["ignored_count"], 2)
        self.assertEqual(
            {item["reason"] for item in result["ignored_sessions"]},
            {"manifest_status:done", "manifest_status:blocked"},
        )

    def test_stopped_pr_task_session_does_not_block_dispatch(self) -> None:
        result = self.filter(
            [session("111")],
            recent_map={"111": recent_task("stopped-task")},
            stopped={"stopped-task"},
        )

        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["ignored_count"], 1)
        self.assertEqual(result["ignored_sessions"][0]["reason"], "stopped_autonomous_pr")

    def test_stale_session_for_closed_stopped_pr_task_is_ignored(self) -> None:
        result = self.filter(
            [session("111", state="AWAITING_USER_FEEDBACK")],
            recent_map={"111": recent_task("done-task", minutes_ago=61)},
        )

        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["ignored_count"], 1)
        self.assertEqual(result["ignored_sessions"][0]["reason"], "manifest_status:done")

    def test_other_sources_and_terminal_states_are_ignored(self) -> None:
        result = self.filter(
            [
                session("111", source="sources/github/other/repo"),
                session("222", state="SUCCEEDED"),
            ]
        )

        self.assertEqual(result["active_total"], 0)
        self.assertEqual(result["blocking_count"], 0)

    def test_recent_map_loads_github_variable_value_shape(self) -> None:
        parsed = module.parse_recent_map_value('{"111":{"task_id":"done-task"}}')

        self.assertEqual(parsed["111"]["task_id"], "done-task")


if __name__ == "__main__":
    unittest.main()

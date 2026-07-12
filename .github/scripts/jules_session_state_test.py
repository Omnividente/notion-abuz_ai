#!/usr/bin/env python3
from datetime import datetime, timezone

import jules_session_state as lifecycle


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


def session(state="IN_PROGRESS", agent=100, user=0, token=0):
    return {
        "name": "sessions/s-1",
        "session_id": "s-1",
        "state": state,
        "task_id": "runtime-task",
        "updateTime": "2026-07-12T11:59:00Z",
        "activity_summary": {
            "latest_agent_epoch": agent,
            "latest_user_epoch": user,
            "latest_token_epoch": token,
            "latest_activity_epoch": max(agent, user, token),
            "wait_reason": "routine_question",
        },
    }


def main():
    assert lifecycle.canonical_state(session("QUEUED"), now=NOW) == "created"
    assert lifecycle.canonical_state(session("FAILED"), now=NOW) == "failed"
    waiting = session("AWAITING_USER_FEEDBACK")
    waiting["updateTime"] = "2026-07-12T11:59:00Z"
    waiting["activity_summary"] = {}
    assert lifecycle.canonical_state(waiting, now=NOW) == "waiting"
    waiting["updateTime"] = "2026-07-12T10:00:00Z"
    assert lifecycle.canonical_state(waiting, now=NOW) == "stale"

    state = {"jules": {"sessions": [session()]}}
    ledger = {"version": 2, "actions": {}, "sessions": {}}
    first = lifecycle.annotate_sessions(state, ledger, now=NOW)
    assert first[0]["progress_delta"] is True
    event = state["jules"]["sessions"][0]["recovery_event_id"]

    second_state = {"jules": {"sessions": [session()]}}
    second = lifecycle.annotate_sessions(second_state, ledger, now=NOW)
    assert second[0]["progress_delta"] is False
    assert second_state["jules"]["sessions"][0]["recovery_event_id"] == event

    progressed = session(agent=200)
    third_state = {"jules": {"sessions": [progressed]}}
    third = lifecycle.annotate_sessions(third_state, ledger, now=NOW)
    assert third[0]["progress_delta"] is True
    assert progressed["recovery_event_id"] != event

    lifecycle.record_recovery(ledger, session_id="s-1", action="run_validation", now=NOW)
    snapshot = ledger["sessions"]["s-1"]
    assert snapshot["attempt"] == 1
    assert snapshot["recovery_action"] == "run_validation"
    print("jules_session_state tests: ok")


if __name__ == "__main__":
    main()

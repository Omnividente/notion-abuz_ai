#!/usr/bin/env python3
"""Observe one Jules session until the durable reconciler must run again.

The observer is deliberately read-only. It keeps unreliable GitHub schedules
out of the critical handoff path without becoming a second state machine: all
task, session, PR, and recovery mutations remain in autonomy_reconciler.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from autonomy_state import (
    ACTIVE,
    TERMINAL,
    API,
    TransientAPIError,
    activity_summary,
    iso,
    output,
    parse_time,
    sanitize,
)


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,160}$")
IMMEDIATE_WAIT_STATES = {"AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK"}
OBSERVED_ACTIVE_STATES = ACTIVE | {"STATE_UNSPECIFIED"}
TERMINAL_STATE_REASONS = {**{state: state.lower() for state in TERMINAL}, "SUCCEEDED": "completed"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def session_name(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("sessions/"):
        identity = raw.removeprefix("sessions/")
    elif "/" not in raw:
        identity = raw
    else:
        raise ValueError("session_id has an invalid format")
    if not SESSION_ID_RE.fullmatch(identity):
        raise ValueError("session_id has an invalid format")
    return f"sessions/{identity}"


def fetch_snapshot(api: API, keys: list[str], name: str) -> dict[str, Any]:
    """Read one sanitized snapshot, trying the key that owns the session."""

    transient_errors: list[str] = []
    permanent_errors: list[str] = []
    missing = 0
    for key in keys:
        try:
            status, session = api.jules(key, name, allow=(404,))
            if status == 404:
                missing += 1
                continue
            activity_status, payload = api.jules(
                key,
                f"{name}/activities?pageSize=100",
                allow=(404,),
            )
            activities = (
                [row for row in payload.get("activities", []) if isinstance(row, dict)]
                if activity_status != 404 and isinstance(payload, dict)
                else []
            )
            summary = activity_summary(activities)
            return {
                "session_id": name.rsplit("/", 1)[-1],
                "state": str(session.get("state") or "STATE_UNSPECIFIED"),
                "session_update_at": str(
                    session.get("updateTime") or session.get("createTime") or ""
                ),
                "latest_agent_at": str(summary.get("latest_agent_at") or ""),
                "activity_count": int(summary.get("count") or 0),
                "activity_fingerprint": str(summary.get("agent_fingerprint") or ""),
            }
        except TransientAPIError as exc:
            transient_errors.append(sanitize(exc, 400))
        except Exception as exc:
            permanent_errors.append(sanitize(exc, 400))

    if missing == len(keys):
        return {
            "session_id": name.rsplit("/", 1)[-1],
            "state": "DELETED",
            "session_update_at": "",
            "latest_agent_at": "",
            "activity_count": 0,
            "activity_fingerprint": "",
        }
    if permanent_errors:
        raise RuntimeError(
            "Jules session read failed for all usable keys: "
            + " | ".join(permanent_errors + transient_errors)
        )
    raise TransientAPIError(
        "transient Jules session read failed for all configured keys: "
        + " | ".join(transient_errors)
    )


def actionable_reason(
    snapshot: dict[str, Any],
    *,
    current: datetime,
    stale_minutes: int,
) -> str:
    state = str(snapshot.get("state") or "STATE_UNSPECIFIED").upper()
    if state in TERMINAL_STATE_REASONS:
        return f"terminal_{TERMINAL_STATE_REASONS[state]}"
    if state in IMMEDIATE_WAIT_STATES:
        return state.lower()
    if state not in OBSERVED_ACTIVE_STATES:
        return f"unsupported_state_{sanitize(state, 80).lower()}"

    latest = parse_time(
        snapshot.get("latest_agent_at") or snapshot.get("session_update_at")
    )
    if latest is None or current - latest >= timedelta(minutes=stale_minutes):
        return "stale_without_agent_progress"
    return ""


def observe(
    fetch: Callable[[], dict[str, Any]],
    *,
    stale_minutes: int,
    poll_seconds: float,
    max_watch_minutes: int,
    max_consecutive_transient_errors: int = 3,
    missing_grace_observations: int = 3,
    clock: Callable[[], datetime] = now,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    started = clock()
    transient_errors = 0
    observations = 0
    consecutive_missing = 0
    snapshot: dict[str, Any] = {}

    while True:
        current = clock()
        if current - started >= timedelta(minutes=max_watch_minutes):
            return {
                **snapshot,
                "reason": "watch_deadline",
                "observations": observations,
                "started_at": iso(started),
                "observed_at": iso(current),
            }
        try:
            snapshot = fetch()
            transient_errors = 0
            observations += 1
        except TransientAPIError:
            transient_errors += 1
            if transient_errors >= max_consecutive_transient_errors:
                raise
            sleep(poll_seconds)
            continue

        current = clock()
        if str(snapshot.get("state") or "").upper() == "DELETED":
            consecutive_missing += 1
        else:
            consecutive_missing = 0
        reason = (
            actionable_reason(
                snapshot,
                current=current,
                stale_minutes=stale_minutes,
            )
            if consecutive_missing == 0
            or consecutive_missing >= missing_grace_observations
            else ""
        )
        if reason:
            return {
                **snapshot,
                "reason": reason,
                "observations": observations,
                "started_at": iso(started),
                "observed_at": iso(current),
            }
        sleep(poll_seconds)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--session-id", required=True)
    value.add_argument("--stale-minutes", type=int, default=20)
    value.add_argument("--poll-seconds", type=float, default=45)
    value.add_argument("--max-watch-minutes", type=int, default=50)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not 5 <= args.stale_minutes <= 180:
            raise ValueError("stale_minutes must be between 5 and 180")
        if not 5 <= args.poll_seconds <= 300:
            raise ValueError("poll_seconds must be between 5 and 300")
        if not 5 <= args.max_watch_minutes <= 50:
            raise ValueError("max_watch_minutes must be between 5 and 50")

        keys = [
            value
            for value in (
                os.environ.get("JULES_API_KEY"),
                os.environ.get("JULES_API_KEY_BACKUP"),
            )
            if value
        ]
        if not keys:
            raise RuntimeError("at least one Jules API key is required")

        name = session_name(args.session_id)
        api = API(os.environ.get("GITHUB_TOKEN") or "unused", keys)
        result = observe(
            lambda: fetch_snapshot(api, keys, name),
            stale_minutes=args.stale_minutes,
            poll_seconds=args.poll_seconds,
            max_watch_minutes=args.max_watch_minutes,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        output("reason", result["reason"])
        output("session_state", result.get("state") or "")
        output("summary", result)
        return 0
    except TransientAPIError as exc:
        print(f"TRANSIENT: {sanitize(exc, 1200)}", file=sys.stderr)
        return 75
    except Exception as exc:
        print(f"ERROR: {sanitize(exc, 1200)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

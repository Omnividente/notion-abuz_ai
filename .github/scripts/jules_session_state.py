"""Canonical Jules lifecycle, progress deltas, and recovery event identity.

Only sanitized metadata is persisted in the Actions-variable ledger. Raw transcripts,
credentials, cookies, production data, and full logs are deliberately excluded.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

CANONICAL_STATES = {
    "created", "active", "waiting", "stale",
    "completed", "failed", "stopped", "deferred",
}
TERMINAL_STATES = {"completed", "failed", "stopped", "deferred"}
RAW_STATE_MAP = {
    "STATE_UNSPECIFIED": "created",
    "QUEUED": "created",
    "PLANNING": "active",
    "IN_PROGRESS": "active",
    "AWAITING_PLAN_APPROVAL": "waiting",
    "AWAITING_USER_FEEDBACK": "waiting",
    "COMPLETED": "completed",
    "SUCCEEDED": "completed",
    "FAILED": "failed",
    "CANCELLED": "stopped",
    "STOPPED": "stopped",
}


def _epoch(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_time(value: str) -> datetime | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        return datetime.fromisoformat(clean.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def canonical_state(session: dict[str, Any], *, now: datetime, stale_minutes: int = 10) -> str:
    explicit = str(session.get("lifecycle_state") or "").lower()
    if explicit in CANONICAL_STATES:
        return explicit
    state = RAW_STATE_MAP.get(str(session.get("state") or "STATE_UNSPECIFIED").upper(), "created")
    if state not in {"active", "waiting"}:
        return state
    summary = session.get("activity_summary") or {}
    newest_epoch = max(
        _epoch(summary.get("latest_agent_epoch")),
        _epoch(summary.get("latest_user_epoch")),
        _epoch(summary.get("latest_token_epoch")),
        _epoch(summary.get("latest_activity_epoch")),
    )
    newest = (
        datetime.fromtimestamp(newest_epoch, timezone.utc)
        if newest_epoch
        else _parse_time(str(session.get("updateTime") or session.get("createTime") or ""))
    )
    if newest and now - newest >= timedelta(minutes=stale_minutes):
        return "stale"
    return state


def progress_fingerprint(session: dict[str, Any]) -> str:
    summary = session.get("activity_summary") or {}
    context = session.get("pr_context") or {}
    payload = {
        "latest_activity": _epoch(summary.get("latest_activity_epoch")),
        "latest_agent": _epoch(summary.get("latest_agent_epoch")),
        "latest_user": _epoch(summary.get("latest_user_epoch")),
        "commit": str(session.get("commit_sha") or ""),
        "diff": str(session.get("diff_sha") or ""),
        "pr": str(context.get("number") or session.get("pr_number") or ""),
        "pr_head": str(context.get("head_sha") or ""),
        "checks": [
            (
                str(check.get("name") or ""),
                str(check.get("status") or ""),
                str(check.get("conclusion") or ""),
            )
            for check in context.get("checks", [])
            if isinstance(check, dict)
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def recovery_event_id(session: dict[str, Any]) -> str:
    summary = session.get("activity_summary") or {}
    payload = {
        "task_id": str(session.get("task_id") or summary.get("task_id") or ""),
        "session_id": str(session.get("session_id") or session.get("name") or ""),
        "state": str(session.get("canonical_state") or session.get("state") or ""),
        "wait_reason": str(summary.get("wait_reason") or ""),
        "progress": str(session.get("progress_fingerprint") or ""),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def annotate_sessions(
    state: dict[str, Any],
    ledger: dict[str, Any],
    *,
    now: datetime,
    stale_minutes: int = 10,
) -> list[dict[str, Any]]:
    snapshots = ledger.setdefault("sessions", {})
    if not isinstance(snapshots, dict):
        snapshots = {}
        ledger["sessions"] = snapshots
    result = []
    for session in (state.get("jules") or {}).get("sessions", []):
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("session_id") or str(session.get("name") or "").rsplit("/", 1)[-1])
        if not session_id:
            continue
        previous = snapshots.get(session_id) if isinstance(snapshots.get(session_id), dict) else {}
        lifecycle = canonical_state(session, now=now, stale_minutes=stale_minutes)
        fingerprint = progress_fingerprint(session)
        delta = not previous or previous.get("progress_fingerprint") != fingerprint
        transition = (
            f"{previous.get('state', 'created')}->{lifecycle}"
            if previous.get("state") != lifecycle else ""
        )
        session.update({
            "canonical_state": lifecycle,
            "progress_fingerprint": fingerprint,
            "progress_delta": delta,
            "state_transition": transition,
        })
        session["recovery_event_id"] = recovery_event_id(session)
        snapshots[session_id] = {
            "task_id": str(session.get("task_id") or ""),
            "state": lifecycle,
            "raw_state": str(session.get("state") or ""),
            "transition": transition,
            "progress_fingerprint": fingerprint,
            "progress_delta": delta,
            "recovery_event_id": session["recovery_event_id"],
            "attempt": 0 if delta else int(previous.get("attempt") or 0),
            "recovery_action": None if delta else previous.get("recovery_action"),
            "next_retry": None if delta else previous.get("next_retry"),
            "observed_at": now.isoformat().replace("+00:00", "Z"),
        }
        result.append(snapshots[session_id])
    return result


def record_recovery(
    ledger: dict[str, Any],
    *,
    session_id: str,
    action: str,
    now: datetime,
    next_retry: str | None = None,
) -> None:
    snapshot = (ledger.get("sessions") or {}).get(session_id)
    if not isinstance(snapshot, dict):
        return
    snapshot["attempt"] = int(snapshot.get("attempt") or 0) + 1
    snapshot["recovery_action"] = action
    snapshot["recovery_at"] = now.isoformat().replace("+00:00", "Z")
    snapshot["next_retry"] = next_retry

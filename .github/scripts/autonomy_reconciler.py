#!/usr/bin/env python3
"""Run the durable notion_abuz task/session/PR reconciler."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from autonomy_state import *  # noqa: F403 - workflow-local module with explicit __all__


def latest_terminal_recovery_fingerprint(
    ledger: dict[str, Any], task_id: str, pr_number: int
) -> str:
    """Return a stable fingerprint for the latest terminal recovery session."""

    candidates: list[tuple[Any, str]] = []
    for session_id, row in (ledger.get("sessions") or {}).items():
        if not isinstance(row, dict):
            continue
        if str(row.get("task_id") or "") != task_id:
            continue
        if int(row.get("recovery_pr_number") or 0) != pr_number:
            continue
        state = str(row.get("session_state") or "")
        if state not in TERMINAL:
            continue
        observed = parse_time(
            row.get("session_update_at")
            or row.get("last_progress_at")
            or row.get("last_observed_at")
        )
        signal = digest(
            "terminal-pr-recovery",
            session_id,
            state,
            row.get("state_version"),
            row.get("progress_fingerprint"),
            row.get("session_update_at"),
        )
        candidates.append((observed or parse_time("1970-01-01T00:00:00Z"), signal))
    return max(candidates, default=(None, ""), key=lambda item: item[0])[1]


def pr_recovery_fingerprints(
    ledger: dict[str, Any],
    task_id: str,
    task: dict[str, Any],
    pr: dict[str, Any],
    checks: dict[str, Any],
) -> tuple[str, str]:
    """Separate external PR evidence from the bounded attempt fingerprint."""

    pr_number = int(pr.get("number") or 0)
    head_sha = str(((pr.get("head") or {}).get("sha") or ""))
    evidence_key = digest(
        "pr-recovery-evidence",
        pr_number,
        head_sha,
        checks.get("fingerprint"),
        task_fingerprint(task),
    )
    terminal_key = latest_terminal_recovery_fingerprint(ledger, task_id, pr_number)
    return evidence_key, digest("pr-session-recovery", evidence_key, terminal_key)


def terminal_session_is_superseded(
    task_state: dict[str, Any],
    *,
    task_id: str,
    session_id: str,
    session_state: str,
    active_task_ids: set[str],
) -> bool:
    """Keep a historical terminal row from replacing the active task owner."""

    current_owner = str(task_state.get("session_id") or "")
    return bool(
        session_state in TERMINAL
        and task_id in active_task_ids
        and current_owner
        and current_owner != session_id
    )


def reconcile(args: argparse.Namespace) -> int:
    github_token = os.environ.get("GITHUB_API_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    jules_keys = [x for x in (os.environ.get("JULES_API_KEY"), os.environ.get("JULES_API_KEY_BACKUP")) if x]
    if not github_token or not jules_keys:
        raise RuntimeError("GITHUB_API_TOKEN and at least one Jules API key are required")
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY") or "Omnividente/notion-abuz_ai"
    api = API(github_token, jules_keys)
    _, repo_meta = api.gh(f"/repos/{repo}")
    default_branch = str(repo_meta.get("default_branch") or "master")
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    tasks = {str(x.get("id")): x for x in manifest.get("tasks", []) if isinstance(x, dict) and x.get("id")}
    store = LedgerStore(api, repo, default_branch, args.state_branch, args.ledger_path)
    ledger, ledger_sha = store.load()
    current = now()
    actions: list[dict[str, Any]] = []
    progress: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    errors: list[str] = []
    fresh_current_work = False
    mutation_blocked = False

    def checkpoint(reason: str) -> bool:
        nonlocal ledger_sha, mutation_blocked
        if not args.apply:
            return True
        if mutation_blocked:
            return False
        try:
            ledger_sha = store.save(ledger, ledger_sha)
            return True
        except Exception as exc:
            mutation_blocked = True
            errors.append(f"durable checkpoint failed before {reason}: {sanitize(exc, 700)}")
            return False

    pulls = paginate_gh(api, f"/repos/{repo}/pulls?state=open")
    autonomous = [pr for pr in pulls if is_autonomous_pr(pr)]
    pr_by_task = {task_id_from_pr(pr, list(tasks)): pr for pr in autonomous if task_id_from_pr(pr, list(tasks))}
    check_cache: dict[tuple[int, str], dict[str, Any]] = {}

    def checks_for(pr: dict[str, Any] | None) -> dict[str, Any]:
        cache_key = (
            int((pr or {}).get("number") or 0),
            str(((pr or {}).get("head") or {}).get("sha") or ""),
        )
        if cache_key not in check_cache:
            check_cache[cache_key] = check_context(api, repo, pr)
        return check_cache[cache_key]

    active_task_ids: set[str] = set()
    blocking_active = 0

    source = f"sources/github/{repo}"
    session_rows = list_sessions(api, source)
    inspected_sessions = sessions_for_reconcile(session_rows, ledger, current=current)
    for key, session in inspected_sessions:
        terminated = False
        state = str(session.get("state") or "STATE_UNSPECIFIED")
        session_name = str(session.get("name") or "")
        session_id = session_name.rsplit("/", 1)[-1]
        activities = list_activities(api, key, session_name)
        summary = activity_summary(activities)
        previous = dict((ledger.get("sessions") or {}).get(session_id, {}))
        task_id = summary.get("task_id") or previous.get("task_id") or ""
        task_state_id = str(task_id or f"__unknown_session__:{session_id}")
        task = tasks.get(str(task_id))
        pr = pr_by_task.get(str(task_id))
        checks = checks_for(pr)
        pr_fp = digest((pr or {}).get("number"), ((pr or {}).get("head") or {}).get("sha"), checks.get("fingerprint"))
        version = state_version(previous, state, str(summary.get("fingerprint")), pr_fp)
        progress_fp = digest(summary.get("agent_fingerprint"), ((pr or {}).get("head") or {}).get("sha"), checks.get("fingerprint"), (task or {}).get("status"), state)
        delta = bool(previous.get("progress_fingerprint") and previous.get("progress_fingerprint") != progress_fp)
        latest_observed = summary.get("latest_agent_at") or session.get("updateTime") or session.get("createTime")
        initial_recent = state in ACTIVE and not previous.get("progress_fingerprint") and minutes_since(latest_observed, current) < args.fresh_progress_minutes
        record = {**previous, "task_id": task_id, "session_state": state, "state_version": version, "activity_fingerprint": summary.get("fingerprint"), "pr_fingerprint": pr_fp, "progress_fingerprint": progress_fp, "last_observed_at": iso(), "session_update_at": session.get("updateTime") or previous.get("session_update_at")}
        # Keep the in-memory ledger pointing at this record before any
        # side-effect checkpoint. Subsequent mutations are then durable intents.
        ledger["sessions"][session_id] = record
        if delta or initial_recent:
            record["last_progress_at"] = iso()
            record["recoveries_without_progress"] = 0
            progress.append({"session_id": session_id, "task_id": task_id, "kind": "observed_delta" if delta else "initial_recent_activity"})
        durable_task_state = (ledger.get("tasks") or {}).get(task_state_id, {})
        recovery_pr_number = previous.get("recovery_pr_number") or (
            durable_task_state.get("recovery_pr_number") if isinstance(durable_task_state, dict) else None
        )
        recovering_open_pr = bool(
            recovery_pr_number
            and pr
            and int((pr or {}).get("number") or 0) == int(recovery_pr_number)
        )
        task_terminal_in_manifest = bool(
            task and task.get("status") not in {"todo", "doing"} and not recovering_open_pr
        )
        if state in ACTIVE and task_terminal_in_manifest:
            cleanup_key = digest("terminal-manifest-session", session_id, task_id, task.get("status"), version)
            cleanup_intent = ledger["messages"].setdefault(
                cleanup_key,
                {
                    "kind": "terminal_manifest_session_cleanup",
                    "session_id": session_id,
                    "task_id": task_id,
                    "sent_at": iso(),
                    "verified_at": None,
                    "state_version": version,
                },
            )
            if cleanup_intent.get("verified_at"):
                terminated = True
            else:
                if checkpoint(f"terminal session cleanup {session_id}"):
                    try:
                        if args.apply:
                            api.jules(key, session_name, method="DELETE", body=None, allow=(404,))
                        cleanup_intent["verified_at"] = iso()
                        actions.append({"action": "terminate_terminal_task_session", "session_id": session_id, "task_id": task_id, "manifest_status": task.get("status")})
                        terminated = True
                    except Exception as exc:
                        cleanup_intent["delivery_error"] = sanitize(exc, 500)
                        errors.append(f"terminal session cleanup failed for {session_id}: {sanitize(exc, 600)}")
            if not terminated:
                blocking_active += 1
                active_task_ids.add(str(task_id))
            record["ignored_reason"] = f"manifest_task_{task.get('status')}"
        elif state in ACTIVE:
            blocking_active += 1
            fresh_current_work = fresh_current_work or minutes_since(latest_observed, current) < args.stale_minutes
            if task_id:
                active_task_ids.add(str(task_id))
        if state == "AWAITING_PLAN_APPROVAL" and not task_terminal_in_manifest:
            approval_key = digest("approve-plan", session_id, version, summary.get("agent_fingerprint"))
            approval_intent = ledger["messages"].setdefault(
                approval_key,
                {
                    "kind": "plan_approval",
                    "session_id": session_id,
                    "task_id": task_id,
                    "sent_at": iso(),
                    "verified_at": None,
                },
            )
            if not approval_intent.get("verified_at"):
                if checkpoint(f"plan approval {session_id}"):
                    try:
                        if args.apply:
                            api.jules(key, f"{session_name}:approvePlan", method="POST", body={})
                        approval_intent["verified_at"] = iso()
                        actions.append({"action": "approve_plan", "session_id": session_id, "task_id": task_id, "key": approval_key})
                    except Exception as exc:
                        approval_intent["delivery_error"] = sanitize(exc, 500)
                        errors.append(f"plan approval failed for {session_id}: {sanitize(exc, 600)}")
        elif state in ACTIVE and not task_terminal_in_manifest:
            pending_key = str(record.get("pending_message_key") or "")
            if pending_key:
                try:
                    verified, refreshed = verify_message(api, key, session_name, pending_key, str(summary.get("fingerprint")))
                except Exception as exc:
                    verified, refreshed = False, summary
                    errors.append(f"pending recovery verification failed for {session_id}: {sanitize(exc, 500)}")
                if verified:
                    record.pop("pending_message_key", None)
                    record["last_verified_message_key"] = pending_key
                    ledger["messages"].setdefault(pending_key, {})["verified_at"] = iso()
                    summary = refreshed
                    actions.append({"action": "verify_previous_message", "session_id": session_id, "key": pending_key})
                else:
                    intent = ledger["messages"].setdefault(pending_key, {"session_id": session_id, "task_id": task_id, "sent_at": iso(), "verified_at": None})
                    delivery_attempts = int(intent.get("delivery_attempts") or 1)
                    next_retry = parse_time(intent.get("next_retry_at")) or current
                    if delivery_attempts >= 2:
                        record.pop("pending_message_key", None)
                        record["recoveries_without_progress"] = max(args.max_recoveries, int(record.get("recoveries_without_progress") or 0))
                        pending_key = ""
                        errors.append(f"recovery delivery for {session_id} remained unverified after bounded retry; deferring session")
                    elif next_retry <= current and not mutation_blocked:
                        retry_packet = build_packet(task, summary, int(record.get("recoveries_without_progress") or 0), False, "retry_unverified_recovery_delivery", pr, checks)
                        intent["delivery_attempts"] = delivery_attempts + 1
                        intent["last_attempt_at"] = iso()
                        intent["next_retry_at"] = iso(current + timedelta(minutes=5))
                        if checkpoint(f"bounded recovery delivery retry {pending_key}"):
                            try:
                                if args.apply:
                                    api.jules(key, f"{session_name}:sendMessage", method="POST", body={"prompt": recovery_prompt(pending_key, retry_packet)})
                                    retry_verified, retry_summary = verify_message(api, key, session_name, pending_key, str(summary.get("fingerprint")))
                                else:
                                    retry_verified, retry_summary = True, summary
                                if retry_verified:
                                    record.pop("pending_message_key", None)
                                    record["last_verified_message_key"] = pending_key
                                    intent["verified_at"] = iso()
                                    summary = retry_summary
                                    actions.append({"action": "retry_recovery_delivery", "session_id": session_id, "key": pending_key, "verified": True})
                                else:
                                    errors.append(f"bounded recovery delivery retry remained unverified for {session_id}")
                            except Exception as exc:
                                intent["delivery_error"] = sanitize(exc, 500)
                                errors.append(f"bounded recovery delivery retry failed for {session_id}: {sanitize(exc, 600)}")
                    else:
                        errors.append(f"unverified prior recovery message for {session_id}; waiting for bounded retry window")
            scope_request = summary.get("scope_request") if isinstance(summary.get("scope_request"), dict) else None
            if scope_request:
                scope_key = digest("scope-request", session_id, scope_request)
                if scope_key not in ledger["messages"]:
                    approved, scope_reason = assess_scope_request(task or {}, scope_request)
                    task_state = dict(ledger["tasks"].get(task_state_id, {}))
                    if approved:
                        expanded = sorted(set((task or {}).get("allowed_paths", [])) | set(scope_request.get("paths", [])))
                        task_state.update(
                            {
                                "scope_override": expanded,
                                "scope_decision": "approved_same_task",
                                "scope_decision_reason": scope_reason,
                                "scope_evidence": scope_request.get("evidence"),
                                "scope_risk": str(scope_request.get("risk") or (task or {}).get("risk") or "").lower(),
                                "scope_requested_paths": sorted(set(scope_request.get("paths", []))),
                                "scope_request_key": scope_key,
                                "scope_session_id": session_id,
                                "scope_task_fingerprint": task_fingerprint(task or {}),
                                "scope_approved_at": iso(),
                            }
                        )
                        actions.append({"action": "approve_scope_expansion", "task_id": task_id, "session_id": session_id, "paths": scope_request.get("paths", []), "risk": scope_request.get("risk")})
                    else:
                        task_state.update(
                            {
                                "scope_decision": "deferred_for_guarded_review",
                                "scope_decision_reason": scope_reason,
                                "scope_request": scope_request,
                            }
                        )
                    ledger["tasks"][task_state_id] = task_state
                    ledger["messages"][scope_key] = {"kind": "scope_decision", "task_id": task_id, "session_id": session_id, "sent_at": iso(), "verified_at": None, "approved": approved, "reason": scope_reason}
                    if checkpoint(f"scope decision {scope_key}"):
                        decision = {
                            "task_id": task_id,
                            "approved": approved,
                            "paths": scope_request.get("paths", []),
                            "risk": scope_request.get("risk"),
                            "reason": scope_reason,
                            "instruction": "For an approved expansion, update this same task's allowed_paths in the same code PR and include the reproduced evidence; never create a separate manifest-only recovery PR. For a rejected expansion, emit AUTONOMY_DEFER_REQUEST.",
                        }
                        try:
                            if args.apply:
                                api.jules(key, f"{session_name}:sendMessage", method="POST", body={"prompt": f"{TOKEN} key={scope_key}\n\nControlled scope decision:\n```json\n{json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True)}\n```"})
                                verified, _ = verify_message(api, key, session_name, scope_key, str(summary.get("fingerprint")))
                            else:
                                verified = True
                            if verified:
                                ledger["messages"][scope_key]["verified_at"] = iso()
                            else:
                                errors.append(f"scope decision verification failed for {session_id}")
                            actions.append({"action": "deliver_scope_decision", "task_id": task_id, "session_id": session_id, "key": scope_key, "approved": approved, "verified": verified})
                        except Exception as exc:
                            ledger["messages"][scope_key]["delivery_error"] = sanitize(exc, 500)
                            errors.append(f"scope decision delivery failed for {session_id}: {sanitize(exc, 600)}")
            defer_request = summary.get("defer_request") if isinstance(summary.get("defer_request"), dict) else None
            if defer_request and not pending_key:
                defer_key = digest("agent-defer-request", session_id, defer_request)
                requested_review = parse_time(defer_request.get("recheck_at"))
                requested_retry_at = requested_review if requested_review and requested_review > current else current + timedelta(minutes=args.defer_minutes)
                defer_intent = ledger["messages"].setdefault(
                    defer_key,
                    {"kind": "agent_defer_request", "task_id": task_id, "session_id": session_id, "sent_at": iso(), "verified_at": None, "retry_at": iso(requested_retry_at), "request": defer_request},
                )
                retry_at = parse_time(defer_intent.get("retry_at")) or requested_retry_at
                task_state = dict(ledger["tasks"].get(task_state_id, {}))
                task_state.update(
                    {
                        "state": "deferred",
                        "session_id": None,
                        "retry_at": iso(retry_at),
                        "next_review_at": iso(retry_at),
                        "retry_condition": defer_request.get("retry_condition") or "new concrete evidence is available",
                        "evidence_requirement": defer_request.get("evidence_requirement") or defer_request.get("evidence") or "reproduced evidence",
                        "deferred_evidence_fingerprint": progress_fp,
                        "deferred_task_fingerprint": task_fingerprint(task or {}),
                        "reason": defer_request.get("reason") or "agent requested evidence-bound defer",
                    }
                )
                ledger["tasks"][task_state_id] = task_state
                if defer_intent.get("verified_at"):
                    blocking_active = max(0, blocking_active - 1)
                    active_task_ids.discard(str(task_id))
                    terminated = True
                    pending_key = defer_key
                else:
                    if checkpoint(f"agent defer request {session_id}"):
                        try:
                            if args.apply:
                                api.jules(key, session_name, method="DELETE", body=None, allow=(404,))
                            defer_intent["verified_at"] = iso()
                            actions.append({"action": "accept_defer_request", "task_id": task_id, "session_id": session_id, "retry_at": iso(retry_at), "key": defer_key})
                            blocking_active = max(0, blocking_active - 1)
                            active_task_ids.discard(str(task_id))
                            terminated = True
                            pending_key = defer_key
                        except Exception as exc:
                            defer_intent["delivery_error"] = sanitize(exc, 500)
                            errors.append(f"defer request termination failed for {session_id}: {sanitize(exc, 600)}")
            latest = latest_observed
            stale = minutes_since(latest, current) >= args.stale_minutes
            failed = bool(checks.get("failed"))
            recover_now, recovery_trigger = should_recover_session(
                failed_checks=failed,
                previous_pr_fingerprint=previous.get("pr_fingerprint"),
                current_pr_fingerprint=pr_fp,
                stale=stale,
            )
            attempts = int(record.get("recoveries_without_progress") or 0)
            if not pending_key and recover_now:
                if attempts >= args.max_recoveries:
                    retry_at = current + timedelta(minutes=args.defer_minutes)
                    task_state = dict(ledger["tasks"].get(task_state_id, {}))
                    task_state.update(
                        {
                            "state": "deferred",
                            "session_id": None,
                            "retry_at": iso(retry_at),
                            "next_review_at": iso(retry_at),
                            "retry_condition": "new manifest, session, PR or check evidence after next_review_at",
                            "evidence_requirement": "progress fingerprint or task definition must change before redispatch",
                            "deferred_evidence_fingerprint": progress_fp,
                            "deferred_task_fingerprint": task_fingerprint(task or {}),
                            "reason": "bounded recovery exhausted without progress delta",
                        }
                    )
                    ledger["tasks"][task_state_id] = task_state
                    record["terminal_reason"] = "bounded_recovery_exhausted"
                    terminal_key = digest("terminate-and-defer", session_id, version, progress_fp)
                    ledger["messages"].setdefault(
                        terminal_key,
                        {"kind": "terminate_and_defer", "session_id": session_id, "task_id": task_id, "sent_at": iso(), "verified_at": None},
                    )
                    if checkpoint(f"terminate and defer {session_id}"):
                        try:
                            if args.apply:
                                api.jules(key, session_name, method="DELETE", body=None, allow=(404,))
                            ledger["messages"][terminal_key]["verified_at"] = iso()
                            actions.append({"action": "terminate_and_defer", "session_id": session_id, "task_id": task_id, "retry_at": iso(retry_at), "key": terminal_key})
                            blocking_active = max(0, blocking_active - 1)
                            active_task_ids.discard(str(task_id))
                            terminated = True
                        except Exception as exc:
                            errors.append(f"terminate/defer failed for {session_id}: {sanitize(exc, 600)}")
                else:
                    wait_reason = (
                        "new_failed_checks"
                        if recovery_trigger == "new_failed_check_evidence"
                        else f"no_progress_for_{int(minutes_since(latest, current))}_minutes"
                    )
                    packet_task = dict(task or {})
                    scope_override = (ledger.get("tasks") or {}).get(task_state_id, {}).get("scope_override")
                    if isinstance(scope_override, list):
                        packet_task["allowed_paths"] = scope_override
                    packet = build_packet(packet_task, summary, attempts, delta, wait_reason, pr, checks)
                    send_key = message_key(session_id, version, str(summary.get("fingerprint")))
                    if send_key not in ledger["messages"]:
                        record["pending_message_key"] = send_key
                        ledger["messages"][send_key] = {"session_id": session_id, "task_id": task_id, "state_version": version, "activity_fingerprint": summary.get("fingerprint"), "sent_at": iso(), "verified_at": None, "packet_hash": digest(packet), "delivery_attempts": 1, "next_retry_at": iso(current + timedelta(minutes=5))}
                        if checkpoint(f"recovery message {send_key}"):
                            try:
                                if args.apply:
                                    api.jules(key, f"{session_name}:sendMessage", method="POST", body={"prompt": recovery_prompt(send_key, packet)})
                                    verified, refreshed = verify_message(api, key, session_name, send_key, str(summary.get("fingerprint")))
                                else:
                                    verified, refreshed = True, summary
                                if verified:
                                    record.pop("pending_message_key", None)
                                    record["last_verified_message_key"] = send_key
                                    record["recoveries_without_progress"] = attempts + 1
                                    ledger["messages"][send_key]["verified_at"] = iso()
                                    record["post_send_activity_fingerprint"] = refreshed.get("fingerprint")
                                else:
                                    errors.append(f"post-send verification failed for {session_id}")
                                actions.append({"action": "send_recovery", "session_id": session_id, "task_id": task_id, "key": send_key, "verified": verified, "wait_reason": wait_reason})
                            except Exception as exc:
                                ledger["messages"][send_key]["delivery_error"] = sanitize(exc, 500)
                                errors.append(f"recovery delivery failed for {session_id}: {sanitize(exc, 600)}")
        ledger["sessions"][session_id] = record
        if task_id and not terminated and not task_terminal_in_manifest:
            task_state = dict(ledger["tasks"].get(task_state_id, {}))
            if terminal_session_is_superseded(
                task_state,
                task_id=str(task_id),
                session_id=session_id,
                session_state=state,
                active_task_ids=active_task_ids,
            ):
                record["ignored_reason"] = f"superseded_by_active_session:{task_state.get('session_id')}"
            else:
                task_state["current_evidence_fingerprint"] = progress_fp
                if state in ACTIVE:
                    task_state.update({"state": "active", "session_id": session_id, "session_name": session_name, "session_state": state, "pr_number": (pr or {}).get("number"), "last_observed_at": iso()})
                elif task_state.get("state") != "deferred":
                    task_state.update({"state": state.lower(), "session_id": session_id, "session_name": session_name, "session_state": state, "pr_number": (pr or {}).get("number"), "last_observed_at": iso()})
                ledger["tasks"][task_state_id] = task_state

    for task_id, pr in pr_by_task.items():
        if task_id in active_task_ids:
            continue
        checks = checks_for(pr)
        pr_number = int(pr.get("number") or 0)
        task = tasks.get(task_id) or {}
        task_state = dict(ledger["tasks"].get(task_id, {}))
        pr_progress_fp = digest(((pr.get("head") or {}).get("sha") or ""), checks.get("fingerprint"), pr.get("mergeable_state"))
        recovery_evidence_key, recovery_key = pr_recovery_fingerprints(
            ledger, task_id, task, pr, checks
        )
        previous_recovery_evidence_key = str(task_state.get("pr_recovery_evidence_key") or "")
        recovery_evidence_changed = bool(
            previous_recovery_evidence_key
            and previous_recovery_evidence_key != recovery_evidence_key
        )
        if recovery_evidence_changed:
            task_state["pr_session_recoveries"] = 0
            for field in (
                "retry_at",
                "next_review_at",
                "retry_condition",
                "evidence_requirement",
                "deferred_evidence_fingerprint",
                "deferred_task_fingerprint",
                "reason",
            ):
                task_state.pop(field, None)
        deferred_unchanged = bool(
            task_state.get("state") == "deferred"
            and previous_recovery_evidence_key == recovery_evidence_key
            and task_state.get("pr_session_recovery_key") == recovery_key
        )
        pr_delta = bool(task_state.get("progress_fingerprint") and task_state.get("progress_fingerprint") != pr_progress_fp)
        pr_initial_recent = not task_state.get("progress_fingerprint") and minutes_since(pr.get("updated_at") or pr.get("created_at"), current) < args.fresh_progress_minutes
        fresh_current_work = fresh_current_work or minutes_since(pr.get("updated_at") or pr.get("created_at"), current) < args.stale_minutes
        pending_pr_recovery = bool(
            task_state.get("state") in {"pr_recovery_dispatch_requested", "session_create_requested", "session_created"}
            and (parse_time(task_state.get("lease_expires_at")) or current) > current
        )
        expired_pr_recovery = bool(
            task_state.get("state") in {"pr_recovery_dispatch_requested", "session_create_requested", "session_created"}
            and (parse_time(task_state.get("lease_expires_at")) or current) <= current
        )
        retry_failed_dispatch = bool(
            task_state.get("state") == "dispatch_failed"
            and (parse_time(task_state.get("retry_at")) or current) <= current
        )
        task_state.update({"pr_number": pr_number, "session_id": None, "progress_fingerprint": pr_progress_fp, "last_observed_at": iso()})
        if not pending_pr_recovery and not deferred_unchanged:
            task_state["state"] = "pr_open_without_active_session"
        if pr_delta or pr_initial_recent:
            task_state["last_progress_at"] = iso()
            progress.append({"task_id": task_id, "pr_number": pr_number, "kind": "pr_delta" if pr_delta else "initial_recent_pr"})
        if checks.get("failed"):
            key = digest("pr-recovery", pr_number, ((pr.get("head") or {}).get("sha") or ""), checks.get("fingerprint"))
            if key not in ledger["messages"]:
                packet = build_packet(tasks.get(task_id), {"task_id": task_id, "last_jules_message": "No active Jules session is visible for this open PR."}, int(task_state.get("pr_recoveries") or 0), False, "failed_checks_without_active_session", pr, checks)
                body = f"<!-- {TOKEN} key={key} -->\n\nВнешний reconciler обнаружил failed checks без активной Jules session. Recovery будет привязан к этой ветке: исправь этот же PR и не создавай новый PR.\n\n```json\n{json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True)}\n```"
                ledger["messages"][key] = {"kind": "pr_recovery", "task_id": task_id, "pr_number": pr_number, "sent_at": iso(), "verified_at": None, "packet_hash": digest(packet)}
                task_state["pr_recoveries"] = int(task_state.get("pr_recoveries") or 0) + 1
                ledger["tasks"][task_id] = task_state
                if checkpoint(f"PR recovery comment {pr_number}"):
                    try:
                        if args.apply:
                            api.gh(f"/repos/{repo}/issues/{pr_number}/comments", method="POST", body={"body": body})
                        ledger["messages"][key]["verified_at"] = iso()
                        actions.append({"action": "comment_pr_recovery", "task_id": task_id, "pr_number": pr_number, "key": key})
                    except Exception as exc:
                        ledger["messages"][key]["delivery_error"] = sanitize(exc, 500)
                        errors.append(f"PR recovery comment failed for {pr_number}: {sanitize(exc, 600)}")
            attempts = int(task_state.get("pr_session_recoveries") or 0)
            if deferred_unchanged:
                blocked.append(
                    {
                        "task_id": task_id,
                        "pr_number": pr_number,
                        "reason": task_state.get("reason") or "bounded in-place PR recovery exhausted",
                        "retry_condition": task_state.get("retry_condition") or "new PR, check or task evidence",
                        "evidence_requirement": task_state.get("evidence_requirement") or "new commit or check evidence on the existing PR",
                        "next_review_at": task_state.get("next_review_at"),
                    }
                )
            elif (
                not mutation_blocked
                and blocking_active == 0
                and not pending_pr_recovery
                and (
                    task_state.get("pr_session_recovery_key") != recovery_key
                    or retry_failed_dispatch
                    or expired_pr_recovery
                )
            ):
                if attempts >= args.max_recoveries:
                    retry_at = current + timedelta(minutes=args.defer_minutes)
                    task_state.update(
                        {
                            "state": "deferred",
                            "retry_at": iso(retry_at),
                            "next_review_at": iso(retry_at),
                            "retry_condition": "PR head, failed-check fingerprint or task definition changes",
                            "evidence_requirement": "new commit, check result or concrete task evidence on the existing PR",
                            "deferred_evidence_fingerprint": pr_progress_fp,
                            "deferred_task_fingerprint": task_fingerprint(task),
                            "pr_recovery_evidence_key": recovery_evidence_key,
                            "pr_session_recovery_key": recovery_key,
                            "reason": "bounded in-place PR recovery exhausted",
                        }
                    )
                    blocked_row = {
                        "task_id": task_id,
                        "pr_number": pr_number,
                        "reason": task_state["reason"],
                        "retry_condition": task_state["retry_condition"],
                        "evidence_requirement": task_state["evidence_requirement"],
                        "next_review_at": task_state["next_review_at"],
                    }
                    blocked.append(blocked_row)
                    actions.append({"action": "defer_pr_recovery", **blocked_row})
                else:
                    generation = int(task_state.get("dispatch_generation") or 0) + 1
                    dispatch_key = digest("pr-recovery-dispatch", task_id, pr_number, recovery_key, generation)
                    failed_names = [str(row.get("name") or "failed check") for row in checks.get("failed", []) if isinstance(row, dict)]
                    recovery_reason = sanitize("failed checks on existing PR: " + ", ".join(failed_names), 500)
                    task_state.update(
                        {
                            "state": "pr_recovery_dispatch_requested",
                            "dispatch_key": dispatch_key,
                            "dispatch_generation": generation,
                            "lease_expires_at": iso(current + timedelta(minutes=args.lease_minutes)),
                            "dispatch_requested_at": iso(),
                            "pr_recovery_evidence_key": recovery_evidence_key,
                            "pr_session_recovery_key": recovery_key,
                            "pr_session_recoveries": attempts + 1,
                            "recovery_pr_number": pr_number,
                            "recovery_pr_head": str(((pr.get("head") or {}).get("sha") or "")),
                            "recovery_reason": recovery_reason,
                        }
                    )
                    ledger["tasks"][task_id] = task_state
                    if checkpoint(f"in-place PR recovery dispatch {pr_number}"):
                        try:
                            if args.apply:
                                api.gh(
                                    f"/repos/{repo}/actions/workflows/jules_next_task.yml/dispatches",
                                    method="POST",
                                    body={
                                        "ref": default_branch,
                                        "inputs": {
                                            "task_id": task_id,
                                            "lease_key": dispatch_key,
                                            "focus": str((tasks.get(task_id) or {}).get("area") or "proxy"),
                                            "risk_ceiling": "high" if (tasks.get(task_id) or {}).get("risk") == "high" else "medium",
                                            "allow_parallel": "false",
                                            "recovery_pr_number": str(pr_number),
                                            "recovery_pr_head": str(((pr.get("head") or {}).get("sha") or "")),
                                            "recovery_reason": recovery_reason,
                                        },
                                    },
                                )
                            actions.append({"action": "dispatch_in_place_pr_recovery", "task_id": task_id, "pr_number": pr_number, "dispatch_key": dispatch_key, "generation": generation})
                        except Exception as exc:
                            task_state.update({"state": "dispatch_failed", "retry_at": iso(current + timedelta(minutes=5)), "lease_expires_at": iso(current + timedelta(minutes=5)), "dispatch_error": sanitize(exc, 500)})
                            errors.append(f"in-place PR recovery dispatch failed for #{pr_number}: {sanitize(exc, 600)}")
        ledger["tasks"][task_id] = task_state

    eligible = choose_task(manifest, ledger, current)
    if not mutation_blocked and blocking_active == 0 and not autonomous:
        if eligible:
            task_id = str(eligible.get("id") or "")
            task_state = dict(ledger["tasks"].get(task_id, {}))
            generation = int(task_state.get("dispatch_generation") or 0) + 1
            dispatch_key = digest("dispatch", task_id, generation, task_fingerprint(eligible))
            if task_state.get("dispatch_key") != dispatch_key:
                inputs = {"task_id": task_id, "lease_key": dispatch_key, "focus": str(eligible.get("area") or "proxy"), "risk_ceiling": "high" if eligible.get("risk") == "high" else "medium", "allow_parallel": "false"}
                task_state.update({"state": "dispatch_requested", "dispatch_key": dispatch_key, "dispatch_generation": generation, "lease_expires_at": iso(current + timedelta(minutes=args.lease_minutes)), "dispatch_requested_at": iso(), "task_fingerprint": task_fingerprint(eligible)})
                ledger["tasks"][task_id] = task_state
                ledger["tasks"]["__scheduler__"] = {
                    "last_dispatched_task_id": task_id,
                    "last_dispatched_kind": task_kind(eligible),
                    "last_dispatch_key": dispatch_key,
                    "last_dispatched_at": iso(),
                }
                if checkpoint(f"task dispatch {task_id}"):
                    try:
                        if args.apply:
                            api.gh(f"/repos/{repo}/actions/workflows/jules_next_task.yml/dispatches", method="POST", body={"ref": default_branch, "inputs": inputs})
                        actions.append({"action": "dispatch_task", "task_id": task_id, "dispatch_key": dispatch_key, "generation": generation})
                    except Exception as exc:
                        task_state.update({"state": "dispatch_failed", "retry_at": iso(current + timedelta(minutes=5)), "lease_expires_at": iso(current + timedelta(minutes=5)), "dispatch_error": sanitize(exc, 500)})
                        errors.append(f"task dispatch failed for {task_id}: {sanitize(exc, 600)}")
        else:
            replenish = dict(ledger["tasks"].get("__replenishment__", {}))
            if minutes_since(replenish.get("requested_at"), current) >= args.replenish_cooldown_minutes:
                ledger["tasks"]["__replenishment__"] = {"state": "evidence_requested", "requested_at": iso(), "reason": "project queue has no eligible task; manifest-only automation meta-task is forbidden"}
                if checkpoint("project queue evidence report"):
                    try:
                        if args.apply:
                            api.gh(f"/repos/{repo}/actions/workflows/automation_health.yml/dispatches", method="POST", body={"ref": default_branch, "inputs": {"mode": "shadow"}})
                        actions.append({"action": "request_project_evidence_report", "mode": "shadow"})
                    except Exception as exc:
                        errors.append(f"project evidence report dispatch failed: {sanitize(exc, 600)}")
                errors.append("no eligible project task; a shadow evidence report was requested and no manifest-only recovery task was created")

    fresh = fresh_current_work
    pending_leases = sorted(
        task_id
        for task_id, row in ledger["tasks"].items()
        if isinstance(row, dict)
        and row.get("state") in {"dispatch_requested", "pr_recovery_dispatch_requested", "session_create_requested", "session_created"}
        and (parse_time(row.get("lease_expires_at")) or current) > current
    )
    work = bool(blocking_active or autonomous or eligible or pending_leases)
    if no_op_violation(
        work=work,
        actions=len(actions),
        progress=len(progress),
        fresh=fresh,
        blocked=len(blocked),
    ):
        errors.append("work exists but cycle produced no action or progress delta")
    source_fingerprint = digest(
        sorted((sid, row.get("session_state"), row.get("activity_fingerprint"), row.get("pr_fingerprint")) for sid, row in ledger["sessions"].items() if isinstance(row, dict)),
        sorted((int(pr.get("number") or 0), ((pr.get("head") or {}).get("sha") or "")) for pr in autonomous),
        str((eligible or {}).get("id") or ""),
        pending_leases,
    )
    cycle = {"at": iso(), "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "source_fingerprint": source_fingerprint, "listed_sessions": len(session_rows), "inspected_sessions": len(inspected_sessions), "active_sessions": blocking_active, "open_autonomous_prs": len(autonomous), "eligible_task_id": str((eligible or {}).get("id") or ""), "pending_leases": pending_leases, "actions": actions, "progress": progress, "blocked": blocked, "errors": errors}
    ledger["cycles"] = ledger.get("cycles", [])[-49:] + [cycle]
    if args.apply and not mutation_blocked:
        try:
            ledger_sha = store.save(ledger, ledger_sha)
        except Exception as exc:
            errors.append(f"final durable ledger save failed; prior intents remain authoritative: {sanitize(exc, 700)}")
    elif args.apply and mutation_blocked:
        errors.append("final ledger save skipped after a failed pre-action checkpoint; no unexecuted intent was committed")
    result = {"repo": repo, "default_branch": default_branch, "state_branch": args.state_branch, "ledger_revision": ledger.get("revision"), "migration": ledger.get("migration"), "source_fingerprint": source_fingerprint, "listed_sessions": len(session_rows), "inspected_sessions": len(inspected_sessions), "active_sessions": blocking_active, "open_autonomous_prs": len(autonomous), "eligible_task_id": str((eligible or {}).get("id") or ""), "eligible_task_kind": task_kind(eligible or {}), "pending_leases": pending_leases, "actions": actions, "progress": progress, "blocked": blocked, "fresh_progress": fresh, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    output("summary", result)
    output("healthy", str(not errors).lower())
    return 1 if errors else 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--manifest", default="agent_tasks.json")
    value.add_argument("--repo", default="")
    value.add_argument("--state-branch", default="automation-state-v2")
    value.add_argument("--ledger-path", default="autonomy/ledger.json")
    value.add_argument("--stale-minutes", type=int, default=20)
    value.add_argument("--max-recoveries", type=int, default=2)
    value.add_argument("--defer-minutes", type=int, default=60)
    value.add_argument("--lease-minutes", type=int, default=30)
    value.add_argument("--fresh-progress-minutes", type=int, default=20)
    value.add_argument("--replenish-cooldown-minutes", type=int, default=30)
    value.add_argument("--apply", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        return reconcile(parser().parse_args(argv))
    except Exception as exc:  # workflow boundary: fail closed
        print(f"ERROR: {sanitize(exc, 1600)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

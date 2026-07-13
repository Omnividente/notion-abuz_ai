#!/usr/bin/env python3
"""Execute exactly one Jules task protected by the durable ledger lease."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autonomy_state import ACTIVE, API, LedgerStore, activity_summary, iso, list_activities, list_sessions, now, output, parse_time, sanitize

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def select_exact_task(
    manifest: dict[str, Any],
    task_id: str,
    risk_ceiling: str,
    *,
    allow_terminal_pr_recovery: bool = False,
) -> dict[str, Any]:
    for task in manifest.get("tasks", []):
        if not isinstance(task, dict) or str(task.get("id") or "") != task_id:
            continue
        accepted_statuses = {"todo", "blocked", "deferred"} if allow_terminal_pr_recovery else {"todo"}
        if task.get("status") not in accepted_statuses:
            raise RuntimeError(f"task {task_id} is {task.get('status')!r}, expected one of {sorted(accepted_statuses)}")
        risk = str(task.get("risk") or "")
        if risk not in RISK_ORDER or RISK_ORDER[risk] > RISK_ORDER.get(risk_ceiling, 1):
            raise RuntimeError(f"task {task_id} risk {risk!r} exceeds ceiling {risk_ceiling!r}")
        return task
    raise RuntimeError(f"task {task_id!r} not found")


def validate_lease(ledger: dict[str, Any], task_id: str, lease_key: str, current: datetime) -> dict[str, Any]:
    task_state = dict((ledger.get("tasks") or {}).get(task_id, {}))
    if task_state.get("state") not in {"dispatch_requested", "pr_recovery_dispatch_requested"}:
        raise RuntimeError(f"task {task_id} has no executable durable lease")
    if task_state.get("dispatch_key") != lease_key:
        raise RuntimeError(f"task {task_id} lease key does not match durable ledger")
    expires = parse_time(task_state.get("lease_expires_at"))
    if expires is None or expires <= current:
        raise RuntimeError(f"task {task_id} lease expired")
    return task_state


def render_prompt(args: argparse.Namespace, task: dict[str, Any]) -> str:
    command = [
        sys.executable,
        ".github/scripts/render-jules-next-task-prompt.py",
        "--template",
        ".github/prompts/jules_next_task_prompt.txt",
        "--repository",
        args.repo,
        "--focus",
        args.focus or str(task.get("area") or "proxy"),
        "--task-id",
        args.task_id,
        "--selected-task-title",
        str(task.get("title") or args.task_id),
        "--selected-task-score",
        "durable-ledger",
        "--selected-task-reason",
        "selected by the durable task/session/PR reconciler",
        "--recovery-session-id",
        "",
        "--recovery-reason",
        args.recovery_reason,
        "--risk-ceiling",
        args.risk_ceiling,
    ]
    rendered = subprocess.check_output(command, text=True)
    if args.recovery_pr_number:
        return (
            f"RECOVER EXISTING PR #{args.recovery_pr_number}.\n"
            f"Expected head SHA: {args.recovery_pr_head}.\n"
            "Checkout the existing PR head branch, fix its failed checks, sync it with current master, "
            "and push commits to that same branch. Do not create a new PR, do not switch task_id, and "
            "do not replace the runtime diff with a manifest-only change.\n\n"
            + rendered
        )
    return rendered


def execute(args: argparse.Namespace) -> int:
    github_token = os.environ.get("GITHUB_API_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    jules_keys = [value for value in (os.environ.get("JULES_API_KEY"), os.environ.get("JULES_API_KEY_BACKUP")) if value]
    if not github_token or not jules_keys:
        raise RuntimeError("GITHUB_API_TOKEN and at least one Jules API key are required")

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    task = select_exact_task(
        manifest,
        args.task_id,
        args.risk_ceiling,
        allow_terminal_pr_recovery=bool(args.recovery_pr_number),
    )
    api = API(github_token, jules_keys)
    _, repo_meta = api.gh(f"/repos/{args.repo}")
    default_branch = str(repo_meta.get("default_branch") or "master")
    store = LedgerStore(api, args.repo, default_branch, args.state_branch, args.ledger_path)
    ledger, ledger_sha = store.load()
    task_state = validate_lease(ledger, args.task_id, args.lease_key, now())

    starting_branch = default_branch
    if args.recovery_pr_number:
        _, recovery_pr = api.gh(f"/repos/{args.repo}/pulls/{args.recovery_pr_number}")
        pr_head = (recovery_pr.get("head") or {}) if isinstance(recovery_pr, dict) else {}
        actual_head = str(pr_head.get("sha") or "")
        if str(recovery_pr.get("state") or "") != "open":
            raise RuntimeError(f"recovery PR #{args.recovery_pr_number} is not open")
        if not args.recovery_pr_head or actual_head != args.recovery_pr_head:
            raise RuntimeError(
                f"recovery PR #{args.recovery_pr_number} head changed from {args.recovery_pr_head!r} to {actual_head!r}"
            )
        identity_text = " ".join(
            [
                str(recovery_pr.get("title") or ""),
                str(recovery_pr.get("body") or ""),
                str(pr_head.get("ref") or ""),
            ]
        )
        if args.task_id not in identity_text:
            raise RuntimeError(f"recovery PR #{args.recovery_pr_number} is not bound to task {args.task_id}")
        starting_branch = str(pr_head.get("ref") or "")
        if not starting_branch:
            raise RuntimeError(f"recovery PR #{args.recovery_pr_number} has no head branch")

    source = f"sources/github/{args.repo}"
    active = [session for _, session in list_sessions(api, source) if str(session.get("state") or "") in ACTIVE]
    if active:
        identities = [str(session.get("name") or session.get("id") or "unknown") for session in active]
        raise RuntimeError(f"refusing duplicate dispatch; active Jules sessions exist: {', '.join(identities)}")

    # Persist the task identity before the external create-session side effect.
    # If finalization later loses a CAS race, the next reconciler still has an
    # authoritative intent and cannot create a duplicate session.
    task_state.update(
        {
            "state": "session_create_requested",
            "session_create_requested_at": iso(),
            "lease_expires_at": iso(now() + timedelta(minutes=args.session_lease_minutes)),
            "recovery_pr_number": args.recovery_pr_number or None,
            "recovery_pr_head": args.recovery_pr_head or None,
        }
    )
    ledger["tasks"][args.task_id] = task_state
    ledger_sha = store.save(ledger, ledger_sha)

    prompt = render_prompt(args, task)
    request_body = {
        "prompt": prompt,
        "sourceContext": {
            "source": source,
            "githubRepoContext": {"startingBranch": starting_branch},
        },
        "automationMode": "AUTO_CREATE_PR",
        "requirePlanApproval": False,
        "title": (
            f"notion-abuz: recover PR #{args.recovery_pr_number}"
            if args.recovery_pr_number
            else f"notion-abuz: {task.get('title') or args.task_id}"
        ),
    }

    response: dict[str, Any] | None = None
    failures: list[str] = []
    for key in jules_keys:
        try:
            _, payload = api.jules(key, "sessions", method="POST", body=request_body)
            response = payload
            break
        except Exception as exc:  # try configured backup key without exposing it
            failures.append(sanitize(exc, 400))
    if response is None:
        raise RuntimeError("all configured Jules API keys failed: " + " | ".join(failures))

    session_name = str(response.get("name") or "")
    session_id = str(response.get("id") or session_name.rsplit("/", 1)[-1])
    if not session_id:
        raise RuntimeError("Jules create-session response has no session identity")

    task_state.update(
        {
            "state": "session_created",
            "session_id": session_id,
            "session_name": session_name,
            "session_state": str(response.get("state") or "STATE_UNSPECIFIED"),
            "dispatch_completed_at": iso(),
            "lease_expires_at": iso(now() + timedelta(minutes=args.session_lease_minutes)),
        }
    )
    ledger["tasks"][args.task_id] = task_state
    ledger["sessions"][session_id] = {
        "task_id": args.task_id,
        "session_state": str(response.get("state") or "STATE_UNSPECIFIED"),
        "state_version": 1,
        "last_observed_at": iso(),
        "lease_key": args.lease_key,
        "recovery_pr_number": args.recovery_pr_number or None,
        "recovery_pr_head": args.recovery_pr_head or None,
    }
    finalize_error = ""
    try:
        ledger_sha = store.save(ledger, ledger_sha)
    except Exception as exc:
        # Session creation succeeded and its precommitted task intent remains in
        # the ledger. Report the degraded finalization without retrying create.
        finalize_error = sanitize(exc, 700)
        print(f"WARNING: Jules session exists but ledger finalization is pending: {finalize_error}", file=sys.stderr)

    result = {
        "task_id": args.task_id,
        "session_id": session_id,
        "session_name": session_name,
        "session_state": response.get("state"),
        "web_url": response.get("webUrl") or response.get("url"),
        "lease_key": args.lease_key,
        "ledger_finalize_error": finalize_error,
        "recovery_pr_number": args.recovery_pr_number or None,
        "recovery_pr_head": args.recovery_pr_head or None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    output("session_id", session_id)
    output("summary", result)
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repo", required=True)
    value.add_argument("--manifest", default="agent_tasks.json")
    value.add_argument("--task-id", required=True)
    value.add_argument("--lease-key", required=True)
    value.add_argument("--focus", default="proxy")
    value.add_argument("--risk-ceiling", choices=tuple(RISK_ORDER), default="medium")
    value.add_argument("--recovery-pr-number", type=int, default=0)
    value.add_argument("--recovery-pr-head", default="")
    value.add_argument("--recovery-reason", default="")
    value.add_argument("--state-branch", default="automation-state-v2")
    value.add_argument("--ledger-path", default="autonomy/ledger.json")
    value.add_argument("--session-lease-minutes", type=int, default=45)
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        return execute(parser().parse_args(argv))
    except Exception as exc:
        print(f"ERROR: {sanitize(exc, 1600)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

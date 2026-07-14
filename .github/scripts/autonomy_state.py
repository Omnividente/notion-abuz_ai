#!/usr/bin/env python3
"""Durable task/session/PR reconciler for notion_abuz Jules automation.

GitHub owns branches, PRs and checks. Jules owns sessions and activities. A
small JSON ledger on a dedicated branch provides persistent leases,
idempotency and progress history. The workflow concurrency group is the first
lock; blob-SHA compare-and-swap is the second.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TOKEN = "AUTONOMY_RECONCILER_V2"
ACTIVE = {"QUEUED", "PLANNING", "IN_PROGRESS", "AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "STOPPED", "DELETED"}
LEDGER_SCHEMA = 2
LEDGER_RETENTION_DAYS = 14
LEDGER_MAX_SESSIONS = 120
LEDGER_MAX_TASKS = 220
LEDGER_MAX_MESSAGES = 240
LEDGER_MAX_CYCLES = 50
SESSION_INSPECTION_LIMIT = 40
LEGACY_LEDGER_VARIABLE = "JULES_RECOVERY_ROUTER_LEDGER"
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
RETRYABLE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
TASK_RE = re.compile(r'(?ix)(?:selected\s+task\s+id|task_id|"task_id")\s*[:=]\s*"?([a-z0-9][a-z0-9_.-]{2,})')
SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(authorization|api[\s_-]?key|token|secret|password|passwd|cookie)(\s*[:=]\s*)([^\s,;]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+)\b"), "[REDACTED]"),
    (re.compile(r"(?i)(https?://[^/\s:@]+:)[^@\s/]+(@)"), r"\1[REDACTED]\2"),
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def minutes_since(value: Any, current: datetime | None = None) -> float:
    parsed = parse_time(value)
    return float("inf") if parsed is None else max(0.0, ((current or now()) - parsed).total_seconds() / 60)


def digest(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def sanitize(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [part for item in value for part in text_values(item)]
    if isinstance(value, dict):
        return [part for item in value.values() for part in text_values(item)]
    return []


def structured_request(texts: list[str], marker: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for text in reversed(texts):
        position = text.rfind(marker)
        if position < 0:
            continue
        start = text.find("{", position + len(marker))
        if start < 0:
            continue
        try:
            payload, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        return {
            "reason": sanitize(payload.get("reason"), 500),
            "paths": [sanitize(path, 220) for path in payload.get("paths", [])[:12] if isinstance(path, str)],
            "risk": sanitize(payload.get("risk"), 40),
            "evidence": sanitize(payload.get("evidence"), 900),
            "retry_condition": sanitize(payload.get("retry_condition"), 500),
            "evidence_requirement": sanitize(payload.get("evidence_requirement"), 500),
            "recheck_at": sanitize(payload.get("recheck_at"), 80),
        }
    return None


def activity_summary(activities: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted((x for x in activities if isinstance(x, dict)), key=lambda x: str(x.get("createTime") or x.get("updateTime") or ""))
    last_agent: dict[str, Any] = {}
    last_user: dict[str, Any] = {}
    identities: list[tuple[str, str, str]] = []
    agent_identities: list[tuple[str, str, str]] = []
    recent_activity: list[dict[str, str]] = []
    activity_texts: list[str] = []
    for row in rows[-50:]:
        text = sanitize(" ".join(text_values(row)), 1200)
        stamp = str(row.get("createTime") or row.get("updateTime") or "")
        identity = (str(row.get("id") or row.get("name") or ""), stamp, text)
        activity_texts.append(text)
        identities.append(identity)
        is_user = "user" in str(row.get("originator") or "").lower()
        recent_activity.append({"at": stamp, "actor": "user" if is_user else "agent", "message": sanitize(text, 500)})
        if is_user:
            last_user = row
        else:
            last_agent = row
            agent_identities.append(identity)
    blob = json.dumps(rows, ensure_ascii=False)
    match = TASK_RE.search(blob)
    task_id = match.group(1).rstrip('.,;:!?"\'') if match else ""
    tokens = sorted(set(re.findall(rf"{TOKEN}\s+key=([a-f0-9]{{16,64}})", blob)))
    return {
        "fingerprint": digest(identities),
        # Recovery prompts are user-originated activities.  They prove delivery,
        # but must never reset the no-progress counter by themselves.
        "agent_fingerprint": digest(agent_identities),
        "latest_at": str((rows[-1] if rows else {}).get("createTime") or (rows[-1] if rows else {}).get("updateTime") or ""),
        "latest_agent_at": str(last_agent.get("createTime") or last_agent.get("updateTime") or ""),
        "latest_user_at": str(last_user.get("createTime") or last_user.get("updateTime") or ""),
        "last_jules_message": sanitize(" ".join(text_values(last_agent)), 1200),
        "task_id": task_id,
        "token_keys": tokens,
        "recent_activity": recent_activity[-8:],
        "defer_request": structured_request(activity_texts, "AUTONOMY_DEFER_REQUEST"),
        "scope_request": structured_request(activity_texts, "AUTONOMY_SCOPE_REQUEST"),
        "verified_no_change": structured_request(activity_texts, "AUTONOMY_VERIFIED_NO_CHANGE"),
        "count": len(rows),
    }


def state_version(previous: dict[str, Any], state: str, activity_fp: str, pr_fp: str) -> int:
    old = (previous.get("session_state"), previous.get("activity_fingerprint"), previous.get("pr_fingerprint"))
    new = (state, activity_fp, pr_fp)
    current = int(previous.get("state_version") or 0)
    return current + 1 if old != new else max(current, 1)


def message_key(session_id: str, version: int, activity_fp: str) -> str:
    return digest(session_id, version, activity_fp)


def no_op_violation(*, work: bool, actions: int, progress: int, fresh: bool, blocked: int = 0) -> bool:
    """Reject silent no-ops while allowing an explicit blocked report.

    A durable, evidence-bound defer is not progress, but it is also not silent:
    the reconciler emits an actionable blocked row with the retry condition and
    required evidence. Treating that row as an error on every scheduled cycle
    would turn a bounded defer into another recovery event storm.
    """

    return work and actions == 0 and progress == 0 and not fresh and blocked == 0


def should_recover_session(
    *,
    failed_checks: bool,
    blocked_pr: bool = False,
    previous_pr_fingerprint: Any,
    current_pr_fingerprint: str,
    stale: bool,
    awaiting_user_feedback: bool = False,
) -> tuple[bool, str]:
    if awaiting_user_feedback:
        return True, "awaiting_user_feedback"
    new_blocker_evidence = bool(
        blocked_pr
        and (
            not previous_pr_fingerprint
            or str(previous_pr_fingerprint) != current_pr_fingerprint
        )
    )
    if new_blocker_evidence:
        return True, "new_pr_blocker_evidence"
    new_failed_evidence = bool(
        failed_checks
        and (
            not previous_pr_fingerprint
            or str(previous_pr_fingerprint) != current_pr_fingerprint
        )
    )
    if new_failed_evidence:
        return True, "new_failed_check_evidence"
    if stale:
        return True, "stale_without_agent_progress"
    return False, "unchanged"


def user_feedback_needs_resolution(
    record: dict[str, Any], session_state: str, agent_fingerprint: str
) -> bool:
    """Resolve each distinct Jules question once without requiring a human."""

    return bool(
        session_state == "AWAITING_USER_FEEDBACK"
        and agent_fingerprint
        and record.get("resolved_feedback_agent_fingerprint") != agent_fingerprint
    )


def is_autonomous_pr(pr: dict[str, Any]) -> bool:
    body = str(pr.get("body") or "")
    head = str((pr.get("head") or {}).get("ref") or "")
    login = str((pr.get("user") or {}).get("login") or "")
    return login in {"google-labs-jules[bot]", "google-jules[bot]"} or "jules.google.com/task" in body or "AUTONOMOUS_TASK_EVIDENCE" in body or head.startswith("jules-") or head.startswith("jules/")


def task_id_from_pr(pr: dict[str, Any], known: list[str]) -> str:
    fields = [str(pr.get("body") or ""), str(pr.get("title") or ""), str((pr.get("head") or {}).get("ref") or "")]
    for field in fields:
        match = TASK_RE.search(field)
        if match:
            return match.group(1).rstrip('.,;:!?"\'')
    return next((task_id for task_id in known if any(task_id in field for field in fields)), "")


def task_fingerprint(task: dict[str, Any]) -> str:
    return digest({key: value for key, value in task.items() if key not in {"status", "blocked_reason", "resolution"}})


def task_kind(task: dict[str, Any]) -> str:
    if not task or not task.get("id"):
        return "none"
    paths = [str(x).lower() for x in task.get("allowed_paths", [])]
    area = str(task.get("area") or "").lower()
    control = bool(paths) and all(path == "agent_tasks.json" or path.startswith(".github/") for path in paths)
    if area == "automation" or control:
        return "control"
    runtime_file = any(
        (path.startswith("internal/") or path.startswith("cmd/"))
        and path.endswith(".go")
        and not path.endswith("_test.go")
        for path in paths
    )
    return "runtime" if runtime_file else "project"


def task_score(task: dict[str, Any]) -> int:
    text = json.dumps(task, ensure_ascii=False).lower()
    kind = task_kind(task)
    evidence = any(word in text for word in ("live smoke", "transcript", "runtime failure", "ci failure", "reproduced", "http 500"))
    test_only = any(word in text for word in ("flaky test", "test-only", "marked skipped", "document reason for transient flakes"))
    return (180 if kind == "runtime" else 60 if kind == "project" else -200) + (80 if evidence else 0) + (20 if task.get("risk") == "medium" else 0) - (80 if test_only else 0)


def assess_scope_request(task: dict[str, Any], request: dict[str, Any] | None) -> tuple[bool, str]:
    request = request or {}
    paths = [str(path) for path in request.get("paths", []) if path]
    risk = str(request.get("risk") or task.get("risk") or "").lower()
    if not paths:
        return False, "scope request has no exact paths"
    if risk not in {"low", "medium"}:
        return False, f"scope request risk {risk or 'unknown'} requires guarded review"
    for path in paths:
        if path.startswith("/") or ".." in Path(path).parts:
            return False, f"unsafe repository path: {path}"
        if path.startswith(".github/") and str(task.get("area") or "") != "automation":
            return False, f"project task cannot silently expand into control plane: {path}"
        if not path.startswith(("internal/", "cmd/", "scripts/", "docs/", "web/", ".github/")):
            return False, f"scope root is not allowlisted: {path}"
    if not request.get("evidence"):
        return False, "scope request has no reproduced evidence"
    return True, "bounded low/medium-risk expansion with exact evidence"


def choose_task(manifest: dict[str, Any], ledger: dict[str, Any], current: datetime) -> dict[str, Any] | None:
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    scheduler = (ledger.get("tasks") or {}).get("__scheduler__", {})
    last_dispatched_kind = str(scheduler.get("last_dispatched_kind") or "") if isinstance(scheduler, dict) else ""
    last_dispatched_task_id = str(scheduler.get("last_dispatched_task_id") or "") if isinstance(scheduler, dict) else ""
    for index, task in enumerate(manifest.get("tasks", [])):
        if not isinstance(task, dict) or task.get("status") != "todo" or task.get("risk") not in {"low", "medium", "high"}:
            continue
        if task_kind(task) == "control" and not any(
            task.get(name) for name in ("automation_blocker_evidence", "blocker_evidence", "source_run_id", "failed_check_url")
        ):
            continue
        if (
            task_kind(task) == "control"
            and last_dispatched_kind == "control"
            and str(task.get("id") or "") != last_dispatched_task_id
        ):
            continue
        override = (ledger.get("tasks") or {}).get(str(task.get("id") or ""), {})
        retry_at = parse_time(override.get("retry_at"))
        lease_until = parse_time(override.get("lease_expires_at"))
        if retry_at and retry_at > current or lease_until and lease_until > current:
            continue
        if (
            override.get("state") == "verified_no_change"
            and task_fingerprint(task) == str(override.get("completed_task_fingerprint") or "")
        ):
            continue
        if override.get("state") == "deferred":
            evidence_changed = (
                task_fingerprint(task) != str(override.get("deferred_task_fingerprint") or "")
                or (
                    bool(override.get("current_evidence_fingerprint"))
                    and override.get("current_evidence_fingerprint") != override.get("deferred_evidence_fingerprint")
                )
            )
            if not evidence_changed and not override.get("force_retry"):
                continue
        candidates.append((task_score(task), -index, task))
    return max(candidates, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]


class TransientAPIError(RuntimeError):
    """A retryable remote failure that exhausted bounded request attempts."""


class API:
    def __init__(
        self,
        github_token: str,
        jules_keys: list[str],
        *,
        request_attempts: int = 3,
        retry_base_seconds: float = 1.0,
        sleep_fn: Any = time.sleep,
    ):
        self.github_token = github_token
        self.jules_keys = jules_keys
        self.request_attempts = max(1, request_attempts)
        self.retry_base_seconds = max(0.0, retry_base_seconds)
        self.sleep_fn = sleep_fn

    def retry_delay(self, attempt: int, error: Exception) -> float:
        headers = getattr(error, "headers", None)
        retry_after = headers.get("Retry-After") if headers else None
        if retry_after:
            try:
                return min(30.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
        return min(30.0, self.retry_base_seconds * (2**attempt))

    def request(self, url: str, *, method: str = "GET", body: Any = None, headers: dict[str, str] | None = None, allow: tuple[int, ...] = ()) -> tuple[int, Any]:
        method = method.upper()
        data = None if body is None else json.dumps(body).encode()
        attempts = self.request_attempts if method in RETRYABLE_HTTP_METHODS else 1
        for attempt in range(attempts):
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("Content-Type", "application/json")
            req.add_header("User-Agent", "notion-abuz-autonomy-reconciler")
            for key, value in (headers or {}).items():
                req.add_header(key, value)
            try:
                with urllib.request.urlopen(req, timeout=45) as response:
                    raw = response.read()
                    return response.status, json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                try:
                    payload = json.loads(raw) if raw else {"message": str(exc)}
                except json.JSONDecodeError:
                    payload = {"message": sanitize(raw.decode(errors="replace"), 500)}
                if exc.code in allow:
                    return exc.code, payload
                message = f"HTTP {exc.code} {method} {sanitize(url, 220)}: {sanitize(payload, 700)}"
                if exc.code not in TRANSIENT_HTTP_STATUSES:
                    raise RuntimeError(message) from exc
                error: Exception = TransientAPIError(message)
                delay_source: Exception = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError) as exc:
                error = TransientAPIError(
                    f"transient {method} {sanitize(url, 220)} failure: {sanitize(exc, 700)}"
                )
                delay_source = exc

            if attempt + 1 >= attempts:
                raise error
            self.sleep_fn(self.retry_delay(attempt, delay_source))

        raise AssertionError("request retry loop exited unexpectedly")

    def gh(self, path: str, *, method: str = "GET", body: Any = None, allow: tuple[int, ...] = ()) -> tuple[int, Any]:
        return self.request("https://api.github.com" + path, method=method, body=body, allow=allow, headers={"Authorization": f"Bearer {self.github_token}", "X-GitHub-Api-Version": "2022-11-28"})

    def jules(self, key: str, path: str, *, method: str = "GET", body: Any = None, allow: tuple[int, ...] = ()) -> tuple[int, Any]:
        return self.request("https://jules.googleapis.com/v1alpha/" + path.lstrip("/"), method=method, body=body, allow=allow, headers={"X-Goog-Api-Key": key})


def empty_ledger() -> dict[str, Any]:
    return {"schema": LEDGER_SCHEMA, "revision": 0, "sessions": {}, "tasks": {}, "messages": {}, "cycles": []}


def row_time(row: dict[str, Any]) -> datetime | None:
    for name in (
        "verified_at",
        "sent_at",
        "last_progress_at",
        "last_observed_at",
        "dispatch_completed_at",
        "dispatch_requested_at",
        "session_create_requested_at",
        "scope_approved_at",
        "last_dispatched_at",
        "requested_at",
        "next_review_at",
        "retry_at",
        "time",
        "updated_at",
    ):
        parsed = parse_time(row.get(name))
        if parsed:
            return parsed
    return None


def bounded_rows(
    rows: dict[str, Any],
    *,
    current: datetime,
    limit: int,
    keep_states: set[str] | None = None,
) -> dict[str, Any]:
    cutoff = current - timedelta(days=LEDGER_RETENTION_DAYS)
    keep_states = keep_states or set()
    ranked: list[tuple[bool, datetime, str, dict[str, Any]]] = []
    for key, value in rows.items():
        if not isinstance(value, dict):
            continue
        stamp = row_time(value)
        pinned = str(value.get("state") or value.get("session_state") or "") in keep_states or bool(value.get("pending_message_key"))
        if not pinned and stamp and stamp < cutoff:
            continue
        ranked.append((pinned, stamp or datetime.min.replace(tzinfo=timezone.utc), str(key), value))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return {key: value for _, _, key, value in ranked[:limit]}


def prune_ledger(ledger: dict[str, Any], *, current: datetime | None = None) -> dict[str, Any]:
    current = current or now()
    pruned = dict(ledger)
    pruned["schema"] = LEDGER_SCHEMA
    pruned["sessions"] = bounded_rows(
        dict(ledger.get("sessions") or {}),
        current=current,
        limit=LEDGER_MAX_SESSIONS,
        keep_states=ACTIVE,
    )
    pruned["tasks"] = bounded_rows(
        dict(ledger.get("tasks") or {}),
        current=current,
        limit=LEDGER_MAX_TASKS,
        keep_states={"active", "dispatch_requested", "pr_recovery_dispatch_requested", "session_create_requested", "session_created", "dispatch_failed", "deferred", "verified_no_change"},
    )
    pruned["messages"] = bounded_rows(
        dict(ledger.get("messages") or {}),
        current=current,
        limit=LEDGER_MAX_MESSAGES,
    )
    pruned["cycles"] = [row for row in list(ledger.get("cycles") or []) if isinstance(row, dict)][-LEDGER_MAX_CYCLES:]
    return pruned


def migrate_legacy_ledger(api: API, repo: str, *, current: datetime | None = None) -> dict[str, Any]:
    """Import a bounded audit tail from the former Actions variable once.

    The legacy keys are intentionally hashed: they may contain PR/session text,
    are not used for v2 idempotency, and must not make the new ledger unbounded.
    A failed/invalid legacy read is recorded but never blocks the first v2 run.
    """
    current = current or now()
    ledger = empty_ledger()
    migration: dict[str, Any] = {
        "source": f"actions-variable:{LEGACY_LEDGER_VARIABLE}",
        "mode": "read_once_bounded_audit",
        "migrated_at": iso(current),
    }
    try:
        status, payload = api.gh(f"/repos/{repo}/actions/variables/{LEGACY_LEDGER_VARIABLE}", allow=(404,))
        if status == 404:
            migration["status"] = "source_missing"
            ledger["migration"] = migration
            return ledger
        raw = str((payload or {}).get("value") or "{}")
        legacy = json.loads(raw)
        if not isinstance(legacy, dict):
            raise ValueError("legacy ledger is not an object")
        actions = legacy.get("actions") if isinstance(legacy.get("actions"), dict) else {}
        sessions = legacy.get("sessions") if isinstance(legacy.get("sessions"), dict) else {}
        cutoff = current - timedelta(days=LEDGER_RETENTION_DAYS)
        action_rows: list[tuple[datetime, str, dict[str, Any]]] = []
        for old_key, value in actions.items():
            if not isinstance(value, dict):
                continue
            stamp = parse_time(value.get("time"))
            if not stamp or stamp < cutoff:
                continue
            action_rows.append((stamp, str(old_key), value))
        for stamp, old_key, value in sorted(action_rows, reverse=True)[:LEDGER_MAX_MESSAGES]:
            new_key = "legacy-" + digest(old_key)
            ledger["messages"][new_key] = {
                "kind": "legacy_router_action",
                "source_key_hash": digest(old_key),
                "sent_at": iso(stamp),
                "type": sanitize(value.get("type"), 80),
                "reason": sanitize(value.get("reason"), 240),
                "verified_at": iso(stamp),
            }
        for session_id, value in list(sessions.items())[-LEDGER_MAX_SESSIONS:]:
            if not isinstance(value, dict):
                continue
            ledger["sessions"][str(session_id)] = {
                "source": "legacy_router_variable",
                "task_id": sanitize(value.get("task_id") or value.get("task"), 180),
                "session_state": sanitize(value.get("state") or value.get("session_state"), 80),
                "last_observed_at": sanitize(value.get("updated_at") or value.get("time"), 80),
                "legacy_value_hash": digest(value),
            }
        migration.update(
            {
                "status": "migrated",
                "source_hash": digest(raw),
                "source_action_count": len(actions),
                "source_session_count": len(sessions),
                "imported_action_count": len(ledger["messages"]),
                "imported_session_count": len(ledger["sessions"]),
            }
        )
    except Exception as exc:
        migration.update({"status": "source_unreadable", "error": sanitize(exc, 400)})
    ledger["migration"] = migration
    return prune_ledger(ledger, current=current)


class LedgerStore:
    def __init__(self, api: API, repo: str, default_branch: str, state_branch: str, path: str):
        self.api, self.repo, self.default_branch, self.branch, self.path = api, repo, default_branch, state_branch, path

    def ensure_branch(self) -> None:
        encoded = urllib.parse.quote(self.branch, safe="")
        status, _ = self.api.gh(f"/repos/{self.repo}/git/ref/heads/{encoded}", allow=(404,))
        if status != 404:
            return
        _, base = self.api.gh(f"/repos/{self.repo}/git/ref/heads/{urllib.parse.quote(self.default_branch, safe='')}")
        sha = str((base.get("object") or {}).get("sha") or "")
        self.api.gh(f"/repos/{self.repo}/git/refs", method="POST", body={"ref": f"refs/heads/{self.branch}", "sha": sha})

    def load(self) -> tuple[dict[str, Any], str | None]:
        self.ensure_branch()
        status, payload = self.api.gh(f"/repos/{self.repo}/contents/{urllib.parse.quote(self.path, safe='/')}?ref={urllib.parse.quote(self.branch)}", allow=(404,))
        if status == 404:
            return migrate_legacy_ledger(self.api, self.repo), None
        content = base64.b64decode(str(payload.get("content") or "")).decode()
        ledger = json.loads(content)
        for name, fallback in (("sessions", {}), ("tasks", {}), ("messages", {}), ("cycles", [])):
            ledger.setdefault(name, fallback)
        return prune_ledger(ledger), str(payload.get("sha") or "")

    def save(self, ledger: dict[str, Any], sha: str | None) -> str:
        pruned = prune_ledger(ledger)
        ledger.clear()
        ledger.update(pruned)
        ledger["schema"] = LEDGER_SCHEMA
        ledger["revision"] = int(ledger.get("revision") or 0) + 1
        ledger["updated_at"] = iso()
        body: dict[str, Any] = {"message": f"state: autonomy ledger r{ledger['revision']}", "branch": self.branch, "content": base64.b64encode((json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()).decode()}
        if sha:
            body["sha"] = sha
        status, payload = self.api.gh(f"/repos/{self.repo}/contents/{urllib.parse.quote(self.path, safe='/')}", method="PUT", body=body, allow=(409, 422))
        if status in {409, 422}:
            raise RuntimeError("ledger compare-and-swap conflict; fail closed and recompute next cycle")
        if not payload.get("commit"):
            raise RuntimeError("ledger write returned no commit")
        content = payload.get("content") or {}
        new_sha = str(content.get("sha") or "")
        if not new_sha:
            raise RuntimeError("ledger write returned no content blob sha")
        return new_sha


def paginate_gh(api: API, path: str) -> list[Any]:
    rows: list[Any] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 6):
        _, payload = api.gh(f"{path}{separator}per_page=100&page={page}")
        page_rows = payload if isinstance(payload, list) else []
        rows.extend(page_rows)
        if len(page_rows) < 100:
            break
    return rows


def list_sessions(api: API, source: str) -> list[tuple[str, dict[str, Any]]]:
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for key in api.jules_keys:
        token = ""
        for _ in range(5):
            query = "sessions?pageSize=100" + ("&pageToken=" + urllib.parse.quote(token) if token else "")
            _, payload = api.jules(key, query)
            for session in payload.get("sessions", []):
                if str(((session.get("sourceContext") or {}).get("source") or "")) == source and session.get("name"):
                    found.setdefault(str(session["name"]), (key, session))
            token = str(payload.get("nextPageToken") or "")
            if not token:
                break
    return list(found.values())


def sessions_for_reconcile(
    rows: list[tuple[str, dict[str, Any]]],
    ledger: dict[str, Any],
    *,
    current: datetime | None = None,
    limit: int = SESSION_INSPECTION_LIMIT,
) -> list[tuple[str, dict[str, Any]]]:
    """Inspect every active session and only a bounded recent terminal tail."""
    current = current or now()
    ledger_sessions = ledger.get("sessions") if isinstance(ledger.get("sessions"), dict) else {}
    active: list[tuple[str, dict[str, Any]]] = []
    terminal: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        session = row[1]
        state = str(session.get("state") or "")
        if state in ACTIVE:
            active.append(row)
            continue
        session_id = str(session.get("name") or "").rsplit("/", 1)[-1]
        previous = ledger_sessions.get(session_id, {}) if isinstance(ledger_sessions, dict) else {}
        updated = session.get("updateTime") or session.get("createTime")
        recent = minutes_since(updated, current) <= LEDGER_RETENTION_DAYS * 24 * 60
        pinned = isinstance(previous, dict) and bool(previous.get("pending_message_key"))
        if recent or pinned:
            terminal.append(row)
    rank = lambda row: str(row[1].get("updateTime") or row[1].get("createTime") or "")
    active.sort(key=rank, reverse=True)
    terminal.sort(key=rank, reverse=True)
    return active + terminal[: max(0, limit - len(active))]


def list_activities(api: API, key: str, session_name: str) -> list[dict[str, Any]]:
    _, payload = api.jules(key, f"{session_name}/activities?pageSize=100")
    return [x for x in payload.get("activities", []) if isinstance(x, dict)]


ACTION_RUN_RE = re.compile(r"/actions/runs/(\d+)")
ACTION_JOB_RE = re.compile(r"/job/(\d+)")


def action_run_job_ids(details_url: Any) -> tuple[int, int]:
    text = str(details_url or "")
    run_match = ACTION_RUN_RE.search(text)
    job_match = ACTION_JOB_RE.search(text)
    return (int(run_match.group(1)) if run_match else 0, int(job_match.group(1)) if job_match else 0)


def check_context(api: API, repo: str, pr: dict[str, Any] | None) -> dict[str, Any]:
    if not pr:
        return {"failed": [], "pending": [], "passed": [], "changed_paths": [], "fingerprint": digest([])}
    sha = str(((pr.get("head") or {}).get("sha") or ""))
    if not sha:
        return {"failed": [], "pending": [], "passed": [], "changed_paths": [], "fingerprint": digest([])}
    _, payload = api.gh(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100")
    pr_number = int(pr.get("number") or 0)
    changed_paths: list[str] = []
    if pr_number:
        for row in paginate_gh(api, f"/repos/{repo}/pulls/{pr_number}/files"):
            path = sanitize((row or {}).get("filename"), 220) if isinstance(row, dict) else ""
            if path:
                changed_paths.append(path)
    raw_checks = [row for row in payload.get("check_runs", []) if isinstance(row, dict)]
    run_meta: dict[int, dict[str, Any]] = {}
    for check in raw_checks:
        run_id, _ = action_run_job_ids(check.get("details_url"))
        if not run_id or run_id in run_meta:
            continue
        try:
            _, value = api.gh(f"/repos/{repo}/actions/runs/{run_id}")
            run_meta[run_id] = value if isinstance(value, dict) else {}
        except Exception as exc:
            run_meta[run_id] = {"lookup_error": sanitize(exc, 260)}

    # A commit can retain failed check-runs from an older pull_request/labeled
    # event even after the same workflow/job passes.  Reconcile only the newest
    # run for each workflow/job identity; otherwise one stale run loops forever.
    newest: dict[tuple[str, str], tuple[tuple[str, int, int], dict[str, Any]]] = {}
    for check in raw_checks:
        name = sanitize(check.get("name") or "unknown", 160)
        run_id, _ = action_run_job_ids(check.get("details_url"))
        meta = run_meta.get(run_id, {})
        suite = check.get("check_suite") or {}
        workflow_identity = str(meta.get("workflow_id") or f"suite:{suite.get('id') or check.get('id') or 0}")
        rank = (
            str(meta.get("run_started_at") or meta.get("created_at") or check.get("started_at") or check.get("created_at") or ""),
            int(meta.get("run_attempt") or 0),
            int(check.get("id") or 0),
        )
        identity = (workflow_identity, name)
        if identity not in newest or rank > newest[identity][0]:
            newest[identity] = (rank, check)

    failed, pending, passed, fp = [], [], [], []
    jobs_cache: dict[int, list[dict[str, Any]]] = {}
    for _, check in sorted(newest.values(), key=lambda item: item[0]):
        name = sanitize(check.get("name") or "unknown", 160)
        status, conclusion = str(check.get("status") or ""), str(check.get("conclusion") or "")
        output = check.get("output") or {}
        run_id, job_id = action_run_job_ids(check.get("details_url"))
        meta = run_meta.get(run_id, {})
        workflow_name = sanitize(meta.get("name") or "", 160)
        excerpt_parts = [str(output.get(k) or "") for k in ("title", "summary", "text")]
        fp.append((meta.get("workflow_id"), workflow_name, name, status, conclusion, run_id, int(meta.get("run_attempt") or 0)))
        if status != "completed" or not conclusion:
            pending.append(f"{workflow_name} / {name}" if workflow_name else name)
        elif conclusion in {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}:
            annotations: list[dict[str, Any]] = []
            check_id = int(check.get("id") or 0)
            if check_id:
                try:
                    _, annotation_rows = api.gh(f"/repos/{repo}/check-runs/{check_id}/annotations?per_page=20")
                    for annotation in annotation_rows if isinstance(annotation_rows, list) else []:
                        if not isinstance(annotation, dict):
                            continue
                        annotations.append(
                            {
                                "path": sanitize(annotation.get("path"), 220),
                                "line": annotation.get("start_line"),
                                "message": sanitize(annotation.get("message") or annotation.get("title"), 500),
                            }
                        )
                except Exception as exc:
                    annotations.append({"path": "", "line": None, "message": "annotation lookup unavailable: " + sanitize(exc, 260)})
            if run_id:
                if run_id not in jobs_cache:
                    try:
                        _, jobs_payload = api.gh(f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
                        jobs_cache[run_id] = [row for row in jobs_payload.get("jobs", []) if isinstance(row, dict)]
                    except Exception as exc:
                        jobs_cache[run_id] = []
                        excerpt_parts.append("job lookup unavailable: " + sanitize(exc, 260))
                job = next((row for row in jobs_cache[run_id] if int(row.get("id") or 0) == job_id), None)
                if not job:
                    job = next((row for row in jobs_cache[run_id] if str(row.get("name") or "") == str(check.get("name") or "")), None)
                if job:
                    failed_steps = [
                        sanitize(step.get("name") or "unknown step", 180)
                        for step in job.get("steps", [])
                        if isinstance(step, dict)
                        and str(step.get("conclusion") or "") in {"failure", "cancelled", "timed_out", "action_required"}
                    ]
                    if failed_steps:
                        excerpt_parts.append("failed steps: " + ", ".join(failed_steps))
            excerpt = sanitize(" ".join(excerpt_parts), 900)
            failed.append(
                {
                    "name": name,
                    "workflow": workflow_name,
                    "run_id": run_id or None,
                    "job_id": job_id or None,
                    "conclusion": conclusion,
                    "details_url": sanitize(check.get("details_url") or "", 260),
                    "log_excerpt": excerpt,
                    "annotations": annotations[:12],
                }
            )
        else:
            passed.append(f"{workflow_name} / {name}" if workflow_name else name)
    return {
        "failed": failed[:8],
        "pending": sorted(set(pending)),
        "passed": sorted(set(passed)),
        "changed_paths": sorted(set(changed_paths))[:100],
        "fingerprint": digest(fp, sorted(set(changed_paths))),
    }


def build_packet(task: dict[str, Any] | None, summary: dict[str, Any], attempts: int, delta: bool, wait_reason: str, pr: dict[str, Any] | None, checks: dict[str, Any]) -> dict[str, Any]:
    task = task or {}
    allowed = [sanitize(x, 220) for x in task.get("allowed_paths", [])[:12]]
    changed = [sanitize(x, 220) for x in checks.get("changed_paths", [])[:100]]
    outside_scope = [path for path in changed if path not in allowed and path != "agent_tasks.json"]
    return {
        "task_id": str(task.get("id") or summary.get("task_id") or "unknown"),
        "acceptance": [sanitize(x, 300) for x in task.get("acceptance", [])[:8]],
        "allowed_scope": allowed,
        "risk": str(task.get("risk") or "unknown"),
        "wait_reason": sanitize(wait_reason, 260),
        "last_jules_message": sanitize(summary.get("last_jules_message"), 1200),
        "recent_activity": [row for row in summary.get("recent_activity", [])[-8:] if isinstance(row, dict)],
        "attempt_count": attempts,
        "progress_delta": bool(delta),
        "scope_analysis": {
            "changed_paths": changed,
            "outside_allowed_scope": outside_scope,
            "policy": "If evidence places the root cause outside allowed_scope, report exact paths, evidence and risk for a controlled scope decision; never create a manifest-only recovery follow-up.",
        },
        "pr_context": {
            "number": (pr or {}).get("number"),
            "head_sha": str(((pr or {}).get("head") or {}).get("sha") or ""),
            "mergeable_state": str((pr or {}).get("mergeable_state") or ""),
            "failed_checks": checks.get("failed", []),
            "pending_checks": checks.get("pending", []),
            "passed_checks": checks.get("passed", []),
        },
    }


def recovery_prompt(key: str, packet: dict[str, Any]) -> str:
    encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    return f"""{TOKEN} key={key}

Sanitized recovery packet:
```json
{encoded}
```

Самостоятельно выбери ровно одно действие: recollect_context, continue_work,
run_tests, fix_checks, sync_pr, finalize, recreate_session, defer_task или
verified_no_change, scope_expansion_request или real_blocker. Не повторяй
общий continue и не проси подтверждения. GitHub API,
PR body, checks и evidence обслуживает внешний orchestrator; отсутствие gh CLI
или token внутри sandbox не блокирует project task. После действия создай
измеримый delta: новую activity, commit, code diff, tests/checks или PR update.
Сохрани язык ответа пользователя, но не используй язык upstream Notion AI как
единственный routing signal. Не создавай отдельную manifest-only recovery task.
Если root cause вне allowed_scope, верни exact paths + evidence + risk как
scope_expansion_request; orchestrator примет контролируемое решение. Если код
уже удовлетворяет acceptance, верни verified_no_change с командами и точными
строками evidence вместо blocker.
"""


def verify_message(api: API, key: str, session_name: str, expected: str, before_fp: str) -> tuple[bool, dict[str, Any]]:
    last: dict[str, Any] = {}
    for delay in (0, 2, 5):
        if delay:
            time.sleep(delay)
        last = activity_summary(list_activities(api, key, session_name))
        if expected in last.get("token_keys", []) or last.get("fingerprint") != before_fp:
            return True, last
    return False, last


def output(name: str, value: Any) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
    with open(path, "a", encoding="utf-8") as handle:
        if "\n" in text:
            marker = "EOF_" + digest(name, text)
            handle.write(f"{name}<<{marker}\n{text}\n{marker}\n")
        else:
            handle.write(f"{name}={text}\n")


__all__ = [name for name in globals() if not name.startswith("_")]

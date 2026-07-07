#!/usr/bin/env python3
"""Open a manifest-only PR that blocks a repeatedly failing Jules task."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BLOCK_REASON_TEMPLATE = (
    "Paused after repeated Jules FAILED sessions: {sessions}. "
    "Resume only with human review or concrete live smoke/transcript/CI/offline reproduction evidence."
)
RECOVERY_MARKER = "AUTOMATION_RECOVERY_FAILED_SESSION_BLOCK"
RECOVERY_BRANCH_PREFIX = "automation-recovery-failed-session-block"
RECOVERY_LABELS = {
    "automation-recovery": {
        "color": "5319e7",
        "description": "Control-plane autonomous recovery PR",
    },
    "self-improvement": {
        "color": "0e8a16",
        "description": "Automation self-improvement or recovery",
    },
}


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def safe_branch_part(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned[:limit] or "unknown"


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as manifest_file:
        data = json.load(manifest_file)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be an object")
    return data


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request(method: str, path: str, *, token: str, api_url: str, body: Any = None) -> Any:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(f"{api_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            if not content:
                return None
            return json.loads(content.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def ensure_label(*, name: str, color: str, description: str, token: str, repo: str, api_url: str) -> None:
    try:
        request(
            "POST",
            f"/repos/{repo}/labels",
            token=token,
            api_url=api_url,
            body={"name": name, "color": color, "description": description},
        )
    except RuntimeError as exc:
        if "HTTP 422" not in str(exc):
            raise


def open_block_pr(
    *,
    manifest_path: Path,
    task_id: str,
    failed_sessions: list[str],
    token: str,
    repo: str,
    api_url: str,
) -> int:
    short_session = safe_branch_part(failed_sessions[0] if failed_sessions else "unknown", 20)
    branch = f"{RECOVERY_BRANCH_PREFIX}-{safe_branch_part(task_id, 70)}-{short_session}"

    open_pulls = request("GET", f"/repos/{repo}/pulls?state=open&per_page=100", token=token, api_url=api_url) or []
    for pr in open_pulls:
        head_ref = (pr.get("head") or {}).get("ref", "")
        body = pr.get("body") or ""
        if head_ref == branch or (task_id in body and RECOVERY_MARKER in body):
            print(f"Open failed-session block PR already exists: #{pr['number']}.")
            return 0

    manifest = load_manifest(manifest_path)
    tasks = manifest.get("tasks", [])
    todo_count = 0
    target = None
    for task in tasks:
        if isinstance(task, dict):
            if task.get("id") == task_id:
                target = task
            elif task.get("status") == "todo":
                todo_count += 1

    if target is None:
        print(f"Task {task_id!r} not found; cannot open block PR.")
        return 0
    if target.get("status") != "todo":
        print(f"Task {task_id!r} status is {target.get('status')!r}; block PR not needed.")
        return 0

    sessions_text = ", ".join(failed_sessions)
    target["status"] = "blocked"
    target["blocked_reason"] = BLOCK_REASON_TEMPLATE.format(sessions=sessions_text)

    minimum_todo_tasks = manifest.get("replenishment_policy", {}).get("minimum_todo_tasks", 5)

    if todo_count < minimum_todo_tasks:
        import hashlib
        import datetime

    while todo_count < minimum_todo_tasks:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        h = hashlib.sha256(f"{task_id}-{todo_count}-{now}".encode("utf-8")).hexdigest()[:8]
        new_task_id = f"automation-recovery-replenishment-{h}"
        new_task = {
            "id": new_task_id,
            "status": "todo",
            "area": "automation",
            "risk": "low",
            "title": f"Investigate root cause of Jules failure for {task_id}",
            "description": f"The task {task_id} repeatedly failed and was blocked. We need an offline reproduction and concrete CI artifacts to unblock it or fix the underlying bridge issue.",
            "allowed_paths": [
                "agent_tasks.json"
            ],
            "acceptance": [
                "Concrete offline reproduction evidence is collected.",
                "The root cause is identified using CI logs, local live smoke, or captured Claude Code transcripts.",
                "A fix is proposed or the task is closed if obsolete."
            ],
            "source_reference": f"Blocked task {task_id}"
        }
        tasks.append(new_task)
        todo_count += 1
    write_manifest(manifest_path, manifest)

    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "checkout", "-B", branch])
    run(["git", "add", str(manifest_path)])

    diff = run(["git", "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        print("No manifest changes to commit.")
        return 0

    run(["git", "commit", "-m", f"Block failed Jules task {task_id}"])
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    run(["git", "remote", "set-url", "origin", remote_url])
    run(["git", "push", "-u", "origin", branch, "--force-with-lease"])

    title = f"Блокировка задачи {task_id} после FAILED-сессий Jules"[:120]
    body = (
        f"<!-- {RECOVERY_MARKER} -->\n\n"
        "Открыто автоматически после повторного завершения Jules-сессий в состоянии FAILED.\n\n"
        "- Этап плана: recovery\n"
        f"- Что сделано: задача `{task_id}` переведена в `blocked`.\n"
        "- Что дальше: CI и automerge workflow должны проверить manifest-only изменение.\n"
        "- Зачем: остановить бесконечные retry и сохранить дневной лимит Jules.\n"
        "- Почему так: для этой задачи уже была одна recovery-попытка, повторный FAILED требует ручного/evidence-based возобновления.\n"
        "- Проверки/риски: изменение ограничено `agent_tasks.json`.\n\n"
        f"Jules FAILED sessions: `{sessions_text}`"
    )
    pr = request(
        "POST",
        f"/repos/{repo}/pulls",
        token=token,
        api_url=api_url,
        body={"title": title, "head": branch, "base": "master", "body": body},
    )
    number = pr["number"]
    print(f"Opened failed-session block PR #{number}.")
    for label, meta in RECOVERY_LABELS.items():
        ensure_label(
            name=label,
            color=meta["color"],
            description=meta["description"],
            token=token,
            repo=repo,
            api_url=api_url,
        )
    request(
        "POST",
        f"/repos/{repo}/issues/{number}/labels",
        token=token,
        api_url=api_url,
        body={"labels": sorted(RECOVERY_LABELS)},
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="agent_tasks.json", type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--failed-sessions", required=True)
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_API_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    if not token or not repo:
        print("GITHUB_API_TOKEN and GITHUB_REPOSITORY are required.", file=sys.stderr)
        return 2

    sessions = [item.strip() for item in args.failed_sessions.split(",") if item.strip()]
    if not sessions:
        print("No failed sessions were provided; block PR not needed.")
        return 0

    try:
        return open_block_pr(
            manifest_path=args.manifest,
            task_id=args.task_id,
            failed_sessions=sessions,
            token=token,
            repo=repo,
            api_url=api_url,
        )
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            if exc.stdout:
                print(exc.stdout, file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Apply Automation Health enforcement actions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_VARIABLE = "JULES_LOOP_ENABLED"


@dataclass(frozen=True)
class EnforcementDecision:
    action: str
    reason: str
    variable: str = DEFAULT_VARIABLE
    value: str = "false"

    @property
    def should_pause(self) -> bool:
        return self.action == "pause_loop"

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "action": self.action,
            "reason": self.reason,
            "variable": self.variable,
            "value": self.value,
            "should_pause": self.should_pause,
        }


def load_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as report_file:
        data = json.load(report_file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def critical_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        finding
        for finding in report.get("findings", [])
        if isinstance(finding, dict) and finding.get("severity") == "critical"
    ]


def decide_enforcement(
    report: dict[str, Any],
    *,
    mode: str,
    variable: str = DEFAULT_VARIABLE,
) -> EnforcementDecision:
    if mode != "enforce":
        return EnforcementDecision("none", "mode is shadow; enforcement is disabled", variable)

    status = str(report.get("status") or "")
    pause_loop = report.get("pause_loop") is True
    critical = critical_findings(report)
    if status != "critical":
        return EnforcementDecision("none", f"health status is {status or 'unknown'}, not critical", variable)
    if not pause_loop:
        return EnforcementDecision("none", "health report did not request pause_loop", variable)
    if not critical:
        return EnforcementDecision("none", "health report is critical but has no critical findings", variable)

    codes = ", ".join(sorted({str(finding.get("code") or "unknown") for finding in critical}))
    return EnforcementDecision("pause_loop", f"critical Automation Health findings: {codes}", variable)


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def request_json(
    url: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, method=method, data=payload)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload_obj: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload_obj = {"message": raw[:300]}
        return exc.code, payload_obj


def set_repo_variable_false(
    *,
    repo: str,
    api_url: str,
    token: str,
    variable: str,
) -> str:
    headers = github_headers(token)
    variable_url = f"{api_url}/repos/{repo}/actions/variables/{variable}"
    status, payload = request_json(variable_url, headers)
    current = ""
    if 200 <= status < 300 and isinstance(payload, dict):
        current = str(payload.get("value") or "")
        if current.lower() == "false":
            return "already_false"

    body = {"name": variable, "value": "false"}
    if 200 <= status < 300:
        write_status, write_payload = request_json(variable_url, headers, method="PATCH", body=body)
    elif status == 404:
        write_status, write_payload = request_json(
            f"{api_url}/repos/{repo}/actions/variables",
            headers,
            method="POST",
            body=body,
        )
    else:
        message = payload.get("message") if isinstance(payload, dict) else payload
        raise RuntimeError(f"could not read repository variable {variable}: HTTP {status}: {message}")

    if 200 <= write_status < 300:
        return "set_false"
    message = write_payload.get("message") if isinstance(write_payload, dict) else write_payload
    raise RuntimeError(f"could not set repository variable {variable}: HTTP {write_status}: {message}")


def write_outputs(path: str, values: dict[str, Any]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as output_file:
        for key, value in values.items():
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
            output_file.write(f"{key}={rendered}\n")


def write_audit(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Automation Health Enforcement",
        "",
        f"- Mode: `{result['mode']}`",
        f"- Health status: `{result['status']}`",
        f"- Action: `{result['action']}`",
        f"- Variable: `{result['variable']}`",
        f"- Result: `{result['result']}`",
        f"- Reason: {result['reason']}",
        "",
        "No repository variables are changed unless mode is `enforce`, health status is `critical`, "
        "and the health report explicitly sets `pause_loop=true`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-report", type=Path, default=Path("automation-health.json"))
    parser.add_argument("--mode", choices=["shadow", "enforce"], default="shadow")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--variable", default=DEFAULT_VARIABLE)
    parser.add_argument("--audit-md", type=Path, default=Path("automation-health-enforcement.md"))
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = load_report(args.health_report)
        decision = decide_enforcement(report, mode=args.mode, variable=args.variable)
        result = "not_required"
        if decision.should_pause:
            if args.dry_run:
                result = "dry_run"
            else:
                token = os.environ.get("GITHUB_API_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
                if not token:
                    raise RuntimeError("enforce mode requires GITHUB_API_TOKEN or GITHUB_TOKEN")
                result = set_repo_variable_false(
                    repo=args.repo,
                    api_url=args.api_url,
                    token=token,
                    variable=args.variable,
                )

        payload = {
            **decision.to_dict(),
            "mode": args.mode,
            "status": str(report.get("status") or ""),
            "result": result,
        }
        write_outputs(
            args.github_output,
            {
                "action": payload["action"],
                "result": payload["result"],
                "paused": decision.should_pause and result in {"set_false", "already_false"},
                "reason": payload["reason"],
            },
        )
        write_audit(args.audit_md, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload["reason"])
        return 0
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

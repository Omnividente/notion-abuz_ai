#!/usr/bin/env python3
"""Regression tests for jules-unattended-monitor.sh."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "jules-unattended-monitor.sh"
TASK_ID = "proxy-runtime-final-answer-mode-stability"


FAKE_CURL = r"""#!/usr/bin/env bash
exec "$PYTHON_FOR_FAKE_CURL" - "$@" <<'PY'
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


args = sys.argv[1:]
method = "GET"
out = ""
url = ""
i = 0
while i < len(args):
    arg = args[i]
    if arg == "-X":
        method = args[i + 1]
        i += 2
        continue
    if arg in {"-H", "-d"}:
        i += 2
        continue
    if arg == "-o":
        out = args[i + 1]
        i += 2
        continue
    if arg.startswith("http://") or arg.startswith("https://"):
        url = arg
    i += 1

if not out:
    print("fake curl requires -o", file=sys.stderr)
    raise SystemExit(2)

now = int(os.environ["FAKE_NOW_EPOCH"])
session_name = "sessions/test-repeat-feedback"
task_id = "proxy-runtime-final-answer-mode-stability"

if method == "GET" and url.endswith("/sessions?pageSize=100"):
    payload = {
        "sessions": [
            {
                "name": session_name,
                "state": "AWAITING_USER_FEEDBACK",
                "sourceContext": {"source": "sources/github/Omnividente/notion-abuz_ai"},
                "createTime": iso(now - 900),
                "updateTime": iso(now - 60),
            }
        ]
    }
elif method == "GET" and f"/{session_name}/activities?" in url:
    payload = {
        "activities": [
            {
                "originator": "AGENT",
                "createTime": iso(now - 500),
                "message": {
                    "text": f"selected task id: {task_id}\nI need input before continuing."
                },
            },
            {
                "originator": "USER",
                "createTime": iso(now - 490),
                "message": {"text": "AUTONOMOUS_CONTINUE_TOKEN\nContinue."},
            },
            {
                "originator": "USER",
                "createTime": iso(now - 450),
                "message": {"text": "AUTONOMOUS_CONTINUE_TOKEN\nContinue again."},
            },
            {
                "originator": "USER",
                "createTime": iso(now - 300),
                "message": {"text": "AUTONOMOUS_CONTINUE_TOKEN\nStill continue."},
            },
        ]
    }
elif method == "DELETE" and url.endswith(f"/{session_name}"):
    Path(os.environ["FAKE_CURL_LOG"]).write_text(
        f"DELETE {session_name}\n",
        encoding="utf-8",
    )
    payload = {}
else:
    print(f"unexpected fake curl call: method={method} url={url}", file=sys.stderr)
    raise SystemExit(22)

Path(out).write_text(json.dumps(payload), encoding="utf-8")
PY
"""


class JulesUnattendedMonitorTest(unittest.TestCase):
    def test_repeated_autonomous_continue_limit_deletes_without_waiting_for_stale_age(self) -> None:
        if not shutil.which("bash"):
            self.skipTest("bash is required for jules-unattended-monitor.sh")
        if not shutil.which("jq"):
            self.skipTest("jq is required for jules-unattended-monitor.sh")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text(FAKE_CURL, encoding="utf-8", newline="\n")
            fake_curl.chmod(0o755)

            output_path = tmp_path / "github-output.txt"
            curl_log = tmp_path / "curl.log"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
                    "PYTHON_FOR_FAKE_CURL": sys.executable,
                    "FAKE_NOW_EPOCH": str(int(time.time())),
                    "FAKE_CURL_LOG": str(curl_log),
                    "GITHUB_OUTPUT": str(output_path),
                    "GITHUB_REPOSITORY": "Omnividente/notion-abuz_ai",
                    "JULES_API_KEY": "fake-key",
                    "LOOKBACK_HOURS": "24",
                    "MIN_USER_REPLY_INTERVAL_MINUTES": "0",
                    "STALE_AWAITING_FEEDBACK_MINUTES": "10",
                    "MAX_STALE_AWAITING_FEEDBACK_ESCALATIONS": "2",
                }
            )
            for name in ("JULES_API_KEY_BACKUP", "GITHUB_API_TOKEN", "GITHUB_API_URL"):
                env.pop(name, None)

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=ROOT,
                env=env,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            self.assertIn(
                "Autonomous continue limit reached for sessions/test-repeat-feedback",
                result.stdout,
            )
            self.assertNotIn("autonomous continue already answers the latest wait state", result.stdout)
            self.assertEqual(curl_log.read_text(encoding="utf-8"), "DELETE sessions/test-repeat-feedback\n")

            outputs = dict(
                line.split("=", 1)
                for line in output_path.read_text(encoding="utf-8").splitlines()
                if "=" in line
            )
            self.assertEqual(outputs["active_sessions"], "0")
            self.assertEqual(outputs["touched_sessions"], "1")
            self.assertEqual(outputs["stale_waiting_count"], "0")
            self.assertEqual(outputs["failed_recovery_action"], "block")
            self.assertEqual(outputs["failed_task_id"], TASK_ID)
            self.assertEqual(outputs["failed_session_id"], "test-repeat-feedback")


if __name__ == "__main__":
    unittest.main()

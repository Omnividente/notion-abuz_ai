#!/usr/bin/env bash
set -euo pipefail

SMOKE_MODEL="${SMOKE_MODEL:-opus-4.8}"
SMOKE_PORT="${SMOKE_PORT:-31081}"
SMOKE_API_KEY="${SMOKE_API_KEY:-local-live-smoke-key}"
SMOKE_SUMMARY_PATH="${SMOKE_SUMMARY_PATH:-/tmp/local-live-smoke-summary.json}"
SMOKE_STATUS="failed"
SMOKE_STAGE="init"
OPENAI_EXPECTED_TOKEN="not_run"
OPENAI_PERSONA_LEAK="not_run"
OPENAI_WORKSPACE_REFRAMING="not_run"
OPENAI_TOOL_REFUSAL="not_run"
ANTHROPIC_EXPECTED_TOKEN="not_run"
ANTHROPIC_PERSONA_LEAK="not_run"
ANTHROPIC_WORKSPACE_REFRAMING="not_run"
ANTHROPIC_TOOL_REFUSAL="not_run"

write_summary() {
  mkdir -p "$(dirname "$SMOKE_SUMMARY_PATH")"
  SMOKE_STATUS="$SMOKE_STATUS" \
  SMOKE_STAGE="$SMOKE_STAGE" \
  SMOKE_MODEL="$SMOKE_MODEL" \
  SMOKE_PORT="$SMOKE_PORT" \
  SMOKE_EXIT_CODE="${SMOKE_EXIT_CODE:-0}" \
  OPENAI_EXPECTED_TOKEN="$OPENAI_EXPECTED_TOKEN" \
  OPENAI_PERSONA_LEAK="$OPENAI_PERSONA_LEAK" \
  OPENAI_WORKSPACE_REFRAMING="$OPENAI_WORKSPACE_REFRAMING" \
  OPENAI_TOOL_REFUSAL="$OPENAI_TOOL_REFUSAL" \
  ANTHROPIC_EXPECTED_TOKEN="$ANTHROPIC_EXPECTED_TOKEN" \
  ANTHROPIC_PERSONA_LEAK="$ANTHROPIC_PERSONA_LEAK" \
  ANTHROPIC_WORKSPACE_REFRAMING="$ANTHROPIC_WORKSPACE_REFRAMING" \
  ANTHROPIC_TOOL_REFUSAL="$ANTHROPIC_TOOL_REFUSAL" \
  python3 - <<'PY' > "$SMOKE_SUMMARY_PATH"
import json
import os
from pathlib import Path

account_count_path = Path("/tmp/live-smoke-account-count.txt")
account_count = None
if account_count_path.exists():
    try:
        account_count = int(account_count_path.read_text(encoding="utf-8").strip())
    except ValueError:
        account_count = None

summary = {
    "status": os.environ["SMOKE_STATUS"],
    "failed_stage": os.environ["SMOKE_STAGE"] if os.environ["SMOKE_STATUS"] != "passed" else "",
    "exit_code": int(os.environ.get("SMOKE_EXIT_CODE") or "0"),
    "model": os.environ["SMOKE_MODEL"],
    "port": int(os.environ["SMOKE_PORT"]),
    "account_file_count": account_count,
    "checks": {
        "openai": {
            "expected_token": os.environ["OPENAI_EXPECTED_TOKEN"],
            "workspace_reframing": os.environ["OPENAI_WORKSPACE_REFRAMING"],
            "tool_refusal": os.environ["OPENAI_TOOL_REFUSAL"],
            "persona_leak": os.environ["OPENAI_PERSONA_LEAK"],
        },
        "anthropic": {
            "expected_token": os.environ["ANTHROPIC_EXPECTED_TOKEN"],
            "workspace_reframing": os.environ["ANTHROPIC_WORKSPACE_REFRAMING"],
            "tool_refusal": os.environ["ANTHROPIC_TOOL_REFUSAL"],
            "persona_leak": os.environ["ANTHROPIC_PERSONA_LEAK"],
        },
    },
}
print(json.dumps(summary, indent=2, sort_keys=True))
PY
}

cleanup() {
  if [ -f /tmp/notion-manager.pid ]; then
    kill "$(cat /tmp/notion-manager.pid)" 2>/dev/null || true
  fi
}

on_exit() {
  exit_code=$?
  trap - EXIT
  set +e
  SMOKE_EXIT_CODE="$exit_code"
  if [ "$exit_code" -eq 0 ]; then
    SMOKE_STATUS="passed"
    SMOKE_STAGE="complete"
  fi
  write_summary
  cleanup
  exit "$exit_code"
}
trap on_exit EXIT

if [ -z "${LIVE_NOTION_ACCOUNTS_B64:-}" ]; then
  echo "::error::Missing environment or repository secret LIVE_NOTION_ACCOUNTS_B64."
  SMOKE_STAGE="missing_secret"
  exit 1
fi

SMOKE_STAGE="decode_accounts"
python3 - <<'PY'
import base64
import json
import os
import pathlib
import zipfile

raw = os.environ["LIVE_NOTION_ACCOUNTS_B64"]
data = base64.b64decode("".join(raw.split()))
accounts_dir = pathlib.Path("accounts")
accounts_dir.mkdir(exist_ok=True)
payload = pathlib.Path("/tmp/live-notion-accounts.payload")
payload.write_bytes(data)

written = []
if zipfile.is_zipfile(payload):
    with zipfile.ZipFile(payload) as archive:
        for member in archive.namelist():
            name = pathlib.PurePosixPath(member).name
            if not name.endswith(".json") or name.startswith("."):
                continue
            target = accounts_dir / name
            target.write_bytes(archive.read(member))
            written.append(target)
else:
    obj = json.loads(data.decode("utf-8"))
    if isinstance(obj, list):
        for index, account in enumerate(obj, start=1):
            target = accounts_dir / f"account-{index}.json"
            target.write_text(json.dumps(account), encoding="utf-8")
            written.append(target)
    elif isinstance(obj, dict) and "token_v2" not in obj and all(isinstance(v, dict) for v in obj.values()):
        for index, account in enumerate(obj.values(), start=1):
            target = accounts_dir / f"account-{index}.json"
            target.write_text(json.dumps(account), encoding="utf-8")
            written.append(target)
    elif isinstance(obj, dict):
        target = accounts_dir / "account-1.json"
        target.write_text(json.dumps(obj), encoding="utf-8")
        written.append(target)
    else:
        raise SystemExit("LIVE_NOTION_ACCOUNTS_B64 decoded JSON is not an object or array")

if not written:
    raise SystemExit("LIVE_NOTION_ACCOUNTS_B64 did not contain any account JSON files")

pathlib.Path("/tmp/live-smoke-account-count.txt").write_text(str(len(written)), encoding="utf-8")
print(f"Decoded {len(written)} live account file(s).")
PY

SMOKE_STAGE="write_config"
cat > config.yaml <<'YAML'
server:
  port: "31081"
  accounts_dir: "accounts"
  token_file: "token.txt"
  api_key: "local-live-smoke-key"
  admin_password: "local-live-smoke-admin"
  log_file: ""
  debug_logging: false
  api_log_input: false
  api_log_output: false
  notion_log_request: false
  notion_log_response: false
  dump_api_input: false
proxy:
  default_model: "opus-4.8"
  disable_notion_prompt: true
  enable_web_search: false
  enable_workspace_search: false
  ask_mode_default: false
timeouts:
  inference_timeout: 180
  research_timeout: 180
  api_timeout: 30
  tls_dial_timeout: 30
refresh:
  interval_minutes: 60
  quota_recheck_minutes: 30
  concurrency: 1
  live_check_seconds: 5
YAML

SMOKE_STAGE="build"
if [ ! -x ./notion-manager ]; then
  go build -ldflags="-s -w" -o notion-manager ./cmd/notion-manager
fi

SMOKE_STAGE="start_server"
PORT="$SMOKE_PORT" \
API_KEY="$SMOKE_API_KEY" \
DEBUG_LOGGING=false \
API_LOG_INPUT=false \
API_LOG_OUTPUT=false \
NOTION_LOG_REQUEST=false \
NOTION_LOG_RESPONSE=false \
./notion-manager > /tmp/notion-manager.stdout.log 2> /tmp/notion-manager.stderr.log &
echo "$!" > /tmp/notion-manager.pid

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${SMOKE_PORT}/health" > /tmp/health.json; then
    cat /tmp/health.json | jq '{status, accounts, available}'
    jq -e '.accounts > 0' /tmp/health.json >/dev/null
    break
  fi
  sleep 2
done

if ! curl -fsS "http://127.0.0.1:${SMOKE_PORT}/health" > /tmp/health.json; then
  echo "::error::local notion-manager did not become healthy."
  tail -100 /tmp/notion-manager.stderr.log || true
  exit 1
fi

SMOKE_STAGE="openai_request"
openai_body="$(jq -n \
  --arg model "$SMOKE_MODEL" \
  '{
    model: $model,
    stream: false,
    max_tokens: 64,
    messages: [
      {
        role: "system",
        content: "You are a Claude Code compatible coding assistant behind an OpenAI-compatible proxy. Do not mention Notion, pages, workspaces, or documents. Follow the user instruction exactly."
      },
      {
        role: "user",
        content: "Reply exactly with this token and nothing else: OK_CLAUDE_PROXY_OPENAI"
      }
    ]
  }')"

openai_response="$(curl -fsS --max-time 180 \
  -X POST "http://127.0.0.1:${SMOKE_PORT}/v1/chat/completions" \
  -H "Authorization: Bearer ${SMOKE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$openai_body")"

openai_content="$(echo "$openai_response" | jq -r '.choices[0].message.content // ""')"
echo "OpenAI-compatible smoke content: $openai_content"

if ! grep -q 'OK_CLAUDE_PROXY_OPENAI' <<<"$openai_content"; then
  OPENAI_EXPECTED_TOKEN="failed"
  echo "::error::OpenAI-compatible local smoke did not contain the expected token."
  echo "Diagnostic (first 256 chars): ${openai_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
OPENAI_EXPECTED_TOKEN="passed"
if grep -Eiq 'notion workspace|notion context|our workspace|reframe the workspace|switch workspace|your notion workspace' <<<"$openai_content"; then
  OPENAI_WORKSPACE_REFRAMING="failed"
  echo "::error::OpenAI-compatible local smoke drifted due to workspace reframing."
  echo "Diagnostic (first 256 chars): ${openai_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
OPENAI_WORKSPACE_REFRAMING="passed"
if grep -Eiq "don't have access to your local machine|cannot run commands directly|cannot access your local system|unable to execute code|you will need to run this|don't have direct access|cannot execute commands directly" <<<"$openai_content"; then
  OPENAI_TOOL_REFUSAL="failed"
  echo "::error::OpenAI-compatible local smoke drifted due to tool-call refusal."
  echo "Diagnostic (first 256 chars): ${openai_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
OPENAI_TOOL_REFUSAL="passed"
if grep -Eiq 'notion|workspace|page|document' <<<"$openai_content"; then
  OPENAI_PERSONA_LEAK="failed"
  echo "::error::OpenAI-compatible local smoke leaked Notion/workspace/page/document persona text."
  echo "Diagnostic (first 256 chars): ${openai_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
OPENAI_PERSONA_LEAK="passed"

SMOKE_STAGE="anthropic_request"
anthropic_body="$(jq -n \
  --arg model "$SMOKE_MODEL" \
  '{
    model: $model,
    stream: false,
    max_tokens: 64,
    system: "You are Claude Code, Anthropic'\''s official CLI for coding. You are behind a compatibility proxy. Do not mention Notion, pages, workspaces, or documents. Follow the user instruction exactly.",
    messages: [
      {
        role: "user",
        content: "Reply exactly with this token and nothing else: OK_CLAUDE_PROXY_ANTHROPIC"
      }
    ]
  }')"

anthropic_response="$(curl -fsS --max-time 180 \
  -X POST "http://127.0.0.1:${SMOKE_PORT}/v1/messages" \
  -H "Authorization: Bearer ${SMOKE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$anthropic_body")"

anthropic_content="$(echo "$anthropic_response" | jq -r '[.content[]? | select(.type == "text") | .text] | join("\n")')"
echo "Anthropic smoke content: $anthropic_content"

if ! grep -q 'OK_CLAUDE_PROXY_ANTHROPIC' <<<"$anthropic_content"; then
  ANTHROPIC_EXPECTED_TOKEN="failed"
  echo "::error::Anthropic local smoke did not contain the expected token."
  echo "Diagnostic (first 256 chars): ${anthropic_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
ANTHROPIC_EXPECTED_TOKEN="passed"
if grep -Eiq 'notion workspace|notion context|our workspace|reframe the workspace|switch workspace|your notion workspace' <<<"$anthropic_content"; then
  ANTHROPIC_WORKSPACE_REFRAMING="failed"
  echo "::error::Anthropic local smoke drifted due to workspace reframing."
  echo "Diagnostic (first 256 chars): ${anthropic_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
ANTHROPIC_WORKSPACE_REFRAMING="passed"
if grep -Eiq "don't have access to your local machine|cannot run commands directly|cannot access your local system|unable to execute code|you will need to run this|don't have direct access|cannot execute commands directly" <<<"$anthropic_content"; then
  ANTHROPIC_TOOL_REFUSAL="failed"
  echo "::error::Anthropic local smoke drifted due to tool-call refusal."
  echo "Diagnostic (first 256 chars): ${anthropic_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
ANTHROPIC_TOOL_REFUSAL="passed"
if grep -Eiq 'notion|workspace|page|document' <<<"$anthropic_content"; then
  ANTHROPIC_PERSONA_LEAK="failed"
  echo "::error::Anthropic local smoke leaked Notion/workspace/page/document persona text."
  echo "Diagnostic (first 256 chars): ${anthropic_content:0:256}"
  grep -E '\[bridge\] decision:|\[session\] decision:' /tmp/notion-manager.stderr.log || true
  exit 1
fi
ANTHROPIC_PERSONA_LEAK="passed"

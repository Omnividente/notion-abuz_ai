# Configuration

[← Back to README](../README.md)

## Priority

```text
environment variables > config.yaml > code defaults
```

## Server

| Setting | Repo sample | Code default | Notes |
| --- | --- | --- | --- |
| `server.port` | `3000` | `8081` | Listening port |
| `server.accounts_dir` | `accounts` | `accounts` | Account JSON directory; also stores `.register_history.json` / `.token_stats.json` / `.register_inputs/` |
| `server.token_file` | `token.txt` | `token.txt` | Fallback single-account file |
| `server.api_key` | empty | auto-generated | Used by `/v1/messages` |
| `server.admin_password` | empty | auto-generated | Hashed on first startup |
| `server.log_file` | `server.stderr.log` | empty (stderr) | All `log.Printf` output is appended here |
| `server.debug_logging` | `true` | `true` | High-volume debug logs |
| `server.api_log_input` | `true` | `false` | Log incoming `/v1/messages` request bodies |
| `server.api_log_output` | `true` | `false` | Log responses returned to API clients |
| `server.notion_log_request` | `true` | `false` | Log `runInferenceTranscript` request bodies |
| `server.notion_log_response` | `true` | `false` | Log raw inference responses |
| `server.dump_api_input` | `false` | `false` | Dump system prompts + tool schemas to disk per request (Claude Code debugging) |

## Proxy / runtime behaviour

| Setting | Repo sample | Code default | Notes |
| --- | --- | --- | --- |
| `proxy.notion_api_base` | `https://www.notion.so/api/v3` | same | Notion API base URL |
| `proxy.client_version` | `23.13.20260313.1423` | same | `x-notion-client-version` header |
| `proxy.default_model` | `opus-4.6` | `opus-4.6` | Fallback model when request omits one |
| `model_map` | (see below) | empty | Map custom model names to Notion internal model IDs |
| `proxy.disable_notion_prompt` | `true` | `false` | Removes Notion's ~33k system prompt for leaner API usage |
| `proxy.enable_web_search` | `true` | `true` | Global web-search toggle (overridable per-request) |
| `proxy.enable_workspace_search` | `false` | `false` | Global workspace-search toggle (overridable per-request) |
| `proxy.ask_mode_default` | unset | `false` | When `true`, every chat runs with `useReadOnlyMode=true` (Notion's "Ask" toggle) — the per-request `-ask` suffix overrides this |
| `proxy.notion_proxy` | empty | empty | Upstream proxy (`http`/`https`/`socks5`/`socks5h`) used for **all** Notion-bound dials, including bulk register, `/ai`, and `/v1/messages` |

## Timeouts / refresh

| Setting | Repo sample | Code default | Notes |
| --- | --- | --- | --- |
| `timeouts.inference_timeout` | `300` | `300` | Standard inference timeout (s) |
| `timeouts.research_timeout` | unset | `360` | Research-mode timeout (s) — applies to `researcher` / `fast-researcher` |
| `timeouts.api_timeout` | `30` | `30` | Quota / models REST timeout (s) |
| `timeouts.tls_dial_timeout` | `30` | `30` | TLS dial timeout (s) |
| `refresh.interval_minutes` | `30` | `30` | Background refresh interval |
| `refresh.quota_recheck_minutes` | `30` | `30` | Min interval between rechecks of an exhausted account |
| `refresh.concurrency` | `10` | `10` | Concurrent refresh workers |
| `refresh.live_check_seconds` | unset | `5` | Min interval between live per-request quota checks for the same account; `0` = check on every request |

## Register (bulk MS SSO)

| Setting | Code default | Notes |
| --- | --- | --- |
| `register.history_file` | `accounts/.register_history.json` | Persisted job history; reloaded on startup |
| `register.history_memory_cap` | `100` | Max jobs kept in RAM (and on disk) |
| `register.default_concurrency` | `1` | Pre-filled value in the dashboard register modal |

## Environment variables

Every `server.*`, `proxy.*`, `timeouts.*`, `refresh.*`, `browser.*` field above has an equivalent env var (uppercased, dotted segments joined by `_`). The most useful ones:

```bash
export PORT=3000
export API_KEY=sk-your-api-key
export ENABLE_WEB_SEARCH=true
export ENABLE_WORKSPACE_SEARCH=false
export ASK_MODE_DEFAULT=false
export NOTION_PROXY=socks5h://127.0.0.1:1080
export QUOTA_LIVE_CHECK_SECONDS=5
export REFRESH_CONCURRENCY=10
```

### Model Map & Reasoning Effort Routing

You can define friendly aliases for models by putting them in `model_map`.
This is particularly useful for routing OpenAI-compatible `reasoning_effort` queries.
If you set up `opus-4.8-high: notion-internal-high-id` in your `config.yaml`, a client requesting `model="opus-4.8"` with `reasoning_effort="high"` will automatically be routed to that internal Notion ID.

```yaml
model_map:
  opus-4.8-high: notion-internal-high-id
  sonnet-4.6-low: notion-internal-low-id
```

An invalid `NOTION_PROXY` is logged once at startup and dropped — runtime falls back to direct dial rather than leaking the misconfigured URL into every Notion request.

## Endpoints

| Path | Purpose | Auth |
| --- | --- | --- |
| `GET /health` | Health and account pool summary | None |
| `POST /v1/messages` | Anthropic Messages API | API key |
| `GET /dashboard/` | Dashboard UI | Dashboard login |
| `GET /proxy/start` | Create a targeted proxy session | Dashboard login |
| `GET /ai` | Local Notion Web proxy entry | `np_session` |
| `GET /admin/accounts` | Pool list (supports `q`, `page`, `page_size`) | Dashboard session |
| `DELETE /admin/accounts/{email}` | Remove account file + pool entry | Dashboard session |
| `GET /admin/models` | Model mapping + pool-discovered models | Dashboard session |
| `GET/POST /admin/refresh` | Refresh status / trigger refresh | Dashboard session |
| `GET/PUT /admin/settings` | Read / update runtime settings (`enable_web_search`, `enable_workspace_search`, `ask_mode_default`, `debug_logging`, `notion_proxy`) | Dashboard session |
| `GET /admin/stats` | Token usage statistics (lifetime + today + 24h + 30-day series + top-N) | Dashboard session |
| `POST /admin/register` | Legacy synchronous bulk register (kept for back-compat) | Dashboard session |
| `GET /admin/register/providers` | List registered Providers | Dashboard session |
| `POST /admin/register/start` | Start a new bulk-register Job | Dashboard session |
| `GET /admin/register/jobs[?limit=]` | Recent Job list | Dashboard session |
| `GET /admin/register/jobs/{id}` | Single Job snapshot | Dashboard session |
| `GET /admin/register/jobs/{id}/events` | SSE event stream | Dashboard session |
| `POST /admin/register/jobs/{id}/retry` | Retry only the failed steps | Dashboard session |
| `DELETE /admin/register/jobs/{id}` | Drop Job + sidecar | Dashboard session |

## Project layout

```text
notion-manager/
├── cmd/notion-manager/        # Server entrypoint
├── cmd/register/              # Standalone bulk-register CLI
├── internal/proxy/            # Account pool, API handler, reverse proxy, uploads, config, stats
├── internal/msalogin/         # Microsoft consumer SSO + Notion onboarding flow
├── internal/regjob/           # Provider-pluggable bulk-register runner + store
├── internal/regjob/providers/ # Provider implementations (microsoft/, ...)
├── internal/netutil/          # Proxy dialer helpers
├── internal/web/dist/         # Embedded Dashboard static assets
├── web/                       # Dashboard frontend source (React + Vite)
├── chrome-extension/          # Chrome extension that extracts Notion sessions
├── accounts/                  # Account JSON files + .register_history.json + .token_stats.json
├── docs/                      # English + Chinese documentation
├── example.config.yaml
├── README.md
└── README_CN.md
```

## Notes

- `admin_password` left empty auto-generates a random password printed to the console, then hashes and writes it back. Save the plaintext shown on first startup — it cannot be recovered.
- Reverse proxy works best with account files that include `full_cookie`; Microsoft-SSO registrations come with a working `full_cookie` out of the box.
- Free accounts can stay exhausted indefinitely; paid accounts make a more stable pool.
- If you change the dashboard source under `web/`, run `npm run build` inside `web/` and copy the output into `internal/web/dist/`.
- `accounts/.register_inputs/<job_id>.json` contains plaintext credentials and **must not be checked into version control** — `.gitignore` already excludes the directory.

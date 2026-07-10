# Health Check & Observability

[← Back to README](../README.md)

The `/health` endpoint provides real-time observability into the proxy's `AccountPool` and the current state of Notion AI quotas. It is critical for debugging routing issues, identifying exhausted accounts, and integrating with external monitoring tools (like Prometheus or Uptime Kuma).

## Endpoint

**`GET /health`**

Returns a JSON snapshot of the account pool's availability and quota statistics. This endpoint does not require authentication, allowing it to be safely exposed to internal health-check services.

## Example Request

```bash
curl -s http://localhost:3000/health | jq
```

## Example Response

```json
{
  "accounts": 3,
  "available": 2,
  "quota": [
    {
      "checked_at": "2023-10-27T10:05:00Z",
      "eligible": true,
      "email": "alice@example.com",
      "exhausted": false,
      "has_premium": true,
      "last_usage_at": 1698401100000,
      "limit": 1000,
      "name": "Alice User",
      "no_workspace": false,
      "permanent": false,
      "plan": "Plus",
      "premium_balance": 500,
      "premium_limit": 500,
      "premium_usage": 0,
      "remaining": 955,
      "research_usage": 10,
      "space_count": 1,
      "space_limit": 1000,
      "space_remaining": 955,
      "space_usage": 45,
      "usage": 45,
      "user_limit": 1000,
      "user_remaining": 955,
      "user_usage": 45,
      "workspace_checked_at": "2023-10-27T10:00:00Z"
    },
    {
      "eligible": true,
      "email": "bob@example.com",
      "exhausted": true,
      "name": "Bob User",
      "no_workspace": false,
      "permanent": true,
      "plan": "Free",
      "space_count": 1,
      "usage": 100,
      "workspace_checked_at": "2023-10-27T10:05:00Z"
    },
    {
      "email": "frank@example.com",
      "exhausted": true,
      "name": "Frank User",
      "no_workspace": true,
      "permanent": true,
      "plan": "Free"
    }
  ],
  "status": "ok"
}
```

## Fields Breakdown

### Top-level Fields
- **`status`**: Overall service status. `ok` means the HTTP server is responsive.
- **`accounts`**: Total number of accounts loaded into the pool from JSON files.
- **`available`**: Number of accounts currently considered "healthy" (not exhausted and possessing a valid workspace). The proxy will route requests to these accounts.

### Quota Entry Fields
Each object in the `quota` array represents the real-time state of an account:
- **`email` / `name`**: Identifiers for the account.
- **`plan`**: The Notion plan type (e.g., `Plus`, `Free`, `Enterprise`).
- **`exhausted`**: Boolean indicating if the proxy currently refuses to route traffic to this account. This happens if the quota is hit or if no valid workspace is found.
- **`permanent`**: Boolean. If `true`, the quota is hard-capped by Notion (e.g., a Free plan hitting the absolute limit), meaning it will not reset next month.
- **`no_workspace`**: Boolean. If `true`, the account failed the workspace probe (e.g., the user hasn't completed onboarding or the workspace lacks AI permissions). The account is skipped during routing.
- **`space_count`**: Number of workspaces the account has access to.
- **`workspace_checked_at`**: ISO-8601 timestamp of the last successful workspace probe.
- **`eligible`**: Boolean indicating if the workspace is theoretically eligible for AI features.
- **`usage`**: The legacy combined usage metric.
- **`limit`**: The legacy combined limit metric.
- **`remaining`**: The legacy combined remaining metric.
- **`space_usage` / `space_limit` / `space_remaining`**: Workspace-level quota metrics.
- **`user_usage` / `user_limit` / `user_remaining`**: User-level quota metrics.
- **`last_usage_at`**: Unix timestamp (milliseconds) of the last AI usage.
- **`research_usage`**: V1 research mode usage.
- **`has_premium`**: Boolean indicating if the account has premium credits.
- **`premium_balance` / `premium_usage` / `premium_limit`**: V2 premium credit metrics.
- **`checked_at`**: ISO-8601 timestamp of the last successful quota probe.

## Debugging Scenarios

1. **All accounts are exhausted (`available: 0`)**
   - **Symptoms:** Proxy returns `503 Service Unavailable` or `429 Too Many Requests` (Quota Exhausted).
   - **Action:** Check the `quota` array.
     - Are they `permanent: true`? You need to add new accounts or upgrade plans.
     - Are they `no_workspace: true`? Ensure the accounts have logged into Notion via a browser at least once and completed the initial setup.

2. **Account added but not serving traffic**
   - **Symptoms:** You added `new-account.json`, but `available` count didn't increase.
   - **Action:** Check if `no_workspace` is `true`. The background `regjob` might not have successfully probed the workspace yet, or the exported cookie is invalid/expired. Restart the proxy to force an immediate probe.

3. **Claude Code / OpenCode bridge failures**
   - **Symptoms:** Intermittent `502 Bad Gateway` errors.
   - **Action:** Monitor `/health` to see if an account is flipping between `exhausted: true` and `exhausted: false`. This can happen if Notion's internal rate limiting kicks in before the strict quota limit is reached.

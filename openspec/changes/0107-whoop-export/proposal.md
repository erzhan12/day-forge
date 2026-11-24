# 0107 — WHOOP morning summary via the export API and MCP

## Why

Every morning the user pastes last night's WHOOP sleep and recovery into the planning coach by hand. The coach already reads the day through the Day Forge MCP connector, so it should fetch the WHOOP numbers the same way. See [docs/features/0107_PLAN.md](../../../docs/features/0107_PLAN.md).

## What changes

- A new `whoop_sync` integration: a one-time OAuth connect and callback, with tokens Fernet-encrypted under their own key. Refreshes run one at a time behind a shared-cache lock, because WHOOP rotates the refresh token on every refresh and rejects concurrent refreshes.
- A new read route, `GET /api/export/whoop/<date>/`, renders recovery, sleep, the previous day's strain and workouts as Markdown. It stores, caches and logs no WHOOP data.
- The personal export token now authorizes exactly two routes, `daily_export` and `whoop_export`, both listed in one allowlist constant. Every other `/api/` route still rejects Bearer.
- A new MCP tool, `get_whoop_day`, forwards the caller's export token to the new route, the same way `get_daily_report` does.
- WHOOP settings are optional at boot: with no `WHOOP_OAUTH_*` set, the integration is disabled; if any is set, all four are required.

## Capabilities

- `integrations/whoop`: ADDED (connect, token lifecycle, date mapping).
- `export/daily-export`: MODIFIED personal export token scope (two routes).
- `export/mcp-server`: ADDED `get_whoop_day`.

## Impact

Backend and the MCP server; no frontend change except the export-token dialog copy. Adds a migration (`WhoopAccount`), four GitHub secrets passed through `deploy.yml`, and one line on the privacy page.

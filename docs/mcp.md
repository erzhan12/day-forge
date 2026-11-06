# MCP connector — feature 0089

Thin, **stateless** [Model Context Protocol](https://modelcontextprotocol.io/) proxy in front of the daily export API (feature 0088). An LLM host (claude.ai custom connector, Claude Code, Grok Bot) calls one tool; the proxy forwards the caller's export token to Day Forge and returns the report. No OAuth, no server-side credential store, no server-side LLM egress.

- Public URL: `https://dayforge.habitreward.org/mcp` (Streamable HTTP, JSON responses, stateless sessions).
- Health: `GET /mcp/health` → `{"status":"ok"}` (public, no auth).
- Package: top-level `mcp_server/` (never name it `mcp/` — that shadows the SDK).
- Upstream: compose-internal `http://web:8006` with `Host: dayforge.habitreward.org` and `X-Forwarded-Proto: https` (same trick as the web healthcheck). Override with `DAYFORGE_API_BASE` (or alias `DAYFORGE_API_URL`) for local Inspector against the public site.

## Tools

| Tool | Arguments | Result |
|---|---|---|
| `ping` | _(none)_ | `"pong"` — connectivity check |
| `get_daily_report` | `date` (`"today"` or `YYYY-MM-DD`, default `today`); `format` (`"markdown"` \| `"json"`, default `markdown`) | Report body as text, or a tool error |

`get_daily_report` requires an `Authorization: Bearer <export token>` **request header** on the MCP call. The proxy forwards it verbatim and never logs the value (only `auth=present/absent` if logging is added later). Mint a token in Settings → Integrations, or `POST /api/user/export-token/` (session-only) — see [api.md](api.md#daily-export--feature-0088).

### Error semantics

Business failures are MCP **tool errors** (`isError: true` + human text), not JSON-RPC protocol errors, so the model can tell the user what went wrong:

| Condition | Message |
|---|---|
| Missing `Authorization` | `missing Authorization header` |
| Bad `date` | `date must be 'today' or YYYY-MM-DD` |
| Upstream 401 / 403 | `invalid or missing day-forge export token` |
| Upstream 404 | `no report for this date` |
| Upstream 429 | `rate limited, try later` |
| Other non-2xx | `day-forge error {status}` |
| Timeout / connect error | `day-forge is unreachable` |

Upstream response bodies are never echoed into tool errors.

## Connecting clients

All three pass the export token as a request header. Auth mode is **"No sign-in"** / no OAuth.

### claude.ai custom connector

1. Open [claude.ai/customize/connectors](https://claude.ai/customize/connectors) → Add custom connector.
2. URL: `https://dayforge.habitreward.org/mcp`.
3. Advanced → auth **"No sign-in"**.
4. Request headers: `Authorization` = `Bearer dfx_…` (your export token).
5. Transport: Streamable HTTP.
6. Save, then ask Claude for "today's Day Forge schedule".

### Claude Code

```bash
claude mcp add --transport http day-forge https://dayforge.habitreward.org/mcp \
  --header "Authorization: Bearer dfx_…"
```

### Grok Bot

Add a custom MCP connector with the same URL and the same `Authorization: Bearer dfx_…` request header.

## Privacy

Schedule text flows **client → MCP proxy → export API** only. Day Forge never sends the report to an LLM provider; the client's own model sees it because the client asked. Revoke the export token in Settings to cut off every connector at once.

## Local development

```bash
uv sync --group mcp --group mcp-dev
# Default DAYFORGE_API_BASE is http://web:8006 (compose-internal). Outside compose,
# set an explicit base — public HTTPS, or local Django with DAYFORGE_API_HOST=localhost:
export DAYFORGE_API_BASE=https://dayforge.habitreward.org
# export DAYFORGE_API_BASE=http://127.0.0.1:8006 DAYFORGE_API_HOST=localhost
uv run --group mcp python -m mcp_server   # :8009
uv run --group mcp --group mcp-dev pytest -p no:django mcp_server/tests -q
```

Or `docker compose up` (dev compose builds `deployment/docker/Dockerfile.mcp` and publishes `8009`).

# Feature 0089 — External review trail

Criteria: `commands/code_review.md`. Engines: Claude Code (opus), Codex (read-only). Grok excluded. Iterations: 2/4. Result: SUCCESS (zero valid P1/P2).

## Iteration 1

Raised:
- P2 (Codex): `docker-compose.yml` set `DAYFORGE_API_HOST=dayforge.habitreward.org` while DEBUG=1 Django `ALLOWED_HOSTS` is only `localhost`/`127.0.0.1` → DisallowedHost on every tool call.
- P2 (Codex): `TransportSecuritySettings.allowed_origins` defaulted to `[]`, so any request with an `Origin` header (claude.ai, Inspector) got HTTP 403.
- P3s (Claude/Codex): timeout parse guard; per-call httpx client; no request logging yet; missing config/unit coverage; token-in-logs assertion; only ConnectTimeout covered; `ping` kept; JSON format as text not structured MCP output; dead 403 STATUS_ERRORS entry; Dockerfile chown layer; docs local-dev base URL; unrelated `CommandBar.vue` commit on branch.

Accepted and fixed:
- P2 Host → `DAYFORGE_API_HOST=localhost` in dev compose.
- P2 Origins → `config.allowed_origins()` + env `MCP_ALLOWED_ORIGINS` (prod/dev compose values) + protocol tests for accept/reject.
- Cheap P3: `MCP_REQUEST_TIMEOUT` must be `> 0`; docs local-dev note clarified.

Deferred P3s: pooling, logging, ping retention, structured JSON output, Dockerfile chown micro-opt, CommandBar split (pre-existing on branch before MCP steps 5–10), remaining test gaps.

## Iteration 2

Both engines: **NO P1/P2 FINDINGS**. Prior fixes verified against SDK origin matching. New optional P3s (dev origins omit dayforge URL; allowlist triplicated across config/compose) deferred.

## Verification

- `uv run ruff check backend/ mcp_server/` — clean
- `uv run --group mcp --group mcp-dev pytest -p no:django mcp_server/tests -q` — 16 passed

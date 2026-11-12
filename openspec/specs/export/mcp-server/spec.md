# export/mcp-server Specification

## Purpose
Stateless Model Context Protocol proxy (`mcp_server/`) in front of the daily export API. It exposes a
`ping` tool and a `get_daily_report` tool over Streamable HTTP at `/mcp`, forwards the caller's
`Authorization` header to Day Forge unchanged, and maps upstream failures to fixed tool-error messages.
It stores no credentials and is configured entirely from environment variables.

## Requirements

### Requirement: MCP tool catalogue
The MCP server SHALL advertise the tools `ping` and `get_daily_report`, where `get_daily_report` takes `date` (default `today`) and `format` (enum `markdown`, `json`; default `markdown`) and never exposes its request context as an argument.
Enforced: mcp_server/app.py::ping, mcp_server/app.py::get_daily_report

#### Scenario: tools/list
- **WHEN** a client calls `tools/list`
- **THEN** `ping` and `get_daily_report` are listed, the latter with `date` and `format` properties, `format` enum `["markdown", "json"]` and no `ctx` property

Tests: mcp_server/tests/test_protocol.py::test_tools_list_includes_get_daily_report_with_format_enum

#### Scenario: ping
- **WHEN** a client calls the `ping` tool
- **THEN** the result text is `pong` and it is not an error

Tests: mcp_server/tests/test_protocol.py::test_ping_returns_pong

### Requirement: MCP Streamable HTTP transport
The MCP server SHALL serve Streamable HTTP at `/mcp` with JSON responses and stateless sessions, and its entry point SHALL bind `0.0.0.0` on `MCP_PORT`.
Enforced: mcp_server/app.py::build_app, mcp_server/config.py::mcp_port

#### Scenario: JSON-RPC over POST
- **WHEN** a client posts `initialize` and then `tools/call` to `/mcp` with `Accept: application/json, text/event-stream`
- **THEN** each call returns HTTP 200 with a JSON-RPC body

Tests: mcp_server/tests/test_protocol.py::test_ping_returns_pong

### Requirement: MCP DNS-rebinding protection
The MCP server SHALL enable DNS-rebinding protection against the configured Host and Origin allowlists, accepting allowed browser origins and rejecting an unknown `Origin` with HTTP 403.
Enforced: mcp_server/app.py::build_app, mcp_server/config.py::allowed_hosts, mcp_server/config.py::allowed_origins

#### Scenario: Allowed browser origin
- **WHEN** a request carries `Origin: https://claude.ai`
- **THEN** it is processed with HTTP 200

Tests: mcp_server/tests/test_protocol.py::test_browser_origin_accepted

#### Scenario: Unknown browser origin
- **WHEN** a request carries `Origin: https://evil.example`
- **THEN** the response is HTTP 403

Tests: mcp_server/tests/test_protocol.py::test_unknown_origin_rejected

### Requirement: get_daily_report date validation
`get_daily_report` SHALL reject any `date` other than `today` or an ASCII `NNNN-NN-NN` pattern as a tool error before calling the backend.
Enforced: mcp_server/app.py::get_daily_report, mcp_server/app.py::DATE_RE

#### Scenario: Malformed date
- **WHEN** `get_daily_report` is called with `date: "abc"`
- **THEN** the result is a tool error mentioning `YYYY-MM-DD` and no upstream request is made

Tests: mcp_server/tests/test_errors.py::test_bad_date_rejected_without_upstream

### Requirement: get_daily_report credential forwarding
`get_daily_report` SHALL require an `Authorization` header on the MCP request and forward it verbatim to the export API, with `Host` set to the configured API host and `X-Forwarded-Proto: https`.
Enforced: mcp_server/app.py::get_daily_report, mcp_server/config.py::api_host

#### Scenario: Missing Authorization
- **WHEN** `get_daily_report` is called without an `Authorization` header
- **THEN** the result is a tool error mentioning `Authorization` and no upstream request is made

Tests: mcp_server/tests/test_auth.py::test_missing_authorization_is_tool_error_without_upstream

#### Scenario: Header forwarded
- **WHEN** the MCP request carries `Authorization: Bearer <token>`
- **THEN** the upstream GET carries the same `Authorization` value, the configured `Host` and `X-Forwarded-Proto: https`

Tests: mcp_server/tests/test_auth.py::test_authorization_forwarded_verbatim_with_host_headers

### Requirement: get_daily_report upstream call and result
`get_daily_report` SHALL GET `<api_base>/api/export/daily/<date>/`, adding `format=json` only for JSON, and return the upstream body text unchanged on success.
Enforced: mcp_server/app.py::get_daily_report, mcp_server/config.py::api_base

#### Scenario: Markdown by default
- **WHEN** `get_daily_report` is called with a date and no format
- **THEN** the upstream URL has no `format` parameter and the tool returns the upstream text

Tests: mcp_server/tests/test_tool.py::test_success_markdown_default

#### Scenario: JSON format
- **WHEN** `get_daily_report` is called with `format: "json"`
- **THEN** the upstream request has `format=json` and the tool returns the JSON text

Tests: mcp_server/tests/test_tool.py::test_format_json_adds_query_param

### Requirement: get_daily_report error mapping
`get_daily_report` SHALL turn upstream failures into tool errors with fixed messages and MUST NOT echo upstream bodies or the upstream address.
Enforced: mcp_server/app.py::get_daily_report, mcp_server/app.py::STATUS_ERRORS

#### Scenario: Non-success status
- **WHEN** the upstream returns 401 or 403, 404, 429, or another non-2xx status
- **THEN** the tool error reads `invalid or missing day-forge export token`, `no report for this date`, `rate limited, try later`, or `day-forge error <status>`, without the upstream body

Tests: mcp_server/tests/test_errors.py::test_status_mapped_to_tool_error

#### Scenario: Transport failure
- **WHEN** the upstream call times out or fails to connect
- **THEN** the tool error reads `day-forge is unreachable`

Tests: mcp_server/tests/test_errors.py::test_timeout_maps_to_unreachable

### Requirement: MCP server configuration
The MCP server SHALL read settings from the environment at call time: `DAYFORGE_API_BASE` (else `DAYFORGE_API_URL`, else `http://web:8006`, trailing slash removed), `DAYFORGE_API_HOST`, `MCP_REQUEST_TIMEOUT` (default 10), `MCP_PORT` (default 8009).
Enforced: mcp_server/config.py::api_base, mcp_server/config.py::api_host, mcp_server/config.py::request_timeout, mcp_server/config.py::mcp_port

#### Scenario: Base URL precedence
- **WHEN** both `DAYFORGE_API_BASE` and `DAYFORGE_API_URL` are set
- **THEN** `DAYFORGE_API_BASE` is used, with any trailing slash removed

#### Scenario: Invalid timeout fails at startup
- **WHEN** `MCP_REQUEST_TIMEOUT` is zero or negative
- **THEN** building the app raises `ValueError`

#### Scenario: Port out of range
- **WHEN** `MCP_PORT` is outside 1-65535
- **THEN** reading the port raises `ValueError`

### Requirement: MCP allowlist configuration
The MCP server SHALL take its Host and Origin allowlists from comma-separated `MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS`, defaulting to local hosts and to claude.ai, the Day Forge site and local origins.
Enforced: mcp_server/config.py::allowed_hosts, mcp_server/config.py::allowed_origins, mcp_server/config.py::_csv_env

#### Scenario: Custom allowlist
- **WHEN** `MCP_ALLOWED_ORIGINS` is set to a comma-separated list with blank entries
- **THEN** the allowlist is the trimmed non-empty entries

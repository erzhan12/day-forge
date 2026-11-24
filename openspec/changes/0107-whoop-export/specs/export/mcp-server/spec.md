## MODIFIED Requirements

### Requirement: MCP tool catalogue
The MCP server SHALL advertise the tools `ping`, `get_daily_report` and `get_whoop_day`, where `get_daily_report` takes `date` (default `today`) and `format` (enum `markdown`, `json`; default `markdown`), `get_whoop_day` takes `date` (default `today`), and neither exposes its request context as an argument.
Enforced: mcp_server/app.py::ping, mcp_server/app.py::get_daily_report

#### Scenario: tools/list
- **WHEN** a client calls `tools/list`
- **THEN** `ping`, `get_daily_report` and `get_whoop_day` are listed, `get_daily_report` with `date` and `format` properties, `format` enum `["markdown", "json"]`, and no tool has a `ctx` property

Tests: mcp_server/tests/test_protocol.py::test_tools_list_includes_get_daily_report_with_format_enum

#### Scenario: ping
- **WHEN** a client calls the `ping` tool
- **THEN** the result text is `pong` and it is not an error

Tests: mcp_server/tests/test_protocol.py::test_ping_returns_pong

## ADDED Requirements

### Requirement: get_whoop_day forwarding and error mapping
`get_whoop_day` SHALL validate `date` like `get_daily_report`, forward the caller's `Authorization` header unchanged to `/api/export/whoop/<date>/`, return the Markdown body, and map failures to fixed messages: 404 to "WHOOP is not connected", 409 to "WHOOP needs to be reconnected".

#### Scenario: Not connected
- **WHEN** Day Forge answers 404
- **THEN** the tool error is "WHOOP is not connected" and no upstream body is included

#### Scenario: Missing credentials
- **WHEN** the MCP request has no `Authorization` header
- **THEN** the tool fails without calling Day Forge

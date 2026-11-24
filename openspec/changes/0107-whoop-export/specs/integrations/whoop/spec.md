## ADDED Requirements

### Requirement: WHOOP settings are all or none
WHOOP SHALL be disabled when no `WHOOP_OAUTH_*` setting is set, without blocking boot. When any is set, a system check SHALL require all four and a valid Fernet key.

#### Scenario: Partial configuration
- **WHEN** only some `WHOOP_OAUTH_*` settings are set
- **THEN** the WHOOP system check reports an error

#### Scenario: No configuration
- **WHEN** no `WHOOP_OAUTH_*` setting is set
- **THEN** the check passes and the WHOOP routes report WHOOP as not configured

### Requirement: WHOOP connect and callback
`connect` SHALL require a logged-in session and redirect to WHOOP consent with an 8-character `state` stored in the session. The callback SHALL accept a code only when `state` matches the stored value (compared in constant time, used once), then store the tokens Fernet-encrypted, replacing any earlier account for that user.

#### Scenario: State mismatch
- **WHEN** the callback arrives with a missing or different `state`
- **THEN** no tokens are exchanged or stored and the result page reports failure

#### Scenario: Reconnect
- **WHEN** a user who already has a WHOOP account completes the flow again
- **THEN** the existing account row is updated instead of a second one being created

### Requirement: WHOOP token refresh is single-flight
At most one refresh per WHOOP account SHALL run at a time, behind a shared-cache lock. The holder SHALL persist the rotated refresh token immediately; other requests SHALL wait for the stored token and fail as transient (502) if none appears.

#### Scenario: Concurrent requests with an expired token
- **WHEN** two requests need a refresh at the same time
- **THEN** WHOOP's token endpoint is called once and both requests use the stored new token

#### Scenario: Refresh rejected
- **WHEN** the refresh is rejected and no fresher token is stored
- **THEN** the export reports that WHOOP must be reconnected (409)

### Requirement: WHOOP export route
`GET /api/export/whoop/<date>/` SHALL authenticate like the daily export and return the day's recovery, sleep, previous-day strain and workouts as Markdown with `Cache-Control: private, no-store`. Statuses: 400 bad date, 401 auth, 404 not connected, 409 reconnect required, 429 WHOOP rate limit, 502 WHOOP failure.

#### Scenario: Not connected
- **WHEN** the owner has no WHOOP account
- **THEN** the response is 404 and no WHOOP call is made

#### Scenario: Provider failure
- **WHEN** WHOOP returns a 5xx or is unreachable
- **THEN** the response is 502 and the WHOOP response body is not passed on

### Requirement: WHOOP data is not retained
WHOOP health data SHALL NOT be stored, cached, logged or sent to the AI chat or draft providers. Only the encrypted tokens and their metadata are stored.

#### Scenario: Export request
- **WHEN** a WHOOP summary is served
- **THEN** no WHOOP payload is written to the database, cache or logs

## MODIFIED Requirements

### Requirement: Export token authenticates no other API route
A Bearer export token MUST NOT authenticate any `/api/` route other than the export routes in `export_auth.BEARER_ROUTE_NAMES` (`daily_export`, `whoop_export`): such a request SHALL get the same status as the anonymous request.
Enforced: backend/schedules/export_auth.py::resolve_export_owner, backend/schedules/export_token_api.py::export_token

#### Scenario: Bearer-only request to another route
- **WHEN** any other `/api/` route in the live urlconf is called with any method and only a Bearer export token
- **THEN** the status equals the anonymous status and never turns a rejection into a success

Tests: backend/tests/test_daily_export_api.py::test_bearer_only_request_behaves_like_an_unauthenticated_request, backend/tests/test_daily_export_api.py::test_matrix_covers_every_other_api_route_in_the_urlconf

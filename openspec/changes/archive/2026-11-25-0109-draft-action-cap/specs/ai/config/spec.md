## MODIFIED Requirements

### Requirement: Provider call timeout and failure normalization
The system SHALL pass `LLM_REQUEST_TIMEOUT` (default 15 seconds) on every chat provider call and `LLM_DRAFT_REQUEST_TIMEOUT` (default 60 seconds, positive) on every draft call, request a JSON-object response at temperature 0, map a provider timeout to `AITimeoutError`, and map any other provider or network failure to `AIProviderError`.
Enforced: backend/ai/service.py::run_draft, backend/ai/service.py::run_chat

#### Scenario: Provider timeout
- **WHEN** the provider call times out
- **THEN** the service raises `AITimeoutError`

Tests: backend/tests/test_ai_service_chat.py::TestProviderErrors::test_timeout_maps_to_ai_timeout

#### Scenario: Provider API error
- **WHEN** the provider returns an API error
- **THEN** the service raises `AIProviderError`

Tests: backend/tests/test_ai_service_chat.py::TestProviderErrors::test_api_error_maps_to_provider

#### Scenario: Timeout per endpoint
- **WHEN** chat and draft call the provider
- **THEN** chat passes `LLM_REQUEST_TIMEOUT` and draft passes `LLM_DRAFT_REQUEST_TIMEOUT`; a non-positive draft timeout raises `ValueError` at settings import

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_chat_action_cap_stays_at_twenty, backend/tests/test_ai_draft_action_cap.py::test_run_draft_uses_draft_timeout_and_accepts_cap, backend/tests/test_settings_validation.py::test_non_positive_draft_request_timeout_raises_at_import

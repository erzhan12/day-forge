# ai/config Specification

## Purpose
Shared configuration and runtime guards for the AI endpoints (draft and chat). It covers the AI-disabled mode when no provider key is set, the provider client and its timeout, the mapping of AI errors to HTTP statuses, the shared explanation length cap, the per-user AI rate-limit buckets, and the `ai.E001` startup check that requires a shared atomic cache once AI is enabled.

## Requirements

### Requirement: AI disabled without a provider key
The system SHALL treat AI as disabled when `LLM_API_KEY` is empty or whitespace-only. Draft and chat services MUST then raise `AIUnavailableError` before creating a provider client, and the endpoints respond 503 with an `errors.detail` message. Manual schedule editing is unaffected.
Enforced: backend/ai/service.py::run_draft, backend/ai/service.py::run_chat, backend/ai/views.py::_AI_ERROR_STATUS

#### Scenario: Draft service without a key
- **WHEN** `LLM_API_KEY` is empty and a draft is requested from the service
- **THEN** `AIUnavailableError` is raised

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_raises_unavailable_without_key

#### Scenario: Chat service without a key
- **WHEN** `LLM_API_KEY` is empty and a chat turn reaches the service
- **THEN** `AIUnavailableError` is raised

Tests: backend/tests/test_ai_service_chat.py::TestInputGuards::test_missing_api_key_raises_unavailable

#### Scenario: Endpoint status
- **WHEN** the service raises `AIUnavailableError` inside a draft request
- **THEN** the response status is 503

Tests: backend/tests/test_ai_views_draft.py::TestProviderErrors::test_errors_mapped

### Requirement: Auto-draft signal requires AI
The system SHALL set the Schedule page prop `auto_draft_pending` true only on the request that created the day's schedule row, when a template exists for the day's slot type and `LLM_API_KEY` is non-blank.
Enforced: backend/schedules/views.py::schedule_view

#### Scenario: Key missing
- **WHEN** a user first visits a day with a template while `LLM_API_KEY` is empty
- **THEN** `auto_draft_pending` is false

Tests: backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_false_without_api_key

#### Scenario: Key, template and first visit
- **WHEN** a user first visits a day with a matching template and a configured key
- **THEN** `auto_draft_pending` is true, and false on the next visit

Tests: backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_true_on_first_visit_with_template_and_key, backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_false_on_second_visit

### Requirement: AI error status mapping
The system SHALL map AI service errors to HTTP statuses with an `errors.detail` body: unavailable 503, invalid input 400, timeout 504, provider error 502, parse error 502. An AI error subclass missing from the mapping MUST be logged and answered with 500.
Enforced: backend/ai/views.py::_AI_ERROR_STATUS, backend/ai/views.py::ai_generate_draft, backend/ai/views.py::ai_chat

#### Scenario: Draft errors mapped
- **WHEN** the draft service raises each mapped error class
- **THEN** the response carries the mapped status

Tests: backend/tests/test_ai_views_draft.py::TestProviderErrors::test_errors_mapped

#### Scenario: Chat errors mapped
- **WHEN** the chat service raises each mapped error class
- **THEN** the response carries the mapped status

Tests: backend/tests/test_ai_views_chat.py::TestAuditEnvelope::test_failure_envelope_carries_error_class

### Requirement: Provider client configuration
The system SHALL call an OpenAI-compatible provider built from `LLM_API_KEY` and `LLM_BASE_URL` (default OpenAI v1), with one cached client per running event loop. A client construction failure MUST surface as `AIProviderError` without logging the exception content, so the key cannot leak.
Enforced: backend/ai/service.py::_get_client

#### Scenario: Client reuse per loop
- **WHEN** two calls run on the same event loop, or on different loops
- **THEN** the same loop reuses one client and different loops get different clients

Tests: backend/tests/test_ai_service_client.py::TestClientPerLoop::test_same_loop_reuses_client, backend/tests/test_ai_service_client.py::TestClientPerLoop::test_different_loops_get_different_clients

#### Scenario: Client construction fails
- **WHEN** constructing the provider client raises
- **THEN** `AIProviderError` is raised

Tests: backend/tests/test_ai_service_client.py::TestClientPerLoop::test_init_failure_raises_provider_error

### Requirement: Provider call timeout and failure normalization
The system SHALL pass `LLM_REQUEST_TIMEOUT` (default 15 seconds) on every provider call, request a JSON-object response at temperature 0, map a provider timeout to `AITimeoutError`, and map any other provider or network failure to `AIProviderError`.
Enforced: backend/ai/service.py::run_draft, backend/ai/service.py::run_chat

#### Scenario: Provider timeout
- **WHEN** the provider call times out
- **THEN** the service raises `AITimeoutError`

Tests: backend/tests/test_ai_service_chat.py::TestProviderErrors::test_timeout_maps_to_ai_timeout

#### Scenario: Provider API error
- **WHEN** the provider returns an API error
- **THEN** the service raises `AIProviderError`

Tests: backend/tests/test_ai_service_chat.py::TestProviderErrors::test_api_error_maps_to_provider

### Requirement: Shared explanation length cap
The system MUST reject a model reply whose `explanation` is not a string or is longer than `LLM_MAX_EXPLANATION_CHARS` (default 300) as a parse error, in both the draft and chat envelopes. A non-positive value of this setting MUST raise `ValueError` at settings import.
Enforced: backend/ai/schemas.py::validate_response_envelope, backend/ai/schemas.py::validate_chat_response_envelope, backend/day_forge/settings.py::LLM_MAX_EXPLANATION_CHARS

#### Scenario: Overlong chat explanation
- **WHEN** the cap is lowered and the model returns a longer explanation
- **THEN** the service raises `AIParseError`

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_overlong_explanation

#### Scenario: Overlong draft explanation
- **WHEN** a draft reply's explanation exceeds the cap
- **THEN** draft validation reports an explanation error

### Requirement: Independent per-user AI rate-limit buckets
The system SHALL keep separate fixed-window hourly counters per user, `ai_draft_rl:<user_id>` and `ai_chat_rl:<user_id>`, in the default cache. Async AI views MUST consume them through the synchronous shared limiter via `sync_to_async`, so Redis increments stay atomic and keep the window's original expiry.
Enforced: backend/ai/views.py::_consume_rate_limit, backend/schedules/ratelimit.py::consume_rate_limit

#### Scenario: Buckets do not share budget
- **WHEN** a draft succeeds
- **THEN** only the draft counter is incremented

Tests: backend/tests/test_ai_views_draft.py::TestHappyPath::test_draft_bucket_independent_of_chat_bucket

#### Scenario: Window expiry preserved
- **WHEN** a counter is incremented after the first request in a window
- **THEN** the key keeps its original one-hour expiry

Tests: backend/tests/test_ratelimit.py::test_consume_rate_limit_preserves_window_ttl

### Requirement: Cache backend selection
The system SHALL use a Redis default cache with key prefix `dayforge` when `REDIS_URL` is set (whitespace stripped), and fall back to a local-memory cache when it is unset or blank.
Enforced: backend/day_forge/settings.py::REDIS_URL

#### Scenario: Redis URL set
- **WHEN** `REDIS_URL` is a Redis URL, possibly with surrounding whitespace
- **THEN** the default cache is Redis at the stripped location with prefix `dayforge`

Tests: backend/tests/test_settings_validation.py::TestCacheBackendConstruction::test_redis_url_selects_rediscache_with_prefix, backend/tests/test_settings_validation.py::TestCacheBackendConstruction::test_redis_url_is_stripped_in_location

#### Scenario: Redis URL unset or blank
- **WHEN** `REDIS_URL` is unset or whitespace-only
- **THEN** the default cache is local memory

Tests: backend/tests/test_settings_validation.py::TestCacheBackendConstruction::test_unset_redis_url_falls_back_to_locmem, backend/tests/test_settings_validation.py::TestCacheBackendConstruction::test_whitespace_redis_url_falls_back_to_locmem

### Requirement: AI requires a shared atomic cache
The system MUST report startup error `ai.E001` whenever `LLM_API_KEY` is non-blank and the default cache backend is local-memory, file-based or dummy, regardless of `DEBUG`. The check is silent when AI is disabled or the backend is shared, such as Redis or Memcached.
Enforced: backend/ai/checks.py::error_locmem_cache_with_ai_in_production

#### Scenario: AI on with an ineffective backend
- **WHEN** the key is set and the backend is local-memory, file-based or dummy
- **THEN** `ai.E001` is reported, even with `DEBUG=True`

Tests: backend/tests/test_checks.py::TestLocmemCacheProductionError::test_errors_when_prod_plus_locmem_plus_ai, backend/tests/test_checks.py::TestLocmemCacheProductionError::test_errors_when_prod_plus_filebased_plus_ai, backend/tests/test_checks.py::TestLocmemCacheProductionError::test_errors_when_dummy_plus_ai, backend/tests/test_checks.py::TestLocmemCacheProductionError::test_fires_even_when_debug_true

#### Scenario: AI disabled
- **WHEN** the key is empty or whitespace-only
- **THEN** `ai.E001` is not reported

Tests: backend/tests/test_checks.py::TestLocmemCacheProductionError::test_silent_when_ai_disabled, backend/tests/test_checks.py::TestLocmemCacheProductionError::test_silent_when_api_key_is_whitespace

#### Scenario: Shared backend
- **WHEN** the key is set and the backend is Redis or Memcached
- **THEN** `ai.E001` is not reported

Tests: backend/tests/test_checks.py::TestLocmemCacheProductionError::test_silent_on_shared_cache_backend, backend/tests/test_checks.py::TestLocmemCacheProductionError::test_silent_on_memcached_backend

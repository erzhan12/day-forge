"""OpenAI-compatible client wrapper for the AI command endpoint.

Module-level sync client constructed from ``settings.LLM_*`` env vars,
``response_format={"type": "json_object"}`` (see note below), schema
embedded in the system prompt (see ``prompts.SYSTEM_PROMPT``), and a
single public ``run_command()`` entrypoint.

**On ``response_format``**: the original Phase 4 plan called for OpenAI
Structured Outputs (``{"type": "json_schema", …, "strict": true}``), which
would reject non-conforming responses at the provider. We deliberately use
the weaker ``json_object`` mode instead: ``settings.LLM_BASE_URL`` lets
this client point at OpenRouter / self-hosted proxies, and not every
OpenAI-compatible provider implements ``json_schema`` mode. Post-parse
validation via ``validate_response_envelope`` and ``validate_action_shape``
in ``ai/schemas.py`` covers the safety gap — a malformed response raises
``AIParseError`` with the raw text preserved for the interaction log.

The view in ``backend/ai/views.py`` maps the errors below to HTTP status
codes; tests monkeypatch ``_get_client()`` so they never hit the network.
"""
import json
import logging
from dataclasses import dataclass

import openai
from django.conf import settings
from openai import OpenAI

from ai.prompts import SYSTEM_PROMPT, build_user_message
from ai.schemas import (
    validate_action_shape,
    validate_response_envelope,
)

logger = logging.getLogger(__name__)


class AIError(Exception):
    """Base class for all AI-service failures surfaced to the view."""


class AIUnavailableError(AIError):
    """LLM_API_KEY unset — AI features disabled. View returns 503."""


class AIInvalidInputError(AIError):
    """Empty / oversized user input. View returns 400."""


class AITimeoutError(AIError):
    """Provider timed out. View returns 504."""


class AIProviderError(AIError):
    """Auth, rate limit, network, or any other SDK exception. View returns 502."""


class AIParseError(AIError):
    """Response was not valid JSON or did not match our schema. View returns 502.

    ``raw_response_text`` carries whatever the provider returned so the view
    can log it to the ``AIInteraction`` row for post-mortem debugging.
    """

    def __init__(self, message: str, raw_response_text: str):
        super().__init__(message)
        self.raw_response_text = raw_response_text


@dataclass
class AICommandResult:
    raw_response_text: str
    parsed_actions: list[dict]
    explanation: str


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily construct the module-level OpenAI client.

    Deferred so tests can run without ``LLM_API_KEY`` set and so the
    ``AIUnavailableError`` branch in ``run_command`` fires before any
    network object is created.
    """
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
    return _client


def run_command(user_command: str, schedule, blocks, now) -> AICommandResult:
    """Call the LLM for one user command. See module docstring for errors."""
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        raise AIUnavailableError("LLM_API_KEY is not configured")

    if not isinstance(user_command, str):
        raise AIInvalidInputError("command must be a string")
    trimmed = user_command.strip()
    if not trimmed:
        raise AIInvalidInputError("command cannot be empty")
    if len(trimmed) > settings.LLM_MAX_COMMAND_CHARS:
        raise AIInvalidInputError(
            f"command too long (max {settings.LLM_MAX_COMMAND_CHARS} chars)"
        )

    user_message = build_user_message(schedule, blocks, now, trimmed)

    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=settings.LLM_REQUEST_TIMEOUT,
        )
    except openai.APITimeoutError as e:
        logger.warning("AI timeout: %s", e)
        raise AITimeoutError("AI provider timed out") from e
    except openai.APIError as e:
        # Log the full provider error server-side; surface a generic message
        # to the client so provider URLs / auth details / proxy info can't
        # leak into the response envelope.
        logger.warning("AI provider error: %s", e)
        raise AIProviderError("AI service error") from e
    except Exception as e:  # network / unexpected — log full traceback
        logger.exception("AI unexpected error")
        raise AIProviderError("AI service error") from e

    raw = response.choices[0].message.content or ""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AIParseError(f"AI returned invalid JSON: {e}", raw_response_text=raw) from e

    envelope_errors = validate_response_envelope(parsed)
    if envelope_errors:
        raise AIParseError(
            "AI response failed envelope validation: " + "; ".join(envelope_errors),
            raw_response_text=raw,
        )

    # Per-action shape validation — second line of defence even though the
    # system prompt spells out the schema. Category enum mirrors the model.
    from schedules.models import TimeBlock  # local import: avoid app-load cycles

    allowed_categories = {c.value for c in TimeBlock.Category}
    per_action_errors = []
    for idx, action in enumerate(parsed["actions"]):
        errs = validate_action_shape(action, allowed_categories)
        if errs:
            per_action_errors.append(f"action[{idx}]: {', '.join(errs)}")
    if per_action_errors:
        raise AIParseError(
            "AI response failed action validation: " + "; ".join(per_action_errors),
            raw_response_text=raw,
        )

    return AICommandResult(
        raw_response_text=raw,
        parsed_actions=list(parsed["actions"]),
        explanation=parsed.get("explanation", ""),
    )

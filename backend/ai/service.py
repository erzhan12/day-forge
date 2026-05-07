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
import os
from dataclasses import dataclass

import openai
from django.conf import settings
from openai import OpenAI

from ai.prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_CHAT,
    SYSTEM_PROMPT_DRAFT,
    build_chat_user_message,
    build_draft_user_message,
    build_user_message,
    serialise_prior_turns,
)
from ai.schemas import (
    validate_action_shape,
    validate_chat_response_envelope,
    validate_draft_response,
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


@dataclass
class AIChatResult:
    """Result envelope for ``run_chat`` (feature 0007).

    Carries the same provider raw text + parsed actions as the one-shot
    ``AICommandResult`` plus an optional ``ask`` clarifying-question
    string. Exactly one of ``parsed_actions`` (non-empty) or ``ask``
    (non-null) is set, OR both are empty/null for a chit-chat turn.
    """

    raw_response_text: str
    parsed_actions: list[dict]
    explanation: str
    ask: str | None


@dataclass
class AIDraftResult:
    """Result envelope for ``run_draft``.

    Same shape as ``AICommandResult`` but kept separate so call sites are
    explicit about which path produced the actions. The view's audit log
    distinguishes the two via the new ``AIInteraction.kind`` field.
    """

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
        try:
            _client = OpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        except Exception as e:
            # Never log ``e`` / repr(e) / the traceback — the failing frame's
            # locals hold ``settings.LLM_API_KEY``. Record only the exception
            # class so the key can't leak to logs / APM / error trackers.
            # ``from None`` suppresses chaining for the same reason.
            logger.warning("AI client init failed: %s", type(e).__name__)
            raise AIProviderError("AI client initialization failed") from None
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


def run_draft(schedule, template, history_schedules, rules, now) -> AIDraftResult:
    """Call the LLM to generate a draft schedule.

    Same exception taxonomy as ``run_command`` so the view can map errors
    via the existing ``_AI_ERROR_STATUS`` table. Uses
    ``settings.LLM_DRAFT_MODEL`` (heavier than ``LLM_MODEL`` because drafts
    shape a whole day from history), and ``validate_draft_response`` which
    additionally rejects any non-``add`` action.
    """
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        raise AIUnavailableError("LLM_API_KEY is not configured")

    user_message = build_draft_user_message(
        schedule, template, history_schedules, rules, now
    )
    # Optional capture for the Phase 6 Test 7 e2e script. Overwrites the
    # target file on EVERY draft call when LLM_DRAFT_CAPTURE_PROMPT_PATH
    # is non-empty — purely test infrastructure, see
    # ``frontend/scripts/playwright/draft-prompt-history-suffix.mjs``.
    # Default-off via empty path; ``ai.E002`` blocks startup when the
    # path is set under DEBUG=False, so this branch can only ever execute
    # in dev. Defense-in-depth on top of E002:
    #   * ``O_NOFOLLOW`` — refuses to write through a pre-existing symlink
    #     (mitigates the symlink-attack vector when the capture lives in a
    #     world-writable dir like ``/tmp``).
    #   * ``mode=0o600`` — owner-read/write only. The captured prompt
    #     embeds the user's full schedule history (PII), so a permissive
    #     umask must not turn it into a world-readable file.
    # The except logs (instead of swallowing) so a misconfigured path
    # surfaces in the operator's dev console rather than silently
    # disabling the test capture.
    if settings.LLM_DRAFT_CAPTURE_PROMPT_PATH:
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
            fd = os.open(
                settings.LLM_DRAFT_CAPTURE_PROMPT_PATH, flags, 0o600
            )
            with os.fdopen(fd, "w") as _f:
                _f.write(user_message)
        except OSError as e:
            logger.warning(
                "Failed to write LLM_DRAFT_CAPTURE_PROMPT_PATH=%r: %s",
                settings.LLM_DRAFT_CAPTURE_PROMPT_PATH,
                e,
            )

    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=settings.LLM_DRAFT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_DRAFT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=settings.LLM_REQUEST_TIMEOUT,
        )
    except openai.APITimeoutError as e:
        logger.warning("AI draft timeout: %s", e)
        raise AITimeoutError("AI provider timed out") from e
    except openai.APIError as e:
        logger.warning("AI draft provider error: %s", e)
        raise AIProviderError("AI service error") from e
    except Exception as e:  # network / unexpected — log full traceback
        logger.exception("AI draft unexpected error")
        raise AIProviderError("AI service error") from e

    raw = response.choices[0].message.content or ""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AIParseError(
            f"AI returned invalid JSON: {e}", raw_response_text=raw
        ) from e

    from schedules.models import TimeBlock  # local import: avoid app-load cycles

    allowed_categories = {c.value for c in TimeBlock.Category}
    errors = validate_draft_response(parsed, allowed_categories)
    if errors:
        raise AIParseError(
            "AI draft response failed validation: " + "; ".join(errors),
            raw_response_text=raw,
        )

    return AIDraftResult(
        raw_response_text=raw,
        parsed_actions=list(parsed["actions"]),
        explanation=parsed.get("explanation", ""),
    )


def run_chat(messages, schedule, blocks, now) -> AIChatResult:
    """Multi-turn chat (feature 0007).

    ``messages`` is the FULL client-supplied transcript ordered
    chronologically; the LAST entry must have ``role="user"`` and is the
    turn the user just sent. The view enforces alternation, role
    membership, and per-message / total length caps before calling here.

    Critically, prior client-supplied turns (everything except the last
    one) are NOT forwarded to the LLM under the ``assistant`` role. They
    are flattened into a single ``user``-role transcript block prefixed
    with the "Untrusted prior transcript" caveat (see
    ``prompts.serialise_prior_turns``). This closes the privilege-
    escalation surface where a tampered client could inject a fake
    ``assistant`` turn that biases the model into destructive actions.
    """
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        raise AIUnavailableError("LLM_API_KEY is not configured")

    # The view layer is responsible for full validation; treat anything
    # malformed reaching this far as an internal contract violation rather
    # than a user-visible 400.
    if not messages or messages[-1].get("role") != "user":
        raise AIInvalidInputError(
            "messages must end with a user turn (view should enforce)"
        )

    schedule_context = build_chat_user_message(schedule, blocks, now)
    prior_transcript = serialise_prior_turns(messages[:-1])
    latest_user_turn = messages[-1]["content"]

    chat_messages = [
        {"role": "system", "content": SYSTEM_PROMPT_CHAT},
        # Schedule context + the flattened prior transcript live in a
        # single leading user message so the model treats them as
        # untrusted input. The latest real user turn stays in its own
        # user message so the model focuses its response on it.
        {
            "role": "user",
            "content": f"{schedule_context}\n\n{prior_transcript}",
        },
        {"role": "user", "content": latest_user_turn},
    ]

    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=chat_messages,
            response_format={"type": "json_object"},
            temperature=0,
            timeout=settings.LLM_REQUEST_TIMEOUT,
        )
    except openai.APITimeoutError as e:
        logger.warning("AI chat timeout: %s", e)
        raise AITimeoutError("AI provider timed out") from e
    except openai.APIError as e:
        logger.warning("AI chat provider error: %s", e)
        raise AIProviderError("AI service error") from e
    except Exception as e:  # network / unexpected
        logger.exception("AI chat unexpected error")
        raise AIProviderError("AI service error") from e

    raw = response.choices[0].message.content or ""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AIParseError(
            f"AI returned invalid JSON: {e}", raw_response_text=raw
        ) from e

    envelope_errors = validate_chat_response_envelope(parsed)
    if envelope_errors:
        raise AIParseError(
            "AI chat response failed envelope validation: "
            + "; ".join(envelope_errors),
            raw_response_text=raw,
        )

    from schedules.models import TimeBlock  # local import: avoid app-load cycles

    allowed_categories = {c.value for c in TimeBlock.Category}
    per_action_errors = []
    for idx, action in enumerate(parsed["actions"]):
        errs = validate_action_shape(action, allowed_categories)
        if errs:
            per_action_errors.append(f"action[{idx}]: {', '.join(errs)}")
    if per_action_errors:
        raise AIParseError(
            "AI chat response failed action validation: "
            + "; ".join(per_action_errors),
            raw_response_text=raw,
        )

    return AIChatResult(
        raw_response_text=raw,
        parsed_actions=list(parsed["actions"]),
        explanation=parsed.get("explanation", ""),
        ask=parsed.get("ask"),
    )

"""Server-side chat replay guard (feature 0083, issue #219).

Pure module — stdlib only (``re``), no Django and no ``schedules.*``
imports (unlike ``ai/free_slot.py``, which imports ``schedules.http`` →
Django) — so unit tests need no DB or settings.

The bug this fixes: turn 1 "add Momentum (Personal)" adds Momentum; turn 2
"Notes" replays turn 1 and emits "Momentum[2]" (the active "same name → add
[N]" Rule's suffix, applied to the wrong title) instead of adding "Notes".
Hard rule 11 (``prompts.py``) tells the model not to do this; this module is
the deterministic backstop the view enforces regardless of what the model
does.

Algorithm (see ``docs/features/0083_PLAN.md`` §B2 for the full rationale
and the false-positive/false-negative trade-offs this makes on purpose):

1. If the immediately preceding assistant turn carried ``is_ask: True``, the
   latest turn is an answer to a pending question — skip the guard entirely
   for this turn.
2. If instead it carried ``is_error: True``, walk back the CONTIGUOUS chain
   of ``(user, is_error assistant)`` pairs. The failed turns (and, if the
   chain began as the answer to a pending ask, that ask turn too) are
   excluded from the "prior text" used as replay evidence in step 4, and a
   title traceable to that ask's own text is allowed through — this lets a
   "try again" retry an add that never actually applied (a 400 aborts the
   whole batch; a 409 ``schedule_changed`` writes nothing).
3. For each ``add`` action, normalise the title (strip a trailing ``[N]``
   duplicate-counter suffix, casefold, collapse whitespace) and check it is
   traceable to the latest user turn (Step A) — ANY significant token
   overlap, tolerant of simple plural/case inflection. Traceable ⇒ allowed.
4. Otherwise (Step B), check whether the title is REPLAY EVIDENCE in the
   prior transcript — the full title appears as a substring with word
   boundaries, or all of its significant tokens appear somewhere in the
   prior text. Evidence found ⇒ flagged as a replay.

Only ``add`` actions are checked (see B4 in the plan for why move/remove/
resize/update are out of scope).
"""

from __future__ import annotations

import re

REPLAY_GUARD_REASON_CODE = "replay_guard"
GUARD_ASK_PREFIX = "I did not change the schedule:"
GUARD_EXPLANATION = "Nothing was changed."

# Mirrors the user-Rule "same name → add [N]" convention observed in issue
# #219 — NOT a product-wide title-naming scheme. Word-style duplicate
# conventions ("... copy", "... II") are intentionally not covered; see the
# plan's Risks section for the accepted false negative.
_TITLE_SUFFIX_RE = re.compile(r"\s*\[\d+\]\s*$")
_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# English + Russian function words (articles, prepositions, conjunctions,
# pronouns, common chat verbs). A title made only of these tokens (e.g.
# "IT", "On") is not permissive by default — see ``_is_replay``'s fallback
# path, which switches to unfiltered letter tokens on every side instead.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "for",
        "of",
        "to",
        "in",
        "on",
        "at",
        "and",
        "or",
        "with",
        "my",
        "me",
        "it",
        "add",
        "please",
        "и",
        "в",
        "на",
        "с",
        "для",
        "по",
        "к",
        "у",
        "а",
        "или",
        "мне",
        "добавь",
    }
)

_GUARD_TITLE_TRUNCATE = 60


def build_guard_ask(title: str) -> str:
    """Server-owned follow-up ask for a tripped guard (English-only, like
    every other ``_build_resolution_ask`` string — see RULES.md)."""
    truncated = (
        title if len(title) <= _GUARD_TITLE_TRUNCATE else title[:_GUARD_TITLE_TRUNCATE] + "..."
    )
    return (
        f'{GUARD_ASK_PREFIX} "{truncated}" is not something you asked for in '
        "your last message. What would you like to add?"
    )


def _normalise(text: str) -> str:
    stripped = _TITLE_SUFFIX_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", stripped.casefold()).strip()


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _has_letter(token: str) -> bool:
    return any(ch.isalpha() for ch in token)


def _tokens_match(a: str, b: str) -> bool:
    """Absorbs simple plural/case inflection without a stemmer.

    Two tokens match if equal, or both are >= 4 chars and share a common
    PREFIX ``p`` with ``len(p) >= max(4, len(shorter) - 2)`` where each
    token extends past ``p`` by at most 2 chars. Rejects compounds/derived
    words (work/workout, notes/notebook) while accepting most plural/case
    endings (meeting/meetings, обед/обеда).
    """
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    common = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        common += 1
    shorter = min(len(a), len(b))
    if common < max(4, shorter - 2):
        return False
    if (len(a) - common) > 2 or (len(b) - common) > 2:
        return False
    return True


def _letter_tokens(text: str) -> list[str]:
    return [t for t in _tokenize(_normalise(text)) if _has_letter(t)]


def _is_replay(title: str, latest_text: str, prior_text: str, ask_text: str | None) -> bool:
    title_norm = _normalise(title)
    title_letters = [t for t in _tokenize(title_norm) if _has_letter(t)]
    if not title_letters:
        # Vacuous title (emoji/number-only): cannot judge → permissive.
        return False

    title_significant = [t for t in title_letters if t not in _STOPWORDS]
    # Stopword-only title (e.g. "IT", "On"): NOT permissive. Fall back to
    # unfiltered letter tokens on every side instead (title, latest turn,
    # ask text, prior text) so a real replay is still caught.
    fallback = not title_significant
    title_tokens = title_letters if fallback else title_significant

    def other_tokens(text: str) -> list[str]:
        letters = _letter_tokens(text)
        return letters if fallback else [t for t in letters if t not in _STOPWORDS]

    def traceable_to(text: str) -> bool:
        candidates = other_tokens(text)
        return any(_tokens_match(a, b) for a in title_tokens for b in candidates)

    if traceable_to(latest_text):
        return False
    if ask_text is not None and traceable_to(ask_text):
        return False

    # Step B: replay evidence in the prior transcript.
    prior_norm = _normalise(prior_text)
    boundary_pattern = re.compile(r"(?<!\w)" + re.escape(title_norm) + r"(?!\w)")
    if boundary_pattern.search(prior_norm):
        return True
    prior_tokens = other_tokens(prior_text)
    if title_tokens and all(any(_tokens_match(t, p) for p in prior_tokens) for t in title_tokens):
        return True
    return False


def _collect_failure_chain_start(messages: list[dict]) -> tuple[int, str | None]:
    """Return ``(prior_end, ask_text)`` for the ``is_error`` widening path.

    ``messages[-2]`` is assumed to already be an ``is_error`` assistant
    turn. Walks back over the CONTIGUOUS ``(user, is_error assistant)``
    chain; ``prior_end`` is the index such that ``messages[:prior_end]`` is
    the prior text used as replay evidence (the failed turns — and, if the
    chain began as the answer to a pending ask, that ask turn too — are
    excluded). ``ask_text`` is the content of that pending-ask turn when
    present and not itself a guard ask (a guard ask quotes the REJECTED
    title, so treating it as evidence would whitelist the exact replay this
    guard blocks) — else ``None``.
    """
    n = len(messages)
    k = n - 3  # earliest failed user turn found so far
    while (
        k - 2 >= 0
        and messages[k - 2].get("role") == "user"
        and messages[k - 1].get("role") == "assistant"
        and messages[k - 1].get("is_error") is True
    ):
        k -= 2

    prior_end = k
    ask_text = None
    ask_turn = messages[k - 1] if k >= 1 else None
    is_assistant_ask_turn = (
        ask_turn is not None
        and ask_turn.get("role") == "assistant"
        and ask_turn.get("is_ask") is True
    )
    if is_assistant_ask_turn:
        ask_content = ask_turn["content"]
        if not ask_content.startswith(GUARD_ASK_PREFIX):
            ask_text = ask_content
        prior_end = k - 1
    return prior_end, ask_text


def find_replayed_actions(parsed_actions: list[dict], messages: list[dict]) -> tuple[int, ...]:
    """Return the indices of ``add`` actions in ``parsed_actions`` that
    replay an earlier, already-handled request rather than the latest user
    turn. An empty tuple means: apply as usual (no violation)."""
    previous_turn = messages[-2] if len(messages) >= 2 else None
    is_previous_assistant = previous_turn is not None and previous_turn.get("role") == "assistant"
    if is_previous_assistant and previous_turn.get("is_ask") is True:
        return ()

    prior_end = len(messages) - 1
    ask_text: str | None = None
    if is_previous_assistant and previous_turn.get("is_error") is True:
        prior_end, ask_text = _collect_failure_chain_start(messages)

    latest_text = messages[-1]["content"]
    prior_text = "\n".join(m["content"] for m in messages[:prior_end])

    offending = []
    for idx, action in enumerate(parsed_actions):
        if action.get("type") != "add":
            continue
        title = action.get("title", "")
        if _is_replay(title, latest_text, prior_text, ask_text):
            offending.append(idx)
    return tuple(offending)

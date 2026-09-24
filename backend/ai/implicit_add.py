"""Implicit "add" rewrite for command-less chat turns (feature 0083, Addendum D).

Pure module — stdlib only (``re``), no Django imports, so unit tests need
no DB or settings, same design constraint as ``ai/replay_guard.py``.

Why. Live test on the 0083 worktree (audit row 268): with Hard rule 11 in
place, the model still misread a bare follow-up turn like "Notes" as a
command referring to an earlier turn. The replay guard correctly blocked
the resulting replayed add, but the user then got a clarifying ask instead
of the "Notes" block they meant. Per the user's own stated habit ("99% of
my commands are like that"), a command-less turn overwhelmingly means
"add this" — so we rewrite the LLM-bound copy of the latest turn to say
so explicitly, deterministically, before ``run_chat`` ever calls the
model. If the resulting sentence doesn't make sense, the model's normal
clarifying-ask path handles it; no extra logic needed here.

Only the copy of the latest turn SENT TO THE LLM is affected. The
stored transcript, the audit ``user_command``, the transcript hash, and
the replay guard (``ai.replay_guard.find_replayed_actions``) all keep
using the ORIGINAL text — callers must pass the original, unmodified
``messages`` list to those, and only substitute the rewritten string in
the outgoing provider message. See ``docs/features/0083_PLAN.md``
§ "Addendum D" for the full exclusion list and rationale.
"""

from __future__ import annotations

import re

# English command verbs. Whole-word match with a handful of simple
# inflections (-s, -ed/-d, -ing) — not a stemmer, just enough to catch
# "Moved" the way the live-test transcript did; spelling irregulars are
# listed explicitly in ``_EN_IRREGULAR_FORMS`` below.
_EN_VERBS = (
    "add",
    "move",
    "remove",
    "delete",
    "make",
    "resize",
    "rename",
    "shift",
    "extend",
    "shorten",
    "cancel",
    "clear",
    "schedule",
    "put",
    "set",
    "change",
    "swap",
    "split",
    "merge",
    "undo",
    "retry",
    "try",
    "repeat",
    "reschedule",
    "postpone",
    "delay",
    "push",
    "pull",
    "bump",
    "replace",
    "update",
    "edit",
    "create",
    "insert",
    "plan",
    "fill",
    "organize",
    "reorganize",
    "rearrange",
    "optimize",
    "free",
    "skip",
    "drop",
    "complete",
    "finish",
    # Read-only requests: never turn "show my blocks" into an add. "check"
    # and "review" are deliberately absent — "Check emails" / "Review PR"
    # are common block titles that SHOULD get the implicit add.
    "list",
    "show",
    "tell",
    "explain",
    "summarize",
    "describe",
)

# Russian command-verb stems. Matched as WORD PREFIXES (not whole words)
# per the plan, since Russian verb conjugation/imperative endings vary
# more than English's simple -s/-ed/-ing.
_RU_STEMS = (
    "добав",
    "перенес",
    "перенос",
    "сдвин",
    "удал",
    "убер",
    "убр",
    "сдел",
    "измен",
    "переимен",
    "продл",
    "сократ",
    "отмен",
    "очист",
    "постав",
    "поменя",
    "запланир",
    "повтор",
    "спланир",
    "распланир",
    "планир",
    "отлож",
    "передвин",
    "заполн",
    "освобод",
    "пропуст",
    "заверш",
    "созда",
    "покаж",
    "расскаж",
    "объясн",
    "напомн",
)

_QUESTION_STARTERS = frozenset(
    {
        "what",
        "when",
        "how",
        "why",
        "which",
        "who",
        "where",
        "is",
        "are",
        "can",
        "could",
        "should",
        "do",
        "does",
        "что",
        "когда",
        "как",
        "почему",
        "зачем",
        "какой",
        "какая",
        "какие",
        "где",
        "кто",
        "сколько",
        "можно",
    }
)

_SHORT_REPLIES = frozenset(
    {
        "ok",
        "okay",
        "thanks",
        "thank you",
        "thx",
        "yes",
        "no",
        "yep",
        "nope",
        "sure",
        "cool",
        "great",
        "hi",
        "hello",
        "hey",
        "bye",
        "good morning",
        "good afternoon",
        "good evening",
        "good night",
        "thanks a lot",
        "again",
        "да",
        "нет",
        "ок",
        "окей",
        "спасибо",
        "привет",
        "хорошо",
        "ладно",
        "отлично",
        "пока",
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "спокойной ночи",
        "ещё раз",
        "еще раз",
    }
)


# Spelling irregulars the simple suffix rules below miss: doubled final
# consonant ("putting", "swapped"), y -> ied/ies ("tried", "retries"),
# British "cancelled", and the irregular past "made".
_EN_IRREGULAR_FORMS = (
    "putting",
    "setting",
    "splitting",
    "swapping",
    "swapped",
    "cancelled",
    "cancelling",
    "tried",
    "tries",
    "retried",
    "retries",
    "made",
    "planning",
    "planned",
    "dropping",
    "dropped",
    "skipping",
    "skipped",
)


def _en_inflections(verb: str) -> set[str]:
    forms = {verb, verb + "s"}
    if verb.endswith("e"):
        # Silent-e verbs: "move" -> "moved" (drop e + "d"), "moving"
        # (drop e + "ing").
        forms.add(verb + "d")
        forms.add(verb[:-1] + "ing")
    else:
        forms.add(verb + "ed")
        forms.add(verb + "ing")
    return forms


_EN_FORMS = sorted(
    {form for verb in _EN_VERBS for form in _en_inflections(verb)} | set(_EN_IRREGULAR_FORMS),
    key=len,
    reverse=True,
)
_EN_VERB_RE = re.compile(r"\b(?:" + "|".join(_EN_FORMS) + r")\b", re.IGNORECASE)
_RU_STEM_RE = re.compile(r"\b(?:" + "|".join(_RU_STEMS) + r")", re.UNICODE | re.IGNORECASE)
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)
# Leading run of letters only, so "What's next" -> "what", "How's" -> "how".
_LEADING_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text))


def _has_command_verb(text: str) -> bool:
    return bool(_EN_VERB_RE.search(text)) or bool(_RU_STEM_RE.search(text))


def _is_question(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith("?"):
        return True
    first_word = _LEADING_WORD_RE.match(stripped)
    return bool(first_word) and first_word.group(0).casefold() in _QUESTION_STARTERS


def _is_short_reply(text: str) -> bool:
    # Punctuation-insensitive: "thanks!", "Ok.", "ещё раз!" still match.
    normalised = " ".join(_EDGE_PUNCT_RE.sub("", text.strip()).casefold().split())
    return normalised in _SHORT_REPLIES


def _continues_previous_turn(messages: list[dict]) -> bool:
    """True when the latest turn answers a pending ask or retries after an error.

    Both carve-outs of Hard rule 11 (a)/(b): the turn continues an earlier
    request, so prefixing "add" would turn "later" or "try again" into a
    fresh add of that literal text.
    """
    if len(messages) < 2:
        return False
    previous_turn = messages[-2]
    if previous_turn.get("role") != "assistant":
        return False
    return previous_turn.get("is_ask") is True or previous_turn.get("is_error") is True


def apply_implicit_add(latest_text: str, messages: list[dict]) -> str:
    """Return the text to send to the LLM in place of ``latest_text``.

    ``messages`` is the full client-supplied transcript (used only to
    check whether ``messages[-2]`` is a pending clarifying ask or an error
    bubble); it is never mutated. When ``latest_text`` carries no explicit
    instruction (see the module docstring / plan for the exclusion list), the
    returned string is prefixed with ``"add "`` (or ``"добавь "`` when
    ``latest_text`` contains Cyrillic letters). Otherwise ``latest_text``
    is returned unchanged.
    """
    if _continues_previous_turn(messages):
        return latest_text
    if not latest_text.strip():
        return latest_text
    if _has_command_verb(latest_text):
        return latest_text
    if _is_question(latest_text):
        return latest_text
    if _is_short_reply(latest_text):
        return latest_text

    prefix = "добавь " if _has_cyrillic(latest_text) else "add "
    return prefix + latest_text

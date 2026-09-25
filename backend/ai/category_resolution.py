"""Category label/slug resolution shared by chat and draft (feature 0084, issue #209).

The bug this fixes: the LLM sometimes puts the user's own wording for a
category ("рабочая", "Work") into the JSON `category` field instead of the
slug (`work`) that `ai/schemas.py` requires. Before this module, that made
the whole action fail schema validation, which for chat meant the whole
turn raised ``AIParseError`` and surfaced a **502** with an internal
validation string (issue #209's repro). Resolution now runs BEFORE schema
validation, so a label or the user's own wording (once it matches a known
slug/label — see ``resolve_category``) is silently normalised instead of
failing the turn.

Pure module — no Django settings, no DB. ``normalize_action_categories``
does import ``ai.schemas.validate_action_shape`` for its category-only-drop
guard (§ below), and that module reads ``django.conf.settings`` for a couple
of length caps, so this module is not stdlib-only the way ``replay_guard.py``
is — but it still does no I/O and needs no DB to be unit-tested.

See ``docs/features/0084_PLAN.md`` for the full design and the accepted
risks (slug/label cross-match, sink fallback on add, English-only server
ask).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from schedules.http import is_plain_int

from ai.schemas import validate_action_shape

logger = logging.getLogger(__name__)


def resolve_category(value, categories) -> str | None:
    """Resolve a user- or model-supplied category value to a slug.

    ``categories`` is an ordered iterable of ``(slug, label)`` pairs — pass
    ``prompts._DEFAULT_CATEGORIES`` when the caller has no per-user catalog.

    Non-``str`` input returns ``None``: it is left to schema validation,
    which still rejects it as malformed.

    Resolution order:
      1. Exact slug match — the common case, and the only step immune to a
         slug/label cross-match (see the plan's Risks section).
      2. Case-folded match against either the slug or the (stripped) label,
         first catalog entry wins. SQLite's ``LOWER`` folds ASCII only while
         Python's ``casefold`` is locale-independent, so two labels that
         differ only in non-ASCII case (e.g. two Cyrillic spellings) CAN
         coexist in the DB even though `unique_user_category_label_ci`
         forbids an ASCII-equivalent collision — catalog order breaks the
         tie deterministically.
      3. No match — ``None``. No fuzzy matching, stemming or translation:
         inflected forms (e.g. Russian "рабочая" for "work") are the
         prompt's job (``ai/prompts.py`` Hard rule 4), and callers fall back
         to the sink slug (``add``) or ask the user (``update``) instead.
    """
    if not isinstance(value, str):
        return None

    slugs = {slug for slug, _label in categories}
    if value in slugs:
        return value

    key = value.strip().casefold()
    for slug, label in categories:
        if slug.casefold() == key or label.strip().casefold() == key:
            return slug
    return None


@dataclass(frozen=True)
class UnresolvedCategory:
    """One category value ``normalize_action_categories`` could not resolve.

    ``original_index`` is the position in the model's OWN ``actions`` list
    (the index space of ``raw``/``parsed`` before normalisation) — NOT the
    index of the returned, normalised list, which may be shorter when
    ``dropped`` is ``True``. The view keys the audit `unresolved_categories`
    payload by this field precisely so the two index spaces never mix (see
    the plan §2 "One index space").
    """

    original_index: int
    task_id: int | None
    # Excluded from ``repr`` so a stray ``%r`` of a record never logs the
    # user's own wording (the module never logs it; see the docstring below).
    value: str = field(repr=False)
    dropped: bool


@dataclass(frozen=True)
class NormalizeResult:
    """Return value of ``normalize_action_categories``.

    ``original_indices[i]`` is the position in the model's OWN ``actions``
    list that produced ``actions[i]`` — the two lists are aligned 1:1 and
    both shrink together when a category-only ``update`` is dropped, so a
    caller building an ``action[i]``-style message from ``actions`` can
    report the model's own index instead of the post-drop one.
    """

    actions: list[dict]
    unresolved: tuple[UnresolvedCategory, ...]
    original_indices: tuple[int, ...]


def _normalize_add(action: dict, categories, sink_slug: str) -> dict:
    """Return a normalised copy of one ``add`` action. Never mutates ``action``."""
    if "category" not in action or action.get("category") is None:
        # Absent key or explicit ``null`` — Hard rule 4's "Default to
        # <sink> if unclear", applied structurally. The value is SUPPLIED
        # here, not rewritten, so it is never recorded as unresolved.
        new_action = dict(action)
        new_action["category"] = sink_slug
        logger.debug("AI category default applied (type=add, outcome=sink)")
        return new_action

    value = action["category"]
    if not isinstance(value, str):
        # Any other non-str value (e.g. a number) is left untouched and
        # still fails schema validation — not this module's job to guess.
        return action

    resolved = resolve_category(value, categories)
    new_action = dict(action)
    if resolved is not None:
        new_action["category"] = resolved
        logger.debug("AI category resolved (type=add, outcome=rewritten)")
    else:
        # Unresolved on add is never recorded — it's expected fallback
        # behaviour (Hard rule 4), not something the user is asked about.
        new_action["category"] = sink_slug
        logger.debug("AI category unresolved (type=add, outcome=sink)")
    return new_action


def _loggable_task_id(task_id):
    """Log only a plain-int ``task_id``: this runs before schema validation,
    so any other model-supplied value could carry arbitrary text."""
    return task_id if is_plain_int(task_id) else "<invalid>"


def _normalize_update(
    action: dict,
    categories,
    known_task_ids,
    original_index: int,
) -> tuple[dict, UnresolvedCategory | None]:
    """Return ``(normalised_or_original_action, unresolved_or_None)``.

    ``action`` is returned unchanged (same object, not a copy) for every
    path that leaves it untouched, matching ``normalize_action_categories``'s
    "never mutates" contract — callers must not mutate a returned dict
    either way.
    """
    changes = action.get("changes")
    if type(changes) is not dict or "category" not in changes:
        return action, None

    value = changes["category"]
    if not isinstance(value, str):
        # e.g. ``null`` or a number — left untouched, still fails schema
        # validation. Only an ``add``'s absent/``null`` category gets the
        # sink-slug exception (see ``_normalize_add``).
        return action, None

    resolved = resolve_category(value, categories)
    if resolved is not None:
        new_changes = dict(changes)
        new_changes["category"] = resolved
        new_action = dict(action)
        new_action["changes"] = new_changes
        logger.debug(
            "AI category resolved (type=update, task_id=%r, outcome=rewritten)",
            _loggable_task_id(action.get("task_id")),
        )
        return new_action, None

    task_id = action.get("task_id")
    other_changes = {k: v for k, v in changes.items() if k != "category"}
    if other_changes:
        # Unresolved with other changes remaining: drop just the category
        # key and keep applying the rest. Never quietly recategorise an
        # existing block, but also never silently drop the whole action —
        # the view (§4) tells the user via a category ask.
        new_action = dict(action)
        new_action["changes"] = other_changes
        logger.debug(
            "AI category unresolved (type=update, task_id=%r, outcome=dropped_field)",
            _loggable_task_id(task_id),
        )
        return new_action, UnresolvedCategory(
            original_index=original_index, task_id=task_id, value=value, dropped=False
        )

    # ``category`` was the ONLY change. Drop the whole action, but only when
    # it would otherwise be valid AND references a real block — a malformed
    # action or an unknown ``task_id`` must still fail validation (502) as
    # today, never turn into a silent 200 clarifying question.
    # ``| {value}`` lets the unresolved (still-original-wording) category
    # pass ``validate_action_shape``'s category check here, so the guard
    # below only fires — and drops the action — when every OTHER field is
    # already valid; a genuinely malformed action still fails schema
    # validation (502) instead of silently becoming a category ask.
    allowed_categories = {slug for slug, _label in categories} | {value}
    guard_errors = validate_action_shape(action, allowed_categories)
    if not guard_errors and task_id in known_task_ids:
        logger.debug(
            "AI category unresolved (type=update, task_id=%r, outcome=dropped_action)",
            _loggable_task_id(task_id),
        )
        return action, UnresolvedCategory(
            original_index=original_index, task_id=task_id, value=value, dropped=True
        )
    return action, None


def normalize_action_categories(
    actions: list, categories, sink_slug: str, known_task_ids
) -> NormalizeResult:
    """Resolve every action's category to a slug before schema validation.

    Pure function: returns a NEW list (the input list and its dicts are
    never mutated) plus the ``UnresolvedCategory`` records for the ``update``
    actions the caller (the view, §4 of the plan) needs to ask the user
    about. Entries that are not dicts, and actions whose category-bearing
    field is present but not a ``str`` (other than the add null/absent
    exception above), are left untouched — they keep failing validation
    exactly as before this module existed.

    Never logs the rejected value itself: it is the user's own wording, and
    the audit row's ``raw`` field already holds it (``logger.debug`` here
    carries only the action type, ``task_id``, and the outcome label).
    """
    normalized: list = []
    original_indices: list[int] = []
    unresolved: list[UnresolvedCategory] = []

    for original_index, action in enumerate(actions):
        if not isinstance(action, dict):
            normalized.append(action)
            original_indices.append(original_index)
            continue

        action_type = action.get("type")
        if action_type == "add":
            normalized.append(_normalize_add(action, categories, sink_slug))
            original_indices.append(original_index)
            continue

        if action_type == "update":
            new_action, record = _normalize_update(
                action, categories, known_task_ids, original_index
            )
            if record is not None:
                unresolved.append(record)
                if record.dropped:
                    continue
            normalized.append(new_action)
            original_indices.append(original_index)
            continue

        # move / remove / resize carry no category — pass through as-is.
        normalized.append(action)
        original_indices.append(original_index)

    return NormalizeResult(
        actions=normalized, unresolved=tuple(unresolved), original_indices=tuple(original_indices)
    )

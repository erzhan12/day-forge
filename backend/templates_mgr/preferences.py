"""Canonical lookup path for ``UserPreferences``.

Both page-prop renderers and the JSON API go through ``get_user_preferences``
so that:

1. The default row is created on first authenticated access (idempotent via
   ``get_or_create``).
2. Invalid persisted values are normalized on read without writing the DB
   — corruption healing happens only on explicit PATCH (see ``api.py``).
3. Callers always receive a frozen DTO, not the ORM instance — eliminates
   write-on-read hazards if a caller later does ``.save()`` on the result.
"""

from dataclasses import dataclass

from templates_mgr.models import UserPreferences

# SYNC ALERT: mirror these defaults and limits in the Phase 2 frontend utility
# `frontend/src/utils/chatSuggestions.ts`.
DEFAULT_CHAT_SUGGESTIONS = [
    "Plan my remaining day",
    "Add a focused work block",
    "Make room for a break",
]
MAX_CHAT_SUGGESTIONS = 8
MAX_CHAT_SUGGESTION_LENGTH = 120


@dataclass(frozen=True)
class UserPreferencesDTO:
    """Read-only DTO returned by :func:`get_user_preferences`.

    ``theme`` is guaranteed to be recognized. ``chat_suggestions`` is an
    immutable tuple copy of the normalized JSON list, so callers cannot
    mutate the ORM value through the frozen DTO.
    """

    theme: str
    chat_suggestions: tuple[str, ...]


def ui_preferences_payload(prefs: UserPreferencesDTO) -> dict:
    """Serialize the normalized read-side DTO for API and Inertia output."""
    return {
        "theme": prefs.theme,
        "chat_suggestions": list(prefs.chat_suggestions),
    }


_VALID_THEMES = frozenset(UserPreferences.Theme.values)


def normalize_theme(raw: str) -> str:
    """Map a stored theme value to a recognized id, defaulting to ``classic``.

    Does not write the DB. Used as a read-side safety net for rows that
    bypassed the choices validator (raw SQL, fixture typo, retired value).
    """
    if raw in _VALID_THEMES:
        return raw
    return UserPreferences.Theme.CLASSIC


def normalize_chat_suggestions(raw) -> list[str]:
    """Resolve stored suggestions for display without writing the database."""
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return list(DEFAULT_CHAT_SUGGESTIONS)
    return [trimmed for item in raw if (trimmed := item.strip())]


def get_user_preferences(user) -> UserPreferencesDTO:
    """Return the user's preferences as a frozen DTO.

    **Single-user contract**: this helper is for request-scoped lookups
    (one call per authenticated page render). If a future caller needs
    preferences for multiple users at once, query ``UserPreferences``
    directly with ``select_related("user")`` rather than calling this
    helper in a loop — looping would re-issue ``get_or_create`` per user
    and produce an N+1 query pattern.

    ``get_or_create`` is required (not "try fetch, else insert") because
    two concurrent first-visit requests on a cold session would otherwise
    both miss the row and both INSERT, hitting the OneToOne unique
    constraint on the second. ``get_or_create`` is atomic at the DB level
    via ``IntegrityError`` rescue, so the race resolves correctly.
    """
    prefs, _ = UserPreferences.objects.get_or_create(
        user=user,
        defaults={"theme": UserPreferences.Theme.CLASSIC},
    )
    return UserPreferencesDTO(
        theme=normalize_theme(prefs.theme),
        chat_suggestions=tuple(normalize_chat_suggestions(prefs.chat_suggestions)),
    )

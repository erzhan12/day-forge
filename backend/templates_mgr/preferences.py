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


@dataclass(frozen=True)
class UserPreferencesDTO:
    """Read-only DTO returned by :func:`get_user_preferences`.

    ``theme`` is guaranteed to be one of the recognized theme ids — call
    sites can pass it directly into page props or API responses without
    re-validating.
    """

    theme: str


_VALID_THEMES = frozenset(UserPreferences.Theme.values)


def normalize_theme(raw: str) -> str:
    """Map a stored theme value to a recognized id, defaulting to ``classic``.

    Does not write the DB. Used as a read-side safety net for rows that
    bypassed the choices validator (raw SQL, fixture typo, retired value).
    """
    if raw in _VALID_THEMES:
        return raw
    return UserPreferences.Theme.CLASSIC


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
    return UserPreferencesDTO(theme=normalize_theme(prefs.theme))

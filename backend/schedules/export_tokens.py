"""Lifecycle for the personal, read-only daily-export credential (feature 0088).

The raw credential is returned to the caller only once, at creation. Only its
SHA-256 digest is ever persisted or compared. Creation and revocation run
through ``run_user_maintenance`` so both serialize against the same per-user
write lock as every other policy write; lookup reads current database state
on every call so revocation takes effect on the very next request.
"""

import hashlib
import secrets

from schedules.models import PersonalExportToken
from schedules.mutations import run_user_maintenance

TOKEN_PREFIX = "dfx_"
_RANDOM_BYTES = 32


class TokenExistsError(Exception):
    """Raised by ``create_token`` when the user already has an active token."""


def generate_raw_token() -> str:
    """Return a new credential: a fixed prefix plus 32+ random bytes."""
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(_RANDOM_BYTES)}"


def hash_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest of the entire raw credential."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_token(user_id: int) -> tuple[str, PersonalExportToken]:
    """Create and persist a new token for ``user_id``.

    Returns ``(raw_token, row)``. Raises ``TokenExistsError`` without writing
    anything if the user already has an active token.
    """
    raw_token = generate_raw_token()
    digest = hash_token(raw_token)

    def create(user):
        if PersonalExportToken.objects.filter(user=user).exists():
            raise TokenExistsError
        return PersonalExportToken.objects.create(user=user, token_digest=digest)

    row = run_user_maintenance(user_id, create)
    return raw_token, row


def revoke_token(user_id: int) -> None:
    """Delete the user's token, if any. Idempotent."""

    def revoke(user):
        PersonalExportToken.objects.filter(user=user).delete()

    run_user_maintenance(user_id, revoke)


def authenticate(raw_token: str):
    """Return the active owning user for ``raw_token``, or ``None``.

    Always reads current database state; never caches a result, so a
    revocation takes effect on the very next call.
    """
    if not raw_token or not raw_token.startswith(TOKEN_PREFIX):
        return None
    digest = hash_token(raw_token)
    row = (
        PersonalExportToken.objects.filter(token_digest=digest, user__is_active=True)
        .select_related("user")
        .first()
    )
    return row.user if row else None

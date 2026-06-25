"""Fernet symmetric encryption for stored Google OAuth tokens.

Keyed by ``settings.GOOGLE_OAUTH_TOKEN_KEY`` (Fernet URL-safe base64, 32
bytes). The system check ``gcal_sync.E001`` blocks ``DEBUG=False`` startup
when the env var is unset or malformed — see ``checks.py``.

Clones ``calendar_sync/crypto.py`` verbatim but keyed on the Google token
key and with ``encrypt_token`` / ``decrypt_token`` naming (refresh AND
access tokens flow through the same pair).
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    key = getattr(settings, "GOOGLE_OAUTH_TOKEN_KEY", "") or ""
    if not key:
        raise ImproperlyConfigured(
            "GOOGLE_OAUTH_TOKEN_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and add it to .env."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        raise ImproperlyConfigured(
            "GOOGLE_OAUTH_TOKEN_KEY is not a valid Fernet key."
        ) from e


def encrypt_token(plaintext: str) -> bytes:
    if not isinstance(plaintext, str):
        raise TypeError("plaintext token must be str")
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_token(ciphertext: bytes | memoryview) -> str:
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        # Translate to ImproperlyConfigured so a key-rotation bug surfaces
        # as a config problem rather than a generic crypto error in views.
        raise ImproperlyConfigured(
            "Stored Google token could not be decrypted with the current "
            "GOOGLE_OAUTH_TOKEN_KEY. The key may have rotated."
        ) from e

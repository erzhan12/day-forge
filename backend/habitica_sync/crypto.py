"""Fernet symmetric encryption for stored Habitica tokens.

Keyed by ``settings.HABITICA_ENCRYPTION_KEY`` (Fernet URL-safe base64, 32
bytes). The system check ``habitica_sync.E001`` blocks ``DEBUG=False``
startup when the env var is unset — see ``checks.py``.
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    key = getattr(settings, "HABITICA_ENCRYPTION_KEY", "") or ""
    if not key:
        raise ImproperlyConfigured(
            "HABITICA_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and add it to .env."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        raise ImproperlyConfigured(
            "HABITICA_ENCRYPTION_KEY is not a valid Fernet key."
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
            "Stored Habitica token could not be decrypted with the "
            "current HABITICA_ENCRYPTION_KEY. The key may have rotated."
        ) from e

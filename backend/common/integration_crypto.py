"""Fernet helpers for provider credentials, with provider-specific keys."""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def fernet_for_setting(setting_name: str) -> Fernet:
    key = getattr(settings, setting_name, None)
    if not key:
        raise ImproperlyConfigured(f"{setting_name} is not set.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError):
        raise ImproperlyConfigured(f"{setting_name} is not a valid Fernet key.") from None


def encrypt_secret(plaintext: str, *, setting_name: str, secret_name: str) -> bytes:
    if not isinstance(plaintext, str):
        raise TypeError(f"plaintext {secret_name} must be str")
    return fernet_for_setting(setting_name).encrypt(plaintext.encode("utf-8"))


def decrypt_secret(
    ciphertext: bytes | memoryview,
    *,
    setting_name: str,
    safe_error: str,
) -> str:
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    try:
        return fernet_for_setting(setting_name).decrypt(ciphertext).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError):
        raise ImproperlyConfigured(safe_error) from None

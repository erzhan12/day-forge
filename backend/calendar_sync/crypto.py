"""Encryption of stored passwords with the calendar_sync key."""

from common.integration_crypto import decrypt_secret, encrypt_secret, fernet_for_setting
from cryptography.fernet import Fernet

_SETTING = "CALDAV_ENCRYPTION_KEY"
_SAFE_ERROR = (
    "Stored CalDAV password could not be decrypted with the current CALDAV_ENCRYPTION_KEY."
    " The key may have rotated."
)


def _fernet() -> Fernet:
    return fernet_for_setting(_SETTING)


def encrypt_password(plaintext: str) -> bytes:
    return encrypt_secret(plaintext, setting_name=_SETTING, secret_name="password")


def decrypt_password(ciphertext: bytes | memoryview) -> str:
    return decrypt_secret(ciphertext, setting_name=_SETTING, safe_error=_SAFE_ERROR)

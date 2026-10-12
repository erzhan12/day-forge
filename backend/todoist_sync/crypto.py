"""Encryption of stored tokens with the todoist_sync key."""

from common.integration_crypto import decrypt_secret, encrypt_secret, fernet_for_setting
from cryptography.fernet import Fernet

_SETTING = "TODOIST_ENCRYPTION_KEY"
_SAFE_ERROR = (
    "Stored Todoist token could not be decrypted with the current TODOIST_ENCRYPTION_KEY."
    " The key may have rotated."
)


def _fernet() -> Fernet:
    return fernet_for_setting(_SETTING)


def encrypt_token(plaintext: str) -> bytes:
    return encrypt_secret(plaintext, setting_name=_SETTING, secret_name="token")


def decrypt_token(ciphertext: bytes | memoryview) -> str:
    return decrypt_secret(ciphertext, setting_name=_SETTING, safe_error=_SAFE_ERROR)

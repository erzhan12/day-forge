"""Encryption of stored tokens with the gcal_sync key."""

from common.integration_crypto import decrypt_secret, encrypt_secret, fernet_for_setting
from cryptography.fernet import Fernet

_SETTING = "GOOGLE_OAUTH_TOKEN_KEY"
_SAFE_ERROR = (
    "Stored Google token could not be decrypted with the current GOOGLE_OAUTH_TOKEN_KEY."
    " The key may have rotated."
)


def _fernet() -> Fernet:
    return fernet_for_setting(_SETTING)


def encrypt_token(plaintext: str) -> bytes:
    return encrypt_secret(plaintext, setting_name=_SETTING, secret_name="token")


def decrypt_token(ciphertext: bytes | memoryview) -> str:
    return decrypt_secret(ciphertext, setting_name=_SETTING, safe_error=_SAFE_ERROR)

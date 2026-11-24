"""Encryption of stored WHOOP tokens with WHOOP's own key (feature 0107)."""

from common.integration_crypto import decrypt_secret, encrypt_secret

_SETTING = "WHOOP_OAUTH_TOKEN_KEY"
_SAFE_ERROR = (
    "Stored WHOOP token could not be decrypted with the current WHOOP_OAUTH_TOKEN_KEY."
    " The key may have rotated; reconnect WHOOP."
)


def encrypt_token(plaintext: str) -> bytes:
    return encrypt_secret(plaintext, setting_name=_SETTING, secret_name="token")


def decrypt_token(ciphertext: bytes | memoryview) -> str:
    return decrypt_secret(ciphertext, setting_name=_SETTING, safe_error=_SAFE_ERROR)

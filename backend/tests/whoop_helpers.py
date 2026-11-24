"""Shared WHOOP test settings (feature 0107). Synthetic values only."""

from cryptography.fernet import Fernet

FERNET_KEY = Fernet.generate_key().decode()
TOKEN_URI = "https://api.prod.whoop.com/oauth/oauth2/token"
AUTH_URI = "https://api.prod.whoop.com/oauth/oauth2/auth"
API_BASE = "https://api.prod.whoop.com/developer"
REDIRECT_URI = "https://app.test/api/whoop/callback/"
SCOPES = "offline read:recovery read:cycles read:sleep read:workout"

WHOOP_SETTINGS = dict(
    WHOOP_OAUTH_CLIENT_ID="whoop-client-id",
    WHOOP_OAUTH_CLIENT_SECRET="whoop-client-secret",
    WHOOP_OAUTH_REDIRECT_URI=REDIRECT_URI,
    WHOOP_OAUTH_TOKEN_KEY=FERNET_KEY,
)


def token_body(access="access-1", refresh="refresh-1", expires_in=3600, scope=SCOPES):
    body = {"access_token": access, "expires_in": expires_in, "token_type": "bearer"}
    if refresh is not None:
        body["refresh_token"] = refresh
    if scope is not None:
        body["scope"] = scope
    return body

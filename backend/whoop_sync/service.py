"""WHOOP OAuth and REST client for the whoop_sync app (feature 0107).

**This module owns the plaintext.** It is the only caller of
``WhoopAccount.get_refresh_token`` / ``get_access_token``; views pass account
objects and turn the typed errors below into fixed responses. Tokens, codes
and provider response bodies are never logged or put into exception text.

WHOOP data passes through in memory only: nothing fetched here is stored,
cached or logged.
"""

import dataclasses
import datetime
import urllib.parse

import httpx
from django.conf import settings
from django.utils import timezone

from whoop_sync.checks import WHOOP_OAUTH_SETTINGS

STATE_LENGTH = 8


# ----- Typed errors -------------------------------------------------------


class WhoopError(Exception):
    """Base for WHOOP service errors. Messages never carry provider data."""


class WhoopAuthError(WhoopError):
    """The grant was rejected: the user must reconnect (export 409)."""


class WhoopRateLimitError(WhoopError):
    """WHOOP answered 429 (export 429)."""


class WhoopProviderError(WhoopError):
    """WHOOP failed, was unreachable or answered nonsense (export 502)."""


# ----- Configuration ------------------------------------------------------


def is_configured() -> bool:
    """True when all four ``WHOOP_OAUTH_*`` settings are set."""
    return all(getattr(settings, name, "") for name in WHOOP_OAUTH_SETTINGS)


def _headers() -> dict[str, str]:
    return {"User-Agent": settings.WHOOP_USER_AGENT}


# ----- OAuth --------------------------------------------------------------


@dataclasses.dataclass(frozen=True, repr=False)
class TokenGrant:
    access_token: str
    refresh_token: str | None
    expiry: datetime.datetime
    scopes: str

    def __repr__(self) -> str:  # never show tokens
        return f"TokenGrant(expiry={self.expiry.isoformat()}, scopes={self.scopes!r})"


def build_authorization_url(state: str) -> str:
    """WHOOP consent URL. WHOOP requires a client ``state`` of exactly 8 chars."""
    if len(state) != STATE_LENGTH:
        raise ValueError("WHOOP state must be exactly 8 characters")
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.WHOOP_OAUTH_CLIENT_ID,
            "redirect_uri": settings.WHOOP_OAUTH_REDIRECT_URI,
            "scope": settings.WHOOP_OAUTH_SCOPE,
            "state": state,
        }
    )
    return f"{settings.WHOOP_OAUTH_AUTH_URI}?{query}"


def _raise_for_status(status_code: int, *, auth_statuses: tuple[int, ...]) -> None:
    if status_code in auth_statuses:
        raise WhoopAuthError("WHOOP rejected the credentials")
    if status_code == 429:
        raise WhoopRateLimitError("WHOOP rate limit")
    if not 200 <= status_code < 300:
        raise WhoopProviderError(f"WHOOP answered HTTP {status_code}")


def _token_request(fields: dict[str, str]) -> TokenGrant:
    """POST the token endpoint and parse the grant. Never logs fields or body."""
    form = {
        **fields,
        "client_id": settings.WHOOP_OAUTH_CLIENT_ID,
        "client_secret": settings.WHOOP_OAUTH_CLIENT_SECRET,
    }
    try:
        response = httpx.post(
            settings.WHOOP_OAUTH_TOKEN_URI,
            data=form,
            headers=_headers(),
            timeout=settings.WHOOP_REQUEST_TIMEOUT,
        )
    except httpx.HTTPError:
        raise WhoopProviderError("WHOOP token endpoint unreachable") from None
    _raise_for_status(response.status_code, auth_statuses=(400, 401))
    try:
        body = response.json()
    except ValueError:
        raise WhoopProviderError("WHOOP token response is not JSON") from None
    if not isinstance(body, dict):
        raise WhoopProviderError("WHOOP token response is malformed")
    access_token = body.get("access_token")
    expires_in = body.get("expires_in")
    refresh_token = body.get("refresh_token")
    scopes = body.get("scope")
    if (
        not isinstance(access_token, str)
        or not access_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
        or (refresh_token is not None and not isinstance(refresh_token, str))
    ):
        raise WhoopProviderError("WHOOP token response is malformed")
    return TokenGrant(
        access_token=access_token,
        refresh_token=refresh_token or None,
        expiry=timezone.now() + datetime.timedelta(seconds=expires_in),
        scopes=scopes if isinstance(scopes, str) else "",
    )


def exchange_code(code: str) -> TokenGrant:
    """Trade an authorization code for tokens. A grant needs a refresh token."""
    grant = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.WHOOP_OAUTH_REDIRECT_URI,
        }
    )
    if grant.refresh_token is None:
        raise WhoopProviderError("WHOOP granted no refresh token (offline scope missing)")
    return grant

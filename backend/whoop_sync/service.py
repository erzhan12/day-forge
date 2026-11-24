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
import logging
import math
import secrets
import time
import urllib.parse

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, transaction
from django.utils import timezone

from whoop_sync.checks import WHOOP_OAUTH_SETTINGS
from whoop_sync.models import WhoopAccount

logger = logging.getLogger(__name__)

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


# ----- Token lifecycle (single-flight refresh) ----------------------------
#
# WHOOP rotates the refresh token on every refresh and rejects concurrent
# refreshes, so unlike ``gcal_sync`` (which tolerates parallel refreshes and
# relies on ``select_for_update``, a no-op on SQLite) only one request per
# account may refresh at a time. The lock is a ``cache.add`` key in the shared
# cache (Redis in production); a database row lock would hold the SQLite
# writer across a network call.

ACCESS_TOKEN_SKEW = datetime.timedelta(seconds=120)
POLL_INTERVAL_SECONDS = 0.25
PERSIST_ATTEMPTS = 3


def refresh_lock_key(account_id: int) -> str:
    return f"whoop_refresh:{account_id}"


def _lock_timeout_seconds() -> int:
    return math.ceil(settings.WHOOP_REQUEST_TIMEOUT) + 5


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _reload(account_id: int) -> WhoopAccount:
    try:
        return WhoopAccount.objects.get(pk=account_id)
    except WhoopAccount.DoesNotExist:
        raise WhoopAuthError("WHOOP account was disconnected") from None


def _usable_access_token(account: WhoopAccount, rejected: str | None) -> str | None:
    """The stored access token if it is valid for more than the skew and is
    not the one the caller just saw rejected."""
    expiry = account.access_token_expiry
    if expiry is None or timezone.now() >= expiry - ACCESS_TOKEN_SKEW:
        return None
    token = account.get_access_token()
    if token is None or token == rejected:
        return None
    return token


def _persist_grant(account_id: int, grant: TokenGrant) -> None:
    """Save the refreshed tokens at once: a rotated refresh token that is
    received but never stored forces a reconnect. Retries SQLite busy."""
    for attempt in range(1, PERSIST_ATTEMPTS + 1):
        try:
            with transaction.atomic():
                row = _reload(account_id)
                row.set_access_token(grant.access_token)
                row.access_token_expiry = grant.expiry
                if grant.refresh_token is not None:
                    row.set_refresh_token(grant.refresh_token)
                row.last_verified_at = timezone.now()
                row.save()
            return
        except OperationalError:
            if attempt == PERSIST_ATTEMPTS:
                logger.error("WHOOP token persist failed for account %s", account_id)
                raise
            _sleep(0.1 * attempt)


def _refresh_as_lock_holder(account_id: int, rejected: str | None) -> str:
    row = _reload(account_id)
    # Another request may have refreshed between our check and the lock.
    token = _usable_access_token(row, rejected)
    if token is not None:
        return token
    refresh_token = row.get_refresh_token()
    try:
        grant = _token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": "offline"}
        )
    except WhoopAuthError:
        # A slow earlier holder may have outlived its lock and rotated the
        # token under us: use what it stored, otherwise reconnect is needed.
        token = _usable_access_token(_reload(account_id), rejected)
        if token is not None:
            return token
        logger.info("WHOOP refresh rejected for account %s; reconnect required", account_id)
        raise
    finally:
        del refresh_token
    _persist_grant(account_id, grant)
    return grant.access_token


def _wait_for_refresh(account_id: int, rejected: str | None, lock_key: str) -> str:
    """Poll for the token the lock holder stores. Never 409: a holder that
    fails or outlives the wait is a transient failure for this request."""
    deadline = time.monotonic() + _lock_timeout_seconds()
    while time.monotonic() < deadline:
        _sleep(POLL_INTERVAL_SECONDS)
        token = _usable_access_token(_reload(account_id), rejected)
        if token is not None:
            return token
        if cache.get(lock_key) is None:
            break  # the holder finished without storing a usable token
    raise WhoopProviderError("WHOOP token refresh did not complete")


def ensure_access_token(account: WhoopAccount, *, rejected: str | None = None) -> str:
    """Return a usable access token, refreshing behind the single-flight lock.

    ``rejected`` is an access token WHOOP just answered 401 for; it forces a
    refresh unless another request has already stored a different one.
    """
    if rejected is None:
        token = _usable_access_token(account, None)
        if token is not None:
            return token
    lock_key = refresh_lock_key(account.pk)
    owner = secrets.token_hex(8)
    if not cache.add(lock_key, owner, timeout=_lock_timeout_seconds()):
        return _wait_for_refresh(account.pk, rejected, lock_key)
    try:
        return _refresh_as_lock_holder(account.pk, rejected)
    finally:
        if cache.get(lock_key) == owner:
            cache.delete(lock_key)

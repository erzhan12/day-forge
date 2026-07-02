"""Google Calendar OAuth + REST client for the gcal_sync app.

**Service-boundary owns the secret.** This module is the ONLY place that
calls ``account.get_refresh_token()`` / ``account.get_access_token()`` or
decrypts anything. Views pass the ``GoogleCalendarAccount`` instance
through; they never touch plaintext. This keeps the decryption surface to
a single file and makes the "credentials never logged" test tractable.

Auth is OAuth 2.0 authorization-code flow with offline access + refresh
tokens. ``google-auth(-oauthlib)`` handles the security-critical token
bits; ``httpx`` handles the Calendar REST calls. The connect-time helpers
(``build_authorization_url`` / ``exchange_code``) are **sync** (called
from the sync callback view); the events path
(``fetch_events_for_account`` and below) is **async** (the deploy is
ASGI/uvicorn, and the view fans out across accounts × calendars).
"""

import asyncio
import datetime
import logging
import os
import urllib.parse
from datetime import date
from datetime import datetime as dt

import google.auth.exceptions
import google.auth.transport.requests
import google.oauth2.credentials
import google.oauth2.id_token
import httpx
from asgiref.sync import sync_to_async
from calendar_sync.schemas import NormalizedEvent
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone as django_tz
from google_auth_oauthlib.flow import Flow

from gcal_sync.models import GoogleCalendarAccount

logger = logging.getLogger(__name__)

# Belt-and-suspenders for OAuth scope-equality: even with canonical scopes
# requested, a re-consent for a user who has *other* grants on the same OAuth
# client can make Google return a superset scope set, which would make
# oauthlib's ``fetch_token`` raise ``Warning: Scope has changed``. Relaxing the
# check here (the plan's documented fallback) keeps connect working; we still
# only ever *use* the read-only scopes we requested. ``setdefault`` so an
# explicit process-env value wins.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Refresh the cached access token this far before its real expiry so an
# in-flight request never races the token going stale mid-call.
_SKEW = datetime.timedelta(seconds=60)
# Pagination page size for events.list, and a hard ceiling on the loop count
# (worker protection — a misbehaving / proxied endpoint returning an endless
# nextPageToken must not pin a worker forever; mirror Todoist's
# ``_MAX_FILTER_PAGES``). We RAISE on overflow rather than silently truncate.
_EVENTS_PAGE_SIZE = 250
_MAX_PAGES = 100
# Cap concurrent per-calendar fetches within a single account so a user with
# many selected calendars can't open dozens of simultaneous outbound
# connections on the single ASGI event loop (FD pressure + Google per-user
# rate limits). Bounds both the asyncio fan-out (semaphore) and the httpx
# pool (Limits) to the same ceiling.
_MAX_CONCURRENT_CALENDAR_FETCHES = 8


# ----- Typed exception hierarchy -----------------------------------------

class GoogleCalError(Exception):
    """Base for all Google Calendar service-layer errors."""


class GoogleCalAuthError(GoogleCalError):
    """Token refresh failed / revoked grant (→ per-account reconnect)."""


class GoogleCalTimeoutError(GoogleCalError):
    """Network timeout to Google."""


class GoogleCalProviderError(GoogleCalError):
    """Anything else from the REST/transport layer — wrap to keep views simple."""


# ----- HTTP helpers ------------------------------------------------------

def _bearer(token: str) -> dict[str, str]:
    """Authorization header for a Bearer access token. Never logged."""
    return {"Authorization": f"Bearer {token}"}


def _raise_for_rest_status(response) -> None:
    """Map a non-2xx Calendar REST response onto the typed hierarchy.

    401/403 → auth (revoked/expired); everything else → provider. Never
    logs the token or Authorization header.
    """
    if response.status_code in (401, 403):
        raise GoogleCalAuthError("Google authorization failed")
    if not (200 <= response.status_code < 300):
        raise GoogleCalProviderError("Google provider error")


def _aware_utc(value):
    """Promote a (possibly naive) ``datetime`` to timezone-aware UTC.

    ``google-auth`` returns ``credentials.expiry`` as a **naive** UTC
    ``datetime``; storing that in a ``USE_TZ=True`` ``DateTimeField`` would
    warn/misbehave, so coerce to aware UTC here.
    """
    if value is None:
        return None
    if django_tz.is_naive(value):
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)


# ----- OAuth flow (sync; called from the sync connect/callback views) ----

def _client_config() -> dict:
    """Server-side OAuth client config, built per call from settings.

    Never client-provided; ``redirect_uri`` is server-config only.
    """
    return {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": settings.GOOGLE_OAUTH_AUTH_URI,
            "token_uri": settings.GOOGLE_OAUTH_TOKEN_URI,
            "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }


def _build_flow(state: str | None = None) -> Flow:
    # ``.split()`` the space-separated scope string into a list so each scope
    # flows separately — never pass the opaque multi-scope string as one
    # element (Google rejects it).
    flow = Flow.from_client_config(
        _client_config(),
        scopes=settings.GOOGLE_OAUTH_SCOPE.split(),
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        state=state,
    )
    # Disable PKCE. google-auth-oauthlib defaults autogenerate_code_verifier=
    # True, so ``authorization_url`` emits a ``code_challenge`` and stores the
    # matching ``code_verifier`` ON THE FLOW INSTANCE. We rebuild a FRESH,
    # stateless Flow at callback time (connect and callback are separate
    # requests), so that verifier is gone at token exchange and Google rejects
    # it with "invalid_grant: Missing code verifier". This is a confidential
    # Web client authenticating with a client_secret, so PKCE is optional
    # (RFC 7636) — disable it rather than thread the verifier through the
    # session.
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    return flow


def build_authorization_url(state: str) -> str:
    """Build the Google consent URL. ``state`` is generated + stored by the
    view (CSRF guard). ``access_type=offline`` + ``prompt=consent``
    guarantees a refresh token is returned even on re-consent.
    """
    flow = _build_flow(state=state)
    # No ``include_granted_scopes`` — the feature requests a fixed read-only
    # scope set and does not use incremental authorization. Enabling it would
    # let Google merge a user's other grants on this client into the returned
    # token (a superset), tripping oauthlib's scope-equality check on
    # ``fetch_token``. ``access_type=offline`` + ``prompt=consent`` still
    # guarantee a refresh token on every (re-)consent.
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    # Log only the first 8 chars of the state so the full CSRF token never
    # lands in logs; helps future OAuth troubleshooting.
    logger.debug("Built Google OAuth URL (PKCE disabled) for state=%s…", state[:8])
    return url


def _fetch_calendar_list_sync(access_token: str) -> list[dict]:
    """Synchronous ``calendarList.list`` (connect-time only), paginated.

    Doubles as the grant-verification probe and the ``id_token``-absent
    identity fallback. Paginates on ``nextPageToken`` (same ``_MAX_PAGES``
    ceiling as the async path) so the ``primary``-calendar identity fallback
    isn't missed when it sits past page 1. Uses a sync ``httpx.Client`` —
    ``exchange_code`` is sync, called from the sync callback view.
    """
    url = f"{settings.GOOGLE_CALENDAR_API_BASE}/users/me/calendarList"
    items: list[dict] = []
    params: dict = {}
    try:
        with httpx.Client(timeout=settings.GOOGLE_REQUEST_TIMEOUT) as client:
            for _page in range(_MAX_PAGES):
                response = client.get(url, headers=_bearer(access_token), params=params)
                _raise_for_rest_status(response)
                payload = response.json()
                items.extend(payload.get("items", []))
                token = payload.get("nextPageToken")
                if not token:
                    break
                params = {"pageToken": token}
            else:
                raise GoogleCalProviderError(
                    f"Google calendarList pagination exceeded {_MAX_PAGES} pages"
                )
    except GoogleCalError:
        raise
    except httpx.TimeoutException as e:
        raise GoogleCalTimeoutError("Google request timed out") from e
    except httpx.HTTPError as e:
        raise GoogleCalProviderError("Google provider error") from e
    return items


def _verify_id_token(id_token_str: str) -> dict:
    """Verify the Google ID token and return its claims dict.

    Network-fetches Google's signing certs and checks signature, ``aud ==
    client_id``, issuer, and expiry.
    """
    try:
        return google.oauth2.id_token.verify_oauth2_token(
            id_token_str,
            google.auth.transport.requests.Request(),
            audience=settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except (ValueError, google.auth.exceptions.GoogleAuthError) as e:
        raise GoogleCalAuthError("Google id_token verification failed") from e


def _identify_and_verify_grant(credentials, access_token: str) -> tuple[str, str]:
    """Resolve ``(google_account_id, email)`` and prove the grant is live.

    With ``openid`` + ``userinfo.email`` requested, ``credentials.id_token``
    is a signed JWT carrying ``sub`` + ``email`` — verify it, then issue one
    ``calendarList`` call as the grant probe. If the id_token is somehow
    absent (should not happen with the requested scopes), the single
    ``calendarList`` call doubles as both identity (``primary`` calendar id
    == account email) and grant probe.
    """
    id_tok = getattr(credentials, "id_token", None)
    if id_tok:
        claims = _verify_id_token(id_tok)
        # Grant probe — confirm the access token actually works before we
        # persist anything (mirrors CalDAV's second-endpoint verify).
        _fetch_calendar_list_sync(access_token)
        return claims["sub"], claims["email"]
    # Fallback: identity + grant probe in one call.
    items = _fetch_calendar_list_sync(access_token)
    primary = next((c for c in items if c.get("primary")), None)
    if primary is None or not primary.get("id"):
        raise GoogleCalProviderError(
            "Could not determine Google account identity"
        )
    return primary["id"], primary["id"]


def exchange_code(code: str, state: str) -> dict:
    """Exchange an OAuth ``code`` for tokens + account identity (sync).

    The ``code`` is never logged. Returns
    ``{google_account_id, email, refresh_token, access_token, expiry}``.
    A missing ``refresh_token`` is a **hard error** — ``prompt=consent``
    makes it unreachable in practice, but we fail loud rather than store a
    half-account that can never refresh.
    """
    flow = _build_flow(state=state)
    try:
        flow.fetch_token(code=code)
    except GoogleCalError:
        raise
    except Exception as e:
        # oauthlib / transport failure on the token POST. Never include the
        # code or token in the message.
        raise GoogleCalProviderError("Google token exchange failed") from e

    credentials = flow.credentials
    refresh_token = credentials.refresh_token
    if not refresh_token:
        raise GoogleCalAuthError("Google did not return a refresh token")
    access_token = credentials.token
    expiry = _aware_utc(credentials.expiry)

    google_account_id, email = _identify_and_verify_grant(
        credentials, access_token
    )
    return {
        "google_account_id": google_account_id,
        "email": email,
        "refresh_token": refresh_token,
        "access_token": access_token,
        "expiry": expiry,
    }


# ----- Access-token lifecycle (async; cache-then-refresh) ----------------

def _refresh_sync(refresh_token: str) -> tuple[str, datetime.datetime, str | None]:
    """Pure-network token refresh — NO ORM write (the locked persist in
    ``_persist_refreshed_tokens`` owns the write).

    Returns ``(new_access_token, new_expiry_utc, rotated_refresh_or_None)``.
    ``rotated_refresh`` is non-None only when Google returned a *different*
    refresh token (Google may invalidate the old one when it rotates).
    """
    creds = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=settings.GOOGLE_OAUTH_TOKEN_URI,
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=settings.GOOGLE_OAUTH_SCOPE.split(),
    )
    try:
        creds.refresh(google.auth.transport.requests.Request())
    except google.auth.exceptions.RefreshError as e:
        # Revoked / expired / deleted grant — never a silent fallback.
        raise GoogleCalAuthError("Google token refresh failed") from e
    except google.auth.exceptions.TransportError as e:
        raise GoogleCalProviderError("Google provider error") from e
    new_expiry = _aware_utc(creds.expiry)
    rotated = (
        creds.refresh_token
        if creds.refresh_token and creds.refresh_token != refresh_token
        else None
    )
    return creds.token, new_expiry, rotated


def _persist_refreshed_tokens(
    pk: int,
    new_access_token: str,
    new_expiry: datetime.datetime,
    rotated_refresh_or_None: str | None,
) -> tuple[str, datetime.datetime]:
    """Locked read-modify-write of the refreshed tokens (sync; ORM-bound).

    Reloads + row-locks the freshest row so two concurrent refreshers of the
    same account cannot lost-update each other. Returns
    ``(access_token, updated_at)`` — the caller propagates ``updated_at`` back
    onto the in-memory account so the post-fetch cache write keys on the
    **post-refresh** version (otherwise it would land under the now-dead
    pre-refresh version key and the next read would miss it). **Full
    ``save()`` (no ``update_fields``)** so ``auto_now`` advances ``updated_at``
    and the events-cache version rotates.
    """
    with transaction.atomic():
        row = GoogleCalendarAccount.objects.select_for_update().get(pk=pk)
        now = django_tz.now()
        already_fresh = (
            row.access_token_expiry is not None
            and now < row.access_token_expiry - _SKEW
        )
        # Double-checked refresh: if another concurrent request already
        # refreshed AND this caller has no rotated refresh token to persist,
        # reuse the row's token and skip the write (so only one full-save
        # bumps updated_at). But if THIS caller received a rotated refresh
        # token, never skip — Google may have invalidated the old one when it
        # issued the rotation, so discarding it would break future refreshes.
        if already_fresh and rotated_refresh_or_None is None:
            cached = row.get_access_token()
            if cached is not None:
                # Return the freshest version the concurrent writer persisted.
                return cached, row.updated_at
            # Defensive: expiry fresh but no token stored — fall through.
        row.set_access_token(new_access_token)
        row.access_token_expiry = new_expiry
        if rotated_refresh_or_None is not None:
            row.set_refresh_token(rotated_refresh_or_None)
        row.save()
        return new_access_token, row.updated_at


async def _ensure_access_token(account) -> str:
    """Return a valid access token, refreshing if the cached one is stale.

    The only refresh-token decryption call site. Single-flight is NOT
    guaranteed (deliberate, per the plan's P2): the row lock is acquired in
    ``_persist_refreshed_tokens`` *after* the network refresh, never held
    across it — pinning a ``select_for_update`` lock across an external HTTP
    refresh is an anti-pattern. The guarantee is persisted-token
    correctness, not token-endpoint call count.

    When a refresh persists, the post-refresh ``updated_at`` is copied back
    onto the in-memory ``account`` so the caller's later
    ``set_cached_events`` keys on the same (post-refresh) version the next
    read will compute — without this the cache write lands under the dead
    pre-refresh version and is unreachable.
    """
    now = django_tz.now()
    if (
        account.access_token_expiry is not None
        and now < account.access_token_expiry - _SKEW
    ):
        cached = account.get_access_token()
        if cached is not None:
            return cached

    refresh_token = account.get_refresh_token()
    try:
        new_access, new_expiry, rotated = await asyncio.to_thread(
            _refresh_sync, refresh_token
        )
    finally:
        # Drop the plaintext binding promptly (best-effort), mirroring
        # CalDAV/Todoist.
        del refresh_token
    access_token, new_updated_at = await sync_to_async(
        _persist_refreshed_tokens, thread_sensitive=True
    )(account.pk, new_access, new_expiry, rotated)
    # Reflect the rotated cache version on the in-memory instance.
    account.updated_at = new_updated_at
    return access_token


# ----- REST fetch (async; httpx.AsyncClient) -----------------------------

def _day_window(target_date: date) -> tuple[dt, dt]:
    """``[start, end)`` for the date in ``settings.TIME_ZONE``, in UTC.

    Google wants RFC3339 strings; ``.isoformat()`` on these aware-UTC
    datetimes yields the ``+00:00`` form Google accepts.
    """
    tz = django_tz.get_current_timezone()
    start = dt.combine(target_date, datetime.time.min, tzinfo=tz)
    end = start + datetime.timedelta(days=1)
    return start.astimezone(datetime.UTC), end.astimezone(datetime.UTC)


def _date_to_utc(value: date) -> dt:
    """All-day date → UTC midnight in ``settings.TIME_ZONE`` (CalDAV parity)."""
    naive = dt.combine(value, datetime.time.min)
    aware = django_tz.make_aware(naive, django_tz.get_current_timezone())
    return aware.astimezone(datetime.UTC)


async def _fetch_selected_calendars(client, access_token: str) -> list[dict]:
    """Enumerate the user's selected calendars (paginate on nextPageToken)."""
    url = f"{settings.GOOGLE_CALENDAR_API_BASE}/users/me/calendarList"
    items: list[dict] = []
    params: dict = {}
    for _page in range(_MAX_PAGES):
        response = await client.get(url, headers=_bearer(access_token), params=params)
        _raise_for_rest_status(response)
        payload = response.json()
        items.extend(payload.get("items", []))
        token = payload.get("nextPageToken")
        if not token:
            break
        params = {"pageToken": token}
    else:
        raise GoogleCalProviderError(
            f"Google calendarList pagination exceeded {_MAX_PAGES} pages"
        )
    return [
        {"id": item["id"], "summary": item.get("summary", "")}
        for item in items
        if item.get("selected") is True
    ]


async def _fetch_events_for_calendar(
    client, access_token: str, calendar_id: str, time_min: str, time_max: str
) -> list[dict]:
    """Fetch raw events for one calendar in the window (paginate)."""
    # URL-encode the calendar id: Google ids routinely contain ``@`` (shared
    # ``…@group.calendar.google.com``), ``#``, ``/`` — unescaped they break
    # into extra path segments / a fragment and silently fail the fetch.
    encoded = urllib.parse.quote(calendar_id, safe="")
    url = f"{settings.GOOGLE_CALENDAR_API_BASE}/calendars/{encoded}/events"
    base_params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": time_min,
        "timeMax": time_max,
        "maxResults": _EVENTS_PAGE_SIZE,
    }
    raw_events: list[dict] = []
    params = dict(base_params)
    for _page in range(_MAX_PAGES):
        response = await client.get(url, headers=_bearer(access_token), params=params)
        _raise_for_rest_status(response)
        payload = response.json()
        raw_events.extend(payload.get("items", []))
        token = payload.get("nextPageToken")
        if not token:
            break
        params = {**base_params, "pageToken": token}
    else:
        raise GoogleCalProviderError(
            f"Google events pagination exceeded {_MAX_PAGES} pages"
        )
    return raw_events


def _normalize_gcal_event(
    raw: dict, calendar_name: str, account_email: str
) -> NormalizedEvent | None:
    """Build a NormalizedEvent from one raw Google event; return ``None`` on
    a cancelled or malformed event rather than crashing the whole fetch."""
    try:
        # Cancelled-event skip (first check): with singleEvents=true Google
        # emits cancelled instances of recurring events (often start/end-less)
        # — they must not become ghost rows in the merged list.
        if raw.get("status") == "cancelled":
            return None
        start = raw["start"]
        end = raw["end"]
        if "dateTime" in start:
            # Timed: Google returns offset-aware RFC3339 → parse → UTC.
            start_utc = dt.fromisoformat(start["dateTime"]).astimezone(datetime.UTC)
            end_utc = dt.fromisoformat(end["dateTime"]).astimezone(datetime.UTC)
            all_day = False
        else:
            # All-day: date-only, exclusive ``end.date`` (kept as-is, matching
            # CalDAV's +1-day all-day convention).
            start_utc = _date_to_utc(date.fromisoformat(start["date"]))
            end_utc = _date_to_utc(date.fromisoformat(end["date"]))
            all_day = True
        title = raw.get("summary") or "(no title)"
        # Namespaced so a Google id can't collide with a CalDAV UID in the
        # merged list.
        external_uid = f"{raw['id']}@google"
        return NormalizedEvent(
            title=title,
            start=start_utc,
            end=end_utc,
            calendar_name=calendar_name,
            all_day=all_day,
            external_uid=external_uid,
            account_label=account_email,
        )
    except (KeyError, ValueError, TypeError) as e:
        # Narrow catch — bug-class errors (NameError, ImportError) propagate
        # so real defects surface. Never log token-bearing fields.
        logger.warning(
            "Failed to normalize Google event (%s: %s); skipping",
            type(e).__name__,
            e,
        )
        return None


async def fetch_events_for_account(
    account, target_date: date
) -> list[NormalizedEvent]:
    """Fetch + normalise Google events for one account on one date.

    Wraps every provider error in the typed hierarchy so the view translates
    to per-account status. ``ImproperlyConfigured`` (key rotation, raised by
    the refresh-token decrypt) propagates unwrapped so the view maps it to a
    server-wide config-500.
    """
    access_token = await _ensure_access_token(account)
    time_min_dt, time_max_dt = _day_window(target_date)
    time_min, time_max = time_min_dt.isoformat(), time_max_dt.isoformat()
    try:
        async with httpx.AsyncClient(
            timeout=settings.GOOGLE_REQUEST_TIMEOUT,
            limits=httpx.Limits(
                max_connections=_MAX_CONCURRENT_CALENDAR_FETCHES
            ),
        ) as client:
            selected = await _fetch_selected_calendars(client, access_token)
            # Bound the per-calendar fan-out so a many-calendar account doesn't
            # spike concurrent connections (the across-account fan-out in the
            # view is small — one bound per account is sufficient for V1).
            sem = asyncio.Semaphore(_MAX_CONCURRENT_CALENDAR_FETCHES)

            async def _fetch_bounded(cal):
                async with sem:
                    return await _fetch_events_for_calendar(
                        client, access_token, cal["id"], time_min, time_max
                    )

            results = await asyncio.gather(
                *[_fetch_bounded(cal) for cal in selected]
            )
        normalized: list[NormalizedEvent] = []
        for cal, raw_list in zip(selected, results):
            for raw in raw_list:
                ev = _normalize_gcal_event(raw, cal["summary"], account.email)
                if ev is None:
                    continue
                # Defensive window guard — drop anything outside [start, end).
                if ev.end <= time_min_dt or ev.start >= time_max_dt:
                    continue
                normalized.append(ev)
        normalized.sort(key=lambda e: (e.start, e.title, e.external_uid))
        return normalized
    except GoogleCalError:
        raise
    except ImproperlyConfigured:
        raise
    except httpx.TimeoutException as e:
        raise GoogleCalTimeoutError("Google request timed out") from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise GoogleCalAuthError("Google authorization failed") from e
        raise GoogleCalProviderError("Google provider error") from e
    except httpx.HTTPError as e:
        raise GoogleCalProviderError("Google provider error") from e

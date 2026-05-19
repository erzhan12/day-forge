"""Request/response schemas for the CalDAV API endpoints.

Kept deliberately small — Django views do the validation inline rather
than reaching for a heavier schema lib. These helpers exist so the view
body stays focused on the happy path.
"""

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email


@dataclass(frozen=True)
class NormalizedEvent:
    """The normalised event shape returned by ``service.fetch_events_for_date``.

    Fields match the response shape documented in the plan:
    ``title``, ``start``, ``end``, ``calendar_name``, ``all_day``,
    ``external_uid``. ``start`` / ``end`` are timezone-aware datetimes
    in UTC after service normalisation; the cache layer stores them as
    ISO8601 strings (see ``service.normalized_event_to_dict``).
    """

    title: str
    start: datetime
    end: datetime
    calendar_name: str
    all_day: bool
    external_uid: str


def normalized_event_to_dict(event: NormalizedEvent) -> dict:
    return {
        "title": event.title,
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "calendar_name": event.calendar_name,
        "all_day": event.all_day,
        "external_uid": event.external_uid,
    }


def validate_account_payload(data: dict) -> tuple[dict, dict]:
    """Validate the POST /api/calendar/account/ body.

    Returns ``(cleaned, errors)`` — ``errors`` is empty on success. Does
    not raise; the view translates ``errors`` to the standard envelope.
    """
    errors: dict = {}
    if not isinstance(data, dict):
        errors["detail"] = "Request body must be a JSON object."
        return {}, errors

    apple_id = data.get("apple_id")
    password = data.get("password")
    base_url = data.get("base_url")

    if not isinstance(apple_id, str) or not apple_id.strip():
        errors["apple_id"] = "apple_id is required."
    else:
        try:
            validate_email(apple_id.strip())
        except ValidationError:
            errors["apple_id"] = "apple_id must be a valid email address."

    if not isinstance(password, str) or not password:
        errors["password"] = "password is required."
    elif len(password) > 128:
        # Apple app-specific passwords are 16-27 chars; 128 is 4x the
        # longest realistic value and tight enough to reject pathological
        # payloads before they reach Fernet or the DAVClient.
        errors["password"] = "password is too long (max 128 characters)."

    if base_url is not None:
        if not isinstance(base_url, str):
            errors["base_url"] = "base_url must be a string."
        elif base_url.strip():
            # Only validate non-empty base_url. An empty/whitespace value
            # falls back to settings.CALDAV_DEFAULT_BASE_URL in the view.
            validator = URLValidator(schemes=["http", "https"])
            try:
                validator(base_url.strip())
            except ValidationError:
                errors["base_url"] = "base_url must be a valid http(s) URL."

    if errors:
        errors.setdefault("detail", "Invalid request body.")
        return {}, errors

    cleaned = {
        "apple_id": apple_id.strip(),
        "password": password,
        "base_url": (base_url or "").strip() or None,
    }
    return cleaned, {}

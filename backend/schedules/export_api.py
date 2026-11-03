"""``GET /api/export/daily/<date>/`` — personal daily Markdown/JSON export (feature 0088).

Authenticates via ``export_auth.resolve_export_owner`` (Bearer export token
or an active session — see that module for precedence). Loads the day
through the shared read-only ``reads.read_schedule_day`` snapshot; an absent
day returns a ``200`` empty report with ``0/0`` counts without creating a
schedule. Every response — including errors — is ``private, no-store``.
"""

import datetime
import re

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.daily_export import format_daily_export
from schedules.export_auth import resolve_export_owner
from schedules.reads import read_schedule_day
from schedules.window import user_local_date_readonly

_STRICT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALID_FORMATS = {"markdown", "json"}


def _error(detail: str, status: int) -> JsonResponse:
    response = JsonResponse({"errors": {"detail": detail}}, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _parse_date(raw: str, owner) -> tuple[datetime.date | None, JsonResponse | None]:
    if raw == "today":
        return user_local_date_readonly(owner), None
    if not _STRICT_DATE_RE.match(raw):
        return None, _error("Invalid date. Use YYYY-MM-DD or 'today'.", 400)
    try:
        return datetime.date.fromisoformat(raw), None
    except ValueError:
        return None, _error("Invalid date. Use YYYY-MM-DD or 'today'.", 400)


def _resolve_format(request) -> tuple[str | None, JsonResponse | None]:
    raw = request.GET.get("format", "markdown")
    if raw not in _VALID_FORMATS:
        return None, _error("Invalid format. Use 'markdown' or 'json'.", 400)
    return raw, None


def _export_block(block) -> dict:
    """Formatter-only fields — no ``id``, no Undo's ``restore_proof``."""
    return {
        "title": block.title,
        "start_time": block.start_time.strftime("%H:%M"),
        "end_time": block.end_time.strftime("%H:%M"),
        "category": block.category,
        "is_completed": block.is_completed,
        "sort_order": block.sort_order,
    }


@require_http_methods(["GET"])
def daily_export(request, date: str) -> HttpResponse:
    owner, error_response = resolve_export_owner(request)
    if error_response is not None:
        return error_response

    export_format, error_response = _resolve_format(request)
    if error_response is not None:
        return error_response

    parsed_date, error_response = _parse_date(date, owner)
    if error_response is not None:
        return error_response

    day = read_schedule_day(owner, parsed_date)
    blocks = [] if day is None else [_export_block(block) for block in day[1]]
    iso_date = parsed_date.isoformat()
    # The export dialog's note is transient, component-local state (see
    # DailyExportDialog.vue); HTTP exports never substitute DailyReview
    # notes or persist one, so this is always empty.
    note = ""

    if export_format == "json":
        markdown = format_daily_export(date=iso_date, blocks=blocks, note=note)
        completed_count = sum(1 for block in blocks if block["is_completed"])
        response = JsonResponse(
            {
                "date": iso_date,
                "blocks": blocks,
                "completed_count": completed_count,
                "planned_count": len(blocks),
                "note": note,
                "markdown": markdown,
            }
        )
    else:
        markdown = format_daily_export(date=iso_date, blocks=blocks, note=note)
        response = HttpResponse(markdown, content_type="text/markdown; charset=utf-8")

    response["Cache-Control"] = "private, no-store"
    return response

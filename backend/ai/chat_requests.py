"""Durable chat claims and fenced, atomic result storage.

All callbacks are synchronous database work. The provider runs between claim
and finish, outside the User lock. Finish wraps the existing schedule executor
and response construction in the same transaction as the terminal result.
"""

import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from schedules.mutations import MutationRejected, ScheduleChanged, run_user_maintenance

from ai.models import ChatRequest


@dataclass(frozen=True)
class ChatClaim:
    pk: int
    user_id: int
    token: uuid.UUID


def request_identity(data):
    """Validate without writing, and hash the complete original JSON object."""
    raw = data.get("request_id")
    if not isinstance(raw, str):
        raise ValueError("request_id must be a canonical UUID.")
    try:
        identity = uuid.UUID(raw)
    except ValueError as exc:
        raise ValueError("request_id must be a canonical UUID.") from exc
    if str(identity) != raw:
        raise ValueError("request_id must be a canonical UUID.")
    try:
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Request body must contain valid JSON values.") from exc
    return identity, hashlib.sha256(canonical.encode()).hexdigest()


def processing_response():
    response = JsonResponse(
        {
            "code": "request_in_progress",
            "errors": {"detail": "The previous AI request is still processing. Check it again."},
        },
        status=409,
    )
    response["Retry-After"] = "2"
    return response


def unavailable_response():
    return JsonResponse(
        {
            "code": "request_unavailable",
            "errors": {
                "detail": "AI request state is temporarily unavailable. Retry the same request."
            },
        },
        status=503,
    )


def _stored_response(row):
    response = HttpResponse(
        row.response_body, status=row.response_status, content_type="application/json"
    )
    response.chat_request_replayed = True
    return response


def claim_request(user_id, date, request_id, body_hash):
    def claim(_user):
        now = timezone.now()
        row = ChatRequest.objects.filter(user_id=user_id, date=date, request_id=request_id).first()
        if row is not None:
            if row.body_hash != body_hash:
                return JsonResponse(
                    {
                        "code": "request_id_conflict",
                        "errors": {
                            "detail": "request_id was already used for a different request."
                        },
                    },
                    status=409,
                )
            if row.completed_at is not None:
                return _stored_response(row)
            if row.lease_expires_at > now:
                return processing_response()
        token = uuid.uuid4()
        # Longer than ordinary provider timeout/retries. A takeover fences any
        # old worker even if its network call eventually returns successfully.
        expiry = now + datetime.timedelta(seconds=max(120, settings.LLM_REQUEST_TIMEOUT * 4 + 30))
        if row is None:
            row = ChatRequest.objects.create(
                user_id=user_id,
                date=date,
                request_id=request_id,
                body_hash=body_hash,
                lease_token=token,
                lease_expires_at=expiry,
            )
        else:
            row.lease_token, row.lease_expires_at = token, expiry
            row.save(update_fields=["lease_token", "lease_expires_at"])
        return ChatClaim(row.pk, user_id, token)

    try:
        return run_user_maintenance(user_id, claim)
    except ScheduleChanged:
        return unavailable_response()


def finish_request(claim, build_response):
    def finish(_user):
        row = ChatRequest.objects.get(pk=claim.pk, user_id=claim.user_id)
        if row.completed_at is not None:
            return _stored_response(row)
        if row.lease_token != claim.token:
            return processing_response()
        try:
            # A scope violation detected after planning rolls back that entire
            # plan before its terminal error is durably stored.
            with transaction.atomic():
                response = build_response()
        except MutationRejected as exc:
            response = exc.response
        payload = json.loads(response.content)
        payload.update(request_id=str(row.request_id), request_completed=True)
        response.content = JsonResponse(payload).content
        row.response_status = response.status_code
        row.response_body = response.content.decode("utf-8")
        row.completed_at = timezone.now()
        row.save(update_fields=["response_status", "response_body", "completed_at"])
        return response

    try:
        return run_user_maintenance(claim.user_id, finish)
    except ScheduleChanged:
        return unavailable_response()

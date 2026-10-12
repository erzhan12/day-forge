"""Revision-aware client for existing domain-behavior tests.

Each request models a client that has just loaded the day. Tests of missing,
stale, concurrent or legacy-page revisions must use Django Client directly
(or pass expected_revision explicitly); this helper never changes the server.
Malformed and oversized bodies are left untouched to test the HTTP boundary.
"""

import json
import re

from django.test import Client
from schedules.models import Schedule, TimeBlock


class RevisionClient(Client):
    def generic(self, method, path, data="", content_type="application/octet-stream", **extra):
        if method in {"POST", "PATCH", "DELETE"}:
            user_id = self.session.get("_auth_user_id")
            day = re.match(r"/api/(?:ai/|analytics/)?schedules/(\d{4}-\d{2}-\d{2})/", path)
            block = re.fullmatch(r"/api/blocks/(\d+)/", path)
            reorder = path == "/api/blocks/reorder/"
            if user_id and (day or block or reorder) and len(data) <= 100_000:
                try:
                    payload = json.loads(data) if data else {}
                except ValueError, UnicodeDecodeError:
                    payload = None
                if isinstance(payload, dict) and "expected_revision" not in payload:
                    schedule = None
                    if day:
                        schedule = Schedule.objects.filter(user_id=user_id, date=day[1]).first()
                    else:
                        block_id = block[1] if block else None
                        if reorder and isinstance(payload.get("updates"), list):
                            entry = next(
                                (row for row in payload["updates"] if isinstance(row, dict)), {}
                            )
                            block_id = entry.get("id")
                        if type(block_id) is int or (
                            isinstance(block_id, str) and block_id.isdigit()
                        ):
                            schedule_id = TimeBlock.objects.filter(
                                pk=block_id, schedule__user_id=user_id
                            ).values_list("schedule_id", flat=True).first()
                            schedule = Schedule.objects.filter(pk=schedule_id).first()
                    payload["expected_revision"] = schedule.revision if schedule else 0
                    data = json.dumps(payload)
                    content_type = "application/json"
        return super().generic(method, path, data, content_type, **extra)

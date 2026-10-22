"""Separate-process continuation against a private SQLite test database."""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import django
from django.conf import settings


def main():
    settings.DATABASES["default"]["NAME"] = sys.argv[1]
    settings.DATABASES["default"]["OPTIONS"] = {"timeout": 3}
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    django.setup()
    from ai import views
    from ai.service import AIChatResult
    from asgiref.sync import async_to_sync
    from django.contrib.auth.models import User
    from django.test import RequestFactory

    root = Path(sys.argv[1]).parent
    scope = {
        "type": "add",
        "task_id": None,
        "target_ids": [],
        "known_fields": {"title": "Parallel", "category": "work"},
        "missing_fields": ["start_time", "end_time"],
    }

    async def provider(*args):
        # Rendezvous inside the provider proves both workers captured version 1.
        (root / f"intent-provider-{os.getpid()}").touch()
        for _ in range(500):
            if len(list(root.glob("intent-provider-*"))) == 2:
                break
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("Provider rendezvous failed")
        asking = sys.argv[5] == "ask"
        return AIChatResult(
            "{}",
            []
            if asking
            else [
                {
                    "type": "add",
                    "title": "Parallel",
                    "category": "work",
                    "start_time": "14:00",
                    "end_time": "14:30",
                }
            ],
            "Need a time." if asking else "Added.",
            "When?" if asking else None,
            intent_decision="continue",
            pending_actions=[scope] if asking else [],
        )

    views.run_chat = provider
    user = User.objects.get(pk=int(sys.argv[2]))

    async def auser():
        return user

    request = RequestFactory().post(
        "/api/ai/schedules/2027-01-15/chat/",
        json.dumps(
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 0,
                "pending_intent_id": sys.argv[3],
                "pending_intent_version": int(sys.argv[4]),
                "messages": [{"role": "user", "content": "14:00"}],
            }
        ),
        content_type="application/json",
    )
    request.user, request.auser = user, auser
    response = async_to_sync(views.ai_chat)(request, "2027-01-15")
    print(response.status_code)


if __name__ == "__main__":
    main()

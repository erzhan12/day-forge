"""One real chat HTTP worker against the concurrency test's private SQLite copy."""

import asyncio
import json
import os
import sys
import time
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
    (root / f"ready-{os.getpid()}").touch()
    for _ in range(500):
        if len(list(root.glob("ready-*"))) == 2:
            break
        time.sleep(0.01)
    else:
        raise RuntimeError("process rendezvous failed")

    async def provider(*args):
        with (root / "provider-calls").open("a") as calls:
            calls.write("call\n")
        await asyncio.sleep(0.4)
        return AIChatResult(
            "{}", [{"type": "add", "title": "Parallel", "category": "work",
                    "start_time": "14:00", "end_time": "14:30"}], "Added.", None,
        )

    views.run_chat = provider
    user = User.objects.get(pk=int(sys.argv[2]))

    async def auser():
        return user

    request = RequestFactory().post(
        "/api/ai/schedules/2027-01-15/chat/",
        json.dumps({"request_id": sys.argv[3], "expected_revision": 0,
                    "messages": [{"role": "user", "content": "Add Parallel at 14:00"}]}),
        content_type="application/json",
    )
    request.user = user
    request.auser = auser
    response = async_to_sync(views.ai_chat)(request, "2027-01-15")
    print(response.status_code)


if __name__ == "__main__":
    main()

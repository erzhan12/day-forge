"""Reset the Playwright user's Todoist connection without storing a token."""

import os

from django.contrib.auth.models import User
from todoist_sync.models import TodoistAccount


def main() -> None:
    mode = os.environ["SEED_MODE"]
    username = os.environ["SEED_USERNAME"]
    if mode == "reset-ensure":
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(os.environ["SEED_PASSWORD"])
            user.save()
        deleted, _ = TodoistAccount.objects.filter(user=user).delete()
        print("user created:", created, "| deleted todoist accounts:", deleted)
    elif mode == "reset-strict":
        user = User.objects.get(username=username)
        deleted, _ = TodoistAccount.objects.filter(user=user).delete()
        print("deleted todoist accounts:", deleted)
    elif mode == "disconnect":
        user = User.objects.get(username=username)
        TodoistAccount.objects.filter(user=user).delete()
        print("disconnected playwright todoist account")
    else:
        raise RuntimeError(f"Unknown SEED_MODE: {mode}")


if __name__ == "__main__":
    main()

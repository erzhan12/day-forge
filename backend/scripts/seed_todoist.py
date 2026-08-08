"""Reset the Playwright user's Todoist connection without storing a token."""

from django.contrib.auth.models import User
from todoist_sync.models import TodoistAccount

from scripts import _required, _user


def main() -> None:
    mode = _required("SEED_MODE")
    if mode == "reset-ensure":
        user, created = User.objects.get_or_create(username=_required("SEED_USERNAME"))
        if created:
            user.set_password(_required("SEED_PASSWORD"))
            user.save()
        deleted, _ = TodoistAccount.objects.filter(user=user).delete()
        print("user created:", created, "| deleted todoist accounts:", deleted)
    elif mode == "reset-strict":
        user = _user()
        deleted, _ = TodoistAccount.objects.filter(user=user).delete()
        print("deleted todoist accounts:", deleted)
    elif mode == "disconnect":
        user = _user()
        TodoistAccount.objects.filter(user=user).delete()
        print("disconnected playwright todoist account")
    else:
        raise RuntimeError(f"Unknown SEED_MODE: {mode}")


if __name__ == "__main__":
    main()

"""Reset theme preferences before or after the persistence smoke test."""

from templates_mgr.models import UserPreferences

from scripts import _required, _user


def main() -> None:
    mode = _required("SEED_MODE")
    user = _user()
    if mode == "preflight":
        preferences, _ = UserPreferences.objects.get_or_create(
            user=user, defaults={"theme": UserPreferences.Theme.CLASSIC}
        )
        preferences.theme = UserPreferences.Theme.CLASSIC
        preferences.save(update_fields=["theme"])
        print("reset theme to classic for", user.username)
    elif mode == "postflight":
        UserPreferences.objects.filter(user=user).update(
            theme=UserPreferences.Theme.CLASSIC
        )
        print("postflight: theme reset to classic")
    else:
        raise RuntimeError(f"Unknown SEED_MODE: {mode}")


if __name__ == "__main__":
    main()

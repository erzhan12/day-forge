"""Reset or pin theme preferences for the browser smoke scripts."""

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
    elif mode == "set_theme":
        # Feature 0106: pin a theme for a smoke run and print the previous
        # one so the script can restore the owner's choice afterwards.
        theme = _required("SEED_THEME")
        if theme not in UserPreferences.Theme.values:
            raise RuntimeError(f"Unknown SEED_THEME: {theme}")
        preferences, _ = UserPreferences.objects.get_or_create(
            user=user, defaults={"theme": UserPreferences.Theme.CLASSIC}
        )
        previous = preferences.theme
        preferences.theme = theme
        preferences.save(update_fields=["theme"])
        print("PREVIOUS_THEME", previous)
    else:
        raise RuntimeError(f"Unknown SEED_MODE: {mode}")


if __name__ == "__main__":
    main()

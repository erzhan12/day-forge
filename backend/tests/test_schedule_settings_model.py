import datetime

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from schedules.models import UserScheduleSettings
from schedules.window import DEFAULT_DAY_END, DEFAULT_DAY_START, get_schedule_window


@pytest.fixture
def user(db):
    return User.objects.create_user(username="windowuser", password="pass")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="windowuser2", password="pass")


# --- get_schedule_window: defaults + idempotency ---


@pytest.mark.django_db
class TestGetScheduleWindow:
    def test_default_window_created(self, user):
        """First lookup provisions a row and returns the 06:00-23:00 default."""
        window = get_schedule_window(user)
        assert window.day_start == datetime.time(6, 0)
        assert window.day_end == datetime.time(23, 0)
        assert window.day_start == DEFAULT_DAY_START
        assert window.day_end == DEFAULT_DAY_END
        assert UserScheduleSettings.objects.filter(user=user).count() == 1

    def test_get_or_create_idempotent(self, user):
        """Calling get_schedule_window twice never duplicates the row."""
        get_schedule_window(user)
        get_schedule_window(user)
        assert UserScheduleSettings.objects.filter(user=user).count() == 1

    def test_returns_persisted_custom_window(self, user):
        """After a custom row is saved, the lookup reflects it (no re-defaulting)."""
        settings = UserScheduleSettings.objects.create(
            user=user, day_start=datetime.time(8, 0), day_end=datetime.time(22, 0)
        )
        window = get_schedule_window(user)
        assert window.day_start == datetime.time(8, 0)
        assert window.day_end == datetime.time(22, 0)
        assert UserScheduleSettings.objects.filter(user=user).count() == 1
        # No second row was created by the lookup.
        assert UserScheduleSettings.objects.get(user=user).pk == settings.pk


# --- OneToOne uniqueness ---


@pytest.mark.django_db
class TestOneToOne:
    def test_second_row_for_same_user_rejected(self, user):
        # save()->full_clean() runs validate_unique before the DB, so a
        # duplicate OneToOne surfaces as ValidationError (not IntegrityError).
        UserScheduleSettings.objects.create(user=user)
        with pytest.raises(ValidationError):
            UserScheduleSettings.objects.create(user=user)


# --- Multi-user isolation ---


@pytest.mark.django_db
class TestMultiUserIsolation:
    def test_custom_window_does_not_touch_other_users_default(self, user, other_user):
        """User A saving a custom window never changes user B's default."""
        UserScheduleSettings.objects.create(
            user=user, day_start=datetime.time(9, 0), day_end=datetime.time(17, 0)
        )

        b_window = get_schedule_window(other_user)
        assert b_window.day_start == datetime.time(6, 0)
        assert b_window.day_end == datetime.time(23, 0)

        # A keeps its custom window; the rows are independent.
        a_window = get_schedule_window(user)
        assert a_window.day_start == datetime.time(9, 0)
        assert a_window.day_end == datetime.time(17, 0)
        assert UserScheduleSettings.objects.count() == 2


# --- Model-level invariant enforcement (full_clean via save/create) ---


@pytest.mark.django_db
class TestInvalidModelRejection:
    def test_full_clean_rejects_off_grid_start(self, user):
        settings = UserScheduleSettings(
            user=user, day_start=datetime.time(6, 3), day_end=datetime.time(23, 0)
        )
        with pytest.raises(ValidationError):
            settings.full_clean()

    def test_full_clean_rejects_off_grid_end(self, user):
        settings = UserScheduleSettings(
            user=user, day_start=datetime.time(6, 0), day_end=datetime.time(23, 3)
        )
        with pytest.raises(ValidationError):
            settings.full_clean()

    def test_full_clean_rejects_seconds_on_start(self, user):
        # A grid-aligned minute carrying non-zero seconds must be rejected:
        # HH:MM serialization truncates it, but downstream comparisons use the
        # full value → alignment mismatch.
        settings = UserScheduleSettings(
            user=user,
            day_start=datetime.time(6, 0, 30),
            day_end=datetime.time(23, 0),
        )
        with pytest.raises(ValidationError) as exc:
            settings.full_clean()
        assert "day_start" in exc.value.message_dict

    def test_full_clean_rejects_microseconds_on_end(self, user):
        settings = UserScheduleSettings(
            user=user,
            day_start=datetime.time(6, 0),
            day_end=datetime.time(23, 0, 0, 1),
        )
        with pytest.raises(ValidationError) as exc:
            settings.full_clean()
        assert "day_end" in exc.value.message_dict

    def test_save_rejects_seconds(self, user):
        """save() calls full_clean(), so a seconds-bearing create never persists."""
        with pytest.raises(ValidationError):
            UserScheduleSettings.objects.create(
                user=user,
                day_start=datetime.time(6, 0, 30),
                day_end=datetime.time(23, 0),
            )
        assert UserScheduleSettings.objects.filter(user=user).count() == 0

    def test_full_clean_rejects_start_after_end(self, user):
        settings = UserScheduleSettings(
            user=user, day_start=datetime.time(23, 0), day_end=datetime.time(6, 0)
        )
        with pytest.raises(ValidationError):
            settings.full_clean()

    def test_full_clean_rejects_start_equals_end(self, user):
        settings = UserScheduleSettings(
            user=user, day_start=datetime.time(10, 0), day_end=datetime.time(10, 0)
        )
        with pytest.raises(ValidationError):
            settings.full_clean()

    def test_save_rejects_off_grid(self, user):
        """save() calls full_clean(), so an off-grid create never persists."""
        with pytest.raises(ValidationError):
            UserScheduleSettings.objects.create(
                user=user, day_start=datetime.time(6, 3), day_end=datetime.time(23, 0)
            )
        assert UserScheduleSettings.objects.filter(user=user).count() == 0

    def test_save_rejects_inverted_pair(self, user):
        """objects.create hits full_clean() first (ValidationError, not IntegrityError)."""
        with pytest.raises(ValidationError):
            UserScheduleSettings.objects.create(
                user=user, day_start=datetime.time(23, 0), day_end=datetime.time(6, 0)
            )
        assert UserScheduleSettings.objects.filter(user=user).count() == 0


# --- DB-level CheckConstraint (save()-bypassing path) ---


@pytest.mark.django_db
class TestCheckConstraint:
    def test_bulk_create_inverted_pair_hits_db_constraint(self, user):
        """bulk_create bypasses save()/full_clean(), so the inverted pair reaches
        the DB CheckConstraint (schedule_window_start_lt_end) and raises IntegrityError.

        objects.create can't reach the constraint because save()->full_clean()
        raises first, so the DB-level guard must be proven via bulk_create.
        """
        with pytest.raises(IntegrityError):
            UserScheduleSettings.objects.bulk_create(
                [
                    UserScheduleSettings(
                        user=user,
                        day_start=datetime.time(23, 0),
                        day_end=datetime.time(6, 0),
                    )
                ]
            )

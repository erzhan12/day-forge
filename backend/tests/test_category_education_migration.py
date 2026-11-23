"""Feature 0106 Phase 9: Education stops sharing Health's emerald colour."""

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection, migrations
from schedules.models import Category

MIGRATION = "schedules.migrations.0012_education_color"


def run_migration():
    module = importlib.import_module(MIGRATION)
    module.recolour_education(apps, SimpleNamespace(connection=connection))


def make_user(username="education-user"):
    return get_user_model().objects.create_user(username=username)


def category(user, slug, label, color_id):
    return Category.objects.create(user=user, slug=slug, label=label, color_id=color_id)


def colour(row):
    row.refresh_from_db()
    return row.color_id


@pytest.mark.django_db
def test_recolours_education_when_it_matches_health():
    user = make_user()
    category(user, "health", "Health", "emerald")
    education = category(user, "education", "Education", "emerald")

    run_migration()

    assert colour(education) == "amber"


@pytest.mark.django_db
def test_keeps_education_with_another_colour():
    user = make_user()
    category(user, "health", "Health", "emerald")
    education = category(user, "education", "Education", "violet")

    run_migration()

    assert colour(education) == "violet"


@pytest.mark.django_db
def test_keeps_health_unchanged():
    user = make_user()
    health = category(user, "health", "Health", "emerald")
    category(user, "education", "Education", "emerald")

    run_migration()

    assert colour(health) == "emerald"


@pytest.mark.django_db
def test_skips_users_without_an_education_category():
    user = make_user()
    health = category(user, "health", "Health", "emerald")
    work = category(user, "work", "Work", "blue")

    run_migration()

    assert colour(health) == "emerald"
    assert colour(work) == "blue"


@pytest.mark.django_db
def test_skips_education_when_health_has_another_colour():
    user = make_user()
    category(user, "health", "Health", "rose")
    education = category(user, "education", "Education", "emerald")

    run_migration()

    assert colour(education) == "emerald"


@pytest.mark.django_db
def test_leaves_other_emerald_categories_alone():
    user = make_user()
    category(user, "health", "Health", "emerald")
    category(user, "education", "Education", "emerald")
    pet = category(user, "pet", "Pet", "emerald")
    other_user = make_user("other-user")
    lone_education = category(other_user, "education", "Education", "emerald")

    run_migration()

    assert colour(pet) == "emerald"
    assert colour(lone_education) == "emerald"


@pytest.mark.django_db
def test_is_idempotent():
    user = make_user()
    category(user, "health", "Health", "emerald")
    education = category(user, "education", "Education", "emerald")

    run_migration()
    run_migration()

    assert colour(education) == "amber"


@pytest.mark.django_db
def test_matches_renamed_category_by_label():
    # Slugs are frozen at creation; labels are what the user sees and renames.
    user = make_user()
    category(user, "custom-1", "  health ", "emerald")
    education = category(user, "custom-2", "EDUCATION", "emerald")
    old_slug = category(user, "education", "Study", "emerald")

    run_migration()

    assert colour(education) == "amber"
    assert colour(old_slug) == "emerald"


@pytest.mark.django_db
def test_keeps_preexisting_amber_education():
    user = make_user()
    category(user, "health", "Health", "emerald")
    education = category(user, "education", "Education", "amber")

    run_migration()

    assert colour(education) == "amber"


def test_reverse_is_a_noop():
    # Unapplying keeps the colours: no predicate can tell migrated rows from a
    # deliberate later amber. A no-op reverse keeps older migration tests able
    # to roll schedules back.
    module = importlib.import_module(MIGRATION)
    (operation,) = module.Migration.operations
    assert operation.reversible
    assert operation.reverse_code is migrations.RunPython.noop

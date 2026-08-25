"""Per-user category catalog loading, validation and mutations."""

import re
import unicodedata

from analytics.models import DailyReview
from calendar_sync.models import TravelRule
from django.contrib.auth.models import User
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from templates_mgr.models import Template

from schedules.category_palette import PALETTE, SEED_CATEGORIES
from schedules.models import Category, TimeBlock

MAX_CATEGORIES = 8
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def ordered_categories(user):
    rows = list(Category.objects.filter(user=user).order_by("sort_order", "id"))
    if rows:
        return rows
    # Retrying the whole transaction addresses SQLite's deferred transaction
    # upgrade race on the first concurrent seed.
    for attempt in range(3):
        try:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=user.pk)
                rows = list(Category.objects.filter(user=user).order_by("sort_order", "id"))
                if rows:
                    return rows
                for values in SEED_CATEGORIES:
                    Category.objects.get_or_create(user=user, slug=values["slug"], defaults=values)
            return list(Category.objects.filter(user=user).order_by("sort_order", "id"))
        except (IntegrityError, OperationalError):
            if attempt == 2:
                rows = list(Category.objects.filter(user=user).order_by("sort_order", "id"))
                if rows:
                    return rows
                raise
    # Unreachable: every attempt returns or the final attempt re-raises. Make the
    # invariant explicit so a future refactor can't silently return an empty
    # catalog (every caller assumes at least the four seeded rows).
    raise RuntimeError("ordered_categories: seeding failed after 3 attempts")


def serialize_category(category):
    return {
        key: getattr(category, key)
        for key in (
            "id",
            "slug",
            "label",
            "color_id",
            "sort_order",
            "is_sink",
            "is_new_block_default",
        )
    }


def catalog_by_slug(categories):
    return {category.slug: category for category in categories}


def sink_category(categories):
    sink = next((category for category in categories if category.is_sink), None)
    if sink is None:
        raise RuntimeError("Category catalog has no sink row.")
    return sink


def default_category(categories):
    default = next((category for category in categories if category.is_new_block_default), None)
    if default is None:
        raise RuntimeError("Category catalog has no new-block-default row.")
    return default


def validate_slug(value, categories, *, unknown_to_sink=False):
    if not isinstance(value, str):
        raise ValueError("Category must be a string.")
    rows = catalog_by_slug(categories)
    if value in rows:
        return value
    if unknown_to_sink:
        return sink_category(categories).slug
    raise ValueError("Invalid category.")


def _slugify(label, existing):
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "category"
    base = base[:32].rstrip("-") or "category"
    slug, number = base, 2
    while slug in existing:
        suffix = f"-{number}"
        slug = f"{base[: 32 - len(suffix)].rstrip('-')}{suffix}"
        number += 1
    return slug


def create_category(user, label, color_id):
    label = label.strip() if isinstance(label, str) else ""
    if not label or len(label) > 64:
        raise ValueError("Label must be between 1 and 64 characters.")
    if not isinstance(color_id, str) or color_id not in PALETTE:
        raise ValueError("Invalid color_id.")
    # select_for_update is a no-op on SQLite, so a concurrent create with the
    # same slugified label can slip past the checks and collide on the
    # (user, slug) unique constraint. Retry the whole attempt on IntegrityError
    # (re-reading rows re-slugifies to the next free suffix or re-triggers the
    # duplicate-label check) rather than surfacing a 500.
    for attempt in range(3):
        try:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=user.pk)
                rows = ordered_categories(user)
                if len(rows) >= MAX_CATEGORIES:
                    raise ValueError(
                        f"You have reached the maximum of {MAX_CATEGORIES} categories."
                    )
                if label.casefold() in {row.label.strip().casefold() for row in rows}:
                    raise ValueError("A category with that label already exists.")
                slug = _slugify(label, {row.slug for row in rows})
                return Category.objects.create(
                    user=user,
                    slug=slug,
                    label=label,
                    color_id=color_id,
                    sort_order=(max((r.sort_order for r in rows), default=-1) + 1),
                )
        except IntegrityError:
            if attempt == 2:
                raise ValueError("A category with that label already exists.") from None
    raise ValueError("A category with that label already exists.")


def update_category(user, category, data):
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        category = Category.objects.select_for_update().get(pk=category.pk, user=user)
        if "slug" in data or "is_sink" in data:
            raise ValueError("Slug and sink status are immutable.")
        if "label" in data:
            label = data["label"].strip() if isinstance(data["label"], str) else ""
            if not label or len(label) > 64:
                raise ValueError("Label must be between 1 and 64 characters.")
            if (
                Category.objects.filter(user=user, label__iexact=label)
                .exclude(pk=category.pk)
                .exists()
            ):
                raise ValueError("A category with that label already exists.")
            category.label = label
        if "color_id" in data:
            if not isinstance(data["color_id"], str) or data["color_id"] not in PALETTE:
                raise ValueError("Invalid color_id.")
            category.color_id = data["color_id"]
        if "is_new_block_default" in data:
            if data["is_new_block_default"] is not True:
                raise ValueError("Select another category to change the default.")
            Category.objects.filter(user=user, is_new_block_default=True).update(
                is_new_block_default=False
            )
            category.is_new_block_default = True
        category.save()
        return category


def delete_category(user, category):
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        target = Category.objects.select_for_update().get(pk=category.pk, user=user)
        if target.is_sink:
            raise ValueError("The sink category cannot be deleted.")
        rows = ordered_categories(user)
        sink = sink_category(rows)
        TimeBlock.objects.filter(schedule__user=user, category=target.slug).update(
            category=sink.slug
        )
        templates = list(Template.objects.select_for_update().filter(user=user))
        changed = []
        for template in templates:
            blocks = [dict(block) for block in template.blocks]
            for block in blocks:
                if block.get("category") == target.slug:
                    block["category"] = sink.slug
            if blocks != template.blocks:
                template.blocks = blocks
                changed.append(template)
        if changed:
            Template.objects.bulk_update(changed, ["blocks"])
        TravelRule.objects.filter(user=user, category=target.slug).update(category=sink.slug)
        # Only reviews whose maps actually mention the deleted slug need
        # remapping — lock and load those, not the user's whole review history.
        reviews = list(
            DailyReview.objects.select_for_update()
            .filter(schedule__user=user)
            .filter(
                Q(planned_minutes_by_category__has_key=target.slug)
                | Q(completed_minutes_by_category__has_key=target.slug)
            )
        )
        for review in reviews:
            updates = {}
            for field in ("planned_minutes_by_category", "completed_minutes_by_category"):
                values = dict(getattr(review, field) or {})
                removed = values.pop(target.slug, 0)
                removed = (
                    removed
                    if isinstance(removed, (int, float)) and not isinstance(removed, bool)
                    else 0
                )
                current = values.get(sink.slug, 0)
                current = (
                    current
                    if isinstance(current, (int, float)) and not isinstance(current, bool)
                    else 0
                )
                values[sink.slug] = current + removed
                updates[field] = values
            review.planned_minutes_by_category = updates["planned_minutes_by_category"]
            review.completed_minutes_by_category = updates["completed_minutes_by_category"]
        if reviews:
            DailyReview.objects.bulk_update(
                reviews, ["planned_minutes_by_category", "completed_minutes_by_category"]
            )
        if target.is_new_block_default:
            Category.objects.filter(pk=target.pk).update(is_new_block_default=False)
            Category.objects.filter(pk=sink.pk).update(is_new_block_default=True)
        target.delete()


def swap_categories(user, first_id, second_id):
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        rows = list(
            Category.objects.select_for_update()
            .filter(user=user, pk__in=[first_id, second_id])
            .order_by("id")
        )
        if len(rows) != 2 or {row.pk for row in rows} != {first_id, second_id}:
            return None
        first, second = rows
        first.sort_order, second.sort_order = second.sort_order, first.sort_order
        Category.objects.bulk_update([first, second], ["sort_order"])
        return first, second

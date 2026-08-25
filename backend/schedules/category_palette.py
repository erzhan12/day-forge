"""Authoritative category swatches and first-read seed metadata."""

PALETTE = {
    "blue": "#3B82F6",
    "violet": "#8B5CF6",
    "emerald": "#059669",
    "gray": "#6B7280",
    "amber": "#D97706",
    "rose": "#E11D48",
    "cyan": "#0891B2",
    "indigo": "#6366F1",
}

SEED_CATEGORIES = (
    {
        "slug": "work",
        "label": "Work",
        "color_id": "blue",
        "sort_order": 0,
        "is_sink": False,
        "is_new_block_default": True,
    },
    {
        "slug": "personal",
        "label": "Personal",
        "color_id": "violet",
        "sort_order": 1,
        "is_sink": False,
        "is_new_block_default": False,
    },
    {
        "slug": "health",
        "label": "Health",
        "color_id": "emerald",
        "sort_order": 2,
        "is_sink": False,
        "is_new_block_default": False,
    },
    {
        "slug": "other",
        "label": "Other",
        "color_id": "gray",
        "sort_order": 3,
        "is_sink": True,
        "is_new_block_default": False,
    },
)

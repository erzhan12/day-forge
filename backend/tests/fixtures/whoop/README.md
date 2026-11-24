# WHOOP fixtures (feature 0107)

- `synthetic_2026-11-23.json` is synthetic data shaped after the plan's example output. Tests use only this file.
- `real_*.json` files hold one real day of WHOOP records for a local check of the date mapping. They are health data: they are gitignored and must never be committed. Shape: the keys of the synthetic file plus `"date": "YYYY-MM-DD"` and optionally `"expected_markdown"`. `test_whoop_sync_day.py::test_real_day_fixture_maps` runs only when one exists.

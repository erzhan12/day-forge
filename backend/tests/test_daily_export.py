"""Backend/frontend parity tests for the daily-export Markdown formatter.

Both ``schedules.daily_export.format_daily_export`` (Python) and
``frontend/src/utils/dailyExport.ts::formatDailyExport`` (TypeScript) must
render byte-identical Markdown from the same JSON fixtures in
``tests/fixtures/daily_export/``. See ``frontend/tests/dailyExport.test.ts``
for the TypeScript side of this contract.
"""

import json
from pathlib import Path

import pytest
from schedules.daily_export import format_daily_export

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "daily_export"


def _load(name: str) -> list[dict]:
    with open(FIXTURES_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


MARKDOWN_CASES = _load("markdown.json")
NOTES_CASES = _load("notes.json")


@pytest.mark.parametrize("case", MARKDOWN_CASES, ids=[c["name"] for c in MARKDOWN_CASES])
def test_markdown_fixture_matches_exactly(case):
    result = format_daily_export(date=case["date"], blocks=case["blocks"])
    assert result == case["expected"]
    # Exact UTF-8 bytes, not just str equality (catches silent BOM/newline drift).
    assert result.encode("utf-8") == case["expected"].encode("utf-8")


@pytest.mark.parametrize("case", NOTES_CASES, ids=[c["name"] for c in NOTES_CASES])
def test_notes_fixture_matches_exactly(case):
    kwargs = {"date": case["date"], "blocks": case["blocks"]}
    if case["note_present"]:
        kwargs["note"] = case["note"]
    result = format_daily_export(**kwargs)
    assert result == case["expected"]


def test_formatter_does_not_mutate_input_blocks():
    blocks = [
        {
            "title": "Later task",
            "start_time": "10:00",
            "end_time": "11:30",
            "category": "other",
            "is_completed": False,
            "sort_order": 1,
        },
        {
            "title": "Morning run",
            "start_time": "08:00",
            "end_time": "08:45",
            "category": "health",
            "is_completed": True,
        },
    ]
    snapshot = json.loads(json.dumps(blocks))
    format_daily_export(date="2026-08-29", blocks=blocks, note="  hi  ")
    assert blocks == snapshot

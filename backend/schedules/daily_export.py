"""Pure Python Markdown/JSON report formatter, byte-for-byte matching
``frontend/src/utils/dailyExport.ts::formatDailyExport`` (feature 0088).

Both implementations are exercised against the same JSON fixtures in
``tests/fixtures/daily_export/`` (see ``tests/test_daily_export.py`` and
``frontend/tests/dailyExport.test.ts``) so they cannot silently drift.

Note normalization must match ECMAScript's ``String.prototype.trim()`` and
``.replace(/\\s+/g, " ")`` exactly, not Python's ``str.strip()``: the two
whitespace definitions disagree on several code points (e.g. Python's
``str.isspace()`` treats U+0085 and U+001C-U+001F as whitespace; JavaScript's
``\\s`` does not, but does treat U+FEFF as whitespace).
"""

import re

# ECMAScript WhiteSpace + LineTerminator code points matched by `\s` in a JS
# regex and stripped by `.trim()`. Built from explicit code points (rather
# than literal characters) to keep this source file plain ASCII. Excludes
# U+0085 (NEL) and U+001C-U+001F (information separators): Python's
# `str.isspace()` treats those as whitespace, but JavaScript does not.
_JS_WHITESPACE_CODEPOINTS = (
    0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20,  # tab, LF, VT, FF, CR, space
    0xA0,  # no-break space
    0x1680,  # ogham space mark
    *range(0x2000, 0x200B),  # en quad .. hair space (U+2000-U+200A)
    0x2028, 0x2029,  # line separator, paragraph separator
    0x202F,  # narrow no-break space
    0x205F,  # medium mathematical space
    0x3000,  # ideographic space
    0xFEFF,  # zero-width no-break space / BOM
)
_JS_WHITESPACE = "".join(chr(code) for code in _JS_WHITESPACE_CODEPOINTS)
_JS_WHITESPACE_RUN_RE = re.compile("[" + re.escape(_JS_WHITESPACE) + "]+")


def _normalize_note(note: str | None) -> str:
    """Match JavaScript's ``(note ?? "").trim().replace(/\\s+/g, " ")``."""
    text = note or ""
    trimmed = text.strip(_JS_WHITESPACE)
    return _JS_WHITESPACE_RUN_RE.sub(" ", trimmed)


def _time_to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _format_duration_minutes(minutes: int) -> str:
    """Match ``formatDurationMinutes``: nonpositive input falls back to ``"0m"``."""
    if minutes <= 0:
        return "0m"
    if minutes < 60:
        return f"{minutes}m"
    hours, remainder = divmod(minutes, 60)
    return f"{hours}h" if remainder == 0 else f"{hours}h {remainder}m"


def format_block_duration(start_time: str, end_time: str) -> str:
    return _format_duration_minutes(_time_to_minutes(end_time) - _time_to_minutes(start_time))


def _sorted_blocks(blocks: list[dict]) -> list[dict]:
    """Stable sort by start minutes then ``sort_order`` (missing -> 0).

    Returns a new list; never mutates ``blocks`` or its dict elements.
    """
    return sorted(
        blocks,
        key=lambda block: (_time_to_minutes(block["start_time"]), block.get("sort_order") or 0),
    )


def _render_block_line(block: dict) -> str:
    checkbox = "[x]" if block["is_completed"] else "[ ]"
    category = "" if block["category"] == "other" else f" ({block['category']})"
    duration = format_block_duration(block["start_time"], block["end_time"])
    return f"- {checkbox} {block['start_time']} {block['title']}{category} {duration}"


def build_export_report(date: str, blocks: list[dict], note: str | None = None) -> dict:
    """Build the shared report dict backing both the Markdown and JSON responses.

    Never mutates ``blocks`` or its elements.
    """
    completed_count = sum(1 for block in blocks if block["is_completed"])
    ordered_blocks = _sorted_blocks(blocks)
    return {
        "date": date,
        "blocks": ordered_blocks,
        "completed_count": completed_count,
        "planned_count": len(blocks),
        "note": _normalize_note(note),
    }


def format_daily_export(date: str, blocks: list[dict], note: str | None = None) -> str:
    """Render the locked daily-export Markdown contract.

    Byte-identical to ``formatDailyExport`` in
    ``frontend/src/utils/dailyExport.ts`` for the same inputs. Never mutates
    ``blocks`` or its elements.
    """
    report = build_export_report(date, blocks, note)
    sections = [
        "## day-forge · " + report["date"],
        f"blocks: {report['completed_count']}/{report['planned_count']} done",
    ]
    if report["blocks"]:
        sections.append("\n".join(_render_block_line(block) for block in report["blocks"]))
    if report["note"]:
        sections.append(f"note: {report['note']}")
    return "\n\n".join(sections)

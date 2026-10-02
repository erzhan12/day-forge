"""Reject add actions that lost a user's relative placement constraint."""

from __future__ import annotations

import datetime
import re
from collections.abc import Sequence

_ADD_COMMAND_RE = re.compile(
    r"\b(?:add|schedule|place|put|create|insert|добав\w*|постав\w*|запланир\w*)\b",
    re.IGNORECASE | re.UNICODE,
)
_RELATION_RE = re.compile(r"\b(after|before|после|до)\b", re.IGNORECASE | re.UNICODE)
_GAP_RE = re.compile(
    r"\b(?:"
    r"(\d+)\s*[- ]?\s*(?:min(?:ute)?s?|мин(?:ут\w*)?)\s+"
    r"(?:gap|отступ\w*|промежут\w*|интервал\w*)"
    r"|(?:gap|отступ\w*|промежут\w*|интервал\w*|через)\s+"
    r"(?:of\s+)?(\d+)\s*(?:min(?:ute)?s?|мин(?:ут\w*)?)"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)
_CLOCK_REF_RE = re.compile(
    r"^\s*(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)\b",
    re.IGNORECASE,
)


def _relations_after_prefix(
    text: str, prefix_end: int, *, allow_leading: bool = False
) -> list[re.Match[str]]:
    return [
        match
        for match in _RELATION_RE.finditer(text, prefix_end)
        if allow_leading or text[prefix_end : match.start()].strip()
    ]


def _active_request_index(messages: list[dict]) -> int | None:
    """Find a relative add in the latest turn or its pending ask chain."""
    user_index = len(messages) - 1
    while user_index >= 0:
        text = messages[user_index]["content"]
        command = _ADD_COMMAND_RE.search(text)
        prefix_end = command.end() if command is not None else 0
        leading_answer = (
            command is None
            and user_index == len(messages) - 1
            and user_index >= 2
            and (
                messages[user_index - 1].get("is_ask") is True
                or messages[user_index - 1].get("is_error") is True
            )
        )
        if _relations_after_prefix(text, prefix_end, allow_leading=leading_answer):
            return user_index
        if command is not None:
            # A fresh add command supersedes a pending request.
            break
        if user_index < 2 or not (
            messages[user_index - 1].get("is_ask") is True
            or messages[user_index - 1].get("is_error") is True
        ):
            break
        user_index -= 2
    return None


def _minutes(value: datetime.time | str) -> int:
    if isinstance(value, str):
        hour, minute = map(int, value.split(":", 1))
        return hour * 60 + minute
    return value.hour * 60 + value.minute


def _title_in_tail(title: str, tail: str) -> bool:
    if re.search(r"(?<!\w)" + re.escape(title) + r"(?!\w)", tail, re.IGNORECASE):
        return True
    title_words = re.findall(r"\w+", title.casefold())
    tail_words = re.findall(r"\w+", tail.casefold())
    if not title_words:
        return False
    for start in range(len(tail_words) - len(title_words) + 1):
        candidate = tail_words[start : start + len(title_words)]
        if all(
            left == right
            or (
                min(len(left), len(right)) >= 3
                and abs(len(left) - len(right)) <= 2
                and (left.startswith(right) or right.startswith(left))
            )
            for left, right in zip(title_words, candidate)
        ):
            return True
    return False


def relative_add_guard_ask(
    messages: list[dict], actions: list[dict], blocks: Sequence
) -> str | None:
    """Ask for a concrete time when an add could violate after/before.

    The model sometimes reduces "add Vocal after Gym" to an untimed add.
    Ordinary auto-placement can then put Vocal *before* Gym. This guard
    applies only to a current relative add request, and checks explicit
    intervals too. It never infers a slot from natural-language text.
    """
    if not any(action.get("type") == "add" for action in actions):
        return None
    request_index = _active_request_index(messages)
    if request_index is None:
        return None
    request = messages[request_index]["content"]
    command = _ADD_COMMAND_RE.search(request)
    prefix_end = command.end() if command is not None else 0
    leading_answer = command is None and request_index == len(messages) - 1 and prefix_end == 0
    relations = _relations_after_prefix(request, prefix_end, allow_leading=leading_answer)
    if len(relations) != 1:
        return "What start time should the new block have?"

    relation = relations[0]
    direction = "after" if relation.group(1).casefold() in {"after", "после"} else "before"
    gap_match = _GAP_RE.search(request)
    required_gap = int(next(group for group in gap_match.groups() if group)) if gap_match else 0
    tail = request[relation.end() :]
    anchors = [block for block in blocks if _title_in_tail(block.title, tail)]
    if len(anchors) != 1:
        if _CLOCK_REF_RE.match(tail):
            return None
        return f"Which existing block should the new block be placed {direction}?"

    anchor = anchors[0]
    for action in actions:
        if action.get("type") != "add":
            continue
        if "start_time" not in action or "end_time" not in action:
            return f"What start time should the new block have {direction} {anchor.title}?"
        if direction == "after" and (
            _minutes(action["start_time"]) < _minutes(anchor.end_time) + required_gap
        ):
            return f"What start time should the new block have after {anchor.title}?"
        if direction == "before" and (
            _minutes(action["end_time"]) > _minutes(anchor.start_time) - required_gap
        ):
            return f"What start time should the new block have before {anchor.title}?"
    return None

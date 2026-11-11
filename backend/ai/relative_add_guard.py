"""Reject add actions that lost a user's relative placement constraint."""

from __future__ import annotations

import datetime
import re
from collections.abc import Sequence

_ADD_COMMAND_RE = re.compile(
    r"\b(?:add|schedule|place|put|create|insert|добав\w*|постав\w*|запланир\w*)\b",
    re.IGNORECASE | re.UNICODE,
)
_RELATION_RE = re.compile(
    r"\b(after|before|после|до|перед)\b", re.IGNORECASE | re.UNICODE
)
_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
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


def _questions(russian: bool, direction: str) -> dict[str, str]:
    """Guard questions in the language the user is writing in."""
    if russian:
        return {
            "time": "Во сколько начать новый блок?",
            "anchor": (
                "После какого блока поставить новый?"
                if direction == "after"
                else "Перед каким блоком поставить новый?"
            ),
            # "блока «…»" keeps the case right whatever the title is.
            "time_near": (
                "Во сколько начать новый блок после блока «{title}»?"
                if direction == "after"
                else "Во сколько начать новый блок перед блоком «{title}»?"
            ),
        }
    return {
        "time": "What start time should the new block have?",
        "anchor": f"Which existing block should the new block be placed {direction}?",
        "time_near": f"What start time should the new block have {direction} {{title}}?",
    }


_QUOTES = "\"'“”«»"


def _bare(text: str) -> str:
    """Text without surrounding whitespace, quotes or case, for exact matches."""
    return text.strip().strip(_QUOTES).strip().casefold()


def _answered_anchors(answer: str, candidates: Sequence) -> list:
    """Blocks named by the user's reply to a clarifying question."""
    named = [block for block in candidates if _title_in_tail(block.title, answer)]
    if len(named) > 1:
        exact = [block for block in named if _bare(block.title) == _bare(answer)]
        return exact or named
    return named


def _relations_after_prefix(
    text: str, prefix_end: int, *, allow_leading: bool = False,
    quoted_titles: re.Pattern[str] | None = None,
) -> list[re.Match[str]]:
    title_spans = list(quoted_titles.finditer(text)) if quoted_titles else []
    return [
        match
        for match in _RELATION_RE.finditer(text, prefix_end)
        if (allow_leading or text[prefix_end : match.start()].strip())
        and not any(span.start() <= match.start() < span.end() for span in title_spans)
    ]


def _command_outside_titles(
    text: str, title_re: re.Pattern[str] | None
) -> re.Match[str] | None:
    """First add verb that is not part of a block title ("Schedule planning")."""
    spans = list(title_re.finditer(text)) if title_re else []
    for match in _ADD_COMMAND_RE.finditer(text):
        if not any(span.start() <= match.start() < span.end() for span in spans):
            return match
    return None


def _active_request_index(
    messages: list[dict], quoted_titles: re.Pattern[str] | None = None,
    block_titles: frozenset[str] = frozenset(),
    title_re: re.Pattern[str] | None = None,
) -> int | None:
    """Find a relative add in the latest turn or its pending ask chain."""
    user_index = len(messages) - 1
    while user_index >= 0:
        text = messages[user_index]["content"]
        # A reply that is only a block title answers a question, even when the
        # title holds a command or relation word ("Schedule planning").
        if user_index > 0 and _bare(text) in block_titles:
            previous = messages[user_index - 1]
            if previous.get("is_ask") is not True and previous.get("is_error") is not True:
                break
            user_index -= 2
            continue
        command = _command_outside_titles(text, title_re)
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
        if _relations_after_prefix(
            text, prefix_end, allow_leading=leading_answer, quoted_titles=quoted_titles
        ):
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
        value = datetime.time.fromisoformat(value)
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
    # Only literal quoted block or proposed titles are opaque, not a whole command.
    titles = {block.title for block in blocks} | {
        action["title"] for action in actions if action.get("title")
    }
    quoted_names = [
        re.escape(opening + title + closing)
        for title in titles if _RELATION_RE.search(title)
        for opening, closing in [('"', '"'), ("'", "'"), ("“", "”"), ("«", "»")]
    ]
    quoted_titles = re.compile("|".join(quoted_names), re.IGNORECASE) if quoted_names else None
    command_titles = [
        re.escape(block.title) for block in blocks if _ADD_COMMAND_RE.search(block.title)
    ]
    title_re = (
        re.compile(r"(?<!\w)(?:" + "|".join(command_titles) + r")(?!\w)", re.IGNORECASE)
        if command_titles else None
    )
    request_index = _active_request_index(
        messages, quoted_titles, frozenset(_bare(block.title) for block in blocks), title_re
    )
    if request_index is None:
        return None
    request = messages[request_index]["content"]
    command = _ADD_COMMAND_RE.search(request)
    prefix_end = command.end() if command is not None else 0
    leading_answer = command is None and request_index == len(messages) - 1 and prefix_end == 0
    relations = _relations_after_prefix(
        request, prefix_end, allow_leading=leading_answer, quoted_titles=quoted_titles
    )
    # Answer in the language of the request or of the latest reply.
    russian = bool(
        _CYRILLIC_RE.search(request) or _CYRILLIC_RE.search(messages[-1]["content"])
    )
    if len(relations) != 1:
        return _questions(russian, "after")["time"]

    relation = relations[0]
    direction = "after" if relation.group(1).casefold() in {"after", "после"} else "before"
    gap_match = _GAP_RE.search(request)
    required_gap = int(next(group for group in gap_match.groups() if group)) if gap_match else 0
    tail = request[relation.end() :]
    anchors = [block for block in blocks if _title_in_tail(block.title, tail)]
    if len(anchors) != 1 and not _CLOCK_REF_RE.match(tail):
        # The user may have answered "which block?" by naming it. Without
        # this the same question repeats forever. The newest reply that names
        # any block decides: one block resolves the anchor, several stay
        # ambiguous candidates (a correction never falls back to an older
        # answer). Replies naming no block, such as a clock answer, are skipped.
        replies = (
            message["content"]
            for message in reversed(messages[request_index + 1 :])
            if message.get("role") == "user"
        )
        for reply in replies:
            answered = _answered_anchors(reply, blocks)
            if answered:
                anchors = answered
                break
    questions = _questions(russian, direction)
    if len(anchors) != 1:
        if _CLOCK_REF_RE.match(tail):
            return None
        latest_clock = _CLOCK_REF_RE.match(messages[-1]["content"])
        if (
            not anchors and request_index < len(messages) - 1
            and latest_clock and ":" in latest_clock.group()
            and all("start_time" in action and "end_time" in action
                    for action in actions if action.get("type") == "add")
        ):
            # A concrete follow-up resolves an unbound reference, including
            # procedural "before adding it". Existing anchors still constrain it.
            return None
        return questions["anchor"]

    anchor = anchors[0]
    add_actions = [action for action in actions if action.get("type") == "add"]
    named_before_relation = [
        action
        for action in add_actions
        if _title_in_tail(action.get("title", ""), request[: relation.start()])
    ]
    # A single named add owns the relative phrase; sibling adds may use
    # ordinary auto-placement. Ambiguous wording stays conservative.
    checked_actions = named_before_relation if len(named_before_relation) == 1 else add_actions
    for action in checked_actions:
        if "start_time" not in action or "end_time" not in action:
            return questions["time_near"].format(title=anchor.title)
        if direction == "after" and (
            _minutes(action["start_time"]) < _minutes(anchor.end_time) + required_gap
        ):
            return questions["time_near"].format(title=anchor.title)
        if direction == "before" and (
            _minutes(action["end_time"]) > _minutes(anchor.start_time) - required_gap
        ):
            return questions["time_near"].format(title=anchor.title)
    return None

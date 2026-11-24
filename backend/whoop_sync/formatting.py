"""Render a ``WhoopDay`` as the Markdown morning summary (feature 0107).

Example (docs/features/0107_PLAN.md)::

    ## whoop · 2026-11-23
    recovery: 73% · RHR 56 · HRV 31.1 · SpO2 95%
    sleep: 21:49–06:57 · asleep 7:43 / need 8:16 · deep 1:16 · REM 1:18 · eff 97% · disturbances 9
    strain (prev day): 16.4 · workouts: HIIT 15.2, walk 4.6

Partial states render explicitly: ``none recorded``, ``pending``
(``PENDING_SCORE``) and ``unscorable`` (``UNSCORABLE``). A missing metric is
left out rather than guessed.
"""

import datetime
import math
import re

from whoop_sync.day import WhoopDay, parse_timestamp

SEP = " · "
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")
_NOT_SCORED = {"PENDING_SCORE": "pending", "UNSCORABLE": "unscorable"}


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _round(value: float) -> int:
    return math.floor(value + 0.5)


def _duration(milli: float) -> str:
    minutes = _round(milli / 60000)
    sign = "-" if minutes < 0 else ""
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours}:{rest:02d}"


def _score(record: dict) -> tuple[dict | None, str | None]:
    """``(score, None)`` when scored, else ``(None, partial-state word)``."""
    word = _NOT_SCORED.get(record.get("score_state"))
    if word is not None:
        return None, word
    score = record.get("score")
    if not isinstance(score, dict):
        return None, "pending"
    return score, None


def _record_zone(record: dict, fallback: datetime.tzinfo) -> datetime.tzinfo:
    match = _OFFSET_RE.match(str(record.get("timezone_offset") or ""))
    if not match:
        return fallback
    sign, hours, minutes = match.groups()
    delta = datetime.timedelta(hours=int(hours), minutes=int(minutes))
    return datetime.timezone(-delta if sign == "-" else delta)


def _recovery_line(recovery: dict | None) -> str:
    if recovery is None:
        return "recovery: none recorded"
    score, word = _score(recovery)
    if word is not None:
        return f"recovery: {word}"
    parts = []
    if (value := _number(score.get("recovery_score"))) is not None:
        parts.append(f"{_round(value)}%")
    if (value := _number(score.get("resting_heart_rate"))) is not None:
        parts.append(f"RHR {_round(value)}")
    if (value := _number(score.get("hrv_rmssd_milli"))) is not None:
        parts.append(f"HRV {value:.1f}")
    if (value := _number(score.get("spo2_percentage"))) is not None:
        parts.append(f"SpO2 {_round(value)}%")
    return "recovery: " + (SEP.join(parts) if parts else "pending")


def _sleep_line(sleep: dict | None, fallback_tz: datetime.tzinfo) -> str:
    if sleep is None:
        return "sleep: none recorded"
    zone = _record_zone(sleep, fallback_tz)
    bed = parse_timestamp(sleep.get("start")).astimezone(zone)
    wake = parse_timestamp(sleep.get("end")).astimezone(zone)
    parts = [f"{bed:%H:%M}–{wake:%H:%M}"]
    score, word = _score(sleep)
    if word is not None:
        return "sleep: " + SEP.join([*parts, word])

    stages = score.get("stage_summary") if isinstance(score.get("stage_summary"), dict) else {}
    light = _number(stages.get("total_light_sleep_time_milli"))
    deep = _number(stages.get("total_slow_wave_sleep_time_milli"))
    rem = _number(stages.get("total_rem_sleep_time_milli"))
    needed = score.get("sleep_needed") if isinstance(score.get("sleep_needed"), dict) else {}
    need_parts = [v for v in (_number(x) for x in needed.values()) if v is not None]

    if None not in (light, deep, rem):
        asleep = f"asleep {_duration(light + deep + rem)}"
        if need_parts:
            asleep += f" / need {_duration(sum(need_parts))}"
        parts.append(asleep)
    if deep is not None:
        parts.append(f"deep {_duration(deep)}")
    if rem is not None:
        parts.append(f"REM {_duration(rem)}")
    if (value := _number(score.get("sleep_efficiency_percentage"))) is not None:
        parts.append(f"eff {_round(value)}%")
    if (value := _number(stages.get("disturbance_count"))) is not None:
        parts.append(f"disturbances {_round(value)}")
    return "sleep: " + SEP.join(parts)


def _workout(workout: dict) -> str:
    name = str(workout.get("sport_name") or "workout")
    score, _ = _score(workout)
    strain = _number(score.get("strain")) if score is not None else None
    return name if strain is None else f"{name} {strain:.1f}"


def _strain_line(cycle: dict | None, workouts: list[dict]) -> str:
    if cycle is None:
        strain = "none recorded"
    else:
        score, word = _score(cycle)
        value = _number(score.get("strain")) if score is not None else None
        strain = word or ("pending" if value is None else f"{value:.1f}")
    listed = ", ".join(_workout(w) for w in workouts) if workouts else "none"
    return f"strain (prev day): {strain}{SEP}workouts: {listed}"


def format_whoop_day(day: WhoopDay) -> str:
    lines = [
        f"## whoop · {day.date.isoformat()}",
        _recovery_line(day.recovery),
        _sleep_line(day.sleep, day.tz),
        _strain_line(day.previous_cycle, day.workouts),
    ]
    return "\n".join(lines) + "\n"

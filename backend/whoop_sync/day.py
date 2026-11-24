"""Map a calendar date to the WHOOP records that describe it (feature 0107).

For date D in the user's zone:

1. Sleep: records from D−1 12:00 to D 12:00 local; naps dropped; the longest
   remaining record wins.
2. Recovery: WHOOP starts a cycle at sleep onset, so ``sleep.cycle_id`` is
   D's cycle and its recovery is D's recovery.
3. Previous day's strain: the cycle that ended at the sleep's start.
4. Workouts: those that started inside that previous cycle, oldest first.

Records stay in memory; nothing is stored, cached or logged.
"""

import dataclasses
import datetime

from whoop_sync import service

NOON = datetime.time(12, 0)


@dataclasses.dataclass(frozen=True)
class WhoopDay:
    date: datetime.date
    sleep: dict | None
    recovery: dict | None
    previous_cycle: dict | None
    workouts: list[dict]
    # The user's zone; bed/wake fall back to it when a record lacks an offset.
    tz: datetime.tzinfo = datetime.UTC


def parse_timestamp(value) -> datetime.datetime:
    """Parse a WHOOP ISO-8601 timestamp into an aware datetime."""
    if not isinstance(value, str):
        raise service.WhoopProviderError("WHOOP record has a malformed timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        raise service.WhoopProviderError("WHOOP record has a malformed timestamp") from None
    if parsed.tzinfo is None:
        raise service.WhoopProviderError("WHOOP record has a malformed timestamp")
    return parsed


def _cycle_id(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise service.WhoopProviderError("WHOOP record has a malformed cycle id")
    return value


def _main_sleep(records: list[dict]) -> dict | None:
    best, best_length = None, None
    for record in records:
        nap = record.get("nap")
        if not isinstance(nap, bool):
            raise service.WhoopProviderError("WHOOP sleep has a malformed nap flag")
        length = parse_timestamp(record.get("end")) - parse_timestamp(record.get("start"))
        _cycle_id(record.get("cycle_id"))
        if nap:
            continue
        if best_length is None or length > best_length:
            best, best_length = record, length
    return best


def _previous_cycle(cycles: list[dict], sleep: dict, sleep_start) -> dict | None:
    """Newest cycle other than the sleep's own that ended by the sleep start."""
    current = sleep["cycle_id"]
    for cycle in cycles:
        if cycle.get("id") == current or cycle.get("end") is None:
            continue
        parse_timestamp(cycle.get("start"))
        if parse_timestamp(cycle["end"]) <= sleep_start:
            return cycle
    return None


def load_day(account, day: datetime.date, tz: datetime.tzinfo) -> WhoopDay:
    window_start = datetime.datetime.combine(day - datetime.timedelta(days=1), NOON, tzinfo=tz)
    window_end = datetime.datetime.combine(day, NOON, tzinfo=tz)
    sleep = _main_sleep(service.fetch_sleeps(account, window_start, window_end))
    if sleep is None:
        return WhoopDay(
            date=day, sleep=None, recovery=None, previous_cycle=None, workouts=[], tz=tz
        )

    sleep_start = parse_timestamp(sleep["start"])
    recovery = service.fetch_recovery(account, sleep["cycle_id"])
    previous = _previous_cycle(
        service.fetch_cycles_ending_by(account, sleep_start, limit=2), sleep, sleep_start
    )
    workouts: list[dict] = []
    if previous is not None:
        cycle_start = parse_timestamp(previous["start"])
        cycle_end = parse_timestamp(previous["end"])
        started_inside = [
            (parse_timestamp(w.get("start")), w)
            for w in service.fetch_workouts(account, cycle_start, cycle_end)
        ]
        workouts = [
            w
            for start, w in sorted(started_inside, key=lambda item: item[0])
            if cycle_start <= start < cycle_end
        ]
    return WhoopDay(
        date=day,
        sleep=sleep,
        recovery=recovery,
        previous_cycle=previous,
        workouts=workouts,
        tz=tz,
    )

"""
Planner – workstream B.

Pure functions: scores candidate time slots, picks the winner.
All scheduling logic is deterministic code; Gemma is not involved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from touchgrass.nlu import AvailabilityParse, TimeSlot
from touchgrass.weather import DailyForecast

logger = logging.getLogger(__name__)

# Default match window when the player only said a weekday
DEFAULT_START = time(10, 0)
DEFAULT_END = time(22, 0)
MATCH_DURATION = timedelta(hours=1, minutes=30)


@dataclass
class CandidateSlot:
    date: date
    start: time
    end: time
    player_count: int = 0
    weather_score: float = 0.0
    total_score: float = 0.0
    players: list[str] = field(default_factory=list)


def _weekday_to_date(weekday: str, reference: date) -> date:
    """Return the next occurrence of *weekday* on or after *reference*."""
    target = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(
        weekday.lower()
    )
    delta = (target - reference.weekday()) % 7
    return reference + timedelta(days=delta)


def _slot_to_dates(slot: TimeSlot, reference: date) -> list[date]:
    """Expand a TimeSlot to concrete date(s) within the next 7 days."""
    if slot.date:
        try:
            d = date.fromisoformat(slot.date)
            if reference <= d <= reference + timedelta(days=7):
                return [d]
        except ValueError:
            pass
        return []
    if slot.weekday:
        d = _weekday_to_date(slot.weekday, reference)
        if d <= reference + timedelta(days=7):
            return [d]
    return []


def _slot_time(slot: TimeSlot) -> tuple[time, time]:
    """Return (start, end) for a slot, falling back to defaults."""
    try:
        start = time.fromisoformat(slot.start) if slot.start else DEFAULT_START
    except ValueError:
        start = DEFAULT_START
    try:
        end = time.fromisoformat(slot.end) if slot.end else DEFAULT_END
    except ValueError:
        end = DEFAULT_END
    if end <= start:
        end = (datetime.combine(date.today(), start) + MATCH_DURATION).time()
    return start, end


def build_candidate_slots(
    replies: dict[str, AvailabilityParse],  # player_name → parse
    reference_date: date,
) -> list[CandidateSlot]:
    """
    Build candidate slots by collecting every (date, start-hour) window
    any player mentioned, then counting how many players *overlap* with
    each window.

    Two intervals overlap when they intersect: a player available
    09:00–12:00 and one available 10:00–12:00 both count for the
    10:00-start window.
    """
    # Step 1: collect all individual player intervals per date
    player_intervals: dict[date, list[tuple[str, time, time]]] = {}
    for player, parse in replies.items():
        if not parse.can_play:
            continue
        for slot in parse.slots:
            for d in _slot_to_dates(slot, reference_date):
                start, end = _slot_time(slot)
                player_intervals.setdefault(d, []).append((player, start, end))

    # Step 2: for each mentioned start-hour on each date, build a candidate
    # window and count every player whose interval overlaps it.
    window_map: dict[tuple[date, time, time], CandidateSlot] = {}

    for d, intervals in player_intervals.items():
        start_hours: set[time] = {time(s.hour, s.minute) for _, s, _ in intervals}

        for start in start_hours:
            end_dt = datetime.combine(d, start) + MATCH_DURATION
            end = end_dt.time()
            key = (d, start, end)
            if key not in window_map:
                window_map[key] = CandidateSlot(date=d, start=start, end=end)
            cs = window_map[key]

            seen: set[str] = set(cs.players)
            for player, p_start, p_end in intervals:
                if player not in seen and p_start < end and p_end > start:
                    cs.player_count += 1
                    cs.players.append(player)
                    seen.add(player)

    return list(window_map.values())


def score_slots(
    candidates: list[CandidateSlot],
    forecast: dict[date, DailyForecast],
) -> list[CandidateSlot]:
    """
    Score each candidate: total_score = player_count × weather_score.
    Filters out slots that end after sunset.
    Returns list sorted by total_score descending.
    """
    scored: list[CandidateSlot] = []
    for cs in candidates:
        df = forecast.get(cs.date)
        if df is None:
            continue  # no forecast → skip
        # Must finish before sunset
        sunset = df.sunset
        # Give a 15-minute buffer before sunset
        from datetime import datetime as _dt
        sunset_limit = (_dt.combine(cs.date, sunset) - timedelta(minutes=15)).time()
        if cs.end > sunset_limit:
            logger.debug("Slot %s %s-%s rejected: ends after sunset %s", cs.date, cs.start, cs.end, sunset)
            continue

        ws = df.weather_score(cs.start, cs.end)
        cs.weather_score = ws
        cs.total_score = cs.player_count * ws
        scored.append(cs)

    return sorted(scored, key=lambda s: s.total_score, reverse=True)


def pick_best_slot(
    replies: dict[str, AvailabilityParse],
    forecast: dict[date, DailyForecast],
    reference_date: date | None = None,
) -> CandidateSlot | None:
    """End-to-end: parse replies → build candidates → score → return winner."""
    if reference_date is None:
        from datetime import date as _date
        reference_date = _date.today()

    candidates = build_candidate_slots(replies, reference_date)
    if not candidates:
        return None
    scored = score_slots(candidates, forecast)
    return scored[0] if scored else None

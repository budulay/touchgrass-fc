"""Tests for planner.py – pure functions, no network."""
from __future__ import annotations

from datetime import date, time, timedelta, datetime, timezone

import pytest

from touchgrass.nlu import AvailabilityParse, TimeSlot
from touchgrass.planner import (
    build_candidate_slots,
    score_slots,
    pick_best_slot,
    CandidateSlot,
    _weekday_to_date,
    _slot_time,
)
from touchgrass.weather import DailyForecast, HourlyWeather


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_forecast(
    d: date,
    sunset_hour: int = 19,
    precip: float = 0.0,
    wind: float = 5.0,
) -> DailyForecast:
    tz = timezone.utc
    hours = [
        HourlyWeather(datetime(d.year, d.month, d.day, h, 0, tzinfo=tz), precip, wind)
        for h in range(6, 22)
    ]
    return DailyForecast(d, time(sunset_hour, 45), hours)


def _saturday() -> date:
    """Return the next Saturday on or after today."""
    today = date(2026, 10, 10)  # fixed reference for tests
    days = (5 - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


def _parse(can_play: bool, weekday: str, start: str = "10:00", end: str = "12:00") -> AvailabilityParse:
    slots = [TimeSlot(weekday=weekday, start=start, end=end)] if can_play else []
    return AvailabilityParse(can_play=can_play, slots=slots, conditions=[], language="en")


# ── _weekday_to_date ──────────────────────────────────────────────────────────

def test_weekday_to_date_same_day():
    ref = date(2026, 10, 10)  # Saturday
    d = _weekday_to_date("saturday", ref)
    assert d == ref


def test_weekday_to_date_next_week():
    ref = date(2026, 10, 10)  # Saturday
    d = _weekday_to_date("friday", ref)
    assert d == date(2026, 10, 16)


def test_weekday_to_date_sunday():
    ref = date(2026, 10, 10)  # Saturday
    d = _weekday_to_date("sunday", ref)
    assert d == date(2026, 10, 11)


# ── _slot_time ────────────────────────────────────────────────────────────────

def test_slot_time_explicit():
    slot = TimeSlot(weekday="saturday", start="09:00", end="11:00")
    start, end = _slot_time(slot)
    assert start == time(9, 0)
    assert end == time(11, 0)


def test_slot_time_defaults():
    slot = TimeSlot(weekday="saturday")
    start, end = _slot_time(slot)
    assert start == time(10, 0)
    assert end == time(22, 0)


# ── build_candidate_slots ─────────────────────────────────────────────────────

def test_build_slots_counts_players():
    ref = date(2026, 10, 10)
    replies = {
        "Alice": _parse(True, "saturday", "10:00", "12:00"),
        "Bob":   _parse(True, "saturday", "10:00", "12:00"),
        "Carol": _parse(False, "saturday"),
    }
    candidates = build_candidate_slots(replies, ref)
    assert len(candidates) == 1
    assert candidates[0].player_count == 2
    assert set(candidates[0].players) == {"Alice", "Bob"}


def test_build_slots_unavailable_ignored():
    ref = date(2026, 10, 10)
    replies = {"Dave": _parse(False, "sunday")}
    candidates = build_candidate_slots(replies, ref)
    assert candidates == []


def test_build_slots_multiple_days():
    ref = date(2026, 10, 10)
    parse = AvailabilityParse(
        can_play=True,
        slots=[
            TimeSlot(weekday="saturday", start="10:00", end="12:00"),
            TimeSlot(weekday="sunday", start="10:00", end="12:00"),
        ],
        conditions=[],
        language="en",
    )
    candidates = build_candidate_slots({"Eve": parse}, ref)
    assert len(candidates) == 2


# ── score_slots ───────────────────────────────────────────────────────────────

def test_score_filters_after_sunset():
    ref = date(2026, 10, 10)
    # Slot ends after sunset
    cs = CandidateSlot(date=ref, start=time(19, 0), end=time(21, 0), player_count=3, players=["a", "b", "c"])
    df = _make_forecast(ref, sunset_hour=19)  # sunset 19:45
    # slot ends at 21:00 → after sunset
    scored = score_slots([cs], {ref: df})
    assert scored == []


def test_score_keeps_before_sunset():
    ref = date(2026, 10, 10)
    cs = CandidateSlot(date=ref, start=time(10, 0), end=time(12, 0), player_count=2, players=["a", "b"])
    df = _make_forecast(ref, sunset_hour=19)
    scored = score_slots([cs], {ref: df})
    assert len(scored) == 1
    assert scored[0].total_score > 0


def test_score_ranks_by_total():
    ref = date(2026, 10, 10)
    tomorrow = ref + timedelta(days=1)
    cs1 = CandidateSlot(date=ref,      start=time(10, 0), end=time(12, 0), player_count=3, players=["a","b","c"])
    cs2 = CandidateSlot(date=tomorrow, start=time(10, 0), end=time(12, 0), player_count=1, players=["d"])
    forecast = {
        ref:      _make_forecast(ref,      precip=0),
        tomorrow: _make_forecast(tomorrow, precip=0),
    }
    scored = score_slots([cs1, cs2], forecast)
    assert scored[0].player_count == 3


def test_score_penalises_rain():
    ref = date(2026, 10, 10)
    cs_rain  = CandidateSlot(date=ref, start=time(10,0), end=time(12,0), player_count=2, players=["a","b"])
    cs_clear = CandidateSlot(date=ref, start=time(14,0), end=time(16,0), player_count=2, players=["c","d"])
    df_rain  = _make_forecast(ref, precip=90, wind=5)
    df_clear = _make_forecast(ref, precip=5,  wind=5)
    # same date, different times → use same DailyForecast but different hours
    # Build a forecast with mixed hours
    tz = timezone.utc
    hours = []
    for h in range(6, 22):
        precip = 90.0 if h < 13 else 5.0
        hours.append(HourlyWeather(datetime(ref.year, ref.month, ref.day, h, 0, tzinfo=tz), precip, 5.0))
    df_mixed = DailyForecast(ref, time(19, 45), hours)
    scored = score_slots([cs_rain, cs_clear], {ref: df_mixed})
    scores = {s.start.hour: s.weather_score for s in scored}
    assert scores[14] > scores[10]


# ── pick_best_slot ────────────────────────────────────────────────────────────

def test_pick_best_slot_end_to_end():
    ref = date(2026, 10, 10)
    replies = {
        "Alice": _parse(True, "saturday", "10:00", "12:00"),
        "Bob":   _parse(True, "saturday", "10:00", "12:00"),
        "Carol": _parse(True, "saturday", "10:00", "12:00"),
    }
    sat = _weekday_to_date("saturday", ref)
    forecast = {sat: _make_forecast(sat, precip=5)}
    best = pick_best_slot(replies, forecast, ref)
    assert best is not None
    assert best.player_count == 3


def test_pick_best_slot_no_replies():
    ref = date(2026, 10, 10)
    best = pick_best_slot({}, {}, ref)
    assert best is None


def test_pick_best_slot_all_unavailable():
    ref = date(2026, 10, 10)
    replies = {"Dave": _parse(False, "saturday")}
    best = pick_best_slot(replies, {}, ref)
    assert best is None

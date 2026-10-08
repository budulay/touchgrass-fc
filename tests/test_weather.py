"""Tests for weather.py using a recorded API fixture (no network)."""
from __future__ import annotations

import json
from datetime import date, time

import pytest

from touchgrass.weather import _parse_response, DailyForecast

# Minimal recorded Open-Meteo response fixture
FIXTURE = {
    "utc_offset_seconds": 10800,  # UTC+3
    "hourly": {
        "time": [
            "2026-10-10T00:00", "2026-10-10T01:00", "2026-10-10T06:00",
            "2026-10-10T09:00", "2026-10-10T12:00", "2026-10-10T18:00",
            "2026-10-11T06:00", "2026-10-11T12:00", "2026-10-11T18:00",
        ],
        "precipitation_probability": [0, 0, 10, 20, 30, 80, 5, 5, 10],
        "wind_speed_10m":            [3, 3,  5, 10, 15, 30, 4, 6,  8],
    },
    "daily": {
        "time":   ["2026-10-10", "2026-10-11"],
        "sunset": ["2026-10-10T18:45", "2026-10-11T18:43"],
    },
}


def test_parse_response_returns_two_days():
    result = _parse_response(FIXTURE)
    assert date(2026, 10, 10) in result
    assert date(2026, 10, 11) in result


def test_parse_response_sunset():
    result = _parse_response(FIXTURE)
    assert result[date(2026, 10, 10)].sunset == time(18, 45)


def test_weather_score_rainy_evening():
    result = _parse_response(FIXTURE)
    df = result[date(2026, 10, 10)]
    score_evening = df.weather_score(time(18, 0), time(20, 0))
    score_morning = df.weather_score(time(6, 0), time(12, 0))
    assert score_evening < score_morning, "Rainy evening should score lower"


def test_weather_score_empty_window():
    result = _parse_response(FIXTURE)
    df = result[date(2026, 10, 10)]
    # 02:00–05:00 has no hours → neutral 0.5
    score = df.weather_score(time(2, 0), time(5, 0))
    assert score == 0.5


def test_weather_score_range():
    result = _parse_response(FIXTURE)
    for df in result.values():
        for h_start in range(6, 20):
            s = df.weather_score(time(h_start, 0), time(h_start + 1, 0))
            assert 0.0 <= s <= 1.0

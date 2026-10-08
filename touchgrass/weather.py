"""
Weather module – workstream B.

Fetches hourly precipitation probability and wind speed + daily sunset
from Open-Meteo (free, no key). All network I/O is isolated here so
planner.py can be tested on recorded fixtures.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx

from touchgrass import config

logger = logging.getLogger(__name__)

# ── Data types ────────────────────────────────────────────────────────────────


class HourlyWeather:
    """Lightweight weather record for a single hour."""

    __slots__ = ("dt", "precip_prob", "wind_kmh")

    def __init__(self, dt: datetime, precip_prob: float, wind_kmh: float) -> None:
        self.dt = dt
        self.precip_prob = precip_prob  # 0-100
        self.wind_kmh = wind_kmh


class DailyForecast:
    """Sunset time and hourly records for one day."""

    __slots__ = ("date", "sunset", "hours")

    def __init__(self, date: date, sunset: time, hours: list[HourlyWeather]) -> None:
        self.date = date
        self.sunset = sunset
        self.hours = hours

    def weather_score(self, start: time, end: time) -> float:
        """
        Return a 0-1 weather quality score for a time window.
        Penalises precipitation probability and high wind.
        """
        window = [h for h in self.hours if start <= h.dt.time() < end]
        if not window:
            return 0.5  # unknown → neutral
        avg_precip = sum(h.precip_prob for h in window) / len(window)
        avg_wind = sum(h.wind_kmh for h in window) / len(window)
        # rain penalty: 0 → score 1.0; 100 → score 0.0
        rain_score = 1.0 - avg_precip / 100.0
        # wind penalty: calm=1, gale(60+)=0
        wind_score = max(0.0, 1.0 - avg_wind / 60.0)
        return round(0.6 * rain_score + 0.4 * wind_score, 4)


# ── API call ──────────────────────────────────────────────────────────────────


async def fetch_forecast(
    lat: float,
    lon: float,
    days: int = 7,
    *,
    base_url: str = config.OPEN_METEO_URL,
    client: httpx.AsyncClient | None = None,
) -> dict[date, DailyForecast]:
    """
    Fetch next *days* days of forecast from Open-Meteo.
    Returns a mapping of date → DailyForecast.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation_probability,wind_speed_10m",
        "daily": "sunset",
        "timezone": "auto",
        "forecast_days": days,
    }

    async def _do_request(c: httpx.AsyncClient) -> Any:
        resp = await c.get(base_url, params=params, timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    if client:
        data = await _do_request(client)
    else:
        async with httpx.AsyncClient() as c:
            data = await _do_request(c)

    return _parse_response(data)


def _parse_response(data: dict[str, Any]) -> dict[date, DailyForecast]:
    hourly = data["hourly"]
    times: list[str] = hourly["time"]
    precips: list[float | None] = hourly["precipitation_probability"]
    winds: list[float | None] = hourly["wind_speed_10m"]

    daily_raw = data["daily"]
    sunset_times: list[str] = daily_raw["sunset"]
    daily_dates: list[str] = daily_raw["time"]

    tz_offset_s: int = data.get("utc_offset_seconds", 0)
    tz = timezone(timedelta(seconds=tz_offset_s))

    # Build per-hour records grouped by date
    hours_by_date: dict[date, list[HourlyWeather]] = {}
    for t_str, p, w in zip(times, precips, winds):
        dt = datetime.fromisoformat(t_str).replace(tzinfo=tz)
        d = dt.date()
        hours_by_date.setdefault(d, []).append(
            HourlyWeather(dt, float(p or 0), float(w or 0))
        )

    result: dict[date, DailyForecast] = {}
    for d_str, s_str in zip(daily_dates, sunset_times):
        d = date.fromisoformat(d_str)
        sunset_dt = datetime.fromisoformat(s_str)
        sunset_t = sunset_dt.time()
        result[d] = DailyForecast(d, sunset_t, hours_by_date.get(d, []))

    return result

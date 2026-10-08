"""
Pitches module – workstream B.

Finds nearest football pitches via Overpass API.
Uses Nominatim for city → coordinates geocoding.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from touchgrass import config

logger = logging.getLogger(__name__)


@dataclass
class Pitch:
    name: str
    lat: float
    lon: float
    osm_id: int


# ── Geocoding ──────────────────────────────────────────────────────────────────

_nominatim_lock = asyncio.Lock()
_last_nominatim_call: float = 0.0


async def geocode_city(city: str) -> tuple[float, float] | None:
    """Return (lat, lon) for *city* using Nominatim. Rate-limited to 1 req/s."""
    global _last_nominatim_call
    import time

    async with _nominatim_lock:
        now = time.monotonic()
        wait = 1.0 - (now - _last_nominatim_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_nominatim_call = time.monotonic()

        params = {
            "q": city,
            "format": "jsonv2",
            "limit": 1,
        }
        headers = {"User-Agent": config.NOMINATIM_UA}
        async with httpx.AsyncClient() as client:
            resp = await client.get(config.NOMINATIM_URL, params=params, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()

    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


# ── Overpass pitch search ─────────────────────────────────────────────────────

_OVERPASS_QUERY = """
[out:json][timeout:15];
(
  node["leisure"="pitch"]["sport"="soccer"](around:{radius},{lat},{lon});
  way["leisure"="pitch"]["sport"="soccer"](around:{radius},{lat},{lon});
  relation["leisure"="pitch"]["sport"="soccer"](around:{radius},{lat},{lon});
);
out center 10;
"""


async def find_nearest_pitch(
    lat: float,
    lon: float,
    radius_m: int = 5000,
    *,
    overpass_url: str = config.OVERPASS_URL,
    client: httpx.AsyncClient | None = None,
) -> Pitch | None:
    """Return the nearest football pitch within *radius_m* metres, or None."""
    query = _OVERPASS_QUERY.format(radius=radius_m, lat=lat, lon=lon)

    async def _req(c: httpx.AsyncClient) -> list[dict]:
        resp = await c.post(overpass_url, data={"data": query}, timeout=20.0)
        resp.raise_for_status()
        return resp.json()["elements"]

    if client:
        elements = await _req(client)
    else:
        async with httpx.AsyncClient() as c:
            elements = await _req(c)

    if not elements:
        return None

    def _coords(el: dict) -> tuple[float, float]:
        if "center" in el:
            return el["center"]["lat"], el["center"]["lon"]
        return el["lat"], el["lon"]

    def _dist(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
        # Haversine-lite (good enough for ~5 km)
        import math
        dlat = math.radians(b_lat - a_lat)
        dlon = math.radians(b_lon - a_lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(
            math.radians(b_lat)
        ) * math.sin(dlon / 2) ** 2
        return 6371000 * 2 * math.asin(math.sqrt(a))

    closest = min(elements, key=lambda el: _dist(lat, lon, *_coords(el)))
    p_lat, p_lon = _coords(closest)
    name = closest.get("tags", {}).get("name", "Local football pitch")
    return Pitch(name=name, lat=p_lat, lon=p_lon, osm_id=closest["id"])

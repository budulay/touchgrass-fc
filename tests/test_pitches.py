"""Tests for pitches.py using respx-mocked HTTP calls."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from touchgrass.pitches import find_nearest_pitch, Pitch

OVERPASS_RESPONSE = {
    "elements": [
        {
            "type": "way",
            "id": 123456,
            "center": {"lat": 50.451, "lon": 30.523},
            "tags": {"name": "Spartak Training Ground", "sport": "soccer", "leisure": "pitch"},
        },
        {
            "type": "node",
            "id": 789,
            "lat": 50.480,
            "lon": 30.550,
            "tags": {"sport": "soccer", "leisure": "pitch"},
        },
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_find_nearest_pitch_returns_closest():
    respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(200, json=OVERPASS_RESPONSE)
    )
    pitch = await find_nearest_pitch(50.450, 30.522, overpass_url="https://overpass-api.de/api/interpreter")
    assert pitch is not None
    assert pitch.name == "Spartak Training Ground"
    assert abs(pitch.lat - 50.451) < 0.01


@pytest.mark.asyncio
@respx.mock
async def test_find_nearest_pitch_no_results():
    respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    pitch = await find_nearest_pitch(50.0, 30.0, overpass_url="https://overpass-api.de/api/interpreter")
    assert pitch is None


@pytest.mark.asyncio
@respx.mock
async def test_find_nearest_pitch_unnamed():
    respx.post("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(200, json={
            "elements": [{"type": "node", "id": 1, "lat": 51.0, "lon": 31.0, "tags": {}}]
        })
    )
    pitch = await find_nearest_pitch(51.0, 31.0, overpass_url="https://overpass-api.de/api/interpreter")
    assert pitch is not None
    assert pitch.name == "Local football pitch"

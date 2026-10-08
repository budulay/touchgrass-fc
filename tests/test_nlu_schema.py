"""Tests for NLU schema + Pydantic validation (no Ollama needed)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from touchgrass.nlu import AvailabilityParse, TimeSlot


def test_valid_parse():
    p = AvailabilityParse(
        can_play=True,
        slots=[TimeSlot(weekday="saturday", start="10:00", end="12:00")],
        conditions=["no_rain"],
        language="uk",
    )
    assert p.can_play is True
    assert p.slots[0].weekday == "saturday"


def test_slot_requires_weekday_or_date():
    with pytest.raises(ValidationError):
        TimeSlot(start="10:00", end="12:00")


def test_slot_invalid_weekday():
    with pytest.raises(ValidationError):
        TimeSlot(weekday="funday")


def test_slot_weekday_normalised():
    slot = TimeSlot(weekday="Saturday")
    assert slot.weekday == "saturday"


def test_parse_roundtrip_json():
    p = AvailabilityParse(
        can_play=False,
        slots=[],
        conditions=[],
        language="en",
    )
    json_str = p.model_dump_json()
    p2 = AvailabilityParse.model_validate_json(json_str)
    assert p2 == p


def test_parse_multilingual_language_field():
    for lang in ("uk", "ru", "en"):
        p = AvailabilityParse(can_play=True, slots=[], conditions=[], language=lang)
        assert p.language == lang

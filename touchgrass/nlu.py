"""
NLU module – workstream A.

Sends player availability messages to local Gemma via Ollama's
structured-output (format=JSON schema) endpoint, validates with Pydantic,
and retries once on failure.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from touchgrass import config

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
CONDITIONS = {"no_rain", "no_wind", "evening_only", "morning_only", "any"}


class TimeSlot(BaseModel):
    """A concrete or relative time window when a player can play."""

    weekday: str | None = Field(
        default=None,
        description=(
            "Lowercase English weekday name, e.g. 'saturday'. "
            "Set if the player named a day of the week."
        ),
    )
    date: str | None = Field(
        default=None,
        description="ISO 8601 date YYYY-MM-DD. Set only if an explicit date was given.",
    )
    start: str | None = Field(
        default=None,
        description="HH:MM 24-h start time, or null if not specified.",
    )
    end: str | None = Field(
        default=None,
        description="HH:MM 24-h end time, or null if not specified.",
    )

    @model_validator(mode="after")
    def needs_day_or_date(self) -> "TimeSlot":
        if self.weekday is None and self.date is None:
            raise ValueError("A slot must have at least a weekday or a date")
        return self

    @model_validator(mode="after")
    def weekday_lowercase(self) -> "TimeSlot":
        if self.weekday:
            self.weekday = self.weekday.lower()
            if self.weekday not in WEEKDAYS:
                raise ValueError(f"Unknown weekday: {self.weekday!r}")
        return self


class AvailabilityParse(BaseModel):
    """Structured parse of a single player message."""

    can_play: bool = Field(description="True if the player is available / willing to play.")
    slots: list[TimeSlot] = Field(
        default_factory=list,
        description="List of time windows when the player can play.",
    )
    conditions: list[str] = Field(
        default_factory=list,
        description=(
            "Conditions attached to availability. "
            "Valid values: no_rain, no_wind, evening_only, morning_only, any."
        ),
    )
    language: str = Field(
        description="Detected language: 'uk' (Ukrainian), 'ru' (Russian), or 'en' (English).",
    )


# JSON schema fed to Ollama for structured output
_SCHEMA: dict[str, Any] = AvailabilityParse.model_json_schema()

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM = (
    "You are a football-match availability parser. "
    "Players write in Ukrainian, Russian, or English – sometimes mixing languages or using slang. "
    "Extract structured availability from their message and respond ONLY with valid JSON "
    "matching the provided schema. Do not add commentary. "
    "If a player says they CANNOT play, set can_play=false and leave slots empty. "
    "Relative words: 'завтра'/'tomorrow'='next day', 'після роботи'='after work'≈18:00-20:00, "
    "'вранці'/'morning'=08:00-12:00, 'вдень'/'afternoon'=12:00-17:00, "
    "'ввечері'/'evening'=18:00-21:00."
)

# ── Ollama client ─────────────────────────────────────────────────────────────


async def _call_ollama(
    message: str,
    model: str,
    base_url: str,
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Raw call to Ollama /api/chat with structured output."""
    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0},
        "format": _SCHEMA,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": message},
        ],
    }
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
    raw_content: str = data["message"]["content"]
    return json.loads(raw_content)


async def parse_availability(
    message: str,
    model: str | None = None,
    base_url: str | None = None,
) -> AvailabilityParse:
    """
    Parse a player's availability message into structured data.

    Tries once; on Pydantic ValidationError, appends the error and retries;
    raises on second failure.
    """
    model = model or config.OLLAMA_MODEL
    base_url = base_url or config.OLLAMA_BASE_URL

    last_error: str = ""
    for attempt in range(2):
        prompt = message if not last_error else f"{message}\n\n[Previous parse error: {last_error}]"
        try:
            raw = await _call_ollama(prompt, model, base_url)
            return AvailabilityParse.model_validate(raw)
        except ValidationError as exc:
            last_error = str(exc)
            logger.warning("NLU validation error (attempt %d): %s", attempt + 1, last_error)
            if attempt == 1:
                raise
        except Exception as exc:
            logger.error("NLU call failed: %s", exc)
            raise

    raise RuntimeError("Unreachable")  # pragma: no cover


async def write_invite(
    slot_description: str,
    pitch_name: str,
    language: str = "en",
    model: str | None = None,
    base_url: str | None = None,
) -> str:
    """
    Ask Gemma to write a 2-sentence match invite in the given language.
    Returns plain text (no JSON schema needed here).
    """
    model = model or config.OLLAMA_MODEL
    base_url = base_url or config.OLLAMA_BASE_URL

    lang_names = {"uk": "Ukrainian", "ru": "Russian", "en": "English"}
    lang_full = lang_names.get(language, "English")

    system = (
        f"Write exactly 2 sentences in {lang_full}. "
        "Be enthusiastic but not cringe. No hashtags, no emoji spam."
    )
    user = (
        f"Write a match invite for a football pitch called '{pitch_name}'. "
        f"The match is on {slot_description}. "
        "Tell people to vote in the poll above."
    )

    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0.4},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["message"]["content"].strip()

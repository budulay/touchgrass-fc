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
from pydantic import BaseModel, Field, ValidationError, model_validator, field_validator

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
            "Lowercase English weekday name ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'). "
            "You MUST set this if a day of the week is mentioned."
        ),
    )
    date: str | None = Field(
        default=None,
        description="ISO 8601 date YYYY-MM-DD. Set only if an explicit date was given.",
    )
    start: str | None = Field(
        default=None,
        description="HH:MM 24-h start time (e.g. '09:00', '18:00'), or null.",
    )
    end: str | None = Field(
        default=None,
        description="HH:MM 24-h end time (e.g. '12:00', '21:00'), or null.",
    )

    @field_validator("weekday", mode="before")
    @classmethod
    def normalize_weekday(cls, v: Any) -> str | None:
        if isinstance(v, str):
            v_low = v.strip().lower()
            day_map = {
                # Monday
                "mon": "monday", "понед": "monday", "lunes": "monday", "montag": "monday", "poniedz": "monday", "lundi": "monday",
                # Tuesday
                "tue": "tuesday", "вівт": "tuesday", "втор": "tuesday", "martes": "tuesday", "dienstag": "tuesday", "wtorek": "tuesday", "mardi": "tuesday",
                # Wednesday
                "wed": "wednesday", "серед": "wednesday", "miérc": "wednesday", "mierc": "wednesday", "mittwoch": "wednesday", "środ": "wednesday", "srod": "wednesday", "mercredi": "wednesday",
                # Thursday
                "thu": "thursday", "четв": "thursday", "jueves": "thursday", "donnerstag": "thursday", "czwart": "thursday", "jeudi": "thursday",
                # Friday
                "fri": "friday", "п'ят": "friday", "пят": "friday", "viernes": "friday", "freitag": "friday", "piąt": "friday", "piat": "friday", "vendredi": "friday",
                # Saturday
                "sat": "saturday", "суб": "saturday", "sábad": "saturday", "sabad": "saturday", "samstag": "saturday", "sobot": "saturday", "samedi": "saturday",
                # Sunday
                "sun": "sunday", "нед": "sunday", "воскр": "sunday", "domingo": "sunday", "sonntag": "sunday", "niedziel": "sunday", "dimanche": "sunday",
            }
            for k, day in day_map.items():
                if k in v_low:
                    return day
            if v_low in WEEKDAYS:
                return v_low
            raise ValueError(f"Unknown weekday: {v!r}")
        return v

    @field_validator("start", "end", mode="before")
    @classmethod
    def clean_time(cls, v: Any) -> str | None:
        if isinstance(v, str):
            v_str = v.strip()
            # If not containing digits, it's not a valid HH:MM time
            if not any(c.isdigit() for c in v_str):
                return None
            return v_str
        return v

    @model_validator(mode="after")
    def needs_day_or_date(self) -> "TimeSlot":
        if self.weekday is None and self.date is None:
            raise ValueError("A slot must have at least a weekday or a date")
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
        description="Detected language code: 'uk', 'en', 'es', 'de', 'pl', 'fr', or 'ru'.",
    )

    @field_validator("language", mode="before")
    @classmethod
    def normalize_lang(cls, v: Any) -> str:
        if isinstance(v, str):
            v_low = v.strip().lower()
            if v_low.startswith("uk"):
                return "uk"
            if v_low.startswith("es") or "span" in v_low:
                return "es"
            if v_low.startswith("de") or "germ" in v_low:
                return "de"
            if v_low.startswith("pl") or "pol" in v_low:
                return "pl"
            if v_low.startswith("fr") or "fren" in v_low:
                return "fr"
            if v_low.startswith("ru"):
                return "ru"
            if v_low.startswith("en"):
                return "en"
        return "en"

    @model_validator(mode="before")
    @classmethod
    def filter_slots(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("can_play", True):
                data["slots"] = []
            elif "slots" in data and isinstance(data["slots"], list):
                clean = []
                for s in data["slots"]:
                    if isinstance(s, dict):
                        if s.get("weekday") or s.get("date"):
                            clean.append(s)
                    elif isinstance(s, TimeSlot):
                        if s.weekday or s.date:
                            clean.append(s)
                    else:
                        clean.append(s)
                data["slots"] = clean
        return data


# JSON schema fed to Ollama for structured output
_SCHEMA: dict[str, Any] = AvailabilityParse.model_json_schema()

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM = (
    "You are a football-match availability parser.\n"
    "Respond ONLY with valid JSON matching the schema.\n\n"
    "Supported languages: 'uk' (Ukrainian), 'en' (English), 'es' (Spanish), 'de' (German), 'pl' (Polish), 'fr' (French), 'ru' (Russian).\n\n"
    "Days of week mapping across languages:\n"
    "- monday: понеділок, lunes, montag, poniedziałek, lundi\n"
    "- tuesday: вівторок, martes, dienstag, wtorek, mardi\n"
    "- wednesday: середа, miércoles, mittwoch, środa, mercredi\n"
    "- thursday: четвер, jueves, donnerstag, czwartek, jeudi\n"
    "- friday: п'ятниця, viernes, freitag, piątek, vendredi\n"
    "- saturday: субота, sábado, samstag, sobota, samedi\n"
    "- sunday: неділя, domingo, sonntag, niedziela, dimanche\n\n"
    "Rules:\n"
    "1. If player CANNOT play (e.g. 'не можу', 'not this week', 'no puedo', 'kann nicht', 'nie mogę', 'pas dispo'): set can_play=false, slots=[].\n"
    "2. If player cannot play on one day but CAN on another (e.g. 'суботу не можу, тільки неділя', 'no sábado, sólo domingo', 'Samstag nicht, nur Sonntag'): set can_play=true, include ONLY the day they CAN play.\n"
    "3. Every slot in 'slots' MUST have 'weekday' specified as lowercase English (e.g. 'saturday', 'sunday'). Never leave weekday null if a day was mentioned.\n"
    "4. 'start' and 'end' must be 'HH:MM' 24-hour time strings (e.g. '18:00', '09:00') or null. Never put text like 'morning' or 'nachmittag' into start/end.\n"
    "5. Approximate times:\n"
    "   - morning / вранці / mañana / morgen / rano / matin -> start='09:00', end='12:00'\n"
    "   - afternoon / вдень / tarde / nachmittag / po południu / après-midi -> start='12:00', end='17:00'\n"
    "   - evening / ввечері / noche / abend / wieczór / soir -> start='18:00', end='21:00'\n"
    "   - 'після 18' / 'after 6pm' / 'después de las 18' / 'ab 18 Uhr' / 'po 18' -> start='18:00', end='21:00'\n"
    "   - 'any time' / 'будь-який час' / 'a cualquier hora' / 'jederzeit' on a day -> start='10:00', end='20:00'\n"
    "6. Conditions: no rain / без дощу / sin lluvia / kein Regen / bez deszczu / sans pluie -> 'no_rain'; no wind / без вітру / sin viento / kein Wind -> 'no_wind'."
)

# ── Ollama client ─────────────────────────────────────────────────────────────


async def _call_ollama(
    message: str,
    model: str,
    base_url: str,
    *,
    timeout: float = 180.0,
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

    lang_names = {
        "uk": "Ukrainian",
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "pl": "Polish",
        "fr": "French",
        "ru": "Russian",
    }
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

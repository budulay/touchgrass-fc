"""Shared configuration loaded from environment / .env file."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from cwd or repo root
load_dotenv(Path.cwd() / ".env", override=False)


def _get(key: str, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    if val is None:
        raise RuntimeError(f"Required env var {key!r} is not set")
    return val


# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")  # empty = simulate mode only

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "gemma3:4b")

# ── Behaviour ─────────────────────────────────────────────────────────────────
AUTO_PLAN_AFTER: int = int(os.environ.get("AUTO_PLAN_AFTER", "5"))
AUTO_PLAN_TIMEOUT: int = int(os.environ.get("AUTO_PLAN_TIMEOUT", "3600"))
DB_PATH: str = os.environ.get("DB_PATH", "touchgrass.db")

# ── External API ──────────────────────────────────────────────────────────────
NOMINATIM_UA: str = "TouchGrassFC/0.1 (hacktoberfest-demo)"
OPEN_METEO_URL: str = "https://api.open-meteo.com/v1/forecast"
NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL: str = "https://overpass-api.de/api/interpreter"

"""
CLI chat simulator – workstream C.

Replays a scripted group conversation WITHOUT Telegram.
Judges can run: python -m touchgrass simulate

The simulator:
  - Uses a real Ollama NLU call (if Ollama is running) or mocks it offline.
  - Applies the real planner with a mocked weather fixture.
  - Prints a colourful transcript to stdout.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, time
from textwrap import indent
from typing import Any

logging.basicConfig(level=logging.WARNING)

# ── Scripted conversation ─────────────────────────────────────────────────────

SCRIPT = [
    # (player_name, message)
    ("Олексій", "можу в суботу після 18, якщо не буде дощу"),
    ("Maria", "Saturday morning works for me, 9-11am"),
    ("Дмитро", "суботу не можу, тільки неділя вранці"),
    ("Carlos", "¡Cuenta conmigo el domingo, a cualquier hora!"),
    ("Іванна", "можу і в суботу після 18 і в неділю вранці"),
]

MOCK_WEATHER: dict[str, Any] = {
    "saturday_18": {"weather_score": 0.82},
    "sunday_09": {"weather_score": 0.91},
}

# ── ANSI colours ──────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_RED = "\033[31m"


def _header(text: str) -> str:
    return f"\n{_BOLD}{_BLUE}{'═' * 60}{_RESET}\n{_BOLD}{_BLUE}{text}{_RESET}\n{'═' * 60}"


def _bot(text: str) -> str:
    return f"  {_CYAN}🤖 BOT:{_RESET} {text}"


def _player(name: str, text: str) -> str:
    return f"  {_YELLOW}👤 {name}:{_RESET} {text}"


def _nlu(data: dict) -> str:
    pretty = json.dumps(data, ensure_ascii=False, indent=2)
    return indent(f"{_MAGENTA}[NLU]{_RESET} {pretty}", "       ")


def _result(text: str) -> str:
    return f"  {_GREEN}✅ {text}{_RESET}"


def _error(text: str) -> str:
    return f"  {_RED}❌ {text}{_RESET}"


# ── Mock / real NLU ──────────────────────────────────────────────────────────

async def _nlu_call(message: str, player: str) -> dict:
    """Try real Ollama; fall back to hardcoded mock if unavailable."""
    try:
        from touchgrass.nlu import parse_availability
        parse = await asyncio.wait_for(parse_availability(message), timeout=30.0)
        return parse.model_dump()
    except Exception as exc:
        print(f"       {_RED}[Ollama unavailable — using mock: {exc}]{_RESET}")
        # Sensible mock parses
        _mocks = {
            "Олексій": {"can_play": True, "slots": [{"weekday": "saturday", "start": "18:00", "end": "20:00", "date": None}], "conditions": ["no_rain"], "language": "uk"},
            "Maria":   {"can_play": True, "slots": [{"weekday": "saturday", "start": "09:00", "end": "11:00", "date": None}], "conditions": [], "language": "en"},
            "Дмитро":  {"can_play": True, "slots": [{"weekday": "sunday",   "start": "09:00", "end": "12:00", "date": None}], "conditions": [], "language": "uk"},
            "Carlos":  {"can_play": True, "slots": [{"weekday": "sunday",   "start": "10:00", "end": "20:00", "date": None}], "conditions": [], "language": "es"},
            "Іванна":  {"can_play": True, "slots": [{"weekday": "saturday", "start": "18:00", "end": "20:00", "date": None}, {"weekday": "sunday", "start": "09:00", "end": "11:00", "date": None}], "conditions": [], "language": "uk"},
        }
        return _mocks.get(player, {"can_play": False, "slots": [], "conditions": [], "language": "en"})


# ── Mocked weather / planner ──────────────────────────────────────────────────

def _build_mock_forecast(reference: date):
    """Build a DailyForecast dict using synthetic data."""
    from touchgrass.weather import DailyForecast, HourlyWeather
    from datetime import datetime, timedelta, timezone

    forecast = {}
    tz = timezone.utc
    for day_offset in range(7):
        d = reference + timedelta(days=day_offset)
        # make hours
        hours = []
        for h in range(6, 22):
            dt = datetime(d.year, d.month, d.day, h, 0, tzinfo=tz)
            # synthetic: Sundays are sunny, Saturdays 30% rain after 18h
            if d.weekday() == 5 and h >= 18:  # Saturday evening
                precip = 30
            else:
                precip = 10
            hours.append(HourlyWeather(dt, precip, 8.0))
        sunset_t = time(19, 45)
        forecast[d] = DailyForecast(d, sunset_t, hours)
    return forecast


# ── Main simulation ───────────────────────────────────────────────────────────

async def run_simulation() -> None:
    print(_header("TouchGrass FC — CLI Simulator"))
    print(f"  {_BOLD}Replaying a scripted group chat (no Telegram token needed){_RESET}\n")

    # Step 1: /setlocation
    print(_bot("/setlocation Kyiv → 📍 (50.45, 30.52) saved"))

    # Step 2: /play
    print(_bot("📋 Collecting availability — reply to this message in your own words."))
    print()

    # Step 3: Player replies
    from touchgrass.nlu import AvailabilityParse
    replies: dict[str, AvailabilityParse] = {}

    for player, msg in SCRIPT:
        print(_player(player, msg))
        raw_parse = await _nlu_call(msg, player)
        print(_nlu(raw_parse))
        try:
            parse = AvailabilityParse.model_validate(raw_parse)
            replies[player] = parse
            if parse.can_play:
                slot_str = ", ".join(
                    f"{s.weekday or s.date} {s.start or '?'}–{s.end or '?'}"
                    for s in parse.slots
                )
                print(f"       {_GREEN}→ available: {slot_str}{_RESET}")
            else:
                print(f"       {_YELLOW}→ unavailable{_RESET}")
        except Exception as exc:
            print(_error(f"Validation failed: {exc}"))
        print()

    # Step 4: /plan
    print(_header("Planning…"))
    reference = date.today()
    # Advance to next Saturday
    days_ahead = (5 - reference.weekday()) % 7 or 7
    reference = reference  # keep as today; planner looks 7 days forward

    from touchgrass.planner import pick_best_slot
    forecast = _build_mock_forecast(reference)
    best = pick_best_slot(replies, forecast, reference)

    if best:
        print(_result(
            f"Best slot: {best.date.strftime('%A %d %b')} "
            f"{best.start.strftime('%H:%M')}–{best.end.strftime('%H:%M')} "
            f"| {best.player_count} players | weather {best.weather_score:.0%}"
        ))
        print(_result(f"Players confirmed: {', '.join(best.players)}"))
        pitch_name = "Olimpiyskiy Training Ground"
        pitch_lat, pitch_lon = 50.434, 30.521
        print(_result(f"Nearest pitch (mocked): {pitch_name}"))

        # Gemma invite
        print()
        print(_bot("Writing Gemma-generated invite…"))
        try:
            invite = await asyncio.wait_for(
                nlu_write_invite_safe(
                    f"{best.date.strftime('%A, %d %B')} {best.start.strftime('%H:%M')}",
                    pitch_name,
                    "uk",
                ),
                timeout=30.0,
            )
        except Exception:
            invite = (
                "⚽ Виходимо грати! Голосуй у опитуванні — хочемо зібрати повну команду.\n"
                "Побачимось на полі — не забудь бутси!"
            )
        print(_bot(invite))
        print()
        print(_bot(f"📊 POLL: ⚽ Are you in for {best.date.strftime('%A %d %b')} {best.start.strftime('%H:%M')}–{best.end.strftime('%H:%M')}?"))
        print(_bot("   ✅ In! | ❌ Out | 🤔 Maybe"))
        print(_bot(f"📍 Location pin: {pitch_lat}, {pitch_lon}"))
        print()
        print(_bot("✅ Match scheduled! I'll remind you 3h before. Now go outside. 🌱"))
    else:
        print(_error("No valid slot found — need more replies or better weather."))

    print(_header("End of simulation"))
    print(f"  Run the real bot with: {_BOLD}python -m touchgrass bot{_RESET}")
    print()


async def nlu_write_invite_safe(slot_desc: str, pitch_name: str, lang: str) -> str:
    from touchgrass import nlu
    return await nlu.write_invite(slot_desc, pitch_name, lang)

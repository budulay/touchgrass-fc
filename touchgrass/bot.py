"""
Telegram bot – workstream C.

Handlers:
  /start         - welcome
  /setlocation   - store city or Telegram location
  /play          - open an availability round
  /in <text>     - submit availability via command
  reply-to-bot   - submit availability via reply
  /plan          - manually trigger planning
  /played /nope  - post-match outcome
  /forget        - wipe chat data
  /stats         - how many matches actually happened
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message,
    Poll,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from touchgrass import config, db, nlu, pitches, planner, scheduler, weather
from touchgrass.nlu import AvailabilityParse

logger = logging.getLogger(__name__)

dp = Dispatcher()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _player_name(msg: Message) -> str:
    u = msg.from_user
    if not u:
        return "Unknown"
    return u.full_name or u.username or str(u.id)


async def _run_planning(chat_id: int, bot: Bot) -> None:
    """Score replies, pick best slot, post poll + location pin + invite."""
    round_row = await db.get_open_round(chat_id)
    if not round_row:
        return
    round_id = round_row["id"]

    chat_row = await db.get_chat(chat_id)
    if not chat_row:
        await bot.send_message(chat_id, "⚠️ No location set. Use /setlocation first.")
        return

    reply_rows = await db.get_replies(round_id)
    if not reply_rows:
        await bot.send_message(chat_id, "No availability replies collected yet.")
        return

    # Rebuild parse objects
    replies_dict: dict[str, AvailabilityParse] = {}
    for row in reply_rows:
        if row["parse_json"]:
            try:
                parse = AvailabilityParse.model_validate_json(row["parse_json"])
                replies_dict[row["player_name"]] = parse
            except Exception:
                pass

    lat, lon = chat_row["lat"], chat_row["lon"]

    # Fetch forecast
    try:
        forecast = await weather.fetch_forecast(lat, lon)
    except Exception as exc:
        logger.error("Weather fetch failed: %s", exc)
        forecast = {}

    best = planner.pick_best_slot(replies_dict, forecast, date.today())
    if best is None:
        await bot.send_message(
            chat_id,
            "😔 Couldn't find a slot that works for everyone with decent weather. Try /play again.",
        )
        return

    # Find pitch
    pitch = await pitches.find_nearest_pitch(lat, lon)
    if pitch is None:
        pitch_name = "nearest local pitch"
        pitch_lat, pitch_lon = lat, lon
    else:
        pitch_name = pitch.name
        pitch_lat, pitch_lon = pitch.lat, pitch.lon

    # Ask Gemma for the invite text
    dominant_lang = _dominant_language(reply_rows)
    slot_desc = f"{best.date.strftime('%A, %d %B')} {best.start.strftime('%H:%M')}–{best.end.strftime('%H:%M')}"
    try:
        invite = await nlu.write_invite(slot_desc, pitch_name, dominant_lang)
    except Exception:
        invite = f"Football at {pitch_name} on {slot_desc}. Vote below!"

    # Post invite + poll
    await bot.send_message(chat_id, invite)
    poll_msg = await bot.send_poll(
        chat_id,
        question=f"⚽ Are you in for {slot_desc}?",
        options=["✅ In!", "❌ Out", "🤔 Maybe"],
        is_anonymous=False,
    )

    # Pin location
    await bot.send_location(chat_id, pitch_lat, pitch_lon)

    # Persist
    await db.close_round(
        round_id,
        best.date.isoformat(),
        best.start.isoformat("minutes"),
        best.end.isoformat("minutes"),
        pitch_name,
        pitch_lat,
        pitch_lon,
        poll_msg.message_id,
    )

    # Schedule reminders
    async def _send(cid: int, text: str) -> None:
        await bot.send_message(cid, text)

    scheduler.schedule_match_jobs(round_id, chat_id, best.date, best.start, _send)

    players_str = ", ".join(best.players) if best.players else "some players"
    await bot.send_message(
        chat_id,
        f"✅ Match scheduled! {len(best.players)} confirmed. I'll remind you 3h before.\n"
        f"Pitch: {pitch_name} | Weather score: {best.weather_score:.0%}",
    )


def _dominant_language(reply_rows) -> str:
    counts: dict[str, int] = {}
    for row in reply_rows:
        if row["parse_json"]:
            try:
                p = json.loads(row["parse_json"])
                lang = p.get("language", "en")
                counts[lang] = counts.get(lang, 0) + 1
            except Exception:
                pass
    return max(counts, key=counts.get) if counts else "en"  # type: ignore[arg-type]


# ── Handlers ──────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(msg: Message) -> None:
    await msg.reply(
        "👋 I'm TouchGrass FC — I'll organise your football match.\n\n"
        "1. /setlocation <city> — tell me where you play\n"
        "2. /play — start collecting availability\n"
        "3. /plan — post the poll when everyone's replied\n\n"
        "Go outside. Touch grass. 🌱"
    )


@dp.message(Command("setlocation"))
async def cmd_setlocation(msg: Message) -> None:
    assert msg.chat and msg.bot

    # Telegram location pin
    if msg.location:
        lat, lon = msg.location.latitude, msg.location.longitude
        tz = "UTC"  # resolved by Open-Meteo timezone=auto
        await db.upsert_chat(msg.chat.id, lat, lon, tz)
        await msg.reply(f"📍 Location saved: {lat:.4f}, {lon:.4f}")
        return

    # City name from text
    args = (msg.text or "").split(maxsplit=1)
    if len(args) < 2:
        await msg.reply("Usage: /setlocation <city name>  or share your Telegram location.")
        return

    city = args[1].strip()
    coords = await pitches.geocode_city(city)
    if not coords:
        await msg.reply(f"Couldn't find '{city}'. Try a larger city name.")
        return

    lat, lon = coords
    await db.upsert_chat(msg.chat.id, lat, lon, "UTC")
    await msg.reply(f"📍 Location set to {city} ({lat:.4f}, {lon:.4f})")


@dp.message(Command("play"))
async def cmd_play(msg: Message) -> None:
    assert msg.chat and msg.bot

    existing = await db.get_open_round(msg.chat.id)
    if existing:
        await msg.reply("There's already an open round. Reply to the collection message or use /plan.")
        return

    chat_row = await db.get_chat(msg.chat.id)
    if not chat_row:
        await msg.reply("Set your location first with /setlocation.")
        return

    prompt = await msg.reply(
        "📋 Collecting availability — reply to *this message* in your own words.\n"
        "Tell me when you can play (day, time, any conditions). "
        "Ukrainian, Russian, or English all work.\n\n"
        "Example: «можу в суботу після 18» · «Sat morning I'm in»",
        parse_mode=ParseMode.MARKDOWN,
    )
    round_id = await db.open_round(msg.chat.id, prompt.message_id)
    logger.info("Opened round %d for chat %d", round_id, msg.chat.id)


@dp.message(Command("in"))
async def cmd_in(msg: Message) -> None:
    """Allow /in <text> as alternative to reply."""
    assert msg.chat and msg.from_user

    round_row = await db.get_open_round(msg.chat.id)
    if not round_row:
        await msg.reply("No open round. Use /play first.")
        return

    args = (msg.text or "").split(maxsplit=1)
    text = args[1].strip() if len(args) > 1 else ""
    if not text:
        await msg.reply("Tell me when you can play: /in Saturday morning")
        return

    await _handle_availability(msg, round_row["id"], text)


@dp.message(F.reply_to_message)
async def on_reply(msg: Message) -> None:
    """Process replies to the bot's collection message."""
    assert msg.chat and msg.bot and msg.reply_to_message

    # Only care about replies to our messages
    if not msg.reply_to_message.from_user:
        return
    if msg.reply_to_message.from_user.id != (await msg.bot.get_me()).id:
        return

    round_row = await db.get_open_round(msg.chat.id)
    if not round_row:
        return

    # Only accept replies to the specific collection prompt
    if msg.reply_to_message.message_id != round_row["prompt_msg_id"]:
        return

    text = msg.text or msg.caption or ""
    if not text.strip():
        return

    await _handle_availability(msg, round_row["id"], text)


async def _handle_availability(msg: Message, round_id: int, text: str) -> None:
    assert msg.chat and msg.from_user and msg.bot

    player_name = _player_name(msg)
    player_id = msg.from_user.id

    try:
        parse = await nlu.parse_availability(text)
    except Exception as exc:
        logger.warning("NLU failed for %s: %s", player_name, exc)
        await msg.reply(
            "I couldn't understand that. Could you rephrase? "
            "e.g. 'Saturday 10-12' or 'можу в суботу вранці'"
        )
        return

    parse_json = parse.model_dump_json()
    await db.add_reply(round_id, msg.chat.id, player_name, player_id, text, parse_json)

    if parse.can_play:
        slot_texts = [
            f"{s.weekday or s.date} {s.start or ''}–{s.end or ''}".strip()
            for s in parse.slots
        ]
        slots_str = ", ".join(slot_texts) if slot_texts else "some time"
        await msg.react([{"type": "emoji", "emoji": "⚽"}])  # type: ignore[arg-type]
    else:
        await msg.reply("Got it — marked you as unavailable for this round.")

    # Auto-trigger planning?
    count = await db.count_replies(round_id)
    if count >= config.AUTO_PLAN_AFTER:
        assert msg.bot
        await _run_planning(msg.chat.id, msg.bot)


@dp.message(Command("plan"))
async def cmd_plan(msg: Message) -> None:
    assert msg.chat and msg.bot
    await msg.reply("🧠 Crunching the schedule…")
    await _run_planning(msg.chat.id, msg.bot)


@dp.message(Command("played"))
async def cmd_played(msg: Message) -> None:
    assert msg.chat
    round_row = await db.get_open_round(msg.chat.id)
    # Look for planned rounds too
    db_conn = await db.get_db()
    async with db_conn.execute(
        "SELECT id FROM rounds WHERE chat_id=? AND status='planned' ORDER BY id DESC LIMIT 1",
        (msg.chat.id,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        await db.mark_played(row["id"], True)
        await msg.reply("🏆 Legendary. Logged. Go shower.")
    else:
        await msg.reply("No planned match found.")


@dp.message(Command("nope"))
async def cmd_nope(msg: Message) -> None:
    assert msg.chat
    db_conn = await db.get_db()
    async with db_conn.execute(
        "SELECT id FROM rounds WHERE chat_id=? AND status='planned' ORDER BY id DESC LIMIT 1",
        (msg.chat.id,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        await db.mark_played(row["id"], False)
        await msg.reply("😅 Rain check. Happens. Try /play again when you're ready.")
    else:
        await msg.reply("No planned match found.")


@dp.message(Command("stats"))
async def cmd_stats(msg: Message) -> None:
    count = await db.count_matches_played()
    await msg.reply(f"⚽ Matches actually played via this bot: **{count}**", parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("forget"))
async def cmd_forget(msg: Message) -> None:
    assert msg.chat
    await db.delete_chat(msg.chat.id)
    await msg.reply("🗑️ All data for this chat wiped. Fresh start!")


# ── Runner ────────────────────────────────────────────────────────────────────

def run_bot() -> None:
    import asyncio

    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        if not config.BOT_TOKEN:
            print("BOT_TOKEN not set. Use python -m touchgrass simulate instead.")
            return

        bot = Bot(token=config.BOT_TOKEN)
        scheduler.start_scheduler()
        try:
            await dp.start_polling(bot)
        finally:
            scheduler.stop_scheduler()
            await db.close_db()
            await bot.session.close()

    asyncio.run(_main())

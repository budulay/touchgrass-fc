"""
SQLite persistence layer.

All chat state lives here: location, open rounds, replies, match outcomes.
Uses aiosqlite for async I/O; schema is created on first connect.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import aiosqlite

from touchgrass import config

logger = logging.getLogger(__name__)

_DB: aiosqlite.Connection | None = None

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS chats (
    chat_id     INTEGER PRIMARY KEY,
    lat         REAL,
    lon         REAL,
    timezone    TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rounds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    prompt_msg_id   INTEGER,          -- message_id of the "reply here" prompt
    status          TEXT DEFAULT 'open',   -- open | planned | done
    opened_at       TEXT DEFAULT (datetime('now')),
    planned_at      TEXT,
    match_date      TEXT,
    match_start     TEXT,
    match_end       TEXT,
    pitch_name      TEXT,
    pitch_lat       REAL,
    pitch_lon       REAL,
    poll_msg_id     INTEGER,
    reminder_sent   INTEGER DEFAULT 0,
    played          INTEGER,           -- NULL=unknown, 1=yes, 0=no
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
);

CREATE TABLE IF NOT EXISTS replies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id    INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    player_id   INTEGER,
    raw_text    TEXT NOT NULL,
    parse_json  TEXT,                  -- AvailabilityParse as JSON
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (round_id) REFERENCES rounds(id)
);
"""


async def get_db() -> aiosqlite.Connection:
    global _DB
    if _DB is None:
        path = Path(config.DB_PATH)
        _DB = await aiosqlite.connect(path)
        _DB.row_factory = aiosqlite.Row
        await _DB.executescript(DDL)
        await _DB.commit()
    return _DB


async def close_db() -> None:
    global _DB
    if _DB:
        await _DB.close()
        _DB = None


# ── Chat / location ───────────────────────────────────────────────────────────

async def upsert_chat(chat_id: int, lat: float, lon: float, timezone: str = "UTC") -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO chats(chat_id, lat, lon, timezone)
           VALUES(?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET lat=excluded.lat, lon=excluded.lon,
               timezone=excluded.timezone""",
        (chat_id, lat, lon, timezone),
    )
    await db.commit()


async def get_chat(chat_id: int) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)) as cur:
        return await cur.fetchone()


async def delete_chat(chat_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM replies WHERE chat_id=?", (chat_id,))
    await db.execute("DELETE FROM rounds WHERE chat_id=?", (chat_id,))
    await db.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))
    await db.commit()


# ── Rounds ────────────────────────────────────────────────────────────────────

async def open_round(chat_id: int, prompt_msg_id: int) -> int:
    db = await get_db()
    cur = await db.execute(
        "INSERT INTO rounds(chat_id, prompt_msg_id) VALUES(?,?)",
        (chat_id, prompt_msg_id),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def get_open_round(chat_id: int) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM rounds WHERE chat_id=? AND status='open' ORDER BY id DESC LIMIT 1",
        (chat_id,),
    ) as cur:
        return await cur.fetchone()


async def close_round(
    round_id: int,
    match_date: str,
    match_start: str,
    match_end: str,
    pitch_name: str,
    pitch_lat: float,
    pitch_lon: float,
    poll_msg_id: int,
) -> None:
    db = await get_db()
    await db.execute(
        """UPDATE rounds SET status='planned', planned_at=datetime('now'),
           match_date=?, match_start=?, match_end=?,
           pitch_name=?, pitch_lat=?, pitch_lon=?, poll_msg_id=?
           WHERE id=?""",
        (match_date, match_start, match_end, pitch_name, pitch_lat, pitch_lon, poll_msg_id, round_id),
    )
    await db.commit()


async def mark_reminder_sent(round_id: int) -> None:
    db = await get_db()
    await db.execute("UPDATE rounds SET reminder_sent=1 WHERE id=?", (round_id,))
    await db.commit()


async def mark_played(round_id: int, played: bool) -> None:
    db = await get_db()
    await db.execute("UPDATE rounds SET played=?, status='done' WHERE id=?", (int(played), round_id))
    await db.commit()


# ── Replies ───────────────────────────────────────────────────────────────────

async def add_reply(
    round_id: int,
    chat_id: int,
    player_name: str,
    player_id: int,
    raw_text: str,
    parse_json: str | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO replies(round_id, chat_id, player_name, player_id, raw_text, parse_json)
           VALUES(?,?,?,?,?,?)""",
        (round_id, chat_id, player_name, player_id, raw_text, parse_json),
    )
    await db.commit()


async def get_replies(round_id: int) -> list[aiosqlite.Row]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM replies WHERE round_id=? ORDER BY id", (round_id,)
    ) as cur:
        return await cur.fetchall()


async def count_replies(round_id: int) -> int:
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM replies WHERE round_id=?", (round_id,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


# ── Stats ─────────────────────────────────────────────────────────────────────

async def count_matches_played() -> int:
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM rounds WHERE played=1") as cur:
        row = await cur.fetchone()
        return row[0] if row else 0

"""
Scheduler – workstream C.

Runs the reminder (3h before kickoff) and post-match ping
using APScheduler in asyncio mode.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from touchgrass import db

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()


def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)


def schedule_match_jobs(
    round_id: int,
    chat_id: int,
    match_date: date,
    match_start: time,
    bot_send_callback,  # async callable(chat_id, text)
) -> None:
    """Register reminder + post-match ping for a scheduled match."""
    match_dt = datetime.combine(match_date, match_start)
    reminder_dt = match_dt - timedelta(hours=3)
    after_dt = match_dt + timedelta(hours=2)

    sched = get_scheduler()

    async def _reminder() -> None:
        await bot_send_callback(
            chat_id,
            f"⚽ Reminder: match in 3 hours! ({match_start.strftime('%H:%M')}). Lace up.",
        )
        await db.mark_reminder_sent(round_id)

    async def _post_match() -> None:
        await bot_send_callback(
            chat_id,
            "Did you actually play today? 👍 Reply /played or /nope so we can keep score.",
        )

    if reminder_dt > datetime.utcnow():
        sched.add_job(_reminder, "date", run_date=reminder_dt, id=f"reminder_{round_id}", replace_existing=True)

    if after_dt > datetime.utcnow():
        sched.add_job(_post_match, "date", run_date=after_dt, id=f"postmatch_{round_id}", replace_existing=True)

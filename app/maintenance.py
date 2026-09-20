"""Периодическая уборка. Таблицы дедупликации и токенов растут без неё бесконечно."""

import asyncio
import logging

import asyncpg

from app import setup_tokens
from app.db import queries as q
from app.web import challenges, sessions

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


async def run_housekeeping(pool: asyncpg.Pool, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            events = await q.cleanup_old_events(pool)
            tokens = await setup_tokens.purge_expired(pool)
            stale_sessions = await sessions.purge_expired(pool)
            stale_challenges = await challenges.purge_expired(pool)
            if events or tokens or stale_sessions or stale_challenges:
                logger.info(
                    "уборка: событий %s, токенов %s, сессий %s, challenge %s",
                    events, tokens, stale_sessions, stale_challenges,
                )
        except Exception:
            logger.exception("уборка упала")
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
        except TimeoutError:
            pass

"""Периодическая уборка. Таблицы дедупликации и токенов растут без неё бесконечно."""

import asyncio
import logging

import asyncpg

from app import setup_tokens
from app.db import queries as q

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


async def run_housekeeping(pool: asyncpg.Pool, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            events = await q.cleanup_old_events(pool)
            tokens = await setup_tokens.purge_expired(pool)
            if events or tokens:
                logger.info("уборка: событий %s, токенов %s", events, tokens)
        except Exception:
            logger.exception("уборка упала")
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
        except TimeoutError:
            pass

"""Long Poll — режим локальной разработки.

На проде работает Callback API: у Railway есть публичный адрес, и повторные
доставки ВК обрабатываются дедупликацией. Long Poll нужен, чтобы поднять бота на
ноутбуке без туннеля.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from vkbottle import API
from vkbottle.polling import BotPolling

from app.config import Config

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


def build_polling(cfg: Config) -> BotPolling:
    return BotPolling(api=API(cfg.vk_group_token), skip_old_events=True)


async def run_longpoll(polling, handler: Handler, stop: asyncio.Event) -> None:
    async for batch in polling.listen():
        if stop.is_set():
            return
        for event in batch.get("updates", []):
            if stop.is_set():
                return
            try:
                await handler(event)
            except Exception:
                # Одно сломанное событие не должно останавливать весь опрос.
                logger.exception("обработка события long poll провалилась")

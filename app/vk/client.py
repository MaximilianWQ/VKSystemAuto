"""Обёртка над vkbottle.API: ограничение скорости и единый формат ошибок."""

import logging
from typing import Any

from vkbottle import API, VKAPIError

from app.config import Config
from app.vk.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

# Лимит токена сообщества — около 20 запросов в секунду. Берём с запасом вниз.
VK_RATE = 18.0


class VKCallError(Exception):
    """Ошибка VK API. Несёт код и метод, но никогда — тело сообщения."""

    def __init__(self, code: int, method: str) -> None:
        self.code = code
        self.method = method
        super().__init__(f"VK API {method} вернул ошибку {code}")


class VKClient:
    def __init__(self, api: API, api_version: str, limiter: RateLimiter) -> None:
        self._api = api
        self._version = api_version
        self._limiter = limiter

    async def call(self, method: str, **params: Any) -> dict:
        data = {k: v for k, v in params.items() if v is not None}
        await self._limiter.acquire()
        try:
            raw = await self._api.request(method, data, version=self._version)
        except VKAPIError as exc:
            # Логируем код и метод. Параметры не логируем: там тексты пользователей.
            logger.warning("VK API %s вернул ошибку %s", method, exc.code)
            raise VKCallError(code=exc.code, method=method) from None
        return raw.get("response", raw)


def build_client(cfg: Config) -> VKClient:
    return VKClient(
        api=API(cfg.vk_group_token),
        api_version=cfg.vk_api_version,
        limiter=RateLimiter(rate=VK_RATE, capacity=VK_RATE),
    )

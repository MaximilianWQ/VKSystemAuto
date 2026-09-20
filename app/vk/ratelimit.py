"""Токенное ведро. У токена сообщества лимит около 20 запросов в секунду."""

import asyncio
import time


class RateLimiter:
    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                # Спим ровно столько, сколько нужно на восстановление одного токена.
                await asyncio.sleep((1 - self._tokens) / self._rate)

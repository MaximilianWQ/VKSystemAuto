import asyncio
import time

from app.vk.ratelimit import RateLimiter


async def test_allows_burst_up_to_capacity():
    limiter = RateLimiter(rate=20, capacity=20)
    started = time.monotonic()
    for _ in range(20):
        await limiter.acquire()
    assert time.monotonic() - started < 0.1


async def test_throttles_beyond_capacity():
    limiter = RateLimiter(rate=20, capacity=5)
    started = time.monotonic()
    for _ in range(10):
        await limiter.acquire()
    # 5 сразу, оставшиеся 5 по 20 в секунду — минимум 0.25 с
    assert time.monotonic() - started >= 0.2


async def test_is_safe_under_concurrency():
    limiter = RateLimiter(rate=50, capacity=1)
    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(10)))
    elapsed = time.monotonic() - started
    assert 0.15 <= elapsed < 0.5

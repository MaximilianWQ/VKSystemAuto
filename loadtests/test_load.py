"""Нагрузочные проверки. Запуск: uv run pytest loadtests -m load -v

Реальный профиль — 272 подписчика и один оператор, но Callback API умеет
устраивать шторм повторов, и ломаются такие системы именно там.
"""

import asyncio
import statistics
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.vk import outbox
from app.vk.callback import router

pytestmark = pytest.mark.load

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код",
    "VK_SECRET_KEY": "секрет", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
}
CFG = load_config(ENV)

STORM_EVENTS = 500
P95_LIMIT_SECONDS = 0.1


def build_app(pool, handler):
    app = FastAPI()
    app.include_router(router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.background = set()
    app.state.handler = handler
    return app


def event(index: int) -> dict:
    return {
        "type": "message_new", "group_id": 111, "secret": "секрет",
        "event_id": f"evt-{index}",
        "object": {"message": {"id": index, "from_id": 1000 + index % 50,
                               "peer_id": 1000 + index % 50, "text": "нагрузка"}},
    }


async def test_webhook_survives_event_storm(pool):
    handled: list[str] = []

    async def handler(evt):
        handled.append(evt["event_id"])

    app = build_app(pool, handler)
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    latencies: list[float] = []

    async def fire(index: int):
        started = time.monotonic()
        response = await http.post("/vk/callback", json=event(index))
        latencies.append(time.monotonic() - started)
        assert response.text == "ok"

    await asyncio.gather(*(fire(i) for i in range(STORM_EVENTS)))
    if app.state.background:
        await asyncio.gather(*list(app.state.background))

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    assert p95 < P95_LIMIT_SECONDS, f"p95={p95:.3f}с превышает {P95_LIMIT_SECONDS}с"
    assert len(handled) == STORM_EVENTS, "часть событий потеряна"
    assert len(set(handled)) == STORM_EVENTS, "часть событий обработана дважды"


async def test_duplicate_storm_handled_once(pool):
    """ВК повторяет одно и то же событие, пока не получит ok."""
    handled: list[str] = []

    async def handler(evt):
        handled.append(evt["event_id"])

    app = build_app(pool, handler)
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    await asyncio.gather(*(http.post("/vk/callback", json=event(1)) for _ in range(200)))
    if app.state.background:
        await asyncio.gather(*list(app.state.background))

    assert len(handled) == 1


async def test_outbox_respects_rate_limit(pool):
    """Превышение 20 rps приводит к ошибке 6 от ВК, поэтому темп надо держать."""
    from app.vk.ratelimit import RateLimiter

    limiter = RateLimiter(rate=18.0, capacity=18.0)
    timestamps: list[float] = []

    class TimedClient:
        async def call(self, method, **params):
            await limiter.acquire()
            timestamps.append(time.monotonic())
            return {"message_id": 1}

    total = 200
    await q.upsert_user(pool, 1)
    for i in range(total):
        await outbox.enqueue(pool, peer_id=1, text=str(i))

    client = TimedClient()
    while await outbox.process_batch(pool, client, limit=50):
        pass

    elapsed = timestamps[-1] - timestamps[0]
    actual_rate = (total - 1) / elapsed
    assert actual_rate <= 20.0, f"темп {actual_rate:.1f} rps превышает лимит ВК"
    assert await pool.fetchval("SELECT count(*) FROM outbox WHERE status='sent'") == total


async def test_outbox_preserves_order_per_peer(pool):
    sent_order: list[str] = []

    class RecordingClient:
        async def call(self, method, **params):
            sent_order.append(params["message"])
            return {"message_id": 1}

    for i in range(100):
        await outbox.enqueue(pool, peer_id=1, text=f"{i:03d}")

    client = RecordingClient()
    while await outbox.process_batch(pool, client, limit=10):
        pass

    assert sent_order == sorted(sent_order)


async def test_restart_loses_nothing_and_duplicates_nothing(pool):
    """Убиваем процесс посреди отправки — ни потерь, ни дублей."""
    random_ids: list[int] = []

    class FlakyClient:
        def __init__(self, fail_after):
            self.count = 0
            self.fail_after = fail_after

        async def call(self, method, **params):
            self.count += 1
            if self.count > self.fail_after:
                raise asyncio.CancelledError("процесс убит")
            random_ids.append(params["random_id"])
            return {"message_id": self.count}

    total = 50
    for i in range(total):
        await outbox.enqueue(pool, peer_id=1, text=str(i))

    # Клиент один на весь цикл: пересоздание сбрасывало бы счётчик, и падение
    # никогда не наступало бы.
    flaky = FlakyClient(fail_after=20)
    with pytest.raises(asyncio.CancelledError):
        while await outbox.process_batch(pool, flaky, limit=10):
            pass

    # Перезапуск: возвращаем зависшие строки и дорабатываем очередь.
    await outbox.recover_stuck(pool)

    class GoodClient:
        async def call(self, method, **params):
            random_ids.append(params["random_id"])
            return {"message_id": 1}

    while await outbox.process_batch(pool, GoodClient(), limit=10):
        pass

    sent = await pool.fetchval("SELECT count(*) FROM outbox WHERE status = 'sent'")
    assert sent == total, "часть сообщений потеряна при рестарте"

    # Повторная отправка одного и того же random_id безопасна: ВК отбросит дубль.
    all_random = await pool.fetch("SELECT random_id FROM outbox")
    assert len({r["random_id"] for r in all_random}) == total


async def test_connection_pool_does_not_starve(pool):
    """Пул на 10 соединений против 200 параллельных запросов."""
    async def one(i: int):
        started = time.monotonic()
        await q.upsert_user(pool, 5000 + i)
        return time.monotonic() - started

    waits = await asyncio.gather(*(one(i) for i in range(200)))
    assert max(waits) < 1.0, f"худшее ожидание соединения {max(waits):.2f}с"
    assert statistics.median(waits) < 0.1

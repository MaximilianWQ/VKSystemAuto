import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.web import push, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
    "VAPID_PUBLIC_KEY": "B" * 87, "VAPID_PRIVATE_KEY": "p" * 43,
    "VAPID_SUBJECT": "mailto:a@b.c",
}
CFG = load_config(ENV)

SUBSCRIPTION = {
    "endpoint": "https://push.apple.com/abc",
    "keys": {"p256dh": "ключ", "auth": "секрет"},
}


def build_app(pool):
    app = FastAPI()
    app.include_router(push.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return app


@pytest.fixture
async def client(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


async def test_key_endpoint_returns_public_key(client):
    assert (await client.get("/api/push/key")).json() == {"key": "B" * 87}


async def test_subscribe_stores_subscription(client, pool):
    assert (await client.post("/api/push/subscribe", json=SUBSCRIPTION)).status_code == 200
    row = await pool.fetchrow("SELECT * FROM push_subscriptions")
    assert row["endpoint"] == SUBSCRIPTION["endpoint"]
    assert row["p256dh"] == "ключ"


async def test_subscribe_is_idempotent(client, pool):
    """iOS переподписывается при каждом запуске — дублей быть не должно."""
    await client.post("/api/push/subscribe", json=SUBSCRIPTION)
    await client.post("/api/push/subscribe", json=SUBSCRIPTION)
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 1


async def test_subscribe_rejects_malformed_body(client, pool):
    response = await client.post("/api/push/subscribe", json={"endpoint": ""})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 0


async def test_unsubscribe_removes_it(client, pool):
    await client.post("/api/push/subscribe", json=SUBSCRIPTION)
    await client.post("/api/push/unsubscribe", json={"endpoint": SUBSCRIPTION["endpoint"]})
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 0


async def test_subscribe_requires_session(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    assert (await http.post("/api/push/subscribe", json=SUBSCRIPTION)).status_code == 401


async def test_send_delivers_to_every_subscription(pool, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "_deliver",
                        lambda sub, data, cfg: sent.append(sub["endpoint"]))

    await push.save_subscription(pool, SUBSCRIPTION)
    await push.save_subscription(pool, {**SUBSCRIPTION, "endpoint": "https://push/2"})

    delivered = await push.send_to_all(pool, CFG, {"title": "Новое обращение"})
    assert delivered == 2
    assert sorted(sent) == ["https://push.apple.com/abc", "https://push/2"]


async def test_gone_subscription_is_removed(pool, monkeypatch):
    """410 означает, что браузер отозвал подписку навсегда."""
    class Gone(Exception):
        def __init__(self):
            self.response = type("R", (), {"status_code": 410})()

    monkeypatch.setattr(push, "WebPushException", Gone)

    def deliver(sub, data, cfg):
        raise Gone()

    monkeypatch.setattr(push, "_deliver", deliver)
    await push.save_subscription(pool, SUBSCRIPTION)

    assert await push.send_to_all(pool, CFG, {"title": "тест"}) == 0
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 0


async def test_temporary_failure_keeps_subscription(pool, monkeypatch):
    class Failed(Exception):
        def __init__(self):
            self.response = type("R", (), {"status_code": 500})()

    monkeypatch.setattr(push, "WebPushException", Failed)

    def deliver(sub, data, cfg):
        raise Failed()

    monkeypatch.setattr(push, "_deliver", deliver)
    await push.save_subscription(pool, SUBSCRIPTION)

    assert await push.send_to_all(pool, CFG, {"title": "тест"}) == 0
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 1


async def test_send_without_subscriptions_is_harmless(pool):
    assert await push.send_to_all(pool, CFG, {"title": "тест"}) == 0

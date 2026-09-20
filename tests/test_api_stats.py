import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


def build_app(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return app


@pytest.fixture
async def client(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


async def test_stats_require_session(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    assert (await http.get("/api/stats")).status_code == 401


async def test_empty_stats(client):
    body = (await client.get("/api/stats")).json()
    assert body["day"] == 0
    assert body["week"] == 0
    assert body["open_now"] == 0
    assert body["avg_first_reply_seconds"] is None
    assert body["avg_rating"] is None


async def test_counts_today_and_week(client, pool):
    await q.upsert_user(pool, 1)
    await q.create_ticket(pool, 1)
    await pool.execute(
        "INSERT INTO users (vk_id) VALUES (2);"
        " INSERT INTO tickets (user_id, status, created_at)"
        " VALUES (2, 'closed', now() - interval '3 days')"
    )
    body = (await client.get("/api/stats")).json()
    assert body["day"] == 1
    assert body["week"] == 2


async def test_counts_open_now(client, pool):
    await q.upsert_user(pool, 1)
    await q.create_ticket(pool, 1)
    assert (await client.get("/api/stats")).json()["open_now"] == 1


async def test_average_first_reply(client, pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await pool.execute(
        "UPDATE tickets SET created_at = now() - interval '120 seconds',"
        " first_reply_at = now() WHERE id = $1", ticket_id)
    value = (await client.get("/api/stats")).json()["avg_first_reply_seconds"]
    assert 110 <= value <= 130


async def test_average_rating(client, pool):
    await q.upsert_user(pool, 1)
    first = await q.create_ticket(pool, 1)
    await q.close_ticket(pool, first, rating=5)
    await q.upsert_user(pool, 2)
    second = await q.create_ticket(pool, 2)
    await q.close_ticket(pool, second, rating=3)
    assert (await client.get("/api/stats")).json()["avg_rating"] == 4.0


async def test_old_tickets_excluded_from_week(client, pool):
    await pool.execute(
        "INSERT INTO users (vk_id) VALUES (9);"
        " INSERT INTO tickets (user_id, status, created_at)"
        " VALUES (9, 'closed', now() - interval '30 days')"
    )
    assert (await client.get("/api/stats")).json()["week"] == 0

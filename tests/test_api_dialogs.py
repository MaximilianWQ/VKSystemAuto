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


@pytest.fixture
def anonymous(pool):
    return AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")


async def make_dialog(pool, vk_id=1, name="Максим", text="не работает"):
    await q.upsert_user(pool, vk_id, name, "Новиков")
    ticket_id = await q.create_ticket(pool, vk_id)
    await q.add_message(pool, ticket_id, "in", text)
    return ticket_id


async def test_dialogs_require_session(anonymous):
    assert (await anonymous.get("/api/dialogs")).status_code == 401


async def test_messages_require_session(anonymous):
    assert (await anonymous.get("/api/dialogs/1/messages")).status_code == 401


async def test_empty_list(client):
    assert (await client.get("/api/dialogs")).json() == []


async def test_dialog_carries_user_and_preview(client, pool):
    await make_dialog(pool)
    [dialog] = (await client.get("/api/dialogs")).json()
    assert dialog["user"]["vk_id"] == 1
    assert dialog["user"]["name"] == "Максим Новиков"
    assert dialog["preview"] == "не работает"
    assert dialog["unread"] == 1
    assert dialog["status"] == "open"
    assert dialog["waiting_seconds"] >= 0


async def test_dialogs_sorted_by_recency(client, pool):
    first = await make_dialog(pool, vk_id=1, text="раньше")
    second = await make_dialog(pool, vk_id=2, text="позже")
    ids = [d["id"] for d in (await client.get("/api/dialogs")).json()]
    assert ids == [second, first]


async def test_closed_dialogs_hidden_by_default(client, pool):
    ticket_id = await make_dialog(pool)
    await q.close_ticket(pool, ticket_id)
    assert (await client.get("/api/dialogs")).json() == []


async def test_closed_dialogs_visible_on_request(client, pool):
    ticket_id = await make_dialog(pool)
    await q.close_ticket(pool, ticket_id)
    dialogs = (await client.get("/api/dialogs?status=closed")).json()
    assert [d["id"] for d in dialogs] == [ticket_id]


async def test_messages_in_chronological_order(client, pool):
    ticket_id = await make_dialog(pool, text="раз")
    await q.add_message(pool, ticket_id, "out", "два")
    await q.add_message(pool, ticket_id, "in", "три")
    body = (await client.get(f"/api/dialogs/{ticket_id}/messages")).json()
    assert [m["text"] for m in body["messages"]] == ["раз", "два", "три"]
    assert [m["direction"] for m in body["messages"]] == ["in", "out", "in"]


async def test_messages_include_attachments(client, pool):
    ticket_id = await make_dialog(pool)
    await q.add_message(pool, ticket_id, "in", "", [{"type": "photo", "url": "p.jpg"}])
    body = (await client.get(f"/api/dialogs/{ticket_id}/messages")).json()
    assert body["messages"][-1]["attachments"][0]["type"] == "photo"


async def test_messages_of_unknown_dialog_is_404(client):
    assert (await client.get("/api/dialogs/999/messages")).status_code == 404


async def test_read_resets_unread_counter(client, pool):
    ticket_id = await make_dialog(pool)
    await q.add_message(pool, ticket_id, "in", "ещё")
    assert (await client.post(f"/api/dialogs/{ticket_id}/read")).status_code == 200
    assert await pool.fetchval(
        "SELECT unread_count FROM tickets WHERE id = $1", ticket_id) == 0


async def test_read_marks_incoming_messages(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/read")
    unread = await pool.fetchval(
        "SELECT count(*) FROM ticket_messages"
        " WHERE ticket_id = $1 AND direction = 'in' AND read_at IS NULL", ticket_id)
    assert unread == 0

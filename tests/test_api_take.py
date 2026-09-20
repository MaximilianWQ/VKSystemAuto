import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import personas
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


async def make_dialog(pool, vk_id=1):
    await q.upsert_user(pool, vk_id, "Максим", "Новиков")
    ticket_id = await q.create_ticket(pool, vk_id)
    await q.add_message(pool, ticket_id, "in", "не работает")
    return ticket_id


async def outbox_texts(pool):
    rows = await pool.fetch("SELECT payload FROM outbox ORDER BY id")
    return [r["payload"]["message"] for r in rows]


async def test_take_requires_session(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    assert (await http.post("/api/dialogs/1/take", json={"tier": "operator"})).status_code == 401


async def test_take_assigns_persona(client, pool):
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})
    assert response.status_code == 200

    operator = response.json()["operator"]
    assert operator["name"] in personas.NAMES
    assert operator["role"] in personas.OPERATOR_ROLES
    assert operator["tier"] == "operator"
    assert operator["signature"] == f"{operator['name']}, {operator['role']}"


async def test_lead_tier_gets_lead_role(client, pool):
    ticket_id = await make_dialog(pool)
    operator = (await client.post(
        f"/api/dialogs/{ticket_id}/take", json={"tier": "lead"})).json()["operator"]
    assert operator["role"] in personas.LEAD_ROLES
    assert "руководитель" in operator["role"]


async def test_take_introduces_to_client(client, pool):
    """Клиент должен узнать, кто взял его обращение."""
    ticket_id = await make_dialog(pool)
    operator = (await client.post(
        f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})).json()["operator"]

    [message] = await outbox_texts(pool)
    assert operator["name"] in message
    assert operator["role"] in message
    assert f"№{ticket_id}" in message


async def test_take_moves_to_in_progress(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})
    assert await pool.fetchval(
        "SELECT status FROM tickets WHERE id = $1", ticket_id) == "in_progress"


async def test_take_records_time(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})
    assert await pool.fetchval("SELECT taken_at FROM tickets WHERE id=$1", ticket_id)


async def test_cannot_take_twice(client, pool):
    """Второе представление собьёт клиента с толку."""
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})
    second = await client.post(f"/api/dialogs/{ticket_id}/take", json={"tier": "lead"})
    assert second.status_code == 409
    assert len(await outbox_texts(pool)) == 1


async def test_persona_survives_in_listing(client, pool):
    ticket_id = await make_dialog(pool)
    taken = (await client.post(
        f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})).json()["operator"]

    [dialog] = (await client.get("/api/dialogs")).json()
    assert dialog["operator"]["signature"] == taken["signature"]

    thread = (await client.get(f"/api/dialogs/{ticket_id}/messages")).json()
    assert thread["ticket"]["operator"]["signature"] == taken["signature"]


async def test_untaken_dialog_has_no_operator(client, pool):
    await make_dialog(pool)
    [dialog] = (await client.get("/api/dialogs")).json()
    assert dialog["operator"] is None


async def test_unknown_tier_rejected(client, pool):
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/take", json={"tier": "директор"})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM outbox") == 0


async def test_cannot_take_closed(client, pool):
    ticket_id = await make_dialog(pool)
    await q.close_ticket(pool, ticket_id)
    assert (await client.post(
        f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})).status_code == 409


async def test_take_unknown_is_404(client):
    assert (await client.post(
        "/api/dialogs/999/take", json={"tier": "operator"})).status_code == 404


async def test_blocked_user_gets_no_intro(client, pool):
    ticket_id = await make_dialog(pool)
    await q.mark_cannot_write(pool, 1)
    assert (await client.post(
        f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})).status_code == 200
    assert await outbox_texts(pool) == []


async def test_close_message_names_the_operator(client, pool):
    """Клиент должен понимать, кто вёл его обращение."""
    ticket_id = await make_dialog(pool)
    operator = (await client.post(
        f"/api/dialogs/{ticket_id}/take", json={"tier": "operator"})).json()["operator"]
    await client.post(f"/api/dialogs/{ticket_id}/close")

    closing = (await outbox_texts(pool))[-1]
    assert f"№{ticket_id}" in closing
    assert operator["name"] in closing
    assert "Оцените" in closing
    assert "напишите сюда" in closing


async def test_close_without_operator_still_reads_well(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/close")
    closing = (await outbox_texts(pool))[-1]
    assert f"№{ticket_id}" in closing
    assert "С вами работал" not in closing


async def test_personas_endpoint_lists_roles(client):
    body = (await client.get("/api/personas")).json()
    assert set(body) == {"operator", "lead"}
    assert len(body["operator"]) + len(body["lead"]) == 7

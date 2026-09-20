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


@pytest.fixture
async def client(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


async def make_dialog(pool, vk_id=1):
    await q.upsert_user(pool, vk_id, "Максим", "Новиков")
    ticket_id = await q.create_ticket(pool, vk_id)
    await q.add_message(pool, ticket_id, "in", "не работает")
    return ticket_id


async def test_reply_is_queued_not_sent_directly(client, pool):
    """Прямая отправка теряется при рестарте, поэтому только через outbox."""
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply",
                                 json={"text": "сейчас посмотрю"})
    assert response.status_code == 200

    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["peer_id"] == 1
    assert row["payload"]["message"] == "сейчас посмотрю"
    assert row["status"] == "pending"


async def test_reply_is_stored_in_history(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "сейчас посмотрю"})
    row = await pool.fetchrow("SELECT * FROM ticket_messages WHERE direction = 'out'")
    assert row["text"] == "сейчас посмотрю"


async def test_reply_moves_ticket_to_in_progress(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert await pool.fetchval(
        "SELECT status FROM tickets WHERE id = $1", ticket_id) == "in_progress"


async def test_reply_records_first_reply_time(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert await pool.fetchval(
        "SELECT first_reply_at FROM tickets WHERE id = $1", ticket_id) is not None


async def test_reply_marks_dialog_read(client, pool):
    """Оператор ответил — значит прочитал."""
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert await pool.fetchval(
        "SELECT unread_count FROM tickets WHERE id = $1", ticket_id) == 0


async def test_reply_with_attachment(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply",
                      json={"text": "вот инструкция", "attachment": "photo1_2"})
    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["payload"]["attachment"] == "photo1_2"


async def test_attachment_only_reply_allowed(client, pool):
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply",
                                 json={"text": "", "attachment": "photo1_2"})
    assert response.status_code == 200


async def test_empty_reply_rejected(client, pool):
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "   "})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM outbox") == 0


async def test_reply_to_unknown_dialog_is_404(client):
    assert (await client.post("/api/dialogs/999/reply",
                              json={"text": "привет"})).status_code == 404


async def test_reply_to_blocked_user_is_refused(client, pool):
    """Пользователь запретил сообщения — отправлять некуда, и надо сказать об этом."""
    ticket_id = await make_dialog(pool)
    await q.mark_cannot_write(pool, 1)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert response.status_code == 409
    assert await pool.fetchval("SELECT count(*) FROM outbox") == 0


async def test_close_marks_ticket_closed(client, pool):
    ticket_id = await make_dialog(pool)
    assert (await client.post(f"/api/dialogs/{ticket_id}/close")).status_code == 200
    assert await pool.fetchval(
        "SELECT status FROM tickets WHERE id = $1", ticket_id) == "closed"


async def test_close_asks_user_for_rating(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/close")
    payload = await pool.fetchval("SELECT payload FROM outbox ORDER BY id DESC LIMIT 1")
    assert "keyboard" in payload
    assert "Оцените" in payload["message"]


async def test_close_unknown_dialog_is_404(client):
    assert (await client.post("/api/dialogs/999/close")).status_code == 404


async def test_close_twice_is_refused(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/close")
    assert (await client.post(f"/api/dialogs/{ticket_id}/close")).status_code == 409

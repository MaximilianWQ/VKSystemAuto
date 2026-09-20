from app.db import queries as q


async def test_upsert_user_creates_then_updates(pool):
    await q.upsert_user(pool, 1, "Максим", "Новиков")
    await q.upsert_user(pool, 1, "Максим", "Михайлов")
    user = await q.get_user(pool, 1)
    assert user["last_name"] == "Михайлов"
    count = await pool.fetchval("SELECT count(*) FROM users")
    assert count == 1


async def test_state_roundtrip(pool):
    await q.upsert_user(pool, 1)
    await q.set_user_state(pool, 1, "awaiting_problem", {"from": "menu"})
    user = await q.get_user(pool, 1)
    assert user["state"] == "awaiting_problem"
    assert user["state_data"] == {"from": "menu"}


async def test_mark_cannot_write(pool):
    await q.upsert_user(pool, 1)
    await q.mark_cannot_write(pool, 1)
    assert (await q.get_user(pool, 1))["can_write"] is False


async def test_open_ticket_lifecycle(pool):
    await q.upsert_user(pool, 1)
    assert await q.get_open_ticket(pool, 1) is None

    ticket_id = await q.create_ticket(pool, 1)
    assert (await q.get_open_ticket(pool, 1))["id"] == ticket_id

    await q.close_ticket(pool, ticket_id, rating=5)
    assert await q.get_open_ticket(pool, 1) is None
    row = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    assert row["status"] == "closed"
    assert row["rating"] == 5
    assert row["closed_at"] is not None


async def test_create_ticket_returns_existing_open_one(pool):
    await q.upsert_user(pool, 1)
    first = await q.create_ticket(pool, 1)
    second = await q.create_ticket(pool, 1)
    assert first == second


async def test_add_message_bumps_ticket(pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "in", "не работает", [{"type": "photo"}], 99)

    msg = await pool.fetchrow("SELECT * FROM ticket_messages WHERE ticket_id = $1", ticket_id)
    assert msg["text"] == "не работает"
    assert msg["attachments"] == [{"type": "photo"}]
    assert msg["vk_message_id"] == 99

    ticket = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    assert ticket["unread_count"] == 1


async def test_outgoing_message_does_not_bump_unread(pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "out", "сейчас посмотрю")
    ticket = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    assert ticket["unread_count"] == 0
    assert ticket["first_reply_at"] is not None


async def test_first_reply_at_set_once(pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "out", "раз")
    first = (await pool.fetchrow("SELECT first_reply_at FROM tickets WHERE id=$1", ticket_id))[0]
    await q.add_message(pool, ticket_id, "out", "два")
    second = (await pool.fetchrow("SELECT first_reply_at FROM tickets WHERE id=$1", ticket_id))[0]
    assert first == second


async def test_faq_listing_skips_inactive(pool):
    await pool.execute(
        "INSERT INTO faq (title, answer, position, is_active) VALUES"
        " ('Б', 'ответ Б', 2, TRUE), ('А', 'ответ А', 1, TRUE), ('С', 'ответ С', 3, FALSE)"
    )
    items = await q.list_active_faq(pool)
    assert [i["title"] for i in items] == ["А", "Б"]


async def test_remember_event_deduplicates(pool):
    assert await q.remember_event(pool, "evt-1") is True
    assert await q.remember_event(pool, "evt-1") is False


async def test_cleanup_removes_only_old_events(pool):
    await q.remember_event(pool, "свежее")
    await pool.execute(
        "INSERT INTO processed_events (event_id, created_at)"
        " VALUES ('старое', now() - interval '2 days')"
    )
    assert await q.cleanup_old_events(pool) == 1
    remaining = await pool.fetchval("SELECT event_id FROM processed_events")
    assert remaining == "свежее"

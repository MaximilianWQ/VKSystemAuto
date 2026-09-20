"""Все SQL-запросы приложения. Никакого SQL за пределами этого модуля.

jsonb передаётся и принимается обычными dict и list: кодеки зарегистрированы
в create_pool, поэтому json.dumps здесь не нужен.
"""

import asyncpg


async def upsert_user(
    pool: asyncpg.Pool,
    vk_id: int,
    first_name: str = "",
    last_name: str = "",
    photo_url: str = "",
) -> None:
    await pool.execute(
        """
        INSERT INTO users (vk_id, first_name, last_name, photo_url)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (vk_id) DO UPDATE SET
            first_name   = COALESCE(NULLIF(EXCLUDED.first_name, ''), users.first_name),
            last_name    = COALESCE(NULLIF(EXCLUDED.last_name, ''), users.last_name),
            photo_url    = COALESCE(NULLIF(EXCLUDED.photo_url, ''), users.photo_url),
            last_seen_at = now()
        """,
        vk_id, first_name, last_name, photo_url,
    )


async def get_user(pool: asyncpg.Pool, vk_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM users WHERE vk_id = $1", vk_id)


async def set_user_state(
    pool: asyncpg.Pool, vk_id: int, state: str, state_data: dict | None = None
) -> None:
    await pool.execute(
        "UPDATE users SET state = $2, state_data = $3 WHERE vk_id = $1",
        vk_id, state, state_data or {},
    )


async def mark_cannot_write(pool: asyncpg.Pool, vk_id: int) -> None:
    await pool.execute("UPDATE users SET can_write = FALSE WHERE vk_id = $1", vk_id)


async def get_open_ticket(pool: asyncpg.Pool, user_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT * FROM tickets WHERE user_id = $1 AND status <> 'closed'", user_id
    )


async def create_ticket(pool: asyncpg.Pool, user_id: int) -> int:
    """Возвращает id открытого обращения, создавая его при необходимости.

    Частичный уникальный индекс не даёт завести второе незакрытое обращение,
    поэтому ON CONFLICT молча возвращает существующее.
    """
    row = await pool.fetchrow(
        """
        INSERT INTO tickets (user_id, status) VALUES ($1, 'open')
        ON CONFLICT (user_id) WHERE status <> 'closed' DO NOTHING
        RETURNING id
        """,
        user_id,
    )
    if row is not None:
        return row["id"]
    existing = await get_open_ticket(pool, user_id)
    return existing["id"]


async def close_ticket(pool: asyncpg.Pool, ticket_id: int, rating: int | None = None) -> None:
    await pool.execute(
        "UPDATE tickets SET status = 'closed', closed_at = now(), rating = $2"
        " WHERE id = $1",
        ticket_id, rating,
    )


async def add_message(
    pool: asyncpg.Pool,
    ticket_id: int,
    direction: str,
    text: str,
    attachments: list[dict] | None = None,
    vk_message_id: int | None = None,
) -> int:
    async with pool.acquire() as conn, conn.transaction():
        message_id = await conn.fetchval(
            """
            INSERT INTO ticket_messages
                (ticket_id, direction, text, attachments, vk_message_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            ticket_id, direction, text, attachments or [], vk_message_id,
        )
        await conn.execute(
            """
            UPDATE tickets SET
                last_message_at = now(),
                unread_count = CASE WHEN $2 = 'in' THEN unread_count + 1 ELSE unread_count END,
                first_reply_at = CASE
                    WHEN $2 = 'out' AND first_reply_at IS NULL THEN now()
                    ELSE first_reply_at END,
                status = CASE
                    WHEN $2 = 'out' AND status = 'open' THEN 'in_progress'
                    ELSE status END
            WHERE id = $1
            """,
            ticket_id, direction,
        )
        return message_id


async def list_active_faq(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM faq WHERE is_active ORDER BY position, id"
    )


async def get_faq(pool: asyncpg.Pool, faq_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM faq WHERE id = $1 AND is_active", faq_id)


async def remember_event(pool: asyncpg.Pool, event_id: str) -> bool:
    """True — событие видим впервые. False — это повтор от Callback API."""
    row = await pool.fetchrow(
        "INSERT INTO processed_events (event_id) VALUES ($1)"
        " ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
        event_id,
    )
    return row is not None


async def cleanup_old_events(pool: asyncpg.Pool) -> int:
    result = await pool.execute(
        "DELETE FROM processed_events WHERE created_at < now() - interval '1 day'"
    )
    return int(result.split()[-1])

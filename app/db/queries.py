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


async def list_dialogs(
    pool: asyncpg.Pool, status: str = "all", limit: int = 100
) -> list[asyncpg.Record]:
    """Очередь оператора: свежие сверху, с превью и временем ожидания."""
    condition = {
        "open": "t.status <> 'closed'",
        "closed": "t.status = 'closed'",
    }.get(status, "TRUE")

    return await pool.fetch(
        f"""
        SELECT
            t.id, t.status, t.unread_count, t.created_at, t.last_message_at,
            t.first_reply_at, t.rating,
            t.operator_name, t.operator_role, t.operator_tier, t.taken_at,
            u.vk_id, u.first_name, u.last_name, u.photo_url, u.can_write,
            (SELECT m.text FROM ticket_messages m
              WHERE m.ticket_id = t.id ORDER BY m.created_at DESC LIMIT 1) AS preview,
            (SELECT m.attachments FROM ticket_messages m
              WHERE m.ticket_id = t.id ORDER BY m.created_at DESC LIMIT 1)
              AS preview_attachments,
            EXTRACT(EPOCH FROM (now() - t.last_message_at))::bigint AS waiting_seconds
        FROM tickets t
        JOIN users u ON u.vk_id = t.user_id
        WHERE {condition}
        ORDER BY t.last_message_at DESC
        LIMIT $1
        """,  # noqa: S608 — condition берётся из замкнутого словаря, не из ввода
        limit,
    )


async def get_ticket(pool: asyncpg.Pool, ticket_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT t.*, u.first_name, u.last_name, u.photo_url, u.can_write"
        " FROM tickets t JOIN users u ON u.vk_id = t.user_id WHERE t.id = $1",
        ticket_id,
    )


async def list_messages(
    pool: asyncpg.Pool, ticket_id: int, limit: int = 200
) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM ticket_messages WHERE ticket_id = $1"
        " ORDER BY created_at, id LIMIT $2",
        ticket_id, limit,
    )


async def mark_read(pool: asyncpg.Pool, ticket_id: int) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE ticket_messages SET read_at = now()"
            " WHERE ticket_id = $1 AND direction = 'in' AND read_at IS NULL",
            ticket_id,
        )
        await conn.execute(
            "UPDATE tickets SET unread_count = 0 WHERE id = $1", ticket_id
        )


async def stats(pool: asyncpg.Pool) -> asyncpg.Record:
    return await pool.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE created_at > now() - interval '1 day')  AS day,
            count(*) FILTER (WHERE created_at > now() - interval '7 days') AS week,
            count(*) FILTER (WHERE status <> 'closed')                     AS open_now,
            avg(EXTRACT(EPOCH FROM (first_reply_at - created_at)))
                FILTER (WHERE first_reply_at IS NOT NULL)      AS avg_first_reply,
            avg(rating) FILTER (WHERE rating IS NOT NULL)      AS avg_rating
        FROM tickets
        """
    )


async def list_all_faq(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Все темы, включая выключенные: оператору нужно видеть и их."""
    return await pool.fetch("SELECT * FROM faq ORDER BY position, id")


async def create_faq(pool: asyncpg.Pool, title: str, answer: str) -> asyncpg.Record:
    """Новая тема встаёт в конец списка."""
    return await pool.fetchrow(
        "INSERT INTO faq (title, answer, position)"
        " VALUES ($1, $2, COALESCE((SELECT max(position) + 1 FROM faq), 0))"
        " RETURNING *",
        title, answer,
    )


async def update_faq(
    pool: asyncpg.Pool,
    faq_id: int,
    title: str | None = None,
    answer: str | None = None,
    is_active: bool | None = None,
) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "UPDATE faq SET"
        " title = COALESCE($2, title),"
        " answer = COALESCE($3, answer),"
        " is_active = COALESCE($4, is_active)"
        " WHERE id = $1 RETURNING *",
        faq_id, title, answer, is_active,
    )


async def delete_faq(pool: asyncpg.Pool, faq_id: int) -> bool:
    result = await pool.execute("DELETE FROM faq WHERE id = $1", faq_id)
    return result.split()[-1] != "0"


async def reorder_faq(pool: asyncpg.Pool, ids: list[int]) -> None:
    """Расставляет позиции в порядке переданных идентификаторов.

    Одной транзакцией: половинчатый порядок хуже старого.
    """
    async with pool.acquire() as conn, conn.transaction():
        for position, faq_id in enumerate(ids):
            await conn.execute(
                "UPDATE faq SET position = $2 WHERE id = $1", faq_id, position
            )


async def take_ticket(
    pool: asyncpg.Pool, ticket_id: int, name: str, role: str, tier: str
) -> asyncpg.Record | None:
    """Закрепляет персону за обращением.

    Только если оно ещё не взято: клиент уже мог увидеть, кем ему
    представились, и второе представление собьёт его с толку.
    """
    return await pool.fetchrow(
        "UPDATE tickets SET operator_name = $2, operator_role = $3,"
        " operator_tier = $4, taken_at = now(),"
        " status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END"
        " WHERE id = $1 AND taken_at IS NULL AND status <> 'closed'"
        " RETURNING *",
        ticket_id, name, role, tier,
    )


async def rating_breakdown(pool: asyncpg.Pool) -> dict[int, int]:
    """Сколько раз выбрали каждую оценку. Нули тоже нужны — иначе на графике дыра."""
    rows = await pool.fetch(
        "SELECT rating, count(*) AS total FROM tickets"
        " WHERE rating IS NOT NULL GROUP BY rating"
    )
    counts = {value: 0 for value in range(1, 6)}
    for row in rows:
        counts[row["rating"]] = row["total"]
    return counts

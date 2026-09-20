"""Надёжная отправка сообщений.

Railway перезапускает процесс в любой момент, поэтому прямой messages.send из
обработчика теряет ответ. Всё исходящее сначала ложится строкой в таблицу, а
воркер разгребает её с ретраями.
"""

import asyncio
import logging
import secrets

import asyncpg

from app.db import queries as q
from app.vk.client import VKCallError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
FLOOD_DELAY_SECONDS = 300
MAX_BACKOFF_SECONDS = 60
IDLE_SLEEP_SECONDS = 0.5

ERROR_TOO_MANY_REQUESTS = 6
ERROR_FLOOD_CONTROL = 9
ERROR_CANNOT_WRITE = 901


async def enqueue(
    pool: asyncpg.Pool,
    peer_id: int,
    text: str = "",
    attachment: str | None = None,
    keyboard: str | None = None,
) -> int:
    """Ставит сообщение в очередь.

    random_id генерируется здесь и больше не меняется: ВК считает повтор с тем же
    random_id дублем и не доставляет его, поэтому ретрай безопасен.
    """
    payload: dict[str, str] = {"message": text}
    if attachment:
        payload["attachment"] = attachment
    if keyboard:
        payload["keyboard"] = keyboard

    return await pool.fetchval(
        "INSERT INTO outbox (peer_id, payload, random_id) VALUES ($1, $2, $3)"
        " RETURNING id",
        peer_id, payload, secrets.randbelow(2**31 - 1) + 1,
    )


async def recover_stuck(pool: asyncpg.Pool) -> int:
    """Возвращает в работу строки, застрявшие в 'sending' после падения процесса."""
    result = await pool.execute(
        "UPDATE outbox SET status = 'pending' WHERE status = 'sending'"
    )
    count = int(result.split()[-1])
    if count:
        logger.info("вернули в очередь %s зависших сообщений", count)
    return count


async def process_batch(pool: asyncpg.Pool, client, limit: int = 20) -> int:
    rows = await pool.fetch(
        """
        UPDATE outbox SET status = 'sending'
        WHERE id IN (
            SELECT id FROM outbox
            WHERE status = 'pending' AND next_attempt_at <= now()
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        )
        RETURNING *
        """,
        limit,
    )

    # RETURNING не гарантирует порядок строк, даже когда подзапрос с ORDER BY id.
    # Для переписки порядок важен, поэтому сортируем явно.
    for row in sorted(rows, key=lambda r: r["id"]):
        await _send_one(pool, client, row)
    return len(rows)


async def _send_one(pool: asyncpg.Pool, client, row: asyncpg.Record) -> None:
    payload = row["payload"]
    try:
        await client.call(
            "messages.send",
            peer_id=row["peer_id"],
            random_id=row["random_id"],
            **payload,
        )
    except VKCallError as exc:
        await _handle_error(pool, row, exc)
        return

    await pool.execute(
        "UPDATE outbox SET status = 'sent', sent_at = now() WHERE id = $1", row["id"]
    )


async def _handle_error(pool: asyncpg.Pool, row: asyncpg.Record, exc: VKCallError) -> None:
    attempts = row["attempts"] + 1
    error_text = f"код {exc.code}"

    if exc.code == ERROR_CANNOT_WRITE:
        # Пользователь запретил сообщения. Ретраи бессмысленны навсегда.
        await pool.execute(
            "UPDATE outbox SET status = 'failed', attempts = $2, last_error = $3"
            " WHERE id = $1",
            row["id"], attempts, error_text,
        )
        await q.mark_cannot_write(pool, row["peer_id"])
        return

    if attempts >= MAX_ATTEMPTS:
        await pool.execute(
            "UPDATE outbox SET status = 'failed', attempts = $2, last_error = $3"
            " WHERE id = $1",
            row["id"], attempts, error_text,
        )
        logger.warning("сообщение %s провалено после %s попыток", row["id"], attempts)
        return

    if exc.code == ERROR_FLOOD_CONTROL:
        delay = FLOOD_DELAY_SECONDS
    else:
        delay = min(MAX_BACKOFF_SECONDS, 2**attempts)

    await pool.execute(
        "UPDATE outbox SET status = 'pending', attempts = $2, last_error = $3,"
        " next_attempt_at = now() + make_interval(secs => $4) WHERE id = $1",
        row["id"], attempts, error_text, float(delay),
    )


async def run_worker(pool: asyncpg.Pool, client, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            handled = await process_batch(pool, client)
        except Exception:
            logger.exception("воркер очереди упал на пачке")
            handled = 0
        if handled == 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=IDLE_SLEEP_SECONDS)
            except TimeoutError:
                pass

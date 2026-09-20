"""Пул соединений и накатывание SQL-миграций при старте."""

import json
import logging
import re
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Только строгое NNN_имя.sql. Всё остальное игнорируем: синхронизация папок
# плодит копии вида «001_init 2.sql», и накатывание такой копии роняет старт.
MIGRATION_NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


async def _register_codecs(conn: asyncpg.Connection) -> None:
    """Без этого asyncpg отдаёт jsonb строкой, и весь код разбирает JSON руками.

    С кодеком в запросы передаются обычные dict и list, а обратно приходят они же.
    """
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn, min_size=2, max_size=10, command_timeout=30, init=_register_codecs
    )


async def apply_migrations(pool: asyncpg.Pool) -> list[str]:
    """Накатывает неприменённые .sql по возрастанию имени. Возвращает что применил."""
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}

        applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if not MIGRATION_NAME.match(path.name):
                logger.debug("пропускаем файл, не похожий на миграцию: %s", path.name)
                continue
            if path.name in done:
                continue
            # Миграция и отметка о ней — в одной транзакции, иначе половинчатое состояние.
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES ($1)", path.name
                )
            logger.info("применена миграция %s", path.name)
            applied.append(path.name)
        return applied

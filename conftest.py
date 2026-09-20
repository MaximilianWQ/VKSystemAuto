"""Постгрес для тестов поднимается из пакета pgserver.

Системный Postgres не нужен: ни brew, ни docker, ни запущенного сервиса.
Это же делает набор тестов воспроизводимым в CI.
"""

import os
import pathlib
import tempfile

import pgserver
import pytest
import pytest_asyncio

from app.db.pool import apply_migrations, create_pool

TEST_DB = "vkbot_test"

# Синхронизация папки плодит копии вида «test_foo 2.py». Это не наши файлы и не
# в git, но pytest их собирает и падает на повторном создании таблиц.
collect_ignore_glob = ["* [0-9].py", "*/* [0-9].py"]


@pytest.fixture(scope="session")
def dsn() -> str:
    """Один сервер на весь прогон: старт занимает пару секунд."""
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override

    data_dir = pathlib.Path(tempfile.gettempdir()) / "vkbot-pgserver"
    data_dir.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(data_dir))
    server.psql(f"DROP DATABASE IF EXISTS {TEST_DB};")
    server.psql(f"CREATE DATABASE {TEST_DB};")
    return server.get_uri(database=TEST_DB)


@pytest_asyncio.fixture
async def pool(dsn):
    """Чистая база на каждый тест: дропаем схему, накатываем миграции заново."""
    conn_pool = await create_pool(dsn)
    async with conn_pool.acquire() as conn:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await apply_migrations(conn_pool)
    try:
        yield conn_pool
    finally:
        await conn_pool.close()

import asyncpg
import pytest

from app.db.pool import apply_migrations

EXPECTED_TABLES = {
    "users", "tickets", "ticket_messages", "faq", "processed_events",
    "outbox", "admin_credentials", "sessions", "push_subscriptions",
    "setup_tokens", "schema_migrations",
}


async def test_creates_all_tables(pool):
    rows = await pool.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    assert EXPECTED_TABLES <= {r["tablename"] for r in rows}


async def test_migrations_are_idempotent(pool):
    applied = await apply_migrations(pool)
    assert applied == []


async def test_records_applied_migration(pool):
    names = await pool.fetch("SELECT name FROM schema_migrations ORDER BY name")
    assert [r["name"] for r in names] == [
        "001_init.sql", "002_dashboard.sql", "003_assignment.sql"]


async def test_ticket_status_is_constrained(pool):
    await pool.execute("INSERT INTO users (vk_id) VALUES (1)")
    with pytest.raises(asyncpg.IntegrityConstraintViolationError):
        await pool.execute(
            "INSERT INTO tickets (user_id, status) VALUES (1, 'нет такого статуса')"
        )


def test_only_strict_names_are_treated_as_migrations():
    """Копии от синхронизации вида «001_init 2.sql» не должны накатываться."""
    from app.db.pool import MIGRATION_NAME

    assert MIGRATION_NAME.match("001_init.sql")
    assert MIGRATION_NAME.match("002_dashboard.sql")
    assert not MIGRATION_NAME.match("001_init 2.sql")
    assert not MIGRATION_NAME.match("001_init copy.sql")
    assert not MIGRATION_NAME.match("init.sql")
    assert not MIGRATION_NAME.match("001_Init.SQL")

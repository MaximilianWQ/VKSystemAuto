import asyncpg
import pytest


async def test_challenges_table_exists(pool):
    columns = await pool.fetch(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_name = 'webauthn_challenges'"
    )
    found = {c["column_name"]: c["data_type"] for c in columns}
    assert found["id"] == "text"
    assert found["challenge"] == "bytea"
    assert found["purpose"] == "text"
    assert "used_at" in found


async def test_both_migrations_recorded(pool):
    names = [r["name"] for r in await pool.fetch(
        "SELECT name FROM schema_migrations ORDER BY name")]
    assert names == ["001_init.sql", "002_dashboard.sql", "003_assignment.sql"]


async def test_purpose_is_constrained(pool):
    with pytest.raises(asyncpg.IntegrityConstraintViolationError):
        await pool.execute(
            "INSERT INTO webauthn_challenges (id, challenge, purpose, expires_at)"
            " VALUES ('x', '\\x00'::bytea, 'нечто', now() + interval '5 min')"
        )

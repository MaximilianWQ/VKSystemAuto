"""Одноразовые ссылки для регистрации passkey.

Бот отправляет такую ссылку владельцу ADMIN_ID в личку ВК. В базе хранится только
хеш: утечка дампа не должна давать вход в дашборд.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import asyncpg

TTL_SECONDS = 600
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue(pool: asyncpg.Pool, ttl_seconds: int = TTL_SECONDS) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    await pool.execute(
        "INSERT INTO setup_tokens (token_hash, expires_at) VALUES ($1, $2)",
        _hash(token), expires_at,
    )
    return token


async def consume(pool: asyncpg.Pool, token: str) -> bool:
    """Помечает токен использованным. True только если он был валиден и свеж."""
    row = await pool.fetchrow(
        "UPDATE setup_tokens SET used_at = now()"
        " WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()"
        " RETURNING token_hash",
        _hash(token),
    )
    return row is not None


async def purge_expired(pool: asyncpg.Pool) -> int:
    result = await pool.execute(
        "DELETE FROM setup_tokens WHERE expires_at < now() AND used_at IS NULL"
    )
    return int(result.split()[-1])

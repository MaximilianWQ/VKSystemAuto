"""Хранилище одноразовых challenge для WebAuthn.

Между выдачей опций и проверкой ответа браузера проходит сетевой круг, а
процесс на Railway может перезапуститься. Поэтому challenge живёт в базе,
а не в памяти.
"""

import secrets
from datetime import UTC, datetime, timedelta

import asyncpg

COOKIE_NAME = "vkbot_challenge"
TTL_SECONDS = 300


async def issue(
    pool: asyncpg.Pool, challenge: bytes, purpose: str, ttl_seconds: int = TTL_SECONDS
) -> str:
    challenge_id = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    await pool.execute(
        "INSERT INTO webauthn_challenges (id, challenge, purpose, expires_at)"
        " VALUES ($1, $2, $3, $4)",
        challenge_id, challenge, purpose, expires_at,
    )
    return challenge_id


async def consume(pool: asyncpg.Pool, challenge_id: str, purpose: str) -> bytes | None:
    """Возвращает challenge и сразу гасит его. Назначение обязано совпасть."""
    if not challenge_id:
        return None
    row = await pool.fetchrow(
        "UPDATE webauthn_challenges SET used_at = now()"
        " WHERE id = $1 AND purpose = $2 AND used_at IS NULL AND expires_at > now()"
        " RETURNING challenge",
        challenge_id, purpose,
    )
    return bytes(row["challenge"]) if row is not None else None


async def purge_expired(pool: asyncpg.Pool) -> int:
    result = await pool.execute(
        "DELETE FROM webauthn_challenges WHERE expires_at < now() AND used_at IS NULL"
    )
    return int(result.split()[-1])

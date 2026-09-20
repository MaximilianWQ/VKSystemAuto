"""Серверные сессии дашборда.

В базе лежит только хеш токена: утечка дампа не должна давать вход.
Сессия отзывается удалением строки, поэтому JWT здесь не подходит.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import asyncpg
from fastapi import HTTPException, Request
from fastapi.responses import Response

COOKIE_NAME = "vkbot_session"
TTL_DAYS = 30
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue(pool: asyncpg.Pool, user_agent: str = "", ttl_days: int = TTL_DAYS) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
    await pool.execute(
        "INSERT INTO sessions (id, expires_at, user_agent) VALUES ($1, $2, $3)",
        _hash(token), expires_at, user_agent[:500],
    )
    return token


async def verify(pool: asyncpg.Pool, token: str) -> asyncpg.Record | None:
    if not token:
        return None
    return await pool.fetchrow(
        "SELECT * FROM sessions WHERE id = $1 AND expires_at > now()", _hash(token)
    )


async def revoke(pool: asyncpg.Pool, token: str) -> None:
    await pool.execute("DELETE FROM sessions WHERE id = $1", _hash(token))


async def purge_expired(pool: asyncpg.Pool) -> int:
    result = await pool.execute("DELETE FROM sessions WHERE expires_at < now()")
    return int(result.split()[-1])


async def require_session(request: Request) -> asyncpg.Record:
    """Зависимость FastAPI. Всё в дашборде закрыто ею."""
    token = request.cookies.get(COOKIE_NAME, "")
    session = await verify(request.app.state.pool, token)
    if session is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return session


def set_cookie(response: Response, token: str, ttl_days: int = TTL_DAYS) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=ttl_days * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")

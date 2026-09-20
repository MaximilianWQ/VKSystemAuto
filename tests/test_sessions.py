from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.web import sessions


async def test_issued_session_verifies(pool):
    token = await sessions.issue(pool, user_agent="Safari")
    row = await sessions.verify(pool, token)
    assert row is not None
    assert row["user_agent"] == "Safari"


async def test_raw_token_is_not_stored(pool):
    """Дамп базы не должен давать вход в дашборд."""
    token = await sessions.issue(pool)
    stored = await pool.fetchval("SELECT id FROM sessions")
    assert stored != token
    assert token not in stored


async def test_unknown_token_rejected(pool):
    assert await sessions.verify(pool, "выдуманный") is None


async def test_expired_session_rejected(pool):
    token = await sessions.issue(pool, ttl_days=-1)
    assert await sessions.verify(pool, token) is None


async def test_revoked_session_rejected(pool):
    token = await sessions.issue(pool)
    await sessions.revoke(pool, token)
    assert await sessions.verify(pool, token) is None


async def test_tokens_are_unique(pool):
    assert len({await sessions.issue(pool) for _ in range(20)}) == 20


async def test_purge_removes_expired_only(pool):
    fresh = await sessions.issue(pool)
    await sessions.issue(pool, ttl_days=-1)
    assert await sessions.purge_expired(pool) == 1
    assert await sessions.verify(pool, fresh) is not None


def build_guarded_app(pool):
    app = FastAPI()
    app.state.pool = pool

    @app.get("/api/secret")
    async def secret(session=Depends(sessions.require_session)):
        return {"ok": True}

    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


async def test_guard_rejects_without_cookie(pool):
    http = build_guarded_app(pool)
    assert (await http.get("/api/secret")).status_code == 401


async def test_guard_rejects_bad_cookie(pool):
    http = build_guarded_app(pool)
    http.cookies.set(sessions.COOKIE_NAME, "garbage")
    assert (await http.get("/api/secret")).status_code == 401


async def test_guard_accepts_valid_cookie(pool):
    token = await sessions.issue(pool)
    http = build_guarded_app(pool)
    http.cookies.set(sessions.COOKIE_NAME, token)
    response = await http.get("/api/secret")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_cookie_flags_are_safe():
    response = JSONResponse({})
    sessions.set_cookie(response, "token-value", ttl_days=30)
    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "samesite=lax" in header.lower()


async def test_clear_cookie_expires_it():
    response = JSONResponse({})
    sessions.clear_cookie(response)
    assert sessions.COOKIE_NAME in response.headers["set-cookie"]

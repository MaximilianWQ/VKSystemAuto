import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.web import auth, challenges, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


@pytest.fixture
def client(pool):
    app = FastAPI()
    app.include_router(auth.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


async def add_credential(pool, credential_id=b"cred-1", sign_count=5):
    await pool.execute(
        "INSERT INTO admin_credentials (credential_id, public_key, sign_count, name)"
        " VALUES ($1, $2, $3, 'iPhone')",
        credential_id, b"pubkey", sign_count,
    )


class FakeAuth:
    credential_id = b"cred-1"
    new_sign_count = 6


async def test_login_options_without_any_key_is_refused(client, pool):
    """Пока ключ не зарегистрирован, входить нечем — и это надо сказать прямо."""
    response = await client.post("/api/auth/login/options")
    assert response.status_code == 409
    assert "/link" in response.json()["detail"]


async def test_login_options_list_registered_keys(client, pool):
    await add_credential(pool)
    response = await client.post("/api/auth/login/options")
    assert response.status_code == 200
    body = response.json()
    assert body["rpId"] == "bot.example"
    assert len(body["allowCredentials"]) == 1
    assert challenges.COOKIE_NAME in response.cookies


async def test_login_verify_opens_session(client, pool, monkeypatch):
    await add_credential(pool)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    response = await client.post("/api/auth/login/verify",
                                 json={"credential": {"id": "x"}})
    assert response.status_code == 200
    assert sessions.COOKIE_NAME in response.cookies


async def test_login_updates_sign_count(client, pool, monkeypatch):
    """Счётчик защищает от клонированного ключа, поэтому его надо сохранять."""
    await add_credential(pool, sign_count=5)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert await pool.fetchval("SELECT sign_count FROM admin_credentials") == 6


async def test_login_records_last_used(client, pool, monkeypatch):
    await add_credential(pool)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert await pool.fetchval("SELECT last_used_at FROM admin_credentials") is not None


async def test_login_with_unknown_credential_rejected(client, pool, monkeypatch):
    await add_credential(pool, credential_id=b"cred-1")

    class Unknown:
        credential_id = b"someone-else"
        new_sign_count = 1

    monkeypatch.setattr(auth, "verify_authentication_response", lambda **kwargs: Unknown())
    await client.post("/api/auth/login/options")
    response = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM sessions") == 0


async def test_login_without_challenge_cookie_fails(client, pool):
    await add_credential(pool)
    response = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert response.status_code == 400


async def test_login_signature_failure_opens_no_session(client, pool, monkeypatch):
    await add_credential(pool)

    def boom(**kwargs):
        raise ValueError("подпись не сошлась")

    monkeypatch.setattr(auth, "verify_authentication_response", boom)
    await client.post("/api/auth/login/options")
    response = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM sessions") == 0


async def test_me_requires_session(client, pool):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_me_returns_key_list(client, pool):
    await add_credential(pool)
    token = await sessions.issue(pool)
    client.cookies.set(sessions.COOKIE_NAME, token)
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["keys"][0]["name"] == "iPhone"


async def test_logout_revokes_session(client, pool):
    token = await sessions.issue(pool)
    client.cookies.set(sessions.COOKIE_NAME, token)
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert await sessions.verify(pool, token) is None


async def test_challenge_is_single_use(client, pool, monkeypatch):
    await add_credential(pool)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    first = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert first.status_code == 200
    second = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert second.status_code == 400

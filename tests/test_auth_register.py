import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import setup_tokens
from app.config import load_config
from app.web import auth, challenges, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
    "VAPID_PUBLIC_KEY": "B" * 87, "VAPID_PRIVATE_KEY": "p" * 43,
    "VAPID_SUBJECT": "mailto:a@b.c",
}
CFG = load_config(ENV)


@pytest.fixture
def client(pool):
    app = FastAPI()
    app.include_router(auth.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


class FakeVerified:
    credential_id = b"cred-1"
    credential_public_key = b"pubkey-1"
    sign_count = 0


async def test_options_require_valid_setup_token(client, pool):
    response = await client.post("/api/auth/register/options", json={"token": "левый"})
    assert response.status_code == 403


async def test_options_return_webauthn_payload(client, pool):
    token = await setup_tokens.issue(pool)
    response = await client.post("/api/auth/register/options", json={"token": token})
    assert response.status_code == 200
    body = response.json()
    assert body["rp"]["id"] == "bot.example"
    assert "challenge" in body
    assert body["user"]["name"]


async def test_options_set_challenge_cookie(client, pool):
    token = await setup_tokens.issue(pool)
    response = await client.post("/api/auth/register/options", json={"token": token})
    assert challenges.COOKIE_NAME in response.cookies


async def test_options_do_not_burn_the_setup_token(client, pool):
    """Прерванный create() в браузере не должен сжигать ссылку."""
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    assert await pool.fetchval("SELECT used_at FROM setup_tokens") is None


async def test_verify_stores_credential_and_opens_session(client, pool, monkeypatch):
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})

    response = await client.post(
        "/api/auth/register/verify",
        json={"token": token, "credential": {"id": "x"}, "name": "iPhone"},
    )
    assert response.status_code == 200

    stored = await pool.fetchrow("SELECT * FROM admin_credentials")
    assert bytes(stored["credential_id"]) == b"cred-1"
    assert bytes(stored["public_key"]) == b"pubkey-1"
    assert stored["name"] == "iPhone"

    assert sessions.COOKIE_NAME in response.cookies
    assert await pool.fetchval("SELECT count(*) FROM sessions") == 1


async def test_verify_burns_the_setup_token(client, pool, monkeypatch):
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}})

    assert await pool.fetchval("SELECT used_at FROM setup_tokens") is not None


async def test_reused_setup_link_is_rejected_at_the_first_step(client, pool, monkeypatch):
    """Повторный заход по ссылке отсекается уже на выдаче опций."""
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}})

    again = await client.post("/api/auth/register/options", json={"token": token})
    assert again.status_code == 403
    assert await pool.fetchval("SELECT count(*) FROM admin_credentials") == 1


async def test_verify_with_spent_token_adds_no_credential(client, pool, monkeypatch):
    """Даже если дойти до verify в обход, второй ключ не появится."""
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}})

    second = await client.post("/api/auth/register/verify",
                               json={"token": token, "credential": {"id": "x"}})
    assert second.status_code >= 400
    assert await pool.fetchval("SELECT count(*) FROM admin_credentials") == 1


async def test_verify_without_challenge_cookie_fails(client, pool, monkeypatch):
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    response = await client.post("/api/auth/register/verify",
                                 json={"token": token, "credential": {"id": "x"}})
    assert response.status_code == 400


async def test_verify_propagates_webauthn_failure(client, pool, monkeypatch):
    def boom(**kwargs):
        raise ValueError("подпись не сошлась")

    monkeypatch.setattr(auth, "verify_registration_response", boom)
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    response = await client.post("/api/auth/register/verify",
                                 json={"token": token, "credential": {"id": "x"}})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM admin_credentials") == 0


async def test_second_key_can_be_added(client, pool, monkeypatch):
    """Телефон и ноутбук — два ключа, оба валидны."""
    class Second(FakeVerified):
        credential_id = b"cred-2"

    token = await setup_tokens.issue(pool)
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}, "name": "iPhone"})

    token2 = await setup_tokens.issue(pool)
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: Second())
    await client.post("/api/auth/register/options", json={"token": token2})
    await client.post("/api/auth/register/verify",
                      json={"token": token2, "credential": {"id": "y"}, "name": "MacBook"})

    names = [r["name"] for r in await auth.list_credentials(pool)]
    assert sorted(names) == ["MacBook", "iPhone"]
